"""The preserved real run can be restored, read and left untouched.

No model is called and no pipeline is run: the provider is a fake that records
what it was handed, and the step tool is exercised through the same reader the
MCP server calls.

The capture is not in git, so on a machine without it every test that needs it
is skipped with a reason that says so. The tests that do not need it -- the
missing-capture refusal and the synthetic case -- always run.

Assertions about leaks compare counts and booleans, never the leaked strings,
so a failure cannot print a sample name or a path into the test log.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import config
from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.explanation.llm import contract, provider
from app.services.explanation.llm import synthesis as llm_synthesis

from . import agent_cases, real_runs

RUN = real_runs.REAL_RUNS["real_cba73e"]

needs_capture = pytest.mark.skipif(
    not real_runs.capture_available(RUN),
    reason=(
        f"보존된 실제 Run capture({RUN.capture_dir.name})가 이 환경에 없음 -- "
        ".capture_* 폴더는 git에 포함되지 않는다"
    ),
)

WARNINGS = {
    ("NM_MD_REPAIRED", "04_processing"),
    ("ZERO_COVERAGE_TARGET_BASES", "05_coverage_qc"),
    ("DBSNP_NOT_CONFIGURED", "06_variant_calling"),
}

STEP_STATUSES = [
    ("00_input_validation", "completed"),
    ("01_raw_qc", "completed"),
    ("02_preprocessing", "completed"),
    ("03_alignment", "completed"),
    ("04_processing", "warning"),
    ("05_coverage_qc", "warning"),
    ("06_variant_calling", "warning"),
    ("99_finalization", "completed"),
]

def _capture_job_row() -> dict[str, object]:
    return real_runs._read_job_row(RUN)


def _leaks(text: str, work: Path) -> int:
    """Forbidden things in `text`, the temporary work directory included."""
    return real_runs.count_leaks(text, RUN, extra=[str(work)])


def _answer() -> dict:
    return {
        "summary": "실행을 확인했습니다.",
        "importantFindings": [
            {"statement": "실행이 끝났습니다.", "evidenceRefs": ["run:status"]}
        ],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }


def _recording_provider():
    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return provider.ProviderResult(payload=_answer(), models=["test-model"])

    fake.seen = seen
    return fake


_BLOCK_OPEN = "\n<run_data>\n"


def _run_data(user_prompt: str) -> str:
    return user_prompt.split(_BLOCK_OPEN, 1)[1]


def _capture_db_counts() -> tuple[int, int, int]:
    uri = (RUN.capture_dir / "app.db").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        return tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("jobs", "uploads", "synthesis_traces")
        )


# --- 1. restoration -----------------------------------------------------------


@needs_capture
def test_the_run_is_restored_into_a_temporary_copy_not_the_capture():
    capture = RUN.capture_dir.resolve()

    with real_runs.materialise(RUN):
        scope = run_scope.for_job(RUN.run_id)
        restored = scope.run_dir.resolve()
        database = Path(config.DB_PATH).resolve()

        assert restored.is_relative_to(Path(config.RUNS_ROOT).resolve())
        assert not restored.is_relative_to(capture)
        assert not database.is_relative_to(capture)
        assert (restored / "core_summary.json").is_file()


@needs_capture
def test_only_the_jobs_row_is_restored_and_command_is_dropped():
    from app import db

    with real_runs.materialise(RUN):
        assert db.query_one("SELECT COUNT(*) AS n FROM jobs")["n"] == 1
        assert db.query_one("SELECT COUNT(*) AS n FROM uploads")["n"] == 0
        assert db.query_one("SELECT COUNT(*) AS n FROM synthesis_traces")["n"] == 0
        row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (RUN.run_id,))
        assert row["command"] is None
        # Kept on purpose: the privacy projection redacts against it.
        kept_sample = row["sample_id"] == _capture_job_row()["sample_id"]
        assert kept_sample is True


# --- 2. status and the three warnings ----------------------------------------


@needs_capture
def test_status_steps_and_the_three_warnings_are_read():
    with real_runs.materialise(RUN) as explanation:
        data = explanation.model_dump()

    assert data["status"] == "completed_with_warnings"
    assert [(s["stepId"], s["status"]) for s in data["steps"]] == STEP_STATUSES
    assert {(d["code"], d["actualStepId"]) for d in data["diagnostics"]} == WARNINGS
    assert data["failures"] == []


@needs_capture
def test_every_warning_reaches_the_payload_with_its_grounding():
    with real_runs.materialise(RUN) as explanation:
        _payload, allowed = contract.build_payload(explanation)

    for code, _step in WARNINGS:
        assert f"dx:{code}" in allowed


# --- 3. V1 and V3 are handed the same initial payload ------------------------


@needs_capture
def test_two_restorations_give_the_same_payload():
    with real_runs.materialise(RUN) as first:
        payload_1, allowed_1 = contract.build_payload(first)
    with real_runs.materialise(RUN) as second:
        payload_2, allowed_2 = contract.build_payload(second)

    assert payload_1 == payload_2
    assert allowed_1 == allowed_2


@needs_capture
def test_v1_and_v3_send_the_same_run_data():
    v1 = _recording_provider()
    v3 = _recording_provider()

    with real_runs.materialise(RUN) as explanation:
        r1 = llm_synthesis.build_run_synthesis(
            explanation, run_provider=v1, offer_tools=False
        )
    with real_runs.materialise(RUN) as explanation:
        r3 = llm_synthesis.build_run_synthesis(explanation, run_provider=v3)

    assert r1.available is True and r3.available is True
    assert _run_data(v1.seen["user_prompt"]) == _run_data(v3.seen["user_prompt"])
    assert v1.seen["mcp_config"] is None
    assert v3.seen["mcp_config"] is not None


# --- 4. step evidence ---------------------------------------------------------


@needs_capture
def test_the_warning_steps_can_be_read_as_step_evidence():
    with real_runs.materialise(RUN):
        scope = run_scope.for_job(RUN.run_id)
        evidence = {
            step: read_step_evidence(scope, step)
            for step in ("04_processing", "05_coverage_qc", "06_variant_calling")
        }

    for code, step in WARNINGS:
        assert evidence[step].status == "warning"
        assert [w.code for w in evidence[step].warnings] == [code]

    metrics = evidence["04_processing"].metrics
    assert metrics["markdup_validation"] == "ONLY_NM"
    assert metrics["markdup_validation_after_calmd"] == "CLEAN"
    # Picard's PERCENT_DUPLICATION, recorded as main.sh wrote it: a fraction.
    assert metrics["percent_duplication"] == 0.003349


# --- 5. privacy ---------------------------------------------------------------


@needs_capture
def test_the_payload_carries_no_sample_name_and_no_path():
    with real_runs.materialise(RUN) as explanation:
        work = Path(config.RUNS_ROOT).parent
        payload, _allowed = contract.build_payload(explanation)

    leaks = _leaks(json.dumps(payload, ensure_ascii=False), work)
    assert leaks == 0


@needs_capture
def test_no_step_evidence_carries_a_sample_name_or_a_path():
    with real_runs.materialise(RUN):
        work = Path(config.RUNS_ROOT).parent
        scope = run_scope.for_job(RUN.run_id)
        blobs = {
            step: read_step_evidence(scope, step).model_dump_json()
            for step, _status in STEP_STATUSES
        }
        withheld = {
            step: read_step_evidence(scope, step).withheldMetricCount
            for step in ("00_input_validation", "03_alignment")
        }

    leaks = {step: _leaks(blob, work) for step, blob in blobs.items()}
    assert leaks == {step: 0 for step in blobs}
    # Both steps record the sample as a metric; it is withheld, and counted.
    assert all(count >= 1 for count in withheld.values())


@needs_capture
def test_the_v3_prompt_carries_no_sample_name_and_no_path():
    fake = _recording_provider()
    with real_runs.materialise(RUN) as explanation:
        work = Path(config.RUNS_ROOT).parent
        llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    leaks = _leaks(fake.seen["user_prompt"], work)
    assert leaks == 0


# --- 6. the capture is left as it was ----------------------------------------


@needs_capture
def test_the_capture_is_unchanged_by_restoring_reading_and_synthesising():
    before = real_runs.capture_manifest(RUN.capture_dir)
    counts_before = _capture_db_counts()

    with real_runs.materialise(RUN) as explanation:
        contract.build_payload(explanation)
        scope = run_scope.for_job(RUN.run_id)
        for step, _status in STEP_STATUSES:
            read_step_evidence(scope, step)
        llm_synthesis.build_run_synthesis(explanation, run_provider=_recording_provider())
        llm_synthesis.build_run_synthesis(
            explanation, run_provider=_recording_provider(), offer_tools=False
        )

    assert real_runs.capture_manifest(RUN.capture_dir) == before
    assert _capture_db_counts() == counts_before
    assert counts_before[2] == 0  # the original capture holds no trace


@needs_capture
def test_the_manifest_names_content_not_location(tmp_path):
    copy = tmp_path / "elsewhere"
    import shutil

    shutil.copytree(RUN.capture_dir, copy)
    assert real_runs.capture_manifest(copy) == real_runs.capture_manifest(
        RUN.capture_dir
    )

    (copy / "runs" / RUN.run_id / "core_summary.json").write_text("{}", "utf-8")
    assert real_runs.capture_manifest(copy) != real_runs.capture_manifest(
        RUN.capture_dir
    )


# --- 7. cleanup ---------------------------------------------------------------


@needs_capture
def test_the_temporary_copy_is_removed_and_config_restored(monkeypatch):
    made: list[Path] = []
    real_mkdtemp = agent_cases.tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        made.append(Path(path))
        return path

    monkeypatch.setattr(agent_cases.tempfile, "mkdtemp", recording_mkdtemp)
    previous = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)

    with real_runs.materialise(RUN):
        assert len(made) == 1 and made[0].is_dir()

    assert not made[0].exists()
    assert (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH) == previous


@needs_capture
def test_the_temporary_copy_is_removed_even_when_the_block_raises(monkeypatch):
    made: list[Path] = []
    real_mkdtemp = agent_cases.tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        made.append(Path(path))
        return path

    monkeypatch.setattr(agent_cases.tempfile, "mkdtemp", recording_mkdtemp)

    with pytest.raises(RuntimeError):
        with real_runs.materialise(RUN):
            raise RuntimeError("boom")

    assert not made[0].exists()


# --- 8. a machine without the capture ----------------------------------------


def test_a_missing_capture_is_refused_before_anything_is_created(tmp_path, monkeypatch):
    missing = real_runs.RealRun(
        name="missing",
        intent="",
        capture_dir=tmp_path / "no_such_capture",
        run_id=RUN.run_id,
        split="dev",
    )
    made: list[str] = []
    monkeypatch.setattr(
        agent_cases.tempfile, "mkdtemp", lambda *a, **k: made.append("x") or ""
    )

    assert real_runs.capture_available(missing) is False
    with pytest.raises(real_runs.CaptureMissing):
        with real_runs.materialise(missing):
            pass
    assert made == []


def test_the_real_run_is_classified_as_dev():
    assert RUN.split == "dev"


# --- 9. the synthetic cases are unaffected -----------------------------------


def test_the_synthetic_case_still_builds_through_the_shared_isolation():
    previous = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)
    case = agent_cases.CASES["agent_failed_step"]

    with agent_cases.materialise(case) as explanation:
        payload, allowed = contract.build_payload(explanation)

    assert explanation.status == "failed"
    assert "fail:markdup_validation" in allowed
    assert [row["stepId"] for row in payload["steps"]["planned"]] == list(case.planned)
    assert (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH) == previous


# --- 10. the expectations file matches the capture ---------------------------

EXPECTATIONS = Path(__file__).resolve().parent / "expectations" / "real_cba73e.json"


def _expectations() -> dict:
    return json.loads(EXPECTATIONS.read_text(encoding="utf-8"))


def _field(document: object, path: str) -> object:
    """A dotted path ("warnings.0.code") into nested dicts and lists."""
    node = document
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


@needs_capture
def test_every_stated_fact_is_what_the_capture_recorded():
    """Each fact names a file and a field; the value there is the stated one."""
    facts = _expectations()["facts"]
    assert facts

    mismatched = []
    for fact in facts:
        source = RUN.capture_dir / fact["source"]["file"]
        document = json.loads(source.read_text(encoding="utf-8"))
        if _field(document, fact["source"]["field"]) != fact["expected"]:
            mismatched.append(fact["id"])

    assert mismatched == []


@needs_capture
def test_the_expectations_cite_only_what_the_payload_mints():
    expectations = _expectations()
    with real_runs.materialise(RUN) as explanation:
        payload, allowed = contract.build_payload(explanation)

    for spec in expectations["mustCite"]:
        assert spec["ref"] in allowed, spec["ref"]
    for spec in expectations["mustQualify"]:
        assert spec["mustAlsoCite"] in allowed
        assert all(ref in allowed for ref in spec["whenCiting"])
    # Payload facts point at payload ids; tool facts at a step the run planned.
    planned = {row["stepId"] for row in payload["steps"]["planned"]}
    for fact in expectations["facts"]:
        ref = fact["payloadRef"]
        if ref is None:
            continue
        if ref.startswith("step:"):
            assert ref.removeprefix("step:") in planned
        else:
            assert ref in allowed, fact["id"]


@needs_capture
def test_the_mentioned_values_are_numbers_the_payload_carries():
    from app.services.explanation.llm import validation

    with real_runs.materialise(RUN) as explanation:
        payload, _allowed = contract.build_payload(explanation)
    known = validation.collect_known_numbers(payload)

    for value in _expectations()["mustMention"]:
        assert validation.normalise_number(value) in known, value


def test_the_accepted_step_sets_fit_the_budget_and_the_warning_steps():
    from app.services.agent.run_scope import DEFAULT_MAX_DISTINCT_STEPS

    expectations = _expectations()
    warning_steps = {step for _code, step in WARNINGS}

    assert expectations["expectedToolUse"] == "optional"
    assert expectations["split"] == "dev"
    for steps in expectations["acceptableStepSets"]:
        assert 1 <= len(steps) <= DEFAULT_MAX_DISTINCT_STEPS
        assert set(steps) <= warning_steps


def test_b2_terms_are_proposed_not_approved():
    rubric = _expectations()["beginnerRubric"]
    assert rubric["rubric"] == "beginner_v1"
    assert rubric["status"] == "proposed_pending_approval"


def test_the_v2_rubric_is_a_separate_block_tied_to_registered_terms():
    """v2 is chosen separately; it does not replace the v1 block or its terms.

    Every required term names an entry in wes_terms.json, so "explained" can be
    judged against a sourced definition rather than the reviewer's own.
    """
    from app.services.explanation import knowledge

    spec = _expectations()
    v2 = spec["beginnerRubricV2"]
    assert v2["rubric"] == "beginner_v2"
    assert v2["status"] == "proposed_pending_approval"
    assert spec["beginnerRubric"]["rubric"] == "beginner_v1"

    registered = {term.id for term in knowledge.all_terms()}
    required = [row["termId"] for row in v2["requiredTerms"]]
    not_required = [row["termId"] for row in v2["notRequired"]]
    assert set(required) <= registered
    assert set(not_required) <= registered
    assert not set(required) & set(not_required)
    for row in v2["b5NextChecks"]:
        assert row["who"] in ("사용자", "서버 관리자")
        assert row["what"] and row["where"]


# --- 11. the runner: preflight and a record, no model ------------------------


def _fake_synthesis(monkeypatch, run_eval):
    """Route the runner's synthesis through the real code with a fake provider."""
    real_build = run_eval.synthesis.build_run_synthesis

    def build(explanation, **kwargs):
        return real_build(explanation, run_provider=_recording_provider(), **kwargs)

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", build)


