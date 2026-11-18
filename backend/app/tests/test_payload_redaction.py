"""The first payload goes through the same redactor as everything else (P1).

`build_payload` copies pipeline-written strings into the model's prompt: a
failure message, a limitation statement, a check detail. Before this change
none of them was redacted, so a message such as "cannot open
/home/<user>/runs/<sample>/x.bam" would reach the external model verbatim even
though `get_step_detail`, the browser log and the step API all redact that same
text (services/agent/privacy.py, services/public_text.py).

What is under test:

  * every run-written free-text field passes through `Redactor.release`
    (fail-closed) when a redactor is supplied;
  * the fields that are not run-written -- knowledge text, registered codes,
    step ids, numbers -- are byte-for-byte unchanged, so the redaction does not
    erase the diagnosis it is meant to protect;
  * evidence ids built from a run-composed failure code carry the redacted
    code, stay unique, and are exactly the ids the payload exposes.

No process is started and nothing is sent anywhere.
"""

from __future__ import annotations

import json
import re

import pytest

from ..services.agent.privacy import WITHHELD, Redactor
from ..services.explanation import deterministic, run_context
from ..services.explanation.deterministic import (
    DiagnosticExplanation,
    EvidenceRef,
    FailureExplanation,
    Limitation,
)
from ..services.explanation.llm import contract, prompt
from ..services.explanation.run_context import RunCheck

SAMPLE = "PATIENT_X42_canary"
RUN = "run-20260101-canary"
JOB = "job-0f0e0d0c-canary"
REDACTOR = Redactor(literals=((JOB, "<job>"), (RUN, "<run>"), (SAMPLE, "<sample>")))

WINDOWS = r"C:\Users\jdoecanary\wes\runs\a.bam"
LINUX = "/home/jdoecanary/wes/runs/a.bam"
SPACED = r"C:\Users\jdoe canary\My Runs\a b.bam"
RELATIVE = "runs/batch1/a.sorted.bam"
FILENAME = f"{SAMPLE}.raw.vcf.gz"

# Values that may never appear anywhere in the outbound payload or prompt.
FORBIDDEN = (SAMPLE, RUN, JOB, "jdoecanary", "jdoe canary", "batch1", "C:\\", "/home/")


@pytest.fixture
def base(client, make_job, run):
    job = make_job()
    run(job).as_completed_full()
    return deterministic.build_run_explanation(run_context.build_run_diagnostic_context(job))


def _tainted(base: deterministic.RunExplanation) -> deterministic.RunExplanation:
    """`base` with an identifier or a path in every run-written string."""
    ev = EvidenceRef(section="failures")
    failures = [
        FailureExplanation(
            code=f"sort_order_{SAMPLE}.L001",
            message=f"samtools failed on {LINUX}: truncated file",
            actualStepId="04_processing",
            evidence=ev,
        ),
        FailureExplanation(
            code=f"sort_order_{SAMPLE}.L002",
            message=f"cannot open {WINDOWS} (No such file)",
            actualStepId="04_processing",
            evidence=ev,
        ),
        FailureExplanation(
            code="bwa_mem",
            message=f"input {SPACED} for {SAMPLE} in {RUN}",
            actualStepId="03_alignment",
            evidence=ev,
        ),
        FailureExplanation(
            code="gatk_haplotypecaller",
            message=f"see {RELATIVE} and {FILENAME}; job {JOB}",
            actualStepId="06_variant_calling",
            evidence=ev,
        ),
        FailureExplanation(
            code="already_clean",
            message="input <path> was <sample>-redacted already",
            actualStepId="06_variant_calling",
            evidence=ev,
        ),
        FailureExplanation(
            code="long_message",
            message=("word " * 400) + LINUX,
            actualStepId="06_variant_calling",
            evidence=ev,
        ),
    ]
    diagnostics = list(base.diagnostics) + [
        DiagnosticExplanation(
            code="NM_MD_REPAIRED",
            actualStepLabel=f"step for {SAMPLE}",
            message=f"repaired tags in {LINUX}",
            impact=f"output written to {WINDOWS}",
            knowledgeAvailable=False,
            evidence=EvidenceRef(section="diagnostics"),
        )
    ]
    limitations = list(base.limitations) + [
        Limitation(code="sample_scope", statement=f"applies to {SAMPLE} only", basis="test"),
    ]
    summary = base.checkSummary.model_copy(
        update={
            "notable": [
                RunCheck(name=f"bam_{SAMPLE}", status="FAIL", detail=f"missing {LINUX}"),
                RunCheck(name="fastq_pairing", status="WARN", detail="R1/R2 read counts differ"),
            ]
        }
    )
    update: dict = {
        "failures": failures,
        "diagnostics": diagnostics,
        "limitations": limitations,
        "checkSummary": summary,
        "resultsUnavailableReason": f"report missing under {LINUX}",
        "intendedUse": f"research use; produced for {SAMPLE}",
    }
    if base.coverage is not None:
        update["coverage"] = base.coverage.model_copy(
            update={"medianNote": f"median not computed for {WINDOWS}"}
        )
    if base.variantCalling is not None:
        update["variantCalling"] = base.variantCalling.model_copy(
            update={"coreEndpoint": f"raw calls in {LINUX}"}
        )
    return base.model_copy(update=update)


