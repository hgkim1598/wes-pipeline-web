"""Compose one pipeline step's detail from the documents main.sh wrote for it.

This module reads nothing itself. It is the place where the three existing
readers are combined for a single step, so that no endpoint has to know how the
run directory is laid out:

    status + timing + validation   run_status_reader  (status/steps/<step>.json)
    metrics                        run_status_reader  (metrics/<step>.json)
    artifacts                      artifact_reader    (artifacts/*.json)
    warning / failure shapes       result_reader      (shared adapters)

Two consequences of main.sh's writing order shape everything here:

1. finish_step() writes the status, metrics and artifact documents together
   when a step ENDS. While a step runs, none of them exist. That is normal, not
   an error, and this module reports `running` with empty metrics rather than
   404. The elapsed time for that case comes from the STARTED row main.sh
   already appends in start_step().

2. A step's status is taken from run_status_reader.read(), the same call
   GET /api/jobs/{id} makes. The two endpoints cannot disagree about a step
   because neither of them decides its status independently.
"""

from __future__ import annotations

import logging
import ntpath
import re
from pathlib import Path, PurePosixPath
from typing import Any

from . import artifact_reader, result_reader, run_status_reader, stage_status_reader

log = logging.getLogger(__name__)

# Same shape main.sh accepts for a step id. The real gate is membership in the
# recorded plan below; this is a cheap, explicit rejection of anything that is
# not a step id at all, so a traversal attempt reads as 400 rather than 404.
STEP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StepNotPlanned(Exception):
    """The job exists, but this step is not part of the run it planned."""


def _is_absolute(value: str) -> bool:
    """True for anything that names a location outside any run directory.

    Both syntaxes are checked regardless of the host, because the document may
    have been written on the other one. A leading '..' is deliberately NOT
    absolute: '../_jobs/<run>/run_config.json' is the legitimate, documented
    form for the backend's own generated inputs.
    """
    return (
        PurePosixPath(value).is_absolute()
        or ntpath.isabs(value)
        or bool(ntpath.splitdrive(value)[0])
    )


def _io(raw: Any) -> list[dict[str, str]]:
    """Adapt a step's declared inputs or outputs, dropping absolute paths.

    main.sh records these with

        def rel(p):
            try:    return os.path.relpath(p, run_dir).replace(os.sep, "/")
            except ValueError: return p

    so the run-relative form is not guaranteed: on Windows, relpath() raises
    for an input on another drive than the run directory and the raw absolute
    path is stored instead. A reference bundle or upload root mounted
    elsewhere would therefore put a real server path into this response, and
    no API response in this backend returns one. Such an entry is dropped, the
    way artifact_reader drops a record whose path it cannot represent safely.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = str(item["path"])
        if "\\" in path or _is_absolute(path):
            log.warning("dropping absolute step io path from the response: %r", path)
            continue
        out.append({"type": str(item.get("type") or ""), "path": path})
    return out


def _step_artifacts(run_dir: Path, step_id: str) -> list[dict[str, Any]]:
    """This step's registered artifacts, via the shared reader.

    artifact_reader owns the path-containment and file_id rules; they are not
    reimplemented here. A run directory that does not exist yet (queued job) or
    an unreadable registry means this step has no artifacts to show, which is a
    fact worth reporting -- not a reason to fail the whole response.
    """
    try:
        collection = artifact_reader.collect(run_dir)
    except artifact_reader.ArtifactError:
        return []
    return [entry for entry in collection.entries if entry["stepId"] == step_id]


def _state_of(
    run_dir: Path, planned: list[str], run_mode: str, step_id: str
) -> dict[str, Any]:
    """Status and elapsed time, reconciled the way GET /api/jobs/{id} does."""
    adapted = run_status_reader.read(run_dir, planned, run_mode)
    if adapted is None:
        # No run_status.json: the pipeline has not started writing. Every
        # planned step is still ahead of it.
        return {"status": "pending", "elapsedSeconds": 0}
    for state in adapted["steps"]:
        if state["stepId"] == step_id:
            return state
    # build_steps() walks the same plan, so this is unreachable; falling back
    # to pending is still better than raising on a shape surprise.
    return {"status": "pending", "elapsedSeconds": 0}


def read(
    run_dir: Path | str, planned: list[str], run_mode: str, step_id: str
) -> dict[str, Any]:
    """Build the pipeline-derived half of the step detail response.

    The caller supplies jobId and runId.

    Raises ValueError for a step id that is not one, and StepNotPlanned for a
    well-formed id this run never planned. Both checks run before any path is
    assembled, so a client-supplied string never reaches the filesystem.
    """
    if not isinstance(step_id, str) or not STEP_ID_RE.fullmatch(step_id):
        raise ValueError("malformed step id")
    if step_id not in planned:
        raise StepNotPlanned(step_id)

    root = Path(run_dir)
    state = _state_of(root, planned, run_mode, step_id)
    doc = run_status_reader.read_step_document(root, step_id) or {}

    validation = doc.get("validation")
    validation = validation if isinstance(validation, dict) else {}

    started_at = _as_str(doc.get("started_at"))
    if started_at is None and state["status"] == "running":
        # The step document does not exist yet, but the pipeline recorded the
        # start; report it from the same row the elapsed time came from.
        started = stage_status_reader.step_started_at(root, step_id)
        started_at = started.isoformat() if started is not None else None

    exit_code = doc.get("exit_code")

    return {
        "stepId": step_id,
        "status": state["status"],
        "startedAt": started_at,
        "finishedAt": _as_str(doc.get("finished_at")),
        "elapsedSeconds": state["elapsedSeconds"],
        "exitCode": exit_code if isinstance(exit_code, int) else None,
        "inputs": _io(doc.get("inputs")),
        "outputs": _io(doc.get("outputs")),
        "validation": {
            "status": str(validation.get("status") or ""),
            "results": result_reader.checks_of(doc),
        },
        "metrics": run_status_reader.read_step_metrics(root, step_id),
        "artifacts": _step_artifacts(root, step_id),
        "warnings": result_reader.warnings_of(doc.get("warnings")),
        "failures": result_reader.failures_of(doc.get("failures")),
        "nextStepReady": doc.get("next_step_ready") is True,
    }


def _as_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None
