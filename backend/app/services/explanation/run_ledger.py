"""Which planned steps actually ran in this run -- a ledger, derived, never guessed.

Why this exists (2026-11-21)
----------------------------

run_status_reader reports a planned step with no step document as `pending`,
whatever the run's own state. That is right while a run is going -- the step is
still ahead -- but for a run that already ended it is a different fact: the step
never started. The frontend turned that into "실행 안 됨" on its own, and the
model saw only `pending`. Meanwhile knowledge and pipeline text that presume a
later step ran ("개별 FastQC 리포트는 정상적으로 생성되었습니다") reached the
explanation of a run that stopped before that step. Nothing compared the two.

This module states, per planned step, what the run's own records establish:

    ranCompleted / ranWarning / ranFailed / skipped   the step document's status
    running        the current step of a run that has not ended
    waiting        a later step of a run that has not ended
    notRunAfterFailure   no document; the run failed and an earlier step failed
    notRunCancelled      no document; the run was cancelled
    notRunAfterStop      no document; the run stopped at a requested step
    unknown        none of the above can be established

`unknown` is a result, not a fallback for convenience. Two examples that land
there on purpose: a step still marked running in a run that has ended (it
started, but nothing records how it ended), and a step with no document in a
run that says it completed (a missing record, not a skipped step).

It replaces nothing. The run's documents stay the source; each entry names the
record it was derived from (`source`) and why (`basis`), so the derivation can be
checked against the run.

Pure function of values the explanation already carries -- reads no file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Execution = Literal[
    "ranCompleted",
    "ranWarning",
    "ranFailed",
    "skipped",
    "running",
    "waiting",
    "notRunAfterFailure",
    "notRunCancelled",
    "notRunAfterStop",
    "unknown",
]

# Groups other modules ask about. Kept here so the meaning of a state is decided
# in one place.
RAN: frozenset[str] = frozenset({"ranCompleted", "ranWarning", "ranFailed"})
FINISHED_OK: frozenset[str] = frozenset({"ranCompleted", "ranWarning"})
NOT_RUN: frozenset[str] = frozenset({"notRunAfterFailure", "notRunCancelled", "notRunAfterStop"})

# Frontend JobStatus values (run_status_reader.RUN_STATUS_MAP and the backend
# fallback). Anything else is treated as "cannot tell whether the run ended".
_ACTIVE = frozenset({"queued", "running"})
_ENDED = frozenset({"completed", "completed_with_warnings", "failed", "cancelled"})

_FROM_DOCUMENT: dict[str, Execution] = {
    "completed": "ranCompleted",
    "warning": "ranWarning",
    "failed": "ranFailed",
    "skipped": "skipped",
}


class LedgerStep(BaseModel):
    stepId: str
    execution: Execution
    # Which record the state comes from: "step document", "run status".
    source: str
    # One Korean sentence: why this state, in terms of the records.
    basis: str


class RunLedger(BaseModel):
    """Per-step execution facts for one run.

    `stepsKnown` is False when the run has no step list at all (no run status
    document, or an explanation recorded before steps were carried). There are
    then no entries, and every question about a step is `unknown` -- an empty
    list must not read as "no step ran".
    """

    stepsKnown: bool
    runStatus: str
    pipelineStatus: str | None = None
    runEnded: bool | None
    steps: list[LedgerStep]

    def execution_of(self, step_id: str) -> Execution | Literal["notPlanned"] | None:
        """The step's state; "notPlanned" when the plan lacks it; None when unknowable."""
        if not self.stepsKnown:
            return None
        for step in self.steps:
            if step.stepId == step_id:
                return step.execution
        return "notPlanned"


def build_ledger(
    run_status: str,
    pipeline_status: str | None,
    steps: list[tuple[str, str]],
    *,
    recorded_current_step: str | None = None,
) -> RunLedger:
    """`steps` is (stepId, status) in plan order, as run_status_reader reports it.

    `recorded_current_step` is run_status.json's current_step as written. The
    reader clears it once a run has ended, so a cancelled run's step in flight
    arrives here as `pending`; this is how it is told apart from steps that
    never started.
    """
    ended: bool | None = (
        True if run_status in _ENDED else False if run_status in _ACTIVE else None
    )
    out: list[LedgerStep] = []
    failed_before = False

    for step_id, status in steps:
        execution: Execution
        if status in _FROM_DOCUMENT:
            execution = _FROM_DOCUMENT[status]
            entry = LedgerStep(
                stepId=step_id,
                execution=execution,
                source="step document",
                basis=f"단계 문서의 상태가 {status}입니다.",
            )
        elif status == "running":
            if ended is False:
                entry = LedgerStep(
                    stepId=step_id, execution="running", source="run status",
                    basis="끝나지 않은 실행의 현재 단계입니다.",
                )
            else:
                entry = LedgerStep(
                    stepId=step_id, execution="unknown", source="run status",
                    basis="실행은 끝났는데 이 단계는 실행 중으로 남아 있고, 끝난 기록이 없습니다.",
                )
        elif status == "pending" and ended is not False and step_id == recorded_current_step:
            entry = LedgerStep(
                stepId=step_id, execution="unknown", source="run status",
                basis="실행 기록이 마지막으로 진행 중이라고 적은 단계인데, 끝난 기록이 없습니다.",
            )
        elif status == "pending":
            entry = _pending(step_id, run_status, pipeline_status, ended, failed_before)
        else:
            entry = LedgerStep(
                stepId=step_id, execution="unknown", source="run status",
                basis="기록된 단계 상태를 해석할 수 없습니다.",
            )
        if entry.execution == "ranFailed":
            failed_before = True
        out.append(entry)

    return RunLedger(
        stepsKnown=bool(steps),
        runStatus=run_status,
        pipelineStatus=pipeline_status,
        runEnded=ended,
        steps=out,
    )


def _pending(
    step_id: str,
    run_status: str,
    pipeline_status: str | None,
    ended: bool | None,
    failed_before: bool,
) -> LedgerStep:
    """A planned step with no step document."""
    if ended is False:
        return LedgerStep(
            stepId=step_id, execution="waiting", source="run status",
            basis="끝나지 않은 실행에서 아직 차례가 오지 않은 단계입니다.",
        )
    if run_status == "failed" and failed_before:
        return LedgerStep(
            stepId=step_id, execution="notRunAfterFailure", source="run status",
            basis="앞 단계가 실패로 끝나 이 단계는 시작되지 않았습니다.",
        )
    if run_status == "cancelled":
        return LedgerStep(
            stepId=step_id, execution="notRunCancelled", source="run status",
            basis="실행이 취소되어 이 단계는 시작되지 않았습니다.",
        )
    if pipeline_status == "stopped_at_requested_step":
        return LedgerStep(
            stepId=step_id, execution="notRunAfterStop", source="run status",
            basis="요청한 단계까지만 실행하고 멈춰 이 단계는 시작되지 않았습니다.",
        )
    return LedgerStep(
        stepId=step_id, execution="unknown", source="run status",
        basis="단계 문서가 없고, 실행 기록만으로는 이 단계가 왜 없는지 판단할 수 없습니다.",
    )


__all__ = [
    "FINISHED_OK",
    "NOT_RUN",
    "RAN",
    "Execution",
    "LedgerStep",
    "RunLedger",
    "build_ledger",
]
