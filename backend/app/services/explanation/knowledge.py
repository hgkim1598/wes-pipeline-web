"""Shared WES domain knowledge — backend loader.

Canonical source, shared with the frontend:

    config/knowledge/wes_diagnostics.json
    config/knowledge/wes_steps.json

The frontend imports the same two files through its ``@shared`` alias and
validates them with Zod (front/src/registries/knowledge.ts). This module is the
Python half of that contract. **Neither side owns a copy** -- config/ is
repository-level, tracked by git so ``git archive`` ships it, and
``config.ROOT`` resolves correctly inside a deployed release directory.

Why this exists at all: the pipeline records a diagnostic ``code`` but no
judgement about it. ``main.sh``'s step_warning() writes code / message / impact
/ can_continue, so DBSNP_MISSING (a real configuration fault) and
DBSNP_NOT_CONFIGURED (a normal absence) arrive in structurally identical shapes.
The severity that separates them used to live only in a TypeScript constant,
which meant the backend could not read it. This module is how it becomes
readable on both sides.

Knowledge is NOT run data
-------------------------

Everything here answers "what is this, generally". It never answers "what
happened in this run". In particular ``relatedSteps`` lists the steps a
diagnostic *can* be raised from -- derived from where main.sh calls
step_warning -- and is not where it actually occurred. That fact lives in the
run's own ``warnings[].stepId``.

The distinction is not academic: MULTIQC_MISSING is raised from two different
places (validate_tools, reached through 00_input_validation, and run_raw_qc,
which is 01_raw_qc) **with different impact text**. Which one applies is a
property of the run, not of the code. That is also why ``message``, ``impact``
and ``can_continue`` are deliberately absent from this file: they vary per
occurrence and belong to the run.

Enrichment: every claim carries its source
------------------------------------------

``title`` and ``meaning`` say what a code means. They do not say why it can
happen, where to look, or what a value does *not* establish -- and those are
exactly the questions a later synthesis layer will be asked. ``Grounding`` adds
them, under one hard rule: **a claim without a resolvable source is rejected at
load time**. ``sourceIds`` is non-empty by schema and each id must exist in
``wes_sources.json``, so "the model said so" cannot enter this file.

The four buckets are the fact/inference boundary, made structural:

    possibleCauses   general causes this code *can* have -- never this run's
    scope            what the code does NOT establish
    checks           where a reader can look, pinned to a real emitted artifact
    actions          only where the pipeline contract or an official doc says
                     what the action changes

There is deliberately no bucket for a verdict, and no numeric field anywhere.
"7.2% is high" is not expressible here -- not discouraged, unrepresentable.
Where a threshold would be expected, a `scope` claim states that the project has
not established one, which is a fact about the project rather than an opinion
about the number.

An empty bucket means "we do not know", not "there is nothing".
ZERO_COVERAGE_TARGET_BASES ships with ``possibleCauses: []`` on purpose: the
usual explanations for uncovered targets are plausible but were not sourced, and
a plausible-sounding cause is worse than none when the reader cannot tell.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

from ... import config

DiagnosticSeverity = Literal["attention", "info"]
DiagnosticResolution = Literal["repaired"] | None
DiagnosticStatus = Literal["active", "legacy"]


class KnowledgeError(Exception):
    """The shared knowledge source is missing or does not match the contract.

    Raised rather than degraded. This data is owned by the repository, so a
    failure here is a defect to fix before deploying, not a runtime condition
    to work around. Serving explanations built on knowledge that failed
    validation would be worse than serving none.
    """


LocatorKind = Literal["artifact", "metric", "check", "stepFile"]
SourceType = Literal["spec", "tool-doc", "pipeline", "project-doc"]


class Source(BaseModel):
    """One citable origin. Referenced by id from every claim."""

    id: str = Field(min_length=1)
    type: SourceType
    title: str = Field(min_length=1)
    # A URL for external sources; `path#anchor` for in-repo ones, where the
    # anchor is a string that actually greps in that file. Line numbers are
    # never used -- code moves and the citation would quietly become wrong.
    locator: str = Field(min_length=1)


class Claim(BaseModel):
    """One sourced statement.

    ``sourceIds`` has min_length=1, so an unsourced claim cannot be constructed
    at all. The loader additionally checks that each id resolves.
    """

    statement: str = Field(min_length=1)
    sourceIds: list[str] = Field(min_length=1)


class CheckLocator(BaseModel):
    """Where to look, named the way the pipeline names it.

    Not free text. `id` must match something main.sh actually emits -- an
    add_artifact id, a step_metric key, a step_check name, or a file it writes
    under the run directory. A test greps main.sh for every one of them, so a
    check cannot point at a file that does not exist.
    """

    kind: LocatorKind
    id: str = Field(min_length=1)


class Check(BaseModel):
    """One place a reader can look, and what they will find there."""

    statement: str = Field(min_length=1)
    locator: CheckLocator
    sourceIds: list[str] = Field(min_length=1)


class Action(BaseModel):
    """Something a person can do, paired with what it changes.

    ``effect`` is required on purpose. A bare imperative ("install MultiQC") is
    a recommendation; stating what it changes keeps it a fact about the
    pipeline, and makes an ungrounded action hard to write by accident.
    """

    statement: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    sourceIds: list[str] = Field(min_length=1)


class Grounding(BaseModel):
    """Sourced material an explanation can stand on. Buckets default to empty.

    Empty is a real answer -- see the module docstring. Nothing here may be
    filled with a guess to avoid an empty list.
    """

    # General candidates. NEVER this run's cause: the run does not record one.
    possibleCauses: list[Claim] = Field(default_factory=list)
    # What this does not establish. Where "no threshold is set" belongs.
    scope: list[Claim] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)


class DiagnosticKnowledge(BaseModel):
    """What a diagnostic code means, independent of any run."""

    code: str = Field(min_length=1)
    severity: DiagnosticSeverity
    # Nullable but not optional: allowing the key to be omitted would create a
    # third state ("not yet classified") that nothing downstream can act on.
    resolution: DiagnosticResolution
    # Steps this diagnostic CAN be raised from. Not where it occurred.
    relatedSteps: list[str]
    # `legacy` marks a code the pipeline no longer emits. It stays so that runs
    # recorded before the rename remain readable -- e.g. UNCOVERED_TARGETS,
    # replaced by ZERO_COVERAGE_TARGET_BASES.
    status: DiagnosticStatus
    title: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    # Named `grounding`, not `evidence`: DiagnosticExplanation.evidence already
    # means "which runtime event produced this", and the two would be read as
    # the same thing by the layer that consumes both.
    #
    # Optional: only a few codes are enriched so far. `None` means "not written
    # yet" and is distinct from a Grounding whose buckets are empty, which means
    # "looked, found nothing sourceable".
    grounding: Grounding | None = None


class FailureKnowledge(BaseModel):
    """What a curated failure code means.

    Separate from DiagnosticKnowledge because the two obey different rules.
    Diagnostic codes are all literals in main.sh and a test asserts the registry
    is exhaustive. Failure codes are not: main.sh composes some from run values
    (`sort_order_DEMO_WES.L001`), so this set is open and no test may demand
    completeness. Mixing them in one file would apply the wrong rule to one of
    them.

    No severity: a recorded failure already stopped the run.
    """

    code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    grounding: Grounding | None = None


class ConceptKnowledge(BaseModel):
    """A distinction a reader needs so the run's numbers are not misread."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    grounding: Grounding | None = None


