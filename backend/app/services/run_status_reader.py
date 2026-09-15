"""Adapt the pipeline's own status documents to what the frontend renders.

Source of truth, in order:

  <run_dir>/status/run_status.json     run-level state + current_step
  <run_dir>/status/steps/<step>.json   per-step state, warnings, failures

logs/pipeline.log is read only to fill `logTail` for the log viewer. It is never
consulted to decide a status: main.sh's own docs are explicit that the JSON
documents are the machine contract and the log is the human record.

Three things have to be reconciled here:

1. main.sh has eight run states; the frontend understands six.
2. main.sh writes a step document only when a step *finishes*, so "running" and
   "pending" do not exist on disk. The running step is run_status.current_step;
   everything else is inferred from the plan the backend recorded at submit time.
3. main.sh has no progress field, so progress is derived from the plan. It is
   never a function of elapsed time.

The one thing a finished step document cannot supply is how long the *current*
step has been running, because the document does not exist yet. That single
value comes from logs/stage_status.tsv via stage_status_reader; see there for
why that file is the pipeline's own record and not a log-parsing heuristic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import stage_status_reader

LOG_TAIL_LINES = 200

# main.sh run status -> frontend JobStatus.
# check_only is absent on purpose: its outcome depends on whether
# 00_input_validation passed, so it is resolved separately.
RUN_STATUS_MAP = {
    "running": "running",
    "completed": "completed",
    "completed_with_warnings": "completed_with_warnings",
    "failed": "failed",
    "cancelled": "cancelled",
    # A refused resume is a hard stop for this run; the reason is surfaced in
    # `error` rather than being flattened into a success state.
    "resume_refused": "failed",
    # --to-step is a deliberate stop, so the run did what it was asked to do.
    "stopped_at_requested_step": "completed",
}

# main.sh step status -> frontend StepStatus.
# `cancelled` has no icon in the frontend's ICON_MAP and would silently render
# as `pending`, so it is mapped to `failed`, which is what it means for the run.
STEP_STATUS_MAP = {
    "completed": "completed",
    "warning": "warning",
    "failed": "failed",
    "skipped": "skipped",
    "cancelled": "failed",
}

TERMINAL_STEP_STATES = {"completed", "warning", "skipped"}


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a status document, tolerating a concurrent atomic replace.

    main.sh writes every document as <name>.part and then os.replace()s it, so a
    torn read is not possible; a missing file or a transient permission error on
    Windows during the rename is, and both mean "no update yet".
    """
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def read_log_tail(run_dir: Path, limit: int = LOG_TAIL_LINES) -> list[str]:
    log_path = run_dir / "logs" / "pipeline.log"
    if not log_path.is_file():
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def read_step_document(run_dir: Path, step_id: str) -> dict[str, Any] | None:
    return _read_json(run_dir / "status" / "steps" / f"{step_id}.json")


def read_step_metrics(run_dir: Path, step_id: str) -> dict[str, Any]:
    """The step's own metric object, exactly as main.sh recorded it.

    finish_step() writes metrics/<step>.json at the same moment as the status
    document, so an absent file means the step has not finished yet -- not an
    error. The inner object is passed through untouched: its keys are the
    pipeline's metric identifiers (mapped_pct, percent_duplication, ...), and
    adding a step_metric call to main.sh must not require a backend change.
    """
    doc = _read_json(run_dir / "metrics" / f"{step_id}.json")
    metrics = doc.get("metrics") if doc is not None else None
    return metrics if isinstance(metrics, dict) else {}


