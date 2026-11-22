"""Which run an agent tool may read -- decided by the server, never by a model.

Every WES reader in this backend is addressed by (run_dir, planned, run_mode).
An agent tool that accepted those, or a jobId that resolves to them, would let
the model choose the run: one fabricated id in a tool call and it is reading
somebody else's analysis. So the tools take no run identifier at all. The
server binds one scope when it is built, and a tool can only ever read inside
it.

    build the server for job X   ->   RunScope(X)   ->   every tool call
                                                         reads run X

The scope also carries the redactor, because the same decision produces both:
the identifiers that name this run are exactly the identifiers that must not
come back out of it.

What the scope freezes, and what it does not
--------------------------------------------

run_dir, the planned step list and the run mode are fixed at construction.
None of them changes after the job row is written, and freezing them means a
long-lived server cannot be walked onto another run. The *contents* of the run
directory are deliberately NOT cached: a step that finishes after the server
started must be visible to the next call, so every call re-reads through
step_reader.

The one thing derived from the contents and frozen with the scope is the
impact policy (review H1, 2026-11-22). The initial payload sends a pipeline
impact sentence only when this run's ledger supports it
(applicability.decisions_for, applied in contract.build_payload). The tool
used to return the same warning row with the sentence intact, so a model that
opened the step got what the payload had withheld. The scope now carries that
same decision, made once from the same explanation, and step_evidence applies
it. A warning the policy does not know -- one recorded after the scope was
built, or a scope built without a policy -- has its impact withheld: an
unvouched sentence is not sent, in either channel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ... import db
from .privacy import Redactor
from .tool_sink import ToolEvidenceSink

# How many DIFFERENT steps one agent session may open.
#
# This is an operational limit on the agent, not a WES or biological judgement.
# Nothing about this pipeline says two steps are enough to understand a run; the
# number exists because the installed Claude Code CLI has no `--max-turns`, so
# the only deterministic brake on a loop that keeps fetching is the tool itself.
# Re-reading a step already fetched is free and does not count -- the cost being
# capped is "how far can this wander", not "how many times may it ask".
#
# Raise it when there is evidence that a real explanation needed more, not
# because a bigger number looks more capable.
DEFAULT_MAX_DISTINCT_STEPS = 2


# (step id the warning was recorded at, warning code, sha12 of the impact text)
#   -> None when the sentence may be sent, else why it is withheld.
ImpactKey = tuple[str, str, str]
ImpactPolicy = Mapping[ImpactKey, str | None]

IMPACT_NOT_DECIDED = "이 실행에 맞는지 판정되지 않은 파이프라인 문장이라 보내지 않습니다."


class RunNotFound(Exception):
    """No job row with this id, so there is no run to scope a server to."""


@dataclass(frozen=True)
class RunScope:
    """The one run a set of agent tools is allowed to read."""

    run_dir: Path
    planned_steps: tuple[str, ...]
    run_mode: str
    redactor: Redactor
    # Where successful tool results are recorded for the parent process. None
    # means nothing is recorded, and the parent will credit no tool evidence.
    sink: ToolEvidenceSink | None = None
    max_distinct_steps: int = DEFAULT_MAX_DISTINCT_STEPS
    # Which pipeline impact sentences this run may be told (module docstring).
    # None: no decision could be made, so every impact sentence is withheld.
    impact_policy: ImpactPolicy | None = field(default=None, compare=False)

    def impact_decision(self, step_id: str, code: str, text: str) -> str | None:
        """None if `text` may be sent for this warning, else the withhold reason."""
        if self.impact_policy is None:
            return IMPACT_NOT_DECIDED
        from ..explanation.applicability import sha12  # lazy: see impact_policy_for

        return self.impact_policy.get((step_id, code, sha12(text)), IMPACT_NOT_DECIDED)


# The placeholder a job's sample identifier is replaced with. Exported because
# a consumer may need to know whether the redactor CAN hide the sample at all:
# a job row written before jobs.sample_id existed has no such literal.
SAMPLE_PLACEHOLDER = "<sample>"


def redactor_for_row(row: Mapping[str, Any]) -> Redactor:
    """The redactor for one job row: its own identifiers plus the shape rules.

    Used by for_job() and by the public step detail endpoint, so the agent and
    the API redact a job's text with exactly the same literals.
    """
    # Longest first: job_id and run_id are the same string in the current
    # schema, and a shorter identifier must never consume part of a longer one
    # before that one has had its turn.
    candidates = [
        (row["sample_id"], SAMPLE_PLACEHOLDER),
        (row["run_id"], "<run>"),
        (row["job_id"], "<job>"),
    ]
    literals = tuple(
        sorted(
            ((str(value), placeholder) for value, placeholder in candidates if value),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
    )
    return Redactor(literals=literals)


def impact_policy_for(job_id: str) -> ImpactPolicy | None:
    """The impact decisions contract.build_payload applies, keyed for the tool.

    Built from the same deterministic explanation the payload is built from,
    so the two channels cannot disagree. Imported lazily: the explanation layer
    imports agent modules, and this one is imported by them.
    """
    from ..explanation import deterministic, run_context
    from ..explanation.applicability import sha12

    try:
        explanation = deterministic.build_run_explanation(run_context.build_run_diagnostic_context(job_id))
    except Exception:  # noqa: BLE001 -- no decision means nothing is vouched for
        return None
    policy: dict[ImpactKey, str | None] = {}
    for d in explanation.knowledgeDecisions:
        if d.section != "diagnostics" or d.part != "impact":
            continue
        step_id = explanation.diagnostics[d.index].actualStepId or ""
        key = (step_id, d.code, sha12(d.text))
        # Two occurrences with the same words at the same step: withheld wins.
        if d.withheld:
            policy[key] = d.reason or IMPACT_NOT_DECIDED
        else:
            policy.setdefault(key, None)
    return policy


def for_job(
    job_id: str,
    *,
    sink: ToolEvidenceSink | None = None,
    max_distinct_steps: int = DEFAULT_MAX_DISTINCT_STEPS,
) -> RunScope:
    """Resolve a job id to a scope. Server-side only; never from tool input.

    Raises RunNotFound for an unknown id.
    """
    row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        raise RunNotFound(job_id)

    return RunScope(
        run_dir=Path(row["run_dir"]),
        planned_steps=tuple(db.loads(row["planned_steps"], [])),
        run_mode=row["run_mode"],
        redactor=redactor_for_row(row),
        sink=sink,
        max_distinct_steps=max_distinct_steps,
        impact_policy=impact_policy_for(job_id),
    )


__all__ = [
    "DEFAULT_MAX_DISTINCT_STEPS",
    "IMPACT_NOT_DECIDED",
    "ImpactPolicy",
    "RunNotFound",
    "RunScope",
    "SAMPLE_PLACEHOLDER",
    "for_job",
    "impact_policy_for",
    "redactor_for_row",
]
