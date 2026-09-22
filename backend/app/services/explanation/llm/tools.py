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


@dataclass(frozen=True)
class ToolUse:
    """What the agent actually went and looked at, in three values.

    The smallest thing an observer needs in order to ask "did it search, and
    did it search in the right place" -- which is a different question from
    "was the answer grounded", and is scored by a different evaluator.

    Derived from the sink, so it reports execution rather than intention: a
    model that says it consulted a step appears here only if the server
    answered one.

    Deliberately not part of any API response, not persisted, and not shown to
    a user. It exists for the length of one call; `synthesis.py` hands it to an
    observer if one was passed, and otherwise it is discarded with the sink.
    """

    toolUsed: bool
    openedStepIds: tuple[str, ...]
    toolEvidenceIds: tuple[str, ...]
    # The returned objects themselves, for an observer that has to judge the
    # answer against them -- an eval checking for invented numbers has to know
    # that a figure came back from a step, or it reports fetched evidence as
    # invention. Left out of to_json(): an eval RECORD wants the three ids, not
    # a second copy of the evidence.
    evidence: tuple[dict[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "toolUsed": self.toolUsed,
            "openedStepIds": list(self.openedStepIds),
            "toolEvidenceIds": list(self.toolEvidenceIds),
        }


def observe(tool_evidence: list[dict[str, Any]]) -> ToolUse:
    """Summarise one request's recorded tool results.

    Order is the order the tool answered in, and duplicates cannot occur: the
    server answers a repeated step from its own memo without recording it
    again.
    """
    step_ids = tuple(
        str(item["stepId"]) for item in tool_evidence if item.get("stepId")
    )
    evidence_ids = tuple(
        str(item["evidenceId"]) for item in tool_evidence if item.get("evidenceId")
    )
    return ToolUse(
        toolUsed=bool(tool_evidence),
        openedStepIds=step_ids,
        toolEvidenceIds=evidence_ids,
        evidence=tuple(tool_evidence),
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


__all__ = ["ToolUse", "Toolset", "credit", "observe", "step_detail_toolset"]
