"""The one place a job's reported status is put together.

A job has two records and neither is enough alone:

  the job row (db.jobs.status)    the backend's orchestration state: queued,
                                  driving a process, process exited, cancelled
  run_status.json (main.sh)       the pipeline's own verdict while it can write one

The contract, in the order it is applied:

1. No run_status.json: report the row's state through FALLBACK_STATUS. A
   pipeline status that was never written is never guessed.
2. run_status.json exists: it is the authority on the pipeline's verdict --
   except that `running` is only true while the process that writes it lives.
   Once the row says the process has exited (PROCESS_ENDED), a document still
   reading `running` is reported as failed (run_status_reader.INTERRUPTED_ERROR).
   An unknown outcome is never reported as success, and never as still running.
3. A cancel the backend recorded (CANCELLED) reads as cancelled whatever the
   document says, because on Windows main.sh gets no signal it can trap.

Before this module the rules lived in four copies (GET /api/jobs, the job list,
/results, the explanation context) and the step reader applied none of them.
Each copy had to be told about every new case; rule 2 had been told to none.
Every reader of a job's status -- API, explanation, agent tool -- now asks here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .. import db
from . import run_status_reader, worker

# Backend orchestration state -> reported status, used only while the pipeline
# has written no run_status.json of its own.
FALLBACK_STATUS: dict[str, str] = {
    worker.QUEUED: "queued",
    worker.RUNNING: "running",
    worker.CANCELLING: "running",
    worker.CANCELLED: "cancelled",
    worker.EXEC_FAILED: "failed",
    worker.DONE: "failed",  # exited without leaving a status document
}

# Row states in which no process is driving the run any more. QUEUED has not
# started one; RUNNING and CANCELLING still have one (worker.py supervises it,
# including after a backend restart).
PROCESS_ENDED: frozenset[str] = frozenset({worker.DONE, worker.EXEC_FAILED, worker.CANCELLED})

NO_STATUS_DOCUMENT_ERROR = "the pipeline exited without writing a run status document"


def process_ended(row: Mapping[str, Any]) -> bool:
    return row["status"] in PROCESS_ENDED


def _planned(row: Mapping[str, Any]) -> list[str]:
    return db.loads(row["planned_steps"], [])


def _apply_cancel(row: Mapping[str, Any], status: str, error: str | None) -> tuple[str, str | None]:
    """Rule 3. The interrupted-run explanation does not belong to a cancel."""
    if row["status"] == worker.CANCELLED and status != "cancelled":
        if error == run_status_reader.INTERRUPTED_ERROR:
            error = None
        return "cancelled", error
    return status, error


def read(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """run_status_reader.read() for this job, with rules 2 and 3 applied.

    None means no run_status.json (rule 1 is the caller's: see fallback()).
    """
    adapted = run_status_reader.read(
        Path(row["run_dir"]), _planned(row), row["run_mode"], process_ended=process_ended(row)
    )
    if adapted is None:
        return None
    adapted["status"], adapted["error"] = _apply_cancel(row, adapted["status"], adapted["error"])
    return adapted


def read_summary(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """run_status_reader.read_summary() for this job, with rules 2 and 3 applied."""
    summary = run_status_reader.read_summary(Path(row["run_dir"]), process_ended=process_ended(row))
    if summary is None:
        return None
    summary["status"], _ = _apply_cancel(row, summary["status"], None)
    return summary


def fallback(row: Mapping[str, Any]) -> tuple[str, str | None]:
    """Rule 1: (status, error) from the row alone."""
    status = FALLBACK_STATUS.get(row["status"], "failed")
    error = row["error"]
    if status == "failed" and not error:
        error = NO_STATUS_DOCUMENT_ERROR
    return status, error


def status_of(row: Mapping[str, Any]) -> str:
    """Just the reported status, as GET /api/jobs/{id} reports it."""
    adapted = read(row)
    return adapted["status"] if adapted is not None else fallback(row)[0]