def _step_messages(doc: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for warning in doc.get("warnings") or []:
        if isinstance(warning, dict) and warning.get("message"):
            code = warning.get("code")
            messages.append(f"[{code}] {warning['message']}" if code else str(warning["message"]))
    for failure in doc.get("failures") or []:
        if isinstance(failure, dict) and failure.get("message"):
            code = failure.get("code")
            messages.append(f"[{code}] {failure['message']}" if code else str(failure["message"]))
    return messages


def build_steps(
    run_dir: Path, planned: list[str], current_step: str | None
) -> tuple[list[dict[str, Any]], int]:
    """Merge the recorded plan with what is on disk.

    Returns (steps, completed_count).
    """
    steps: list[dict[str, Any]] = []
    completed = 0

    for step_id in planned:
        doc = read_step_document(run_dir, step_id)
        if doc is not None:
            raw = str(doc.get("status", ""))
            status = STEP_STATUS_MAP.get(raw, "failed")
            if raw in TERMINAL_STEP_STATES:
                completed += 1
            steps.append(
                {
                    "stepId": step_id,
                    "status": status,
                    "elapsedSeconds": int(doc.get("elapsed_seconds") or 0),
                    "messages": _step_messages(doc),
                }
            )
            continue

        # No document: the step is either the one in flight or still ahead of
        # it. Only the running step has a start the pipeline has recorded, so
        # only it can report an elapsed time; a pending step stays at 0.
        status = "running" if step_id == current_step else "pending"
        elapsed = (
            stage_status_reader.running_elapsed_seconds(run_dir, step_id)
            if status == "running"
            else 0
        )
        steps.append(
            {
                "stepId": step_id,
                "status": status,
                "elapsedSeconds": elapsed,
                "messages": [],
            }
        )

    return steps, completed


def _check_only_status(run_dir: Path) -> tuple[str, str | None]:
    """Resolve the frontend status of a --check-only run.

    `check_only` only says the preflight finished, not whether it passed, so the
    verdict comes from 00_input_validation.
    """
    doc = read_step_document(run_dir, "00_input_validation")
    if doc is None:
        return "failed", "preflight produced no status document for 00_input_validation"
    raw = str(doc.get("status", ""))
    if raw in TERMINAL_STEP_STATES:
        return ("completed_with_warnings" if raw == "warning" else "completed"), None
    failures = [f.get("message") for f in (doc.get("failures") or []) if isinstance(f, dict)]
    reason = "; ".join(m for m in failures if m) or "preflight validation failed"
    return "failed", reason


def _collect_failure_reason(run_dir: Path, run_status: dict[str, Any]) -> str | None:
    for step_id in run_status.get("failed_steps") or []:
        doc = read_step_document(run_dir, str(step_id))
        if not doc:
            continue
        messages = [f.get("message") for f in (doc.get("failures") or []) if isinstance(f, dict)]
        joined = "; ".join(m for m in messages if m)
        if joined:
            return f"{step_id}: {joined}"
    return None


def read(run_dir: Path, planned: list[str], run_mode: str) -> dict[str, Any] | None:
    """Return the adapted view, or None when the pipeline has written nothing yet.

    None means "no run_status.json"; the caller then falls back to the backend's
    own orchestration state (queued / executor failure / cancelled). A status is
    never fabricated here.
    """
    run_status = _read_json(run_dir / "status" / "run_status.json")
    if run_status is None:
        return None

    pipeline_status = str(run_status.get("status") or "")
    current_step = run_status.get("current_step") or None

    error: str | None = None
    if pipeline_status == "check_only":
        status, error = _check_only_status(run_dir)
        current_step = None
    else:
        status = RUN_STATUS_MAP.get(pipeline_status)
        if status is None:
            # Never fall through to "queued": an unrecognised state is a real
            # problem and must be visible.
            status = "failed"
            error = f"unrecognised pipeline status '{pipeline_status}'"
        elif status == "failed":
            error = _collect_failure_reason(run_dir, run_status) or (
                "resume refused: the configuration changed since this run was created"
                if pipeline_status == "resume_refused"
                else "pipeline reported failure"
            )

    if status != "running":
        current_step = None

    steps, completed = build_steps(run_dir, planned, current_step)
    progress = int(round(completed / len(planned) * 100)) if planned else 0

    return {
        "status": status,
        "progress": progress,
        "steps": steps,
        "error": error,
        "pipelineStatus": pipeline_status,
        "currentStep": current_step,
        "runMode": run_mode,
    }
