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

from ..services.agent import run_scope
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
    """An MCP server whose tools can only read `scope`'s run."""
    server = MCPServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=_INSTRUCTIONS,
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
        try:
            return read_step_evidence(scope, stepId)
        except UnreadableStep as exc:
            # A refusal the model can act on: it says which ids are valid, and
            # carries nothing from the filesystem. Raised as ToolError because
            # any other exception is reported to the client as an opaque
            # "error executing tool" with the message dropped.
            raise ToolError(str(exc)) from exc

    return server


def main() -> int:
    """Run the server over stdio for the job named in the environment.

    Provided so the tool can be exercised end to end by a real MCP client. It
    is not wired into the backend or into the synthesis provider: starting this
    is an explicit act, and the job id comes from the operator's environment,
    never from a model.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    job_id = os.environ.get(JOB_ID_ENV, "").strip()
    if not job_id:
        print(f"{JOB_ID_ENV} is not set: there is no run to expose", file=sys.stderr)
        return 2

    try:
        scope = run_scope.for_job(job_id)
    except run_scope.RunNotFound:
        print(f"no such job: {job_id}", file=sys.stderr)
        return 2

    build_server(scope).run(transport="stdio")
    return 0


__all__ = ["JOB_ID_ENV", "SERVER_NAME", "SERVER_VERSION", "build_server", "main"]
