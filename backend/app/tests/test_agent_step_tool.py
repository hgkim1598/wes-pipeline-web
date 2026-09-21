"""The MCP tool `get_step_detail`, end to end without a model.

Three questions are asked here, in this order of importance:

1. Can a tool call reach anything it should not?  -- addressing and rejection
2. Does what comes back still say what happened?  -- the facts survive
3. Does it say anything it must not?              -- the privacy projection

The server is driven through the official SDK's in-process client, so the tool
is exercised the way a real MCP client exercises it: over the protocol, through
argument validation, with the same structured output and the same error
envelope. Nothing here starts a subprocess, calls Claude, or runs a pipeline.

The run fixtures deliberately carry a sample name in the places a real run
carries it -- inside metric keys, inside artifact names, inside a check detail
and inside an absolute path in a message -- and one test asserts that the raw
reader output still contains it. Otherwise a passing privacy test could just
mean the fixture had nothing to leak.
"""

from __future__ import annotations

import json

import anyio
import pytest
from mcp import Client

from app.agent_mcp import server as mcp_server
from app.services import step_reader
from app.services.agent import run_scope
from app.services.agent.privacy import Redactor
from app.services.agent.step_evidence import (
    MalformedStepId,
    StepEvidence,
    StepNotInThisRun,
    read_step_evidence,
)

SAMPLE = "SRR2962669.subset_5M"
RUN_ID = "wes-20260821-142659-c66d6e"

FULL_PLAN = [
    "00_input_validation",
    "01_raw_qc",
    "02_preprocessing",
    "03_alignment",
    "04_processing",
    "05_coverage_qc",
    "06_variant_calling",
    "99_finalization",
]

# What 04_processing records. Every value that must not leave is here on
# purpose: the sample as a metric, a full digest, and a metric key whose name
# was composed from the lane unit -- which main.sh derives from the sample.
PROCESSING_METRICS = {
    "percent_duplication": 12.7,
    "analysis_ready_records": 41283922,
    "markdup_validation": "ok",
    "nm_md_repaired": "true",
    "sample": SAMPLE,
    "target_bed_sha256": "a" * 64,
    f"reads_after_{SAMPLE}.L001": 41283922,
}


def processing_run(builder):
    """A run stopped just after 04_processing finished with a warning."""
    bam = f"04_processing/{SAMPLE}.markdup.bam"
    builder.file(bam, b"BAM")
    builder.step(
        "04_processing",
        status="completed",
        elapsed_seconds=2531,
        checks=[
            {
                "name": "markdup_validation",
                "status": "PASS",
                "detail": (
                    "samtools quickcheck passed for "
                    f"/srv/wes/runs/{builder.run_id}/{bam}"
                ),
            },
            {
                "name": f"sort_order_{SAMPLE}.L001",
                "status": "WARN",
                "detail": "coordinate sort order was re-applied",
            },
        ],
        warnings=[
            {
                "code": "NM_MD_REPAIRED",
                "message": f"NM/MD tags were repaired in {SAMPLE}.markdup.bam",
                "impact": "다운스트림 호출에는 영향이 없습니다",
                "can_continue": True,
            }
        ],
        outputs=[{"type": "bam", "path": bam}],
    )
    builder.metrics("04_processing", dict(PROCESSING_METRICS))
    builder.artifacts(
        "04_processing",
        [
            builder.entry(
                "04_processing",
                "analysis_ready_bam",
                f"Analysis-ready BAM ({SAMPLE})",
                bam,
                sha256="c" * 64,
                description="Duplicate-marked, tag-repaired alignment",
            )
        ],
    )
    builder.run_status(
        "running",
        current_step="05_coverage_qc",
        steps=[
            {
                "step_id": "04_processing",
                "status": "completed",
                "exit_code": 0,
                "elapsed_seconds": 2531,
                "warnings": 1,
                "failures": 0,
                "next_step_ready": True,
            }
        ],
    )
    return builder


@pytest.fixture
def scope(make_job, run):
    """A RunScope bound to the 04_processing fixture, as a server would build it."""
    processing_run(run(RUN_ID))
    job_id = make_job(RUN_ID, run_mode="full", planned=FULL_PLAN, sample_id=SAMPLE)
    return run_scope.for_job(job_id)


def call_tool(scope, arguments, name="get_step_detail"):
    """Invoke the tool over the protocol, in process."""
    server = mcp_server.build_server(scope)

    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(go)


def list_tools(scope):
    server = mcp_server.build_server(scope)

    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    return anyio.run(go)


def error_text(result) -> str:
    return "\n".join(
        block.text for block in result.content if getattr(block, "text", None)
    )


# --- what the server advertises ---------------------------------------------


def test_only_get_step_detail_is_exposed(scope):
    """One tool. No metrics, log, artifact, file or shell tool beside it."""
    assert [tool.name for tool in list_tools(scope)] == ["get_step_detail"]


