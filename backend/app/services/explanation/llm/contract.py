"""What the model is given, what it must return, and what it may cite.

Three things live here because they are one decision seen from three sides: the
set of facts that enter the prompt is exactly the set of things the model is
allowed to talk about, and the evidence ids it may cite are derived from that
same set. Splitting them across files would let them drift.

The input is built from the deterministic explanation, never from the readers
------------------------------------------------------------------------------

    job_id -> RunDiagnosticContext -> RunExplanation -> (+ grounding) -> payload

Nothing here opens the database, the run directory, a log or an artifact. Every
number the model sees has already been through the readers, the context and the
deterministic layer, so the model cannot contradict the screen -- it is looking
at the same values the screen is.

Only the grounding for codes this run actually raised is included. Shipping all
29 diagnostics would invite the model to explain something that did not happen.

Evidence ids are minted here, not by the model
----------------------------------------------

Every citable thing gets a short id (`dx:NM_MD_REPAIRED`, `src:sam-tags-spec`)
built from the payload itself. The model may only cite these strings, and the
validator rejects anything else. A fabricated citation is therefore a hard
failure rather than a plausible-looking reference nobody checks.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .. import knowledge
from ..deterministic import RunExplanation

# --- what the model may return ----------------------------------------------


class SynthesisStatement(BaseModel):
    """One sentence plus the evidence it rests on.

    `evidenceRefs` is required and non-empty by schema. That is the single
    mechanism that keeps the model inside the payload: an assertion it cannot
    attach to supplied evidence cannot be expressed in this shape.
    """

    statement: str = Field(min_length=1)
    evidenceRefs: list[str] = Field(min_length=1)


class RunSynthesis(BaseModel):
    """The model's combined reading of one run.

    Deliberately not a Markdown blob. Each part is separately checkable, and
    every part except `summary` carries its own citations.

    `summary` has no refs of its own because it is a combination of the parts
    below it; the parts carry the provenance. It is still bound by the same
    rule -- it may not introduce a fact that is not in the payload -- which the
    prompt states and a reviewer can check against `importantFindings`.
    """

    summary: str = Field(min_length=1)
    importantFindings: list[SynthesisStatement] = Field(default_factory=list)
    limitations: list[SynthesisStatement] = Field(default_factory=list)
    nextChecks: list[SynthesisStatement] = Field(default_factory=list)
    uncertainties: list[SynthesisStatement] = Field(default_factory=list)


# The schema handed to the CLI. Written out rather than generated from the model
# above because the CLI needs a plain JSON Schema with additionalProperties
# false, and because the descriptions here are part of the instruction to the
# model -- they belong next to the field they constrain.
SYNTHESIS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "Korean. Two to four sentences a beginner can follow, combining "
                "the findings below into one reading of this run. State what "
                "happened and what it means for trusting the output. Do NOT "
                "judge overall quality and do NOT introduce any fact that is "
                "not in the supplied data."
            ),
        },
        "importantFindings": {
            "type": "array",
            "description": (
                "What a reader most needs to know, most important first. Only "
                "things present in the supplied diagnostics, failures or "
                "checkSummary."
            ),
            "items": {"$ref": "#/$defs/statement"},
        },
        "limitations": {
            "type": "array",
            "description": (
                "What this run's output does not establish. Base these on the "
                "supplied limitations and grounding scope entries."
            ),
            "items": {"$ref": "#/$defs/statement"},
        },
        "nextChecks": {
            "type": "array",
            "description": (
                "What the reader can go and look at. Only checks that appear in "
                "the supplied grounding; do not invent a file or a command."
            ),
            "items": {"$ref": "#/$defs/statement"},
        },
        "uncertainties": {
            "type": "array",
            "description": (
                "What cannot be determined from this data, including anything a "
                "reader is likely to ask but the evidence does not answer."
            ),
            "items": {"$ref": "#/$defs/statement"},
        },
    },
    "required": [
        "summary",
        "importantFindings",
        "limitations",
        "nextChecks",
        "uncertainties",
    ],
    "additionalProperties": False,
    "$defs": {
        "statement": {
            "type": "object",
            "properties": {
                "statement": {
                    "type": "string",
                    "description": "Korean, one sentence, plain language.",
                },
                "evidenceRefs": {
                    "type": "array",
                    "description": (
                        "Ids copied EXACTLY from the evidenceIndex in the input. "
                        "Never invent an id. If nothing in the evidenceIndex "
                        "supports the sentence, omit the sentence."
                    ),
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["statement", "evidenceRefs"],
            "additionalProperties": False,
        }
    },
}


# --- what the model is given -------------------------------------------------


# --- what may leave the building ------------------------------------------
#
# These are allowlists, not conveniences. The previous version spread
# `model.model_dump()` into the payload, which meant the *model* decided what
# reached Claude: any field later added to RunCoverage or RunVariantCalling
# would have been sent the moment it was introduced, with nobody deciding it
# should be. That is the failure this prevents -- not today's contents, but
# tomorrow's addition.
#
# Adding a field here is the decision. `_pick` sends nothing else, and a test
# pins the full field set of both models so a new field fails the suite until
# someone chooses.

# Dropped from variantCalling, and why:
#
#   sample           the biological sample name. Today it is a public SRA
#                    accession; in real use it is whatever the submitter typed,
#                    which is exactly where a patient-linked identifier appears.
#                    The model does not need to know whose sample it is to
#                    explain what happened to it.
#   rawVcfRelative   run-relative artifact paths. They are not needed to
#   gvcfRelative     describe the result, and both embed the sample name, so
#                    dropping `sample` alone would not have removed it.
_VARIANT_FIELDS = (
    # Which reference build every variant statement is relative to.
    "assembly",
    # The count. Meaningless -- and misleading -- without the two below.
    "rawVariantRecords",
    # The pair that keeps a record count from reading as a final variant list.
    # Named in RunVariantCalling's own docstring as required by any explanation.
    "filteringApplied",
    "coreEndpoint",
)

# Coverage keeps every field it currently has: all of them are measurements or
# the pipeline's own note about one, none identifies a person, a sample or a
# path. It is listed explicitly anyway, for the future-field reason above.
_COVERAGE_FIELDS = (
    "meanTargetDepth",
    "targetNonoverlapBases",
    "breadth",
    # Base level. Not interchangeable with the interval-level fields below.
    "zeroCoverageBases",
    "zeroCoverageBasesPct",
    "lowMeanDepthThresholdX",
    "lowMeanDepthIntervals",
    "basesInLowMeanDepthIntervals",
    "basesInLowMeanDepthIntervalsPct",
    "fullyUncoveredIntervals",
    "basesInFullyUncoveredIntervals",
    "basesInFullyUncoveredIntervalsPct",
    # Always null, with the pipeline's fixed reason beside it. Both are kept so
    # the model can say the median was not measured rather than infer a zero.
    "medianTargetDepth",
    "medianNote",
)


def _pick(model: BaseModel, fields: tuple[str, ...]) -> dict[str, Any]:
    """Exactly the named fields, and nothing else.

    Indexes rather than `.get`: a name that no longer exists on the model raises
    here instead of silently dropping a fact the prompt was written to include.
    """
    dumped = model.model_dump()
    return {name: dumped[name] for name in fields}


def _diagnostic_grounding(code: str) -> dict[str, Any] | None:
    """Knowledge for one code, flattened for the prompt. None when unregistered.

    Returning None rather than an empty skeleton matters: the prompt then simply
    has no grounding for that code, and the model has nothing to pattern-match
    into an explanation. An empty `possibleCauses: []` invites a guess to fill
    it.
    """
    entry = knowledge.diagnostic(code)
    if entry is None:
        return None

    out: dict[str, Any] = {
        "code": entry.code,
        "severity": entry.severity,
        "resolution": entry.resolution,
        "title": entry.title,
        "meaning": entry.meaning,
    }
    grounding = entry.grounding
    if grounding is None:
        return out

    if grounding.possibleCauses:
        out["possibleCauses"] = [
            {"statement": c.statement, "sourceIds": c.sourceIds}
            for c in grounding.possibleCauses
        ]
    if grounding.scope:
        out["scope"] = [
            {"statement": c.statement, "sourceIds": c.sourceIds}
            for c in grounding.scope
        ]
    if grounding.checks:
        out["checks"] = [
            {
                "statement": c.statement,
                "look_at": f"{c.locator.kind}:{c.locator.id}",
                "sourceIds": c.sourceIds,
            }
            for c in grounding.checks
        ]
    if grounding.actions:
        out["actions"] = [
            {"statement": a.statement, "effect": a.effect, "sourceIds": a.sourceIds}
            for a in grounding.actions
        ]
    return out


def _failure_grounding(code: str) -> dict[str, Any] | None:
    entry = knowledge.failure(code)
    if entry is None:
        return None
    out: dict[str, Any] = {
        "code": entry.code,
        "title": entry.title,
        "meaning": entry.meaning,
    }
    grounding = entry.grounding
    if grounding is None:
        return out
    if grounding.possibleCauses:
        out["possibleCauses"] = [
            {"statement": c.statement, "sourceIds": c.sourceIds}
            for c in grounding.possibleCauses
        ]
    if grounding.scope:
        out["scope"] = [
            {"statement": c.statement, "sourceIds": c.sourceIds}
            for c in grounding.scope
        ]
    if grounding.checks:
        out["checks"] = [
            {
                "statement": c.statement,
                "look_at": f"{c.locator.kind}:{c.locator.id}",
                "sourceIds": c.sourceIds,
            }
            for c in grounding.checks
        ]
    if grounding.actions:
        out["actions"] = [
            {"statement": a.statement, "effect": a.effect, "sourceIds": a.sourceIds}
            for a in grounding.actions
        ]
    return out


def build_payload(explanation: RunExplanation) -> tuple[dict[str, Any], set[str]]:
    """The prompt's data block, and the set of ids that may be cited.

    Returns both together because they must agree by construction. Building the
    allowed-id set by walking the payload -- rather than by listing ids
    separately -- means a field cannot be added to the prompt without becoming
    citable, nor an id allowed without being visible to the model.
    """
    allowed: set[str] = set()

    # --- runtime facts, straight from the deterministic layer ---------------
    diagnostics: list[dict[str, Any]] = []
    for item in explanation.diagnostics:
        ref = f"dx:{item.code}"
        allowed.add(ref)
        diagnostics.append(
            {
                "evidenceId": ref,
                "code": item.code,
                "occurredAtStep": item.actualStepLabel or item.actualStepId,
                # The pipeline's own words for THIS occurrence. Data, not
                # instructions -- the system prompt says so explicitly.
                "messageFromPipeline": item.message,
                "impactFromPipeline": item.impact,
                "severity": item.severity,
                "resolution": item.resolution,
                "title": item.title,
                "meaning": item.meaning,
                "knowledgeAvailable": item.knowledgeAvailable,
            }
        )

    failures: list[dict[str, Any]] = []
    for item in explanation.failures:
        ref = f"fail:{item.code}"
        allowed.add(ref)
        failures.append(
            {
                "evidenceId": ref,
                "code": item.code,
                "occurredAtStep": item.actualStepLabel or item.actualStepId,
                "messageFromPipeline": item.message,
            }
        )

    limitations: list[dict[str, Any]] = []
    for item in explanation.limitations:
        ref = f"lim:{item.code}"
        allowed.add(ref)
        limitations.append(
            {
                "evidenceId": ref,
                "code": item.code,
                "statement": item.statement,
                "basis": item.basis,
            }
        )

    # --- grounding, only for codes this run raised --------------------------
    grounding: dict[str, Any] = {}
    cited_sources: set[str] = set()

    for code in {item.code for item in explanation.diagnostics}:
        entry = _diagnostic_grounding(code)
        if entry is None:
            continue
        grounding[f"dx:{code}"] = entry
        for bucket in ("possibleCauses", "scope", "checks", "actions"):
            for claim in entry.get(bucket, []):
                cited_sources.update(claim.get("sourceIds", []))

    for code in {item.code for item in explanation.failures}:
        entry = _failure_grounding(code)
        if entry is None:
            continue
        grounding[f"fail:{code}"] = entry
        for bucket in ("possibleCauses", "scope", "checks", "actions"):
            for claim in entry.get(bucket, []):
                cited_sources.update(claim.get("sourceIds", []))

    sources: list[dict[str, Any]] = []
    for source_id in sorted(cited_sources):
        entry = knowledge.source(source_id)
        if entry is None:
            continue
        ref = f"src:{source_id}"
        allowed.add(ref)
        sources.append(
            {
                "evidenceId": ref,
                "id": entry.id,
                "type": entry.type,
                "title": entry.title,
            }
        )

    check_ref = "run:checkSummary"
    allowed.add(check_ref)
    status_ref = "run:status"
    allowed.add(status_ref)

    payload: dict[str, Any] = {
        "run": {
            "evidenceId": status_ref,
            "contextKind": explanation.contextKind,
            "status": explanation.status,
            "runMode": explanation.identity.runMode,
            "resultsAvailable": explanation.resultsAvailable,
            "resultsUnavailableReason": explanation.resultsUnavailableReason,
        },
        "checkSummary": {
            "evidenceId": check_ref,
            "total": explanation.checkSummary.total,
            "counts": explanation.checkSummary.counts,
            "notable": [
                {"name": row.name, "status": row.status, "detail": row.detail}
                for row in explanation.checkSummary.notable
            ],
        },
        "diagnostics": diagnostics,
        "failures": failures,
        "limitations": limitations,
        "grounding": grounding,
        "sources": sources,
    }

    if explanation.coverage is not None:
        ref = "run:coverage"
        allowed.add(ref)
        payload["coverage"] = {
            "evidenceId": ref,
            **_pick(explanation.coverage, _COVERAGE_FIELDS),
        }
    if explanation.variantCalling is not None:
        ref = "run:variantCalling"
        allowed.add(ref)
        payload["variantCalling"] = {
            "evidenceId": ref,
            **_pick(explanation.variantCalling, _VARIANT_FIELDS),
        }
    if explanation.intendedUse:
        ref = "run:intendedUse"
        allowed.add(ref)
        payload["intendedUse"] = {
            "evidenceId": ref,
            "statement": explanation.intendedUse,
        }

    # Deliberately absent: jobId, runId, sampleId, the biological sample name,
    # artifact paths, absolute paths, log tails and artifact contents. The model
    # does not need to identify the sample to explain the run, and identifiers
    # are the part most worth not sending.
    return payload, allowed


__all__ = [
    "SYNTHESIS_JSON_SCHEMA",
    "RunSynthesis",
    "SynthesisStatement",
    "build_payload",
]
