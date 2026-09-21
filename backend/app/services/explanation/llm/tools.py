"""What this synthesis may fetch for itself, and how its findings come back.

`synthesis.py` orchestrates one request: build the input, call a provider,
validate what comes back. Offering a tool adds two concerns to that -- a server
has to be described to the provider, and whatever the model actually fetched has
to reach the guardrails. Both are here, so the orchestration keeps reading as
four steps rather than fifteen.

    app/agent_mcp/launch.py        how to start the server, and the tool name
    app/services/agent/tool_sink   what the tool actually returned
    this module                    the two as one object with one lifetime

Why the results do not come back through the model
--------------------------------------------------

A model that reports its own tool results can report results it never received,
and the guardrails would then be validating a claim against a claim. The sink is
written by the server process only, so `evidence()` is a record of what the tool
answered, not of what the answer says it answered.

Why crediting is a separate function
------------------------------------

Gates 3, 4 and 5 already do the right thing once they are given the full fact
set -- `validation.py` walks lists and dicts, so no gate changes. The only new
decision is *what counts as supplied*, and that decision is one function here:
initial payload plus the evidence objects actually recorded, and nothing else.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ....agent_mcp import launch
from ...agent import tool_sink
from ...agent.run_scope import DEFAULT_MAX_DISTINCT_STEPS


@dataclass(frozen=True)
class Toolset:
    """One request's tool channel: what to offer, and what came of it."""

    mcp_config: dict[str, Any]
    allowed_tools: tuple[str, ...]
    _sink: tool_sink.ToolEvidenceSink

    def evidence(self) -> list[dict[str, Any]]:
        """Every tool result actually returned during this request.

        Empty is the normal single-shot case: the model answered without
        opening a step, and nothing extra is credited.
        """
        return self._sink.evidence()


@contextmanager
def step_detail_toolset(
    job_id: str, *, max_distinct_steps: int = DEFAULT_MAX_DISTINCT_STEPS
) -> Iterator[Toolset]:
    """Offer `get_step_detail` for one run, for the length of one request.

    The scope travels in the server's environment, never in the prompt, so the
    model chooses which STEP to look at and never which RUN. The sink and its
    directory are removed when the block exits.
    """
    with tool_sink.request_sink() as sink:
        yield Toolset(
            mcp_config=launch.build_mcp_config(
                job_id=job_id, sink=sink, max_distinct_steps=max_distinct_steps
            ),
            allowed_tools=(launch.STEP_DETAIL_TOOL,),
            _sink=sink,
        )


def credit(
    payload: dict[str, Any],
    allowed_refs: set[str],
    tool_evidence: list[dict[str, Any]],
) -> tuple[list[Any], set[str]]:
    """(facts, allowed refs) for the guardrails, initial + tool-derived.

    A tool result becomes citable only by appearing here, and it appears here
    only because the server recorded returning it. An `evidenceId` the model
    wrote in its answer but that is not in this set fails gate 3 -- including
    `step:` ids for steps it never opened, which are exactly the ones a model
    would compose from the step list if it decided to skip the call.
    """
    facts: list[Any] = [payload, *tool_evidence]
    refs = set(allowed_refs)
    for item in tool_evidence:
        ref = item.get("evidenceId")
        if isinstance(ref, str) and ref:
            refs.add(ref)
    return facts, refs


__all__ = ["Toolset", "credit", "step_detail_toolset"]
