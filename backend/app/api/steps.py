"""Step detail endpoint.

  GET /api/jobs/{job_id}/steps/{step_id}

A third router on the /api/jobs prefix, for the same reason results.py is a
second one: jobs.py and results.py are left exactly as they were.

Why this is separate from GET /api/jobs/{id} rather than more fields on it:
that endpoint is polled every three seconds by every open job page, and it
already reads run_status.json plus one status document per planned step. Adding
each step's metrics and artifacts to it would mean reading three more documents
per step on every poll, to deliver data that only changes when a step ends and
that the user is looking at for one step at a time. The progress view stays
cheap; the detail is fetched when someone asks for it.

Why it is separate from /results: /results answers "what did this run produce",
and for a full run it deliberately 409s until core_summary.json exists. This
endpoint answers "what happened in this step", which is a question worth asking
while the run is still going.

Status codes, and why:

  400  the job id or step id is malformed        the client can fix it
  404  no such job, or the run never planned     the thing does not exist
       this step
  200  every real step state, including failed   a failed step is a result

A step that failed is not an API error: the whole point of the endpoint is to
show which step failed and why, so it returns 200 with failures populated.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import db
from ..schemas import StepDetailResponse
from ..services import step_reader
from .jobs import _load_job

router = APIRouter(prefix="/api/jobs", tags=["steps"])


@router.get("/{job_id}/steps/{step_id}", response_model=StepDetailResponse)
def get_step(job_id: str, step_id: str) -> StepDetailResponse:
    """One step's inputs, verdict, metrics, artifacts and readiness."""
    row = _load_job(job_id)
    planned: list[str] = db.loads(row["planned_steps"], [])

    try:
        payload = step_reader.read(
            Path(row["run_dir"]), planned, row["run_mode"], step_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="malformed step id") from exc
    except step_reader.StepNotPlanned as exc:
        # Not 400: the id is well formed and may well be a real step of the
        # pipeline. It just is not part of what this run planned to do, and the
        # plan is the useful thing to say back.
        raise HTTPException(
            status_code=404,
            detail={
                "code": "stepNotPlanned",
                "message": f"this run did not plan step '{step_id}'",
                "plannedSteps": planned,
            },
        ) from exc

    return StepDetailResponse(jobId=row["job_id"], runId=row["run_id"], **payload)
