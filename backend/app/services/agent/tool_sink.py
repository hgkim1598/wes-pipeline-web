"""What the agent actually looked at, for the duration of one request.

The problem this solves
-----------------------

The guardrails in `explanation/llm/synthesis.py` check a generated text against
the facts the model was given. When the model can fetch more facts through a
tool, "the facts it was given" is no longer just the prompt payload -- and a
number the tool legitimately returned would be rejected as invented.

So the tool results have to come back to the parent. They cannot come back
through the model: a model that reports its own tool results could report ones
it never received. They come back through this sink, which only the server
writes.

    MCP server process        parent (synthesis.py)
    ------------------        ---------------------
    tool returns evidence     -> append one JSON line
                                 ...
                                 after the provider exits: read the lines
                                 -> merge into allowed refs + known facts

A file, because the tool does not run in this process
-----------------------------------------------------

`provider.run_structured()` spawns the CLI, and the CLI spawns the MCP server
as a THIRD process over stdio. An in-memory list in the backend would never see
a single tool call. The sink is therefore a JSONL file whose path is handed to
the server process in its environment -- server-side only, never in the prompt,
so nothing the model writes can choose where this points.

What may be written here, and what may not
------------------------------------------

Only `StepEvidence` objects -- the projection that has already been through the
allowlist and the redactor in `step_evidence.py` / `privacy.py`. That is the
whole reason the sink records the tool's *return value* rather than a CLI
transcript: a transcript carries the prompt, absolute paths and whatever the
provider decided to echo, and would need its own filtering to be safe. This
file cannot contain a path, a sample name, a jobId, a runId or a log line,
because the object it stores cannot.

Where the file lives
--------------------

A fresh temporary directory per request, removed when the request ends. Never
inside the run directory (a run directory is the pipeline's output, and an
artifact scan would find it) and never inside the repository (nothing about a
model call belongs in version control). Nothing here is a trace store: when
persistent tracing is designed, it will decide separately what may be kept.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# How the server process is told where to write. Set by the parent when it
# describes the server to the CLI; absent for a server started by hand, which
# then simply records nothing.
SINK_PATH_ENV = "WES_AGENT_EVIDENCE_SINK"


@dataclass(frozen=True)
class ToolEvidenceSink:
    """One request's append-only record of tool results."""

    path: Path

    def record(self, tool_name: str, evidence: Any) -> None:
        """Append one successful tool result.

        `evidence` is a Pydantic model (StepEvidence) or its dict form. A
        failure to write is logged and swallowed: losing the record means the
        parent will not credit that evidence, which is the safe direction --
        the guardrails then reject a sentence that used it, and nothing false
        reaches the user.
        """
        payload = (
            evidence.model_dump() if hasattr(evidence, "model_dump") else evidence
        )
        line = json.dumps(
            {"toolName": tool_name, "evidence": payload}, ensure_ascii=False
        )
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError as exc:  # pragma: no cover - filesystem failure
            log.warning("could not record tool evidence: %s", exc)

    def records(self) -> list[dict[str, Any]]:
        """Every recorded call, in the order the tool answered them.

        A malformed line is skipped rather than raising: this file is read
        while deciding whether a model's answer may be shown, and one bad line
        must not turn a working feature into a 500. A skipped line simply is
        not credited as evidence.
        """
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                log.warning("skipping unreadable tool evidence line")
                continue
            if isinstance(entry, dict) and isinstance(entry.get("evidence"), dict):
                out.append(entry)
        return out

    def evidence(self) -> list[dict[str, Any]]:
        """Just the evidence objects, for the guardrails' fact source."""
        return [entry["evidence"] for entry in self.records()]


@contextmanager
def request_sink() -> Iterator[ToolEvidenceSink]:
    """A sink for one synthesis request, removed when it ends."""
    with tempfile.TemporaryDirectory(prefix="wes-agent-evidence-") as directory:
        yield ToolEvidenceSink(path=Path(directory) / "tool_evidence.jsonl")


def sink_from_environment() -> ToolEvidenceSink | None:
    """The sink this server process was told to write to, if any."""
    raw = os.environ.get(SINK_PATH_ENV, "").strip()
    return ToolEvidenceSink(path=Path(raw)) if raw else None


__all__ = [
    "SINK_PATH_ENV",
    "ToolEvidenceSink",
    "request_sink",
    "sink_from_environment",
]
