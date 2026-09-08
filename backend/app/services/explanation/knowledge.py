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


@lru_cache(maxsize=1)
def _diagnostics() -> dict[str, DiagnosticKnowledge]:
    doc = _load(config.DIAGNOSTIC_KNOWLEDGE, _DiagnosticsDoc)
    return _index(doc.diagnostics, "code", config.DIAGNOSTIC_KNOWLEDGE.name)


@lru_cache(maxsize=1)
def _steps() -> dict[str, StepKnowledge]:
    doc = _load(config.STEP_KNOWLEDGE, _StepsDoc)
    return _index(doc.steps, "stepId", config.STEP_KNOWLEDGE.name)


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


def reload() -> None:
    """Drop the cached documents. For tests that rewrite the source files."""
    _diagnostics.cache_clear()
    _steps.cache_clear()
