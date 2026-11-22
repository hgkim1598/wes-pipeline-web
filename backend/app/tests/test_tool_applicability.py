"""The tool sends no pipeline sentence the initial payload withheld (review H1, 2026-11-22).

`contract.build_payload` leaves out a pipeline impact sentence when the run's
ledger does not support it -- the preflight-time line "Per-lane FastQC still
runs" in a run that stopped before 01_raw_qc. `get_step_detail` returned the
same warning row with that sentence intact, so a model that opened the step
received what the payload had withheld. Both channels must apply the same
decision: the one `knowledgeDecisions` made for this run.
"""

from __future__ import annotations

from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.explanation import deterministic, run_context
from app.services.explanation.llm import contract

FASTQC = "Per-lane FastQC still runs; only the aggregated report is unavailable"
NM_MD = "Only the NM and MD tags changed; read sequence, CIGAR, coordinates and duplicate flags are preserved"


def _payload_row(job_id: str, code: str) -> dict:
    explanation = deterministic.build_run_explanation(run_context.build_run_diagnostic_context(job_id))
    payload, _allowed = contract.build_payload(explanation)
    return next(d for d in payload["diagnostics"] if d["code"] == code)


def test_h1_a_sentence_withheld_from_the_payload_is_withheld_from_the_tool(make_job, run):
    run("wes-h1-precheck").as_passing_precheck()
    job_id = make_job("wes-h1-precheck", run_mode="check_only", sample_id="SRR2962669.subset_5M")

    row = _payload_row(job_id, "MULTIQC_MISSING")
    assert row["impactFromPipeline"] is None  # the payload withholds it (precondition)

    evidence = read_step_evidence(run_scope.for_job(job_id), "00_input_validation")
    warning = next(w for w in evidence.warnings if w.code == "MULTIQC_MISSING")
    assert FASTQC not in (warning.impact or "")
    assert "FastQC" not in evidence.model_dump_json()


def test_h1_a_sentence_the_payload_sends_is_still_returned_by_the_tool(make_job, run):
    builder = run("wes-h1-processing")
    builder.step(
        "04_processing",
        status="warning",
        elapsed_seconds=10,
        checks=[{"name": "markdup_validation", "status": "PASS", "detail": "ok"}],
        warnings=[{"code": "NM_MD_REPAIRED", "message": "NM/MD tags were repaired", "impact": NM_MD, "can_continue": True}],
    )
    builder.run_status(
        "running",
        current_step="05_coverage_qc",
        steps=[{"step_id": "04_processing", "status": "warning", "exit_code": 0, "elapsed_seconds": 10,
                "warnings": 1, "failures": 0, "next_step_ready": True}],
    )
    job_id = make_job("wes-h1-processing", run_mode="full", sample_id="SRR2962669.subset_5M")

    assert _payload_row(job_id, "NM_MD_REPAIRED")["impactFromPipeline"] == NM_MD

    evidence = read_step_evidence(run_scope.for_job(job_id), "04_processing")
    assert [w.impact for w in evidence.warnings if w.code == "NM_MD_REPAIRED"] == [NM_MD]