def test_input_schema_is_step_id_only(scope):
    """A model cannot name a run: there is no parameter that would let it.

    This is the test that fails if someone later adds a jobId argument for
    convenience -- which would hand run selection to the model.
    """
    tool = list_tools(scope)[0]

    assert tool.input_schema["properties"] == {
        "stepId": {"title": "Stepid", "type": "string"}
    }
    assert tool.input_schema["required"] == ["stepId"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True


def test_output_schema_is_the_projection(scope):
    """The advertised output schema is StepEvidence, not the reader's shape."""
    tool = list_tools(scope)[0]

    assert tool.output_schema is not None
    assert set(tool.output_schema["properties"]) == set(StepEvidence.model_fields)


# --- addressing and refusal --------------------------------------------------


def test_planned_step_returns_structured_evidence(scope):
    result = call_tool(scope, {"stepId": "04_processing"})

    assert result.is_error is False
    body = result.structured_content
    assert body["stepId"] == "04_processing"
    assert body["status"] == "completed"
    assert body["exitCode"] == 0
    assert body["elapsedSeconds"] == 2531
    assert body["nextStepReady"] is True


def test_step_outside_the_plan_is_refused(scope):
    """11_intervar is a real main.sh step that this run never planned."""
    result = call_tool(scope, {"stepId": "11_intervar"})

    assert result.is_error is True
    message = error_text(result)
    assert "did not plan" in message
    # The refusal is actionable: it says which ids would have worked.
    assert "04_processing" in message


@pytest.mark.parametrize(
    "step_id",
    [
        "../../etc/passwd",
        "..",
        "../_jobs/wes-20260821-142659-c66d6e/run_config.json",
        "/home/vboxuser/runs",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "04_processing/../../secret",
        "04_processing\x00.json",
        "",
    ],
)
def test_path_shaped_ids_are_refused(scope, step_id):
    """A step id is not a way to name a file.

    The gate is step_reader.STEP_ID_RE followed by membership in the recorded
    plan, both of which run before any path is assembled. The wrapper does not
    re-implement either, so this is a test that it does not bypass them.
    """
    result = call_tool(scope, {"stepId": step_id})

    assert result.is_error is True
    message = error_text(result)
    assert "not a step id" in message or "did not plan" in message


def test_a_planned_but_unstarted_step_is_a_normal_answer(scope):
    """06_variant_calling is still ahead of the pipeline. A fact, not an error."""
    result = call_tool(scope, {"stepId": "06_variant_calling"})

    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "pending"
    assert body["exitCode"] is None
    assert body["metrics"] == {}
    assert body["nextStepReady"] is False


def test_the_step_in_flight_is_reported_as_running(scope):
    """05_coverage_qc is the current step: no document yet, but not pending."""
    evidence = read_step_evidence(scope, "05_coverage_qc")

    assert evidence.status == "running"
    assert evidence.exitCode is None


def test_unknown_job_cannot_be_scoped(env):
    with pytest.raises(run_scope.RunNotFound):
        run_scope.for_job("wes-does-not-exist")


def test_stdio_entry_refuses_without_a_job_id(monkeypatch):
    """Without an explicit job in the environment there is no run to expose."""
    monkeypatch.delenv(mcp_server.JOB_ID_ENV, raising=False)

    assert mcp_server.main() == 2


# --- the facts survive -------------------------------------------------------


def test_recorded_facts_are_preserved(scope):
    evidence = read_step_evidence(scope, "04_processing")

    assert evidence.validationStatus == "warn"
    assert [row.status for row in evidence.checks] == ["PASS", "WARN"]
    assert evidence.checks[0].name == "markdup_validation"

    assert [w.code for w in evidence.warnings] == ["NM_MD_REPAIRED"]
    assert evidence.warnings[0].canContinue is True
    assert "다운스트림" in evidence.warnings[0].impact

    # The pipeline's own metric identifiers, with their numbers intact.
    assert evidence.metrics["percent_duplication"] == 12.7
    assert evidence.metrics["analysis_ready_records"] == 41283922
    assert evidence.metrics["markdup_validation"] == "ok"

    # One artifact was registered; how many is evidence, what it is called is not.
    assert evidence.artifactCount == 1


def test_failures_are_preserved(make_job, run):
    builder = run(RUN_ID)
    builder.as_failing_precheck()
    job_id = make_job(RUN_ID, run_mode="check_only", sample_id="DEMO01_S1")
    scope = run_scope.for_job(job_id)

    evidence = read_step_evidence(scope, "00_input_validation")

    assert evidence.status == "failed"
    assert evidence.exitCode == 1
    assert [f.code for f in evidence.failures] == ["required_tools"]
    assert "missing from PATH" in evidence.failures[0].message
    assert evidence.nextStepReady is False


# --- the privacy projection --------------------------------------------------


def test_the_reader_really_does_expose_what_is_being_removed(scope):
    """Guard against a fixture that had nothing to leak in the first place."""
    raw = json.dumps(
        step_reader.read(
            scope.run_dir, list(scope.planned_steps), scope.run_mode, "04_processing"
        ),
        ensure_ascii=False,
    )

    assert SAMPLE in raw
    assert "Analysis-ready BAM" in raw
    assert f"04_processing/{SAMPLE}.markdup.bam" in raw
    assert "c" * 64 in raw


@pytest.mark.parametrize(
    "forbidden",
    [
        SAMPLE,  # the biological sample name
        RUN_ID,  # the run id
        "/srv/wes/runs",  # an absolute server path
        f"04_processing/{SAMPLE}.markdup.bam",  # a run-relative artifact path
        "Analysis-ready BAM",  # an artifact displayName
        "markdup.bam",  # a filename
        "c" * 64,  # an artifact digest
        "a" * 64,  # a target BED digest, recorded as a metric
    ],
)
def test_evidence_contains_no_identifier_or_path(scope, forbidden):
    evidence = read_step_evidence(scope, "04_processing")

    assert forbidden not in evidence.model_dump_json()


def test_tool_output_is_scrubbed_too(scope):
    """The transport does not re-add anything the projection removed."""
    result = call_tool(scope, {"stepId": "04_processing"})

    body = json.dumps(result.structured_content, ensure_ascii=False)
    assert SAMPLE not in body
    assert "/srv/wes" not in body
    # The unstructured text block is a rendering of the same object.
    assert SAMPLE not in error_text(result)


def test_composed_names_lose_the_sample_but_keep_the_code(scope):
    """`sort_order_<sample>.L001` is a real observed shape: a code with a
    lane unit welded on. The code stays readable; the sample does not."""
    evidence = read_step_evidence(scope, "04_processing")

    warn_row = next(row for row in evidence.checks if row.status == "WARN")
    assert warn_row.name.startswith("sort_order_")
    assert SAMPLE not in warn_row.name
    assert "<sample>" in warn_row.name


def test_paths_inside_a_check_detail_are_replaced_not_deleted(scope):
    evidence = read_step_evidence(scope, "04_processing")

    detail = evidence.checks[0].detail
    assert detail.startswith("samtools quickcheck passed for")
    assert "<path>" in detail
    assert "/srv" not in detail


def test_unsafe_metrics_are_withheld_and_counted(scope):
    evidence = read_step_evidence(scope, "04_processing")

    assert "sample" not in evidence.metrics
    assert "target_bed_sha256" not in evidence.metrics
    # The key itself carried the sample name.
    assert not any("SRR" in key for key in evidence.metrics)
    # sample, target_bed_sha256, reads_after_<sample>.L001
    assert evidence.withheldMetricCount == 3


def test_step_evidence_fields_are_pinned():
    """The allowlist is the contract; adding a field must be a decision.

    Same mechanism contract.py uses for the synthesis payload: a new field on
    StepEvidence fails this test until someone has decided a model may see it.
    """
    assert set(StepEvidence.model_fields) == {
        "stepId",
        "status",
        "exitCode",
        "elapsedSeconds",
        "validationStatus",
        "checks",
        "metrics",
        "withheldMetricCount",
        "warnings",
        "failures",
        "artifactCount",
        "nextStepReady",
    }


# --- the redactor's own rules ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/home/vboxuser/runs/wes/x", "<path>"),
        ("C:\\Users\\hgkim\\runs\\wes", "<path>"),
        ("../_jobs/wes-1/run_config.json", "<path>"),
        ("05_coverage_qc/mosdepth.regions.bed.gz", "<path>"),
        ("PATIENT_A.raw.vcf.gz", "<file>"),
        ("b" * 64, "<digest>"),
        # Not a path: a status pair, a percentage and a bare step id must all
        # survive intact, or the tool stops being able to say anything.
        ("PASS/WARN", "PASS/WARN"),
        ("mapped_pct 99.1", "mapped_pct 99.1"),
        ("04_processing", "04_processing"),
    ],
)
def test_redactor_shape_rules(raw, expected):
    assert Redactor().text(raw) == expected


def test_redactor_without_literals_still_removes_shapes():
    """A job row written before the sample_id column existed has no literal.

    The shape rules are what protect that run, which is exactly the case the
    literal-matching approach alone would miss.
    """
    bare = Redactor()

    assert "PATIENT" not in bare.text("/srv/wes/runs/r1/PATIENT_A.raw.vcf.gz")


def test_unknown_step_id_types_are_refused_by_the_wrapper(scope):
    """The wrapper translates the reader's refusals; it does not invent them."""
    with pytest.raises(MalformedStepId):
        read_step_evidence(scope, "../etc/passwd")
    with pytest.raises(StepNotInThisRun):
        read_step_evidence(scope, "11_intervar")
