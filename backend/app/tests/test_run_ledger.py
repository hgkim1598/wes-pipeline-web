"""run_ledger: per-step execution facts, derived from the run's own records.

Each case below is a run shape the ledger must tell apart. The one that started
this (2026-11-21): a run that failed at 00 reported 01..99 as `pending`, the
same word a running run uses for steps still ahead.
"""

from __future__ import annotations

from ..services.explanation.run_ledger import build_ledger

PLAN = [
    "00_input_validation",
    "01_raw_qc",
    "02_preprocessing",
    "03_alignment",
]


def states(ledger):
    return [s.execution for s in ledger.steps]


def test_documents_map_to_ran_states():
    ledger = build_ledger(
        "completed_with_warnings",
        "completed_with_warnings",
        [("00_input_validation", "completed"), ("01_raw_qc", "warning"),
         ("02_preprocessing", "skipped"), ("03_alignment", "failed")],
    )
    assert states(ledger) == ["ranCompleted", "ranWarning", "skipped", "ranFailed"]
    assert all(s.source == "step document" for s in ledger.steps)


def test_steps_after_a_failure_did_not_run():
    ledger = build_ledger(
        "failed", "failed", [("00_input_validation", "failed")] + [(s, "pending") for s in PLAN[1:]]
    )
    assert states(ledger) == ["ranFailed"] + ["notRunAfterFailure"] * 3


def test_pending_in_a_live_run_is_waiting_not_not_run():
    ledger = build_ledger(
        "running", "running",
        [("00_input_validation", "completed"), ("01_raw_qc", "running"),
         ("02_preprocessing", "pending"), ("03_alignment", "pending")],
    )
    assert states(ledger) == ["ranCompleted", "running", "waiting", "waiting"]
    assert ledger.runEnded is False


def test_cancelled_run_marks_the_step_in_flight_unknown():
    """The reader clears current_step for an ended run; the raw value is kept."""
    ledger = build_ledger(
        "cancelled", None,
        [("00_input_validation", "completed"), ("01_raw_qc", "pending"),
         ("02_preprocessing", "pending"), ("03_alignment", "pending")],
        recorded_current_step="01_raw_qc",
    )
    assert states(ledger) == ["ranCompleted", "unknown", "notRunCancelled", "notRunCancelled"]


def test_stopped_at_requested_step():
    ledger = build_ledger(
        "completed", "stopped_at_requested_step",
        [("00_input_validation", "completed"), ("01_raw_qc", "pending")],
    )
    assert states(ledger) == ["ranCompleted", "notRunAfterStop"]


def test_missing_document_in_a_completed_run_is_unknown_not_skipped():
    ledger = build_ledger(
        "completed", "completed",
        [("00_input_validation", "completed"), ("01_raw_qc", "pending")],
    )
    assert states(ledger) == ["ranCompleted", "unknown"]


def test_failed_run_without_a_failed_step_is_unknown():
    """`failed` alone does not say which step stopped it."""
    ledger = build_ledger("failed", None, [(s, "pending") for s in PLAN])
    assert set(states(ledger)) == {"unknown"}


def test_running_step_left_in_an_ended_run_is_unknown():
    ledger = build_ledger("failed", "failed", [("00_input_validation", "running")])
    assert states(ledger) == ["unknown"]


def test_no_step_list_answers_none_not_not_run():
    ledger = build_ledger("failed", None, [])
    assert ledger.stepsKnown is False
    assert ledger.execution_of("01_raw_qc") is None


def test_a_step_outside_the_plan_is_not_planned():
    ledger = build_ledger("completed", "completed", [("00_input_validation", "completed")])
    assert ledger.execution_of("06_variant_calling") == "notPlanned"


def test_every_entry_carries_a_basis():
    ledger = build_ledger(
        "failed", "failed", [("00_input_validation", "failed"), ("01_raw_qc", "pending")]
    )
    assert all(s.basis and s.source for s in ledger.steps)
