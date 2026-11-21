"""Run -> ledger -> knowledge decisions -> model payload, on built runs.

The defect this guards (2026-11-21): a run that failed at 00_input_validation
carried MULTIQC_MISSING, whose knowledge meaning said the per-lane FastQC reports
had been produced and whose pipeline impact said "Per-lane FastQC still runs".
01_raw_qc never started. Both sentences reached the model input under dx:, and
served answers repeated them.
"""

from __future__ import annotations

import json
import re

from ..services.explanation import deterministic, run_context
from ..services.explanation.llm import contract

FASTQC_CLAIM = re.compile(
    r"FastQC[^.。]*?(생성되|만들어지|만들어졌|그대로 있|still runs|unaffected|remain|영향이 없|영향을 받지)"
)
OLD_MULTIQC_IMPACT = "Per-lane FastQC still runs; only the aggregated report is unavailable"


def build(make_job, run, run_mode, setup, **job):
    run_id = make_job(run_mode=run_mode, **job)
    setup(run(run_id))
    return deterministic.build_run_explanation(run_context.build_run_diagnostic_context(run_id))


def _precheck_with_old_impact(builder):
    builder.step(
        "00_input_validation", status="failed",
        warnings=[{"code": "MULTIQC_MISSING", "message": "MultiQC is not installed",
                   "impact": OLD_MULTIQC_IMPACT, "can_continue": True}],
        failures=[{"code": "required_tools", "message": "missing from PATH: fastqc"}],
    )
    builder.run_status("check_only", current_step="00_input_validation",
                       steps=[{"step_id": "00_input_validation", "status": "failed", "exit_code": 1}])


def test_precheck_failure_sends_no_fastqc_claim(make_job, run):
    explanation = build(make_job, run, "check_only", _precheck_with_old_impact)

    payload, _ = contract.build_payload(explanation)
    texts = json.dumps(payload, ensure_ascii=False)

    assert not FASTQC_CLAIM.search(texts), FASTQC_CLAIM.search(texts).group(0)
    row = payload["diagnostics"][0]
    assert row["stepExecution"] == "ranFailed"
    assert row["impactFromPipeline"] is None
    assert {n["part"] for n in row["notSentForThisRun"]} == {"impactFromPipeline"}
    # The observation itself is untouched.
    assert row["messageFromPipeline"] == "MultiQC is not installed"


def test_the_withheld_claim_is_recorded_with_its_reason(make_job, run):
    explanation = build(make_job, run, "check_only", _precheck_with_old_impact)

    withheld = {d.part: d for d in explanation.knowledgeDecisions if d.withheld}
    assert withheld["impact"].decision == "notApplicable"
    assert "01_raw_qc" in (withheld["impact"].reason or "")
    assert withheld["grounding.scope.2"].decision in ("notApplicable", "unknown")
    assert not any(d.decision == "unknown" and not d.withheld for d in explanation.knowledgeDecisions)


def test_full_run_keeps_the_same_claim(make_job, run):
    """Same code, same knowledge -- applicable once 01_raw_qc has run.

    The withholding is conditional, not a deletion: the FastQC sentence the
    precheck run lost is still sent for a run where it is true.
    """
    explanation = build(make_job, run, "full", lambda b: b.as_completed_full())
    payload, _ = contract.build_payload(explanation)

    row = next(r for r in payload["diagnostics"] if r["code"] == "MULTIQC_MISSING")
    # The fixture has no 01_raw_qc document, so the step itself is unknown; the
    # occurrence recorded AT 01_raw_qc is what establishes that QC ran.
    assert row["occurredAtStep"]
    assert row["meaning"]
    scope = payload["grounding"]["dx:MULTIQC_MISSING"]["scope"]
    assert any("FastQC" in claim["statement"] for claim in scope)


def test_an_unregistered_impact_line_is_withheld_not_trusted(make_job, run):
    """The full fixture's impact is test-only wording main.sh never wrote.

    Whether it fits the run cannot be decided, so it is left out of the model
    input -- with the reason -- and kept in the run record.
    """
    explanation = build(make_job, run, "full", lambda b: b.as_completed_full())
    payload, _ = contract.build_payload(explanation)

    row = next(r for r in payload["diagnostics"] if r["code"] == "MULTIQC_MISSING")
    assert row["impactFromPipeline"] is None
    assert [n["part"] for n in row["notSentForThisRun"]] == ["impactFromPipeline"]
    recorded = next(d for d in explanation.diagnostics if d.code == "MULTIQC_MISSING")
    assert recorded.impact  # the record is unchanged


def test_steps_carry_the_ledger_state(make_job, run):
    explanation = build(make_job, run, "full", lambda b: b.as_failing_precheck())

    payload, _ = contract.build_payload(explanation)
    executions = [row["execution"] for row in payload["steps"]["planned"]]
    assert executions[0] == "ranFailed"
    # Not "pending": a run that ended never got to these steps.
    assert "pending" not in executions and "waiting" not in executions


def test_provenance_says_which_fields_are_observed():
    assert contract.PROVENANCE["messageFromPipeline"].startswith("observed")
    assert not contract.PROVENANCE["meaning"].startswith("observed")
    assert not contract.PROVENANCE["impactFromPipeline"].startswith("observed")