class StepKnowledge(BaseModel):
    """What a pipeline step does, independent of any run."""

    stepId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    # Canonical names of the tools that do the step's substantive work,
    # verified against main.sh. Empty for steps that run no analysis tool
    # (00_input_validation, 99_finalization). The on-screen subtitle is a
    # separate, frontend-owned concern and is not derived from this.
    tools: list[str]


class _DiagnosticsDoc(BaseModel):
    schemaVersion: str
    diagnostics: list[DiagnosticKnowledge]


class _StepsDoc(BaseModel):
    schemaVersion: str
    steps: list[StepKnowledge]


class _SourcesDoc(BaseModel):
    schemaVersion: str
    sources: list[Source]


class _FailuresDoc(BaseModel):
    schemaVersion: str
    # Always False, and stated in the document rather than assumed by readers.
    # A future exhaustive set would have to say so explicitly.
    closedSet: bool
    failures: list[FailureKnowledge]


class _ConceptsDoc(BaseModel):
    schemaVersion: str
    concepts: list[ConceptKnowledge]


_Doc = TypeVar("_Doc", bound=BaseModel)
_Row = TypeVar("_Row", bound=BaseModel)


def _load(path: Path, model: type[_Doc]) -> _Doc:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise KnowledgeError(f"{path.name} could not be read: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise KnowledgeError(f"{path.name} is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise KnowledgeError(
            f"{path.name} does not match the shared knowledge contract:\n{exc}"
        ) from exc


def _index(rows: list[_Row], key: str, source: str) -> dict[str, _Row]:
    out: dict[str, _Row] = {}
    for row in rows:
        identifier: str = getattr(row, key)
        # A duplicate key would silently drop one entry, and which one survived
        # would depend on file order.
        if identifier in out:
            raise KnowledgeError(f"{source} has a duplicate {key}: {identifier}")
        out[identifier] = row
    return out


def _check_sources_resolve(
    grounding: Grounding | None, owner: str, source_file: str
) -> None:
    """Reject a claim whose citation does not exist.

    This is the rule that makes the enrichment trustworthy: min_length=1 on
    sourceIds stops an *empty* citation, and this stops a *fake* one. Without
    it, `sourceIds: ["probably-somewhere"]` would validate and the provenance
    would be decoration.
    """
    if grounding is None:
        return
    known = _sources()
    groups: list[tuple[str, list[str]]] = []
    for claim in grounding.possibleCauses:
        groups.append((claim.statement, claim.sourceIds))
    for claim in grounding.scope:
        groups.append((claim.statement, claim.sourceIds))
    for check in grounding.checks:
        groups.append((check.statement, check.sourceIds))
    for action in grounding.actions:
        groups.append((action.statement, action.sourceIds))

    for statement, ids in groups:
        for source_id in ids:
            if source_id not in known:
                raise KnowledgeError(
                    f"{source_file}: {owner} cites an unknown source "
                    f"{source_id!r} in {statement[:40]!r}. "
                    f"Add it to {config.SOURCE_KNOWLEDGE.name} or remove the claim."
                )


@lru_cache(maxsize=1)
def _sources() -> dict[str, Source]:
    doc = _load(config.SOURCE_KNOWLEDGE, _SourcesDoc)
    return _index(doc.sources, "id", config.SOURCE_KNOWLEDGE.name)


@lru_cache(maxsize=1)
def _diagnostics() -> dict[str, DiagnosticKnowledge]:
    doc = _load(config.DIAGNOSTIC_KNOWLEDGE, _DiagnosticsDoc)
    rows = _index(doc.diagnostics, "code", config.DIAGNOSTIC_KNOWLEDGE.name)
    for code, row in rows.items():
        _check_sources_resolve(row.grounding, code, config.DIAGNOSTIC_KNOWLEDGE.name)
    return rows


@lru_cache(maxsize=1)
def _steps() -> dict[str, StepKnowledge]:
    doc = _load(config.STEP_KNOWLEDGE, _StepsDoc)
    return _index(doc.steps, "stepId", config.STEP_KNOWLEDGE.name)


@lru_cache(maxsize=1)
def _failures() -> dict[str, FailureKnowledge]:
    doc = _load(config.FAILURE_KNOWLEDGE, _FailuresDoc)
    if doc.closedSet:
        # Guards a real mistake, not a hypothetical one: main.sh builds some
        # failure codes from run values, so declaring this set closed would make
        # every composed code look like an unregistered defect.
        raise KnowledgeError(
            f"{config.FAILURE_KNOWLEDGE.name} declares closedSet: true, but "
            "main.sh composes failure codes from run values. This set is open."
        )
    rows = _index(doc.failures, "code", config.FAILURE_KNOWLEDGE.name)
    for code, row in rows.items():
        _check_sources_resolve(row.grounding, code, config.FAILURE_KNOWLEDGE.name)
    return rows


@lru_cache(maxsize=1)
def _concepts() -> dict[str, ConceptKnowledge]:
    doc = _load(config.CONCEPT_KNOWLEDGE, _ConceptsDoc)
    rows = _index(doc.concepts, "id", config.CONCEPT_KNOWLEDGE.name)
    for concept_id, row in rows.items():
        _check_sources_resolve(row.grounding, concept_id, config.CONCEPT_KNOWLEDGE.name)
    return rows


def diagnostic(code: str) -> DiagnosticKnowledge | None:
    """Knowledge for one diagnostic code, or None when it is not registered.

    None is a real answer: main.sh can add a code before this file knows it.
    The caller decides the fallback rather than being handed an invented one.
    """
    return _diagnostics().get(code)


def step(step_id: str) -> StepKnowledge | None:
    """Knowledge for one pipeline step, or None when it is not registered."""
    return _steps().get(step_id)


def all_diagnostics() -> list[DiagnosticKnowledge]:
    return list(_diagnostics().values())


def all_steps() -> list[StepKnowledge]:
    return list(_steps().values())


def failure(code: str) -> FailureKnowledge | None:
    """Knowledge for one failure code, or None when it is not curated.

    None is the *common* case here, not an error. Failure codes are an open
    set, so the caller must fall back to the run's own message rather than
    treating an unregistered code as a gap to fill.
    """
    return _failures().get(code)


def all_failures() -> list[FailureKnowledge]:
    return list(_failures().values())


def concept(concept_id: str) -> ConceptKnowledge | None:
    """One interpretation concept, or None when it is not registered."""
    return _concepts().get(concept_id)


def all_concepts() -> list[ConceptKnowledge]:
    return list(_concepts().values())


def source(source_id: str) -> Source | None:
    """One citable source, or None. Used to render provenance for a claim."""
    return _sources().get(source_id)


def all_sources() -> list[Source]:
    return list(_sources().values())


def reload() -> None:
    """Drop the cached documents. For tests that rewrite the source files."""
    _diagnostics.cache_clear()
    _steps.cache_clear()
    _sources.cache_clear()
    _failures.cache_clear()
    _concepts.cache_clear()
