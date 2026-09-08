"""Deterministic run explanation endpoint.

  GET /api/jobs/{job_id}/explanation

A fourth router on the /api/jobs prefix, for the same reason steps.py is a
third one: the existing routers are left exactly as they are.

Nothing is computed here. The route is three calls deep and adds no
interpretation of its own:

    job_id -> build_run_diagnostic_context -> build_run_explanation -> response

That matters more than it looks. The whole value of the layer underneath is
that it is deterministic and testable; a route that reached back into the
readers to "fill in" a field would put logic somewhere the explanation tests
cannot see it.

Why this is separate from /results
----------------------------------

/results answers "what did this run produce" and deliberately 409s until
core_summary.json exists. This endpoint answers "what does this run's record
mean", and that question is worth asking for a run that failed at 03_alignment
-- which is exactly the run /results cannot describe.

Status codes, and why:

  400  malformed job id                    the client can fix it
  404  no such job                         the thing does not exist
  500  a pipeline document is unparseable  server-side data fault
  200  every real run state                including failed and in-progress

**A failed run is not an API error here.** Neither is one still running, nor a
check-only run with no analysis output. Those are four legitimate kinds of
explanation and the response says which one it is in `contextKind`; turning any
of them into a 4xx would hide the case the reader most needs.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..api.jobs import JOB_ID_RE
from ..services import result_reader
from ..services.explanation import deterministic, run_context
from ..services.explanation.deterministic import RunExplanation

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["explanation"])


@router.get("/{job_id}/explanation", response_model=RunExplanation)
def get_explanation(job_id: str) -> RunExplanation:
    """This run's runtime facts combined with what its codes mean.

    No model is involved. The same run produces the same response every time,
    which is why it can be cached, diffed and tested.
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise HTTPException(status_code=400, detail="malformed job id")

    try:
        context = run_context.build_run_diagnostic_context(job_id)
    except run_context.JobNotFound as exc:
        raise HTTPException(status_code=404, detail="unknown job id") from exc
    except result_reader.MalformedPipelineDocument as exc:
        # Already logged with the path by the reader. The client gets none of
        # that: no filename, no parser detail.
        log.error("explanation unavailable for job %s: %s", job_id, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "malformedPipelineDocument",
                "message": "a pipeline document could not be read",
            },
        ) from exc

    return deterministic.build_run_explanation(context)
