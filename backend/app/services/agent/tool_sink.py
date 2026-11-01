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

Attempts that returned nothing new `[설계판단]`
----------------------------------------------

A call that was refused, or that re-asked for a step already opened, returns no
new evidence -- but whether it happened is exactly what an evaluation needs in
order to tell "never called the tool" from "called it and was refused". Those
calls are recorded as a second kind of line, `attempt`, made of fixed codes and
nothing else:

    {"toolName": ..., "attempt": {"outcome": "repeat"|"refused",
                                  "stepId": <a PLANNED step id> | null,
                                  "reason": "budget"|"unknownStep" | null}}

The step id is kept only when it is one this run planned -- the pipeline's own
vocabulary. Whatever else a model typed is dropped, not stored: a refused id is
model-written text, and the refusal message the model saw is not stored either.

An attempt line has no `evidence`, so `records()` / `evidence()` never return
it and it can never be credited as a fact. Only `attempts()` reads it.

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
from typing import Any, Literal

log = logging.getLogger(__name__)

# What a call that returned no new evidence was. Closed sets: anything else
# read back from the file is ignored rather than trusted.
AttemptOutcome = Literal["repeat", "refused"]
RefusalReason = Literal["budget", "unknownStep"]

_ATTEMPT_OUTCOMES = ("repeat", "refused")
_REFUSAL_REASONS = ("budget", "unknownStep")

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
        self._append({"toolName": tool_name, "evidence": payload})

    def record_attempt(
        self,
        tool_name: str,
        outcome: AttemptOutcome,
        *,
        step_id: str | None,
        reason: RefusalReason | None = None,
    ) -> None:
        """Append one call that returned no new evidence.

        `step_id` must already be a planned step id or None -- the server
        decides that, because only it knows the plan. Fails the same way
        record() does: logged and swallowed, so the tool's answer, refusal and
        budget are never affected by whether this line was written.
        """
        self._append(
            {
                "toolName": tool_name,
                "attempt": {"outcome": outcome, "stepId": step_id, "reason": reason},
            }
        )

    def _append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError as exc:  # pragma: no cover - filesystem failure
            log.warning("could not record tool evidence: %s", exc)

    def _lines(self) -> list[dict[str, Any]]:
        """Every well-formed line, in the order the tool answered."""
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
            if isinstance(entry, dict):
                out.append(entry)
        return out

    def records(self) -> list[dict[str, Any]]:
        """Every recorded tool RESULT, in the order the tool answered them.

        Attempt lines are not results and are not returned here. A malformed line is skipped rather than raising: this file is read
        while deciding whether a model's answer may be shown, and one bad line
        must not turn a working feature into a 500. A skipped line simply is
        not credited as evidence.
        """
        return [
            entry for entry in self._lines() if isinstance(entry.get("evidence"), dict)
        ]

    def evidence(self) -> list[dict[str, Any]]:
        """Just the evidence objects, for the guardrails' fact source."""
        return [entry["evidence"] for entry in self.records()]

    def attempts(self) -> list[dict[str, Any]]:
        """Every call the server answered, as `{outcome, stepId, reason}`.

        A successful first open reads as outcome `opened`, from its evidence
        line; the others come from attempt lines. For observation only -- the
        guardrails never read this.
        """
        out: list[dict[str, Any]] = []
        for entry in self._lines():
            evidence = entry.get("evidence")
            attempt = entry.get("attempt")
            if isinstance(evidence, dict):
                step_id = evidence.get("stepId")
                out.append(
                    {
                        "outcome": "opened",
                        "stepId": step_id if isinstance(step_id, str) else None,
                        "reason": None,
                    }
                )
            elif isinstance(attempt, dict) and attempt.get("outcome") in _ATTEMPT_OUTCOMES:
                step_id = attempt.get("stepId")
                reason = attempt.get("reason")
                out.append(
                    {
                        "outcome": attempt["outcome"],
                        "stepId": step_id if isinstance(step_id, str) else None,
                        "reason": reason if reason in _REFUSAL_REASONS else None,
                    }
                )
        return out


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
    "AttemptOutcome",
    "RefusalReason",
    "SINK_PATH_ENV",
    "ToolEvidenceSink",
    "request_sink",
    "sink_from_environment",
]
