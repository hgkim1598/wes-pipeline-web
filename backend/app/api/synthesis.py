"""On-demand AI synthesis endpoint.

  POST /api/jobs/{job_id}/synthesis

POST, and not GET, for one reason: this is the only route in the application
that costs something to serve. Run Detail polls `GET /api/jobs/{id}` every three
seconds and re-fetches `/explanation` with it. A GET here would eventually be
polled, prefetched, or retried by something, and the user's subscription usage
would drain without anyone asking for it. POST makes an accidental call
something you have to write on purpose.

It is not idempotent either, which POST also communicates honestly: the same run
called twice produces two generations, and may produce two different texts.

    GET  /explanation   deterministic, free, safe to poll   <- unchanged
    POST /synthesis     model-backed, costs usage, on demand

Failure is a 200
----------------

"The provider is unavailable" is an ordinary state of this feature, not a server
fault. It returns `{"available": false, "errorCategory": ...}` with 200 so the
frontend renders a message next to the deterministic explanation that is still
on screen. A 5xx would push the client into its error path and risk replacing a
working page with an error page over a feature that is by design optional.

The 4xx/5xx codes that remain are the same ones /explanation uses, and mean the
same things -- they are about the job, not about the model.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..api.jobs import JOB_ID_RE
from ..services import result_reader
from ..services.explanation import deterministic, run_context
from ..services.explanation.llm import synthesis as llm_synthesis
from ..services.explanation.llm import trace
from ..services.explanation.llm.synthesis import SynthesisResult

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["synthesis"])


@router.post("/{job_id}/synthesis", response_model=SynthesisResult)
def create_synthesis(job_id: str) -> SynthesisResult:
    """Generate one combined explanation of this run with a model.

    The input is built from the same deterministic explanation the GET endpoint
    serves -- the model never sees the database, the run directory or a log.
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise HTTPException(status_code=400, detail="malformed job id")

    try:
        context = run_context.build_run_diagnostic_context(job_id)
    except run_context.JobNotFound as exc:
        raise HTTPException(status_code=404, detail="unknown job id") from exc
    except result_reader.MalformedPipelineDocument as exc:
        log.error("synthesis unavailable for job %s: %s", job_id, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "malformedPipelineDocument",
                "message": "a pipeline document could not be read",
            },
        ) from exc

    explanation = deterministic.build_run_explanation(context)
    # The trace is written here rather than inside the service because this is
    # where the job id lives, and because the record is about a REQUEST: the
    # service explains an explanation and does not know it was asked over HTTP.
    # Nothing of it reaches the response -- see services/.../llm/trace.py.
    return llm_synthesis.build_run_synthesis(
        explanation, on_trace=trace.recorder(job_id)
    )