@needs_capture
def test_preflight_checks_everything_without_a_model(monkeypatch):
    from . import run_eval

    def must_not_call(*_args, **_kwargs):
        raise AssertionError("preflight called the model path")

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", must_not_call)

    check = run_eval.preflight_real("real_cba73e")

    assert run_eval.preflight_ok(check) is True
    assert check["restorationsMatch"] is True
    assert check["variantRunDataMatch"] is True
    assert check["privacy"] == "pass"
    assert check["captureUnchanged"] is True
    assert len(check["payloadHash"]) == 64


@needs_capture
def test_a_real_record_says_where_it_came_from(monkeypatch):
    from . import run_eval

    _fake_synthesis(monkeypatch, run_eval)
    before = real_runs.capture_manifest(RUN.capture_dir)

    v1 = run_eval.evaluate_real("real_cba73e", variant="v1")
    v3 = run_eval.evaluate_real("real_cba73e", variant="v3")

    for record in (v1, v3):
        assert record["caseKind"] == "real"
        assert record["source"] == "capture"
        assert record["split"] == "dev"
        assert record["runId"] == RUN.run_id
        assert record["captureDir"] == RUN.capture_dir.name
        assert record["captureManifest"] == before
        assert record["captureUnchanged"] is True
        assert set(record["codeVersion"]) == {"commit", "trackedChanges"}
        rows = {r["name"]: r["outcome"] for r in record["evaluation"]["results"]}
        assert rows["payload-privacy"] == "pass"
        # captureDir names the capture on purpose -- a folder name, not a path.
        # Everything else in the record must carry neither.
        rest = {key: value for key, value in record.items() if key != "captureDir"}
        leaks = real_runs.count_leaks(json.dumps(rest, ensure_ascii=False), RUN)
        assert leaks == 0

    # The same capture, the same payload, for both variants.
    assert v1["payloadHash"] == v3["payloadHash"]
    assert v1["promptHash"] != v3["promptHash"]
    assert v1["toolsOffered"] is False and v3["toolsOffered"] is True
    assert list(v1)[:4] == ["invocationStatus", "invocationSkippedReason", "case", "caseKind"]
    assert real_runs.capture_manifest(RUN.capture_dir) == before
    assert _capture_db_counts()[2] == 0


