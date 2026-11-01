"""The MCP server that exposes `get_step_detail`, and nothing else.

Deliberately thin. Everything below the decorator is two lines: call the
service, translate its refusal into a protocol error. The WES reading and the
privacy projection are in ``app/services/agent`` so that the same safe wrapper
can be called from a test, from an Anthropic API tool loop, or from a future
Claude Code MCP config without any of them re-deciding what may be sent.

One tool, one run
-----------------

The tool takes `stepId` and nothing else. There is no jobId or runId parameter,
so a model cannot address another analysis: the run is bound when the server is
built (see ``services/agent/run_scope.py``). That is the whole reason this
function is created inside ``build_server`` rather than registered once at
import time -- the scope is a closure, not an argument the caller supplies.

Read-only by construction
-------------------------

There is no write path here, and the annotation says so. `readOnlyHint` is a
hint to the client, not an enforcement mechanism; the enforcement is that the
only thing this module can do is call a reader.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..services.agent import run_scope, tool_sink
from ..services.agent.run_scope import RunScope
from ..services.agent.step_evidence import (
    StepEvidence,
    UnreadableStep,
    read_step_evidence,
)

log = logging.getLogger(__name__)

SERVER_NAME = "wes-run-evidence"
SERVER_VERSION = "0.1.0"

# The job id the stdio entry point reads. Only main() uses it: a server built
# in process is given its scope directly, and neither path lets a tool call
# choose one.
JOB_ID_ENV = "WES_AGENT_JOB_ID"

# Optional override of the per-session step budget, for an operator running the
# server by hand. The synthesis path sets it explicitly; see
# run_scope.DEFAULT_MAX_DISTINCT_STEPS for what the number is and is not.
MAX_STEPS_ENV = "WES_AGENT_MAX_STEPS"


def _max_distinct_steps() -> int:
    """The budget for this process. Falls back to the default, never to 0."""
    raw = os.environ.get(MAX_STEPS_ENV, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return run_scope.DEFAULT_MAX_DISTINCT_STEPS
    return value if value > 0 else run_scope.DEFAULT_MAX_DISTINCT_STEPS

_INSTRUCTIONS = (
    "Read-only evidence about ONE WES pipeline run that is already selected. "
    "Tools here report what the pipeline recorded; they never start, change or "
    "re-run anything, and they cannot reach another run. File paths, download "
    "links, log text and sample identifiers are not available through this "
    "server by design."
)

_TOOL_DESCRIPTION = (
    "Read what happened in one step of the WES run currently being explained: "
    "its status, exit code, elapsed time, validation checks, recorded metrics, "
    "warnings and failures, and whether the pipeline considered the next step "
    "ready.\n\n"
    "stepId must be one of the steps this run planned, e.g. '00_input_validation' "
    "or '04_processing'. A step id that the run did not plan is refused, and the "
    "refusal lists the planned steps.\n\n"
    "Values are reported exactly as the pipeline recorded them. elapsedSeconds is "
    "a measured duration, not an estimate of remaining time; metrics keys are the "
    "pipeline's own identifiers. Some of what a step measures is withheld for "
    "privacy -- withheldMetricCount says how much -- and artifacts are reported as "
    "a count only, with no file names or paths."
)


def build_server(scope: RunScope) -> MCPServer:
    """An MCP server whose tools can only read `scope`'s run.

    The per-session state -- which steps have been opened, and what they
    answered -- lives in this closure, next to the scope. It is session state,
    not run state: a second server built for the same run starts with a fresh
    budget, and nothing is written to the run directory.
    """
    server = MCPServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=_INSTRUCTIONS,
    )

    # stepId -> what this session already answered for it.
    opened: dict[str, StepEvidence] = {}

    def _planned_or_none(step_id: object) -> str | None:
        """Keep a requested id only if it is one this run planned."""
        if isinstance(step_id, str) and step_id in scope.planned_steps:
            return step_id
        return None

    def _note(
        outcome: tool_sink.AttemptOutcome,
        step_id: str | None,
        *,
        reason: tool_sink.RefusalReason | None = None,
    ) -> None:
        """Record a call that returned no new evidence. Observation only.

        Written before the answer or refusal is returned, and unable to change
        either: the sink swallows its own write failures.
        """
        if scope.sink is not None:
            scope.sink.record_attempt(
                "get_step_detail", outcome, step_id=step_id, reason=reason
            )

    @server.tool(
        name="get_step_detail",
        title="Get WES pipeline step detail",
        description=_TOOL_DESCRIPTION,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            # Everything it can answer comes from this run directory.
            open_world_hint=False,
        ),
    )
    def get_step_detail(stepId: str) -> StepEvidence:
        # Already opened: answer from this session's own memo. Re-reading the
        # disk could return a DIFFERENT object for the same evidence id if the
        # step finished in between, which would leave the parent validating a
        # sentence against numbers the model never saw. Costs no budget.
        memoised = opened.get(stepId) if isinstance(stepId, str) else None
        if memoised is not None:
            # Noted, not re-recorded as evidence: the parent credits each
            # opened step once. A memo key is always a planned step id.
            _note("repeat", memoised.stepId)
            return memoised

        if len(opened) >= scope.max_distinct_steps:
            _note("refused", _planned_or_none(stepId), reason="budget")
            # Deterministic refusal, not a silent truncation: the model is told
            # it has spent its budget so it can answer with what it has.
            raise ToolError(
                f"step detail budget spent: this session may open at most "
                f"{scope.max_distinct_steps} different steps and already opened "
                f"{', '.join(sorted(opened))}. Answer with the evidence you have."
            )

        try:
            evidence = read_step_evidence(scope, stepId)
        except UnreadableStep as exc:
            # A refusal the model can act on: it says which ids are valid, and
            # carries nothing from the filesystem. Raised as ToolError because
            # any other exception is reported to the client as an opaque
            # "error executing tool" with the message dropped.
            #
            # A refused call costs no budget -- a mistyped id is not an attempt
            # to wander, and charging for it would end the session on a typo.
            #
            # Noted without the id: a refused id is not a planned one, so it is
            # model-written text and is not kept.
            _note("refused", None, reason="unknownStep")
            raise ToolError(str(exc)) from exc

        opened[evidence.stepId] = evidence
        if scope.sink is not None:
            # Recorded only on success, and only what the tool actually
            # returned. This is what lets the parent credit these facts later;
            # a step that was never opened can never be cited.
            scope.sink.record("get_step_detail", evidence)
        return evidence

    return server


def main() -> int:
    """Run the server over stdio for the job named in the environment.

    Provided so the tool can be exercised end to end by a real MCP client. It
    is not wired into the backend or into the synthesis provider: starting this
    is an explicit act, and the job id comes from the operator's environment,
    never from a model.
    """
    # stderr, never stdout: stdout IS the MCP transport here, and a log line
    # written to it would corrupt the protocol stream.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    job_id = os.environ.get(JOB_ID_ENV, "").strip()
    if not job_id:
        print(f"{JOB_ID_ENV} is not set: there is no run to expose", file=sys.stderr)
        return 2

    try:
        scope = run_scope.for_job(
            job_id,
            # Absent when a person starts this by hand; then the session simply
            # records nothing and no parent is waiting for it.
            sink=tool_sink.sink_from_environment(),
            max_distinct_steps=_max_distinct_steps(),
        )
    except run_scope.RunNotFound:
        print(f"no such job: {job_id}", file=sys.stderr)
        return 2

    build_server(scope).run(transport="stdio")
    return 0


__all__ = [
    "JOB_ID_ENV",
    "MAX_STEPS_ENV",
    "SERVER_NAME",
    "SERVER_VERSION",
    "build_server",
    "main",
]
