"""Job endpoints.

  POST /api/jobs              front/src/pages/SubmitPage.tsx
  GET  /api/jobs/{id}         front/src/features/job/useJobStream.ts (polling)
  POST /api/jobs/{id}/cancel  front/src/features/job/useJobStream.ts (cancel)
  GET  /api/jobs/{id}/stream  intentionally 404 (see below)

POST returns as soon as the job is recorded and queued. It never waits for the
pipeline: a WES run takes hours.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from .. import config, db
from ..schemas import CreateJobRequest, CreateJobResponse, JobStateResponse, StepState
from ..services import config_builder, pipeline_executor, run_status_reader, worker
from . import uploads

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
UNSAFE_SAMPLE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_sample_id(raw: str) -> str:
    """main.sh's ID_RE is ^[A-Za-z0-9][A-Za-z0-9._-]*$ and it rejects the row
    outright otherwise, so the name is cleaned here rather than failing later."""
    cleaned = UNSAFE_SAMPLE_CHARS.sub("_", (raw or "").strip()).lstrip("._-")
    if not cleaned or not JOB_ID_RE.fullmatch(cleaned):
        raise HTTPException(
            status_code=400,
            detail=(
                f"sample id '{raw}' cannot be used. It must start with a letter or digit "
                "and contain only letters, digits, dot, underscore and hyphen."
            ),
        )
    return cleaned


@router.post("", response_model=CreateJobResponse, status_code=201)
@router.post("/", response_model=CreateJobResponse, status_code=201, include_in_schema=False)
def create_job(payload: CreateJobRequest) -> CreateJobResponse:
    if not payload.samples:
        raise HTTPException(status_code=400, detail="at least one sample is required")
    if len(payload.samples) > 1:
        # Not silently dropping the extras: main.sh's validate_samplesheet
        # enforces exactly one biological sample per run, so fanning out to
        # several runs is a real feature, not a formatting detail. Until it is
        # implemented the request is refused in full.
        names = ", ".join(s.sampleId for s in payload.samples)
        raise HTTPException(
            status_code=400,
            detail=(
                f"this build accepts one sample per submission, received {len(payload.samples)} "
                f"({names}). main.sh runs exactly one biological sample per run; submitting "
                "several at once needs multi-run fan-out, which is not implemented yet."
            ),
        )

    sample = payload.samples[0]
    missing = [slot for slot in ("r1", "r2") if not sample.files.get(slot)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"paired-end input requires both r1 and r2; missing: {', '.join(missing)}",
        )

    # Order matters: validate the cheap, self-contained parts of the request
    # before touching the upload store. Otherwise a submission with both a bad
    # capture kit and a bad token reports only the token problem, which is the
    # less useful of the two.
    options = dict(payload.options or {})

    requested_assembly = str(options.get("assembly") or "").strip()
    if requested_assembly and requested_assembly.lower() != config.ASSEMBLY.lower():
        raise HTTPException(
            status_code=400,
            detail=(
                f"requested assembly '{requested_assembly}' does not match the reference bundle "
                f"configured on this server ('{config.ASSEMBLY}')."
            ),
        )

    try:
        capture_kit_id = config_builder.resolve_capture_kit_id(payload.captureKitId, options)
    except config_builder.ConfigBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sample_id = _sanitize_sample_id(sample.sampleId)
    fastq_1 = uploads.resolve_token(sample.files["r1"])
    fastq_2 = uploads.resolve_token(sample.files["r2"])
    if fastq_1 == fastq_2:
        raise HTTPException(status_code=400, detail="r1 and r2 refer to the same uploaded file")

    supported, unsupported = config_builder.split_options(options)
    # One decision drives both the recorded plan and the generated config; see
    # resolve_intervar(). When the server cannot honour run_acmg the key moves
    # to the unsupported list rather than being quietly ignored, so the client
    # can see that the option it sent did not take effect.
    intervar, acmg_unavailable = config_builder.resolve_intervar(supported)
    if acmg_unavailable:
        unsupported = sorted({*unsupported, "run_acmg"})

    run_id = config_builder.new_run_id()
    job_dir = config.JOBS_ROOT / run_id
    samplesheet_path = job_dir / "samplesheet.csv"
    config_path = job_dir / "run_config.json"

    try:
        config_builder.write_samplesheet(samplesheet_path, sample_id, fastq_1, fastq_2)
        run_config = config_builder.build_run_config(
            run_id=run_id,
            samplesheet=samplesheet_path,
            capture_kit_id=capture_kit_id,
            intervar=intervar,
        )
        config_builder.write_run_config(config_path, run_config)
    except config_builder.ConfigBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write run inputs: {exc}") from exc

    planned = config_builder.planned_steps(config.RUN_MODE, intervar)
    run_dir = config.RUNS_ROOT / run_id

    db.execute(
        """INSERT INTO jobs
           (job_id, run_id, profile_id, capture_kit_id, status, run_dir, config_path,
            samplesheet_path, run_mode, planned_steps, original_options,
            unsupported_options, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            run_id,
            payload.profileId,
            capture_kit_id,
            worker.QUEUED,
            str(run_dir),
            str(config_path),
            str(samplesheet_path),
            config.RUN_MODE,
            json.dumps(planned),
            json.dumps(options),
            json.dumps(unsupported),
            db.now_iso(),
            db.now_iso(),
        ),
    )
    worker.submit(run_id)
    return CreateJobResponse(jobId=run_id)