def test_a_real_baseline_name_cannot_collide_with_an_agent_one():
    from . import run_eval

    real = run_eval.baseline_path("real_cba73e", "v3", "2026-11-01")
    agent = run_eval.baseline_path("agent_failed_step", "v3", "2026-11-01")

    assert real.name.startswith("2026-11-01_real_cba73e_v3_")
    assert real != agent


def test_the_real_case_is_kept_apart_from_the_agent_and_frozen_groups():
    from . import run_eval

    assert set(run_eval.REAL_CASES.values()) == set(real_runs.REAL_RUNS)
    assert not set(run_eval.REAL_CASES.values()) & set(run_eval.AGENT_CASES.values())
    assert not set(run_eval.REAL_CASES.values()) & set(run_eval.CASES.values())


def test_the_runner_stops_before_calling_when_the_capture_is_missing(
    monkeypatch, capsys, tmp_path
):
    from . import run_eval

    monkeypatch.setitem(
        real_runs.REAL_RUNS,
        "real_cba73e",
        real_runs.RealRun(
            name="real_cba73e",
            intent="",
            capture_dir=tmp_path / ".capture_success_cba73e",
            run_id=RUN.run_id,
            split="dev",
        ),
    )

    def must_not_call(*_args, **_kwargs):
        raise AssertionError("the runner called the model without a capture")

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", must_not_call)
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "real", "--yes"])

    assert run_eval.main() == 2
    out = capsys.readouterr().out
    assert "capture가 이 환경에 없어 중단" in out
    assert ".capture_success_cba73e/" in out


