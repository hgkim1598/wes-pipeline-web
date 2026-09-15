"""Result endpoints.

  GET /api/jobs/{id}/results                       one summary, two result types
  GET /api/jobs/{id}/artifacts                     what the run registered
  GET /api/jobs/{id}/artifacts/{file_id}/download  one registered file

A separate router on the same prefix as jobs.py, so the job endpoints stay
exactly as they were. Everything here is thin: the services decide, this module
maps their outcomes onto status codes.

Status codes, and why:

  400  the job id or file id is malformed          the client can fix it
  403  the artifact is not downloadable            exists, deliberately withheld
  404  no such job, or no such file id             the thing does not exist
  409  the run has not produced this yet           the job exists, state differs
  410  registered, but the file is gone            it existed and was recorded
  500  a pipeline document is unparseable, or      server-side data fault; the
       describes a path outside the run dir        client cannot act on it

404 is deliberately not used for "not ready": the job exists, and saying it
does not would send the frontend down a dead end. 409 says try again.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import db
from ..schemas import ArtifactListResponse, JobResultsResponse
from ..services import artifact_reader, result_reader, run_status_reader, worker
from .jobs import _FALLBACK_STATUS, _load_job

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["results"])

# Same narrow allowlist uploads.py uses for a stored filename. Kept local
# rather than imported: a service-layer module should not depend on an API
# module, and uploads.py is not being modified.
UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_content_disposition(relative_path: str) -> str:
    """Build an attachment header that cannot be used for injection.

    The name comes from the basename of the registered relative path, never
    from display_name, which is free text written by main.sh and may contain
    quotes, newlines or anything else. Two forms are emitted: a hard-sanitised
    ASCII fallback, and RFC 5987 percent-encoded UTF-8 for clients that
    understand it. Percent-encoding leaves no CR, LF or quote in the header.
    """
    basename = Path(relative_path).name
    ascii_name = UNSAFE_NAME_RE.sub("_", basename).lstrip(".")[:200] or "download"
    encoded = quote(basename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def _reconciled_status(row) -> str:
    """The same job status GET /api/jobs/{id} reports.

    Reusing run_status_reader keeps the two endpoints from ever disagreeing
    about a job, including the cancelled case that the pipeline could not
    record itself.
    """
    planned: list[str] = db.loads(row["planned_steps"], [])
    adapted = run_status_reader.read(Path(row["run_dir"]), planned, row["run_mode"])
    if adapted is None:
        return _FALLBACK_STATUS.get(row["status"], "failed")
    status = adapted["status"]
    if row["status"] == worker.CANCELLED and status != "cancelled":
        status = "cancelled"
    return status


@router.get("/{job_id}/results", response_model=JobResultsResponse)
def get_results(job_id: str) -> JobResultsResponse:
    """Summarise whatever the run has actually produced.

    A --check-only run returns 200 with resultType "precheck". It produced no
    BAM or VCF, but it did produce a verdict: named checks, warnings, failures
    and the resource metadata it verified. Reporting that as "unavailable"
    would throw away the only result the run has.
    """
    row = _load_job(job_id)
    run_dir = Path(row["run_dir"])

    try:
        payload = result_reader.read(run_dir)
    except result_reader.ResultsNotReady as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "resultsNotReady", "message": str(exc)},
        ) from exc
    except result_reader.MalformedPipelineDocument as exc:
        # Already logged with the path by the reader. The client gets none of
        # that: no filename, no parser detail, no traceback.
        log.error("results unavailable for job %s: %s", job_id, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "malformedPipelineDocument",
                "message": "a pipeline result document could not be read",
            },
        ) from exc

    try:
        artifact_count = len(artifact_reader.collect(run_dir).entries)
    except artifact_reader.ArtifactError:
        artifact_count = 0

    return JobResultsResponse(
        jobId=row["job_id"],
        runId=row["run_id"],
        status=_reconciled_status(row),
        artifactCount=artifact_count,
        **payload,
    )


@router.get("/{job_id}/artifacts", response_model=ArtifactListResponse)
def list_artifacts(job_id: str) -> ArtifactListResponse:
    """List what the run registered, from artifacts/*.json.

    Not from artifact_manifest.json: main.sh writes that file before the
    finalization step publishes its own artifacts, so it cannot contain
    final_validation.tsv, provenance.json, core_summary.json or methods.md.
    The manifest is reported on, not trusted.
    """
    row = _load_job(job_id)
    try:
        collection = artifact_reader.collect(Path(row["run_dir"]))
    except artifact_reader.RunDirNotReady as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "resultsNotReady", "message": str(exc)},
        ) from exc

    return ArtifactListResponse(
        jobId=row["job_id"],
        artifactCount=len(collection.entries),
        manifestPresent=collection.manifest_present,
        manifestConsistent=collection.manifest_consistent,
        suppressedCount=collection.suppressed_count,
        artifacts=collection.entries,
    )


@router.get("/{job_id}/artifacts/{file_id}/download")
def download_artifact(job_id: str, file_id: str) -> FileResponse:
    """Send one registered artifact.

    file_id is the only value the client supplies, and it is matched against
    the registry before anything touches the filesystem. The path comes from
    the pipeline document, is treated as untrusted, and must resolve inside the
    run directory recorded in the database.
    """
    row = _load_job(job_id)

    try:
        entry, target = artifact_reader.resolve_for_download(
            Path(row["run_dir"]), file_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="malformed file id") from exc
    except artifact_reader.RunDirNotReady as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "resultsNotReady", "message": str(exc)},
        ) from exc
    except artifact_reader.ArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail="unknown artifact id") from exc
    except artifact_reader.ArtifactNotDownloadable as exc:
        raise HTTPException(
            status_code=403,
            detail="this artifact is registered as not downloadable",
        ) from exc
    except artifact_reader.ArtifactFileMissing as exc:
        raise HTTPException(
            status_code=410,
            detail="this artifact was registered but is no longer on disk",
        ) from exc
    except (
        artifact_reader.ArtifactPathRejected,
        artifact_reader.MalformedArtifactDocument,
    ) as exc:
        # Logged with the offending path by the reader; the response says only
        # that the registry is wrong. Never echo the path back.
        log.error("refusing artifact %s of job %s: %s", file_id, job_id, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "malformedArtifactDocument",
                "message": "this artifact cannot be served",
            },
        ) from exc

    return FileResponse(
        path=target,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _safe_content_disposition(entry["relativePath"]),
            "X-Content-Type-Options": "nosniff",
        },
    )