def _load_job(job_id: str):
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise HTTPException(status_code=400, detail="malformed job id")
    row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="unknown job id")
    return row


# Backend orchestration state -> frontend status, used only while the pipeline
# has not written a run_status.json of its own.
_FALLBACK_STATUS = {
    worker.QUEUED: "queued",
    worker.RUNNING: "running",
    worker.CANCELLING: "running",
    worker.CANCELLED: "cancelled",
    worker.EXEC_FAILED: "failed",
    worker.DONE: "failed",  # exited without leaving a status document
}


@router.get("/{job_id}", response_model=JobStateResponse)
def get_job(job_id: str) -> JobStateResponse:
    row = _load_job(job_id)
    run_dir = Path(row["run_dir"])
    planned: list[str] = db.loads(row["planned_steps"], [])
    unsupported: list[str] = db.loads(row["unsupported_options"], [])

    adapted = run_status_reader.read(run_dir, planned, row["run_mode"])

    if adapted is None:
        # No run_status.json yet. Report the backend's own state; never guess a
        # pipeline status that was not written.
        status = _FALLBACK_STATUS.get(row["status"], "failed")
        error = row["error"]
        if status == "failed" and not error:
            error = "the pipeline exited without writing a run status document"
        steps = [
            StepState(stepId=step_id, status="pending") for step_id in planned
        ]
        return JobStateResponse(
            jobId=row["job_id"],
            runId=row["run_id"],
            profileId=row["profile_id"],
            status=status,
            progress=0,
            steps=steps,
            logTail=[],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            error=error,
            runMode=row["run_mode"],
            pipelineStatus=None,
            currentStep=None,
            unsupportedOptions=unsupported,
        )

    status = adapted["status"]
    # A cancel that the backend initiated but the pipeline could not record
    # (Windows: bash gets no trappable signal) must still read as cancelled.
    if row["status"] == worker.CANCELLED and status not in ("cancelled",):
        status = "cancelled"

    return JobStateResponse(
        jobId=row["job_id"],
        runId=row["run_id"],
        profileId=row["profile_id"],
        status=status,
        progress=adapted["progress"],
        steps=[StepState(**step) for step in adapted["steps"]],
        logTail=run_status_reader.read_log_tail(run_dir),
        startedAt=row["started_at"],
        finishedAt=row["finished_at"],
        error=adapted["error"] or row["error"],
        runMode=row["run_mode"],
        pipelineStatus=adapted["pipelineStatus"],
        currentStep=adapted["currentStep"],
        unsupportedOptions=unsupported,
    )


@router.post("/{job_id}/cancel", status_code=204)
def cancel_job(job_id: str) -> Response:
    row = _load_job(job_id)
    if row["status"] not in (worker.QUEUED, worker.RUNNING):
        return Response(status_code=204)

    if row["status"] == worker.QUEUED or not row["pid"]:
        db.update_job(job_id, status=worker.CANCELLED, finished_at=db.now_iso(),
                      error="cancelled before the pipeline started")
        return Response(status_code=204)

    db.update_job(job_id, status=worker.CANCELLING)
    ok, detail = pipeline_executor.terminate(row["pid"], row["pgid"])
    if not ok:
        db.update_job(job_id, error=f"cancellation problem: {detail}")
    return Response(status_code=204)


@router.get("/{job_id}/stream", include_in_schema=False)
def job_stream(job_id: str) -> Response:
    """Not implemented on purpose.

    useJobStream opens an EventSource here first and falls back to 3s polling on
    error, so returning 404 selects the polling path deterministically. Half of
    an SSE endpoint (one that connects and then drops) would put EventSource
    into a reconnect loop, which is strictly worse than not having one.
    """
    return Response(status_code=404, content=b"SSE is not implemented; poll GET /api/jobs/{id}")