def _strings(obj, where=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _strings(value, f"{where}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _strings(value, f"{where}[{index}]")
    elif isinstance(obj, str):
        yield where, obj


def _leaks(payload: dict) -> list[str]:
    text = json.dumps(payload, ensure_ascii=False) + prompt.build_user_prompt(payload)
    found = [bad for bad in FORBIDDEN if bad.lower() in text.lower()]
    found += [where for where, value in _strings(payload) if Redactor.has_residual(value)]
    return found


# --- the defect --------------------------------------------------------------


def test_without_the_jobs_literals_the_sample_name_still_reaches_the_payload(base):
    """Positive control: shape rules alone do not know the sample name.

    Keeps the canaries honest -- if the sample name stopped reaching the
    payload here, the leak test below could pass for the wrong reason. It also
    shows why the route must pass the job's own redactor: the default (shapes
    only) removes paths but cannot recognise a bare identifier.
    """
    payload, _ = contract.build_payload(_tainted(base))
    text = json.dumps(payload, ensure_ascii=False)
    assert SAMPLE in text and RUN in text


def test_no_identifier_or_path_reaches_the_payload_or_prompt(base):
    payload, _ = contract.build_payload(_tainted(base), redactor=REDACTOR)
    assert _leaks(payload) == []


def test_default_build_payload_applies_shape_rules(base):
    """No redactor given (evals, older callers): paths still never go out."""
    payload, _ = contract.build_payload(_tainted(base))
    for where, value in _strings(payload):
        if where.startswith((".failures", ".diagnostics", ".checkSummary", ".run")):
            assert "/home/" not in value and "C:\\" not in value, where


# --- what must survive -------------------------------------------------------


def test_diagnostic_content_survives_redaction(base):
    payload, _ = contract.build_payload(_tainted(base), redactor=REDACTOR)
    messages = [f["messageFromPipeline"] for f in payload["failures"]]
    # Tool names and the actual cause stay readable.
    assert messages[0] == "samtools failed on <path>: truncated file"
    assert messages[1].startswith("cannot open <path>") and "(No such file)" in messages[1]
    assert "<sample>" in messages[2] and "<run>" in messages[2]
    assert "<job>" in messages[3]
    # Already-redacted text is left alone, not double-redacted or withheld.
    assert messages[4] == "input <path> was <sample>-redacted already"
    # A long string is capped, not dropped.
    assert messages[5].startswith("word word") and messages[5] != WITHHELD
    checks = {row["name"]: row for row in payload["checkSummary"]["notable"]}
    assert checks["fastq_pairing"]["detail"] == "R1/R2 read counts differ"
    assert checks["bam_<sample>"]["detail"] == "missing <path>"
    assert payload["run"]["resultsUnavailableReason"] == "report missing under <path>"


def test_registered_codes_and_knowledge_text_are_unchanged(base):
    """Redaction touches run-written text only, never the knowledge layer."""
    before, before_refs = contract.build_payload(base)
    after, after_refs = contract.build_payload(base, redactor=REDACTOR)
    assert before == after
    assert before_refs == after_refs


def test_composed_failure_code_is_redacted_in_the_evidence_id(base):
    payload, allowed = contract.build_payload(_tainted(base), redactor=REDACTOR)
    ids = [f["evidenceId"] for f in payload["failures"]]
    assert "fail:sort_order_<sample>.L001" in ids
    assert "fail:sort_order_<sample>.L002" in ids
    assert len(ids) == len(set(ids))
    assert set(ids) <= allowed
    assert not any(SAMPLE.lower() in ref.lower() for ref in allowed)
    # A plain code is untouched.
    assert "fail:bwa_mem" in ids


def test_codes_that_collapse_to_one_public_form_stay_distinct(base):
    """Two raw codes that redact to the same text still get two ids."""
    ev = EvidenceRef(section="failures")
    expl = base.model_copy(
        update={
            "failures": [
                FailureExplanation(code=f"x_{SAMPLE}", message="a", evidence=ev),
                FailureExplanation(code="x_<sample>", message="b", evidence=ev),
            ]
        }
    )
    payload, allowed = contract.build_payload(expl, redactor=REDACTOR)
    ids = [f["evidenceId"] for f in payload["failures"]]
    assert len(set(ids)) == 2 and set(ids) <= allowed


def test_missing_sample_id_still_redacts_paths(base):
    """A job with no sample_id has a redactor with no literals: shapes only."""
    payload, _ = contract.build_payload(_tainted(base), redactor=Redactor())
    text = json.dumps(payload, ensure_ascii=False)
    assert "/home/" not in text and "C:\\\\" not in text


def test_a_value_the_redactor_cannot_clean_is_withheld_not_sent(base):
    """Fail-closed: release() withholding is honoured, not bypassed."""
    ev = EvidenceRef(section="failures")
    tricky = f"see {SAMPLE[:4]}/{SAMPLE[4:]}/x/y"
    expl = base.model_copy(
        update={"failures": [FailureExplanation(code="t", message=tricky, evidence=ev)]}
    )
    payload, _ = contract.build_payload(expl, redactor=Redactor(literals=((SAMPLE, "<sample>"),)))
    message = payload["failures"][0]["messageFromPipeline"]
    assert SAMPLE.lower() not in message.lower()
    assert not Redactor.has_residual(message)


# --- the route passes the job's own redactor ---------------------------------


def test_the_route_sends_no_job_identifier_to_the_provider(client, make_job, run, monkeypatch):
    """End to end through POST /synthesis with a capturing provider stub.

    The run's failure message is rewritten to carry the job's real sample id,
    its job id and an absolute path -- the shape a pipeline error takes. What
    the provider receives must hold none of them, and must still hold the
    cause. No process is started.
    """
    from ..api import synthesis as synthesis_api
    from ..services.explanation.llm import provider
    from ..services.explanation.llm import synthesis as llm_synthesis

    sample = "ROUTE_SAMPLE_canary7"
    job = make_job(sample_id=sample)
    run(job).as_completed_full()

    real_build = synthesis_api.deterministic.build_run_explanation

    def build(context):
        expl = real_build(context)
        bad = FailureExplanation(
            code=f"sort_order_{sample}.L001",
            message=f"samtools sort failed for {job}: cannot open /srv/wes/{sample}/a.bam",
            actualStepId="04_processing",
            evidence=EvidenceRef(section="failures"),
        )
        return expl.model_copy(update={"failures": [*expl.failures, bad]})

    seen: dict = {}

    def capture(**kwargs):
        seen.update(kwargs)
        raise provider.ProviderError("providerFailed", "stub")

    monkeypatch.setattr(synthesis_api.deterministic, "build_run_explanation", build)
    monkeypatch.setattr(llm_synthesis.provider, "run_structured", capture)

    assert client.post(f"/api/jobs/{job}/synthesis").status_code == 200
    sent = seen["user_prompt"]
    assert sample.lower() not in sent.lower()
    assert job.lower() not in sent.lower()
    assert "/srv/wes" not in sent
    # job_id and run_id are the same string in the current schema; whichever
    # placeholder wins, the cause and the tool name stay readable.
    assert re.search(r"samtools sort failed for <(job|run)>: cannot open <path>", sent)
    assert "fail:sort_order_<sample>.L001" in sent
