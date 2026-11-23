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

The 4xx/5xx codes that remain are about the job, not about the model. Most are
the ones /explanation uses. One is this route's own: 409 for a run that has not
finished yet.

A run that has not finished is refused here
-------------------------------------------

The UI disables the button until the run ends, but the button is not the only
client. A synthesis of a queued or running run goes stale as soon as the next
step finishes, and it still spends usage. So the server applies the same rule
before calling anything: queued and running are refused with 409; every other
status, including failed and cancelled, can be explained. The rule matches
front/src/features/runs/status.ts isTerminalStatus, and the status is the one
GET /api/jobs/{id} reports (run_context reconciles it the same way).
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Path

from .. import config
from ..api.jobs import JOB_ID_RE
from ..services import result_reader
from ..services.agent import run_scope
from ..services.doc_search import agent_link
from ..services.explanation import deterministic, run_context
from ..services.explanation.llm import answers
from ..services.explanation.llm import synthesis as llm_synthesis
from ..services.explanation.llm import trace
from ..services.explanation.llm.synthesis import SynthesisResult

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["synthesis"])

# JobStatus values (schemas.py) that mean the run is still going.
_ACTIVE_STATUSES = ("queued", "running")

# Requests holding a model call right now (log 61). In-process: the backend is
# one uvicorn process with one worker by design (worker.py), so a lock and a set
# are the whole bookkeeping. Taken only after every free refusal above, released
# whatever happens, so a failed or crashed request never leaves a run locked.
_inflight_lock = threading.Lock()
_inflight: set[str] = set()


@contextmanager
def _model_call_slot(job_id: str) -> Iterator[None]:
    with _inflight_lock:
        if job_id in _inflight:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "synthesisInProgress",
                    "message": "an explanation of this run is already being generated",
                },
            )
        if len(_inflight) >= config.SYNTHESIS_MAX_CONCURRENT:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "synthesisBusy",
                    "message": "the server is generating another explanation; try again when it finishes",
                },
            )
        _inflight.add(job_id)
    try:
        yield
    finally:
        with _inflight_lock:
            _inflight.discard(job_id)


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

    if context.outcome.status in _ACTIVE_STATUSES:
        # Before the provider is reached: a refused request costs nothing.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "runNotFinished",
                "message": "the run has not finished; synthesis is available once it ends",
            },
        )

    with _model_call_slot(job_id):
        return _synthesize(job_id, context)


def _synthesize(job_id: str, context: Any) -> SynthesisResult:
    explanation = deterministic.build_run_explanation(context)
    # The trace is written here rather than inside the service because this is
    # where the job id lives, and because the record is about a REQUEST: the
    # service explains an explanation and does not know it was asked over HTTP.
    # Nothing of it reaches the response -- see services/.../llm/trace.py.
    # The job's own identifiers, so run-written text in the payload has its
    # sample, run and job ids replaced before it leaves the machine (P1). The
    # identity was read from the jobs row, the same row run_scope.for_job uses
    # for get_step_detail, so both channels redact with the same literals.
    identity = explanation.identity
    redactor = run_scope.redactor_for_row(
        {
            "sample_id": identity.sampleId,
            "run_id": identity.runId,
            "job_id": identity.jobId,
        }
    )
    # Official documents as agent input (log 27), off by default. A fresh
    # search for this request, stored before the call so the trace can name
    # it; any failure there leaves `prepared` None and the request goes on
    # exactly as it does with the flag off.
    prepared = agent_link.prepare(job_id, redactor) if config.AGENT_DOC_EVIDENCE else None
    captured: dict[str, Any] = {}

    def on_trace(record: trace.SynthesisTrace) -> None:
        captured["trace"] = record
        captured["trace_id"] = trace.record(job_id, record)

    result = llm_synthesis.build_run_synthesis(
        explanation,
        on_trace=on_trace,
        redactor=redactor,
        official_docs=prepared.input.section if prepared is not None else None,
    )
    if prepared is not None:
        agent_link.link(captured.get("trace_id"), prepared, captured.get("trace"))
    # Stored versions (log 66): only a served answer, only with storing on, and
    # never at the cost of the response -- the user has the answer either way.
    if result.available and config.SYNTHESIS_STORE_ANSWERS:
        # Anything here failing is logged by type and the answer still goes
        # out without a version, like a failed trace (trace.py).
        try:
            outcome = answers.store(
                job_id,
                captured.get("trace_id"),
                result,
                captured.get("trace"),
                redactor=redactor,
                run_record_sha256=answers.record_digest(context),
                doc_search_id=prepared.search_id if prepared is not None else None,
            )
            if outcome == answers.STORED:
                version = answers.stored_version(captured["trace_id"])
                if version is not None:
                    result = result.model_copy(update={"storedVersion": version})
        except Exception as exc:  # noqa: BLE001 -- see above
            log.warning("served answer not stored: %s", type(exc).__name__)
    return result


# --- stored versions (log 66) -------------------------------------------------
#
# GET and DELETE only; neither calls a model. The list is cheap enough to poll.


def _current_record(job_id: str) -> str | None:
    """The run record's hash now, or None when it cannot be read (404 if no job)."""
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise HTTPException(status_code=400, detail="malformed job id")
    try:
        return answers.record_digest(run_context.build_run_diagnostic_context(job_id))
    except run_context.JobNotFound as exc:
        raise HTTPException(status_code=404, detail="unknown job id") from exc
    except result_reader.MalformedPipelineDocument:
        # The stored answers are still readable; whether the record changed is not.
        return None


# A version number as SQLite can hold it; larger is a 422, not an OverflowError.
_Version = Path(ge=1, le=2**31 - 1)

_NO_VERSION = {"code": "answerNotFound", "message": "no stored explanation with this version"}


@router.get("/{job_id}/synthesis/answers", response_model=answers.StoredAnswerList)
def list_answers(job_id: str) -> answers.StoredAnswerList:
    return answers.list_versions(job_id, _current_record(job_id))


@router.get("/{job_id}/synthesis/answers/{version}", response_model=answers.StoredAnswer)
def get_answer(job_id: str, version: int = _Version) -> answers.StoredAnswer:
    found = answers.get_version(job_id, version, _current_record(job_id))
    if found is None:
        raise HTTPException(status_code=404, detail=_NO_VERSION)
    return found


@router.delete("/{job_id}/synthesis/answers/{version}")
def delete_answer(job_id: str, version: int = _Version) -> dict[str, Any]:
    """Clear one version's text. The row, its hashes and its number stay."""
    _current_record(job_id)
    if not answers.delete(job_id, version):
        raise HTTPException(status_code=404, detail=_NO_VERSION)
    return {"version": version, "deleted": True}