def test_an_agent_record_keeps_its_key_order(monkeypatch):
    """The shared scoring path must not reshuffle a synthetic agent record."""
    from . import run_eval

    _fake_synthesis(monkeypatch, run_eval)
    record = run_eval.evaluate_agent("agent_no_tool_needed")

    assert list(record) == [
        "invocationStatus", "invocationSkippedReason", "case", "caseKind",
        "caseIntent", "variant", "toolsOffered", "recordedAt", "provider",
        "models", "durationMs", "configuredModel", "promptHash", "knowledgeHash",
        "schemaHash", "allowedRefCount", "toolUse", "trace", "evidenceUse",
        "expectedToolUse", "expectedStepIds", "acceptableStepSets", "evaluation",
        "humanReview", "available", "errorCategory", "output",
        # Appended, not inserted: evaluation-only, see explanation_quality.py.
        "explanationQuality",
    ]


# --- 12. the MCP server as a separate process --------------------------------


def _spawned(monkeypatch):
    """Keep every server process the stdio client starts, to check it exited."""
    import mcp.client.stdio as stdio

    started: list = []
    real_create = stdio._create_platform_compatible_process

    async def recording(*args, **kwargs):
        process = await real_create(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", recording)
    return started


def _call_over_stdio(server_config: dict, step_ids: list[str]):
    import anyio
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(
        command=server_config["command"],
        args=server_config["args"],
        env=server_config["env"],
    )

    async def go():
        with anyio.fail_after(60):
            async with Client(params) as client:
                listed = (await client.list_tools()).tools
                results = [
                    await client.call_tool("get_step_detail", {"stepId": step})
                    for step in step_ids
                ]
                return listed, results

    return anyio.run(go)


def _server_config(toolset) -> dict:
    from app.agent_mcp import launch

    return toolset.mcp_config["mcpServers"][launch.MCP_SERVER_KEY]


@needs_capture
def test_a_spawned_server_reads_the_restored_copy(monkeypatch):
    """The production launch config, a real child process, no model."""
    from app.services.agent.tool_sink import SINK_PATH_ENV
    from app.services.explanation.llm import tools

    started = _spawned(monkeypatch)
    before = real_runs.capture_manifest(RUN.capture_dir)

    with real_runs.materialise(RUN):
        work = Path(config.RUNS_ROOT).parent
        with tools.step_detail_toolset(RUN.run_id) as toolset:
            server = _server_config(toolset)
            sink_path = Path(server["env"][SINK_PATH_ENV])
            # The child is pointed at the temporary copy, never the capture.
            assert Path(server["env"]["WES_DB_PATH"]) == Path(config.DB_PATH)
            assert Path(server["env"]["WES_RUNS_ROOT"]) == Path(config.RUNS_ROOT)
            assert RUN.capture_dir.name not in json.dumps(server["env"])

            listed, results = _call_over_stdio(
                server, ["04_processing", "05_coverage_qc", "06_variant_calling"]
            )
            first = tools.observe(toolset.evidence(), toolset.attempts())

        with tools.step_detail_toolset(RUN.run_id) as toolset:
            _listed, (third,) = _call_over_stdio(
                _server_config(toolset), ["06_variant_calling"]
            )

    # One tool, and it takes a step id only: there is no run to name.
    assert [tool.name for tool in listed] == ["get_step_detail"]
    assert set(listed[0].input_schema["properties"]) == {"stepId"}

    # Budget of two: 04 and 05 open, 06 is refused; a fresh session opens 06.
    r04, r05, r06 = results
    assert r04.is_error is False and r05.is_error is False
    assert r06.is_error is True
    assert first.openedStepIds == ("04_processing", "05_coverage_qc")
    assert [r["reason"] for r in first.refusals] == ["budget"]
    assert third.is_error is False

    # Real evidence, as the capture recorded it.
    assert r04.structured_content["metrics"]["markdup_validation"] == "ONLY_NM"
    assert r04.structured_content["metrics"]["markdup_validation_after_calmd"] == "CLEAN"
    assert [w["code"] for w in r05.structured_content["warnings"]] == [
        "ZERO_COVERAGE_TARGET_BASES"
    ]
    assert [w["code"] for w in third.structured_content["warnings"]] == [
        "DBSNP_NOT_CONFIGURED"
    ]

    # Nothing identifying in anything the child said.
    said = json.dumps(
        [r.structured_content for r in (r04, r05, third)]
        + [[getattr(block, "text", "") for block in r06.content]],
        ensure_ascii=False,
    )
    leaks = _leaks(said, work)
    assert leaks == 0

    # The children exited, the sink went with its toolset, the capture held.
    assert len(started) == 2
    assert all(process.returncode is not None for process in started)
    assert not sink_path.exists()
    assert real_runs.capture_manifest(RUN.capture_dir) == before
    assert _capture_db_counts()[2] == 0


@needs_capture
def test_a_spawned_server_refuses_a_run_that_is_not_the_restored_one(monkeypatch):
    """Scope is the job id in the child's environment, checked against the DB.

    Another real run's id is not in the temporary database, so the child
    refuses to start -- it cannot fall back to the capture or another root.
    """
    from app.services.explanation.llm import tools

    started = _spawned(monkeypatch)

    with real_runs.materialise(RUN):
        with tools.step_detail_toolset(RUN.run_id) as toolset:
            server = _server_config(toolset)
            other = dict(
                server,
                env={**server["env"], "WES_AGENT_JOB_ID": "wes-20260904-172826-68aa20"},
            )
            with pytest.raises(Exception):
                _call_over_stdio(other, ["04_processing"])

    assert len(started) == 1
    assert started[0].returncode is not None
