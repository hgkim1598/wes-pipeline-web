"""How a model client is told to start this server, and what it may call.

`server.py` is the server. This module is the other half of the same transport
decision: the JSON an MCP client needs in order to spawn it, and the one tool
name that client is allowed to use. Both live here so that the layer above --
which only wants "give me the step-detail tool for job X" -- does not have to
know about processes, interpreters or argv.

Why the server is spawned rather than served over HTTP
------------------------------------------------------

A stdio child lives and dies with the one CLI call that owns it. There is no
port to leave open, no second process to supervise, and no window in which a
server scoped to somebody's run is reachable by anything else on the box.

Why the environment carries the scope
-------------------------------------

The job id, the sink path and the step budget go in the child's environment,
which is written by this process. They are not in the prompt, so nothing the
model produces can change which run is exposed, where the evidence is recorded,
or how far the session may go.

The database and runs root are passed explicitly for the same reason the
executable is `sys.executable`: the child must resolve them the way the parent
does, not the way its own defaults would. That also makes the spawned server
follow a test or deployment that pointed the backend somewhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .. import config
from ..services.agent.tool_sink import SINK_PATH_ENV, ToolEvidenceSink
from .server import JOB_ID_ENV, MAX_STEPS_ENV

# The key the server is registered under in the MCP config, and therefore the
# middle segment of the tool name the client sees. Underscores, because that
# name is addressed as an identifier in --allowedTools.
MCP_SERVER_KEY = "wes_run_evidence"

STEP_DETAIL_TOOL = f"mcp__{MCP_SERVER_KEY}__get_step_detail"

# backend/app/agent_mcp/launch.py -> agent_mcp -> app -> backend
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def build_mcp_config(
    *,
    job_id: str,
    sink: ToolEvidenceSink,
    max_distinct_steps: int,
) -> dict[str, Any]:
    """The `--mcp-config` object that starts this server for one run."""
    return {
        "mcpServers": {
            MCP_SERVER_KEY: {
                # The interpreter running the backend, so the child has the same
                # virtualenv -- `python` on PATH may be a different one, or
                # absent, which is how a server that "worked yesterday" stops
                # starting after a deployment.
                "command": sys.executable,
                "args": ["-m", "app.agent_mcp"],
                "env": {
                    # `-m app.agent_mcp` needs backend/ importable. Set here
                    # rather than relying on a working directory, which the
                    # client chooses, not us.
                    "PYTHONPATH": str(_BACKEND_DIR),
                    JOB_ID_ENV: job_id,
                    SINK_PATH_ENV: str(sink.path),
                    MAX_STEPS_ENV: str(max_distinct_steps),
                    "WES_DB_PATH": str(config.DB_PATH),
                    "WES_RUNS_ROOT": str(config.RUNS_ROOT),
                },
            }
        }
    }


__all__ = ["MCP_SERVER_KEY", "STEP_DETAIL_TOOL", "build_mcp_config"]
