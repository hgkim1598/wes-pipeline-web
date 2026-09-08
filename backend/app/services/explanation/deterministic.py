"""Combine runtime facts with shared knowledge, without a model.

This is the first layer that reads both halves at once:

    RunDiagnosticContext   what happened in this run   (run_context.py)
    shared knowledge       what those codes mean       (knowledge.py)

Everything here is a pure function of its input. The same context produces the
same explanation, byte for byte, every time -- which is what makes it testable,
free, instant, and available when a model is not. An LLM layer is meant to sit
*above* this, not replace it.

The merge rule
--------------

    what happened   ->  runtime wins, always
    what it means   ->  knowledge supplies it

Knowledge never overrides a runtime fact. In particular ``relatedSteps`` says
where a diagnostic *can* be raised and is never used to state where it *was*:
MULTIQC_MISSING is raised from two different steps, so only the run knows which
one applies. ``actualStepId`` therefore comes from the warning, never from the
knowledge entry -- and the field is named for that.

What this layer deliberately does not do
----------------------------------------

No cause inference, no risk score, no quality verdict, no recommended actions,
no clinical language. It states what the pipeline recorded and what the codes
mean. Judging whether 7% zero-coverage is acceptable needs thresholds this
project has not established, and inventing one here would put a number behind
an opinion. That, and any synthesis across several findings, is left to a later
layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import knowledge
from .knowledge import DiagnosticResolution, DiagnosticSeverity, DiagnosticStatus
from .run_context import (
    ContextKind,
    RunCheck,
    RunCoverage,
    RunDiagnosticContext,
    RunIdentity,
    RunVariantCalling,
)

# attention first, then codes we have no knowledge for, then info.
#
# Unknown sits in the middle on purpose. Putting it last would bury a brand new
# pipeline code under routine notes; putting it first would treat every
# unregistered code as urgent. Neither is a claim about its severity -- it is
# only an ordering, and `severity` stays None so nothing downstream reads one.
_SEVERITY_ORDER: dict[DiagnosticSeverity | None, int] = {
    "attention": 0,
    None: 1,
    "info": 2,
}


class EvidenceRef(BaseModel):
    """Where one statement came from. Small on purpose.

    Enough to trace a claim back to the runtime event and the reader that
    produced it; not a provenance graph.
    """

    section: str
    # Which reader produced that section, copied from the context.
    source: str | None = None
    stepId: str | None = None
    code: str | None = None


class DiagnosticExplanation(BaseModel):
    """One diagnostic event, with what this run observed and what it means.

    The two halves are kept separately labelled rather than blended, so a later
    reader can always tell which is which.

    When ``knowledgeAvailable`` is False the code is not in the shared source.
    ``severity``, ``resolution``, ``title``, ``meaning`` and ``knowledgeStatus``
    are then all None and carry **no** information -- they are not defaults.
    Nothing may read `resolution is None` as "nothing was repaired" without
    first checking ``knowledgeAvailable``.
    """

    code: str

    # --- what this run observed (authoritative) ---------------------------
    actualStepId: str | None = None
    # Display name for that step, when the step is registered. Convenience
    # only; actualStepId is the fact.
    actualStepLabel: str | None = None
    message: str
    impact: str = ""
    canContinue: bool = False

    # --- what the code means ----------------------------------------------
    knowledgeAvailable: bool
    # Two independent axes. severity is "how much attention"; resolution is
    # "was it already handled". They are not collapsed into one value here --
    # doing so loses the case that is both info and repaired.
    severity: DiagnosticSeverity | None = None
    resolution: DiagnosticResolution = None
    title: str | None = None
    meaning: str | None = None
    # `legacy` marks a code the pipeline no longer emits, kept so older runs
    # stay readable.
    knowledgeStatus: DiagnosticStatus | None = None

    evidence: EvidenceRef


class FailureExplanation(BaseModel):
    """One recorded failure.

    No knowledge lookup: failure codes are not a closed set. main.sh composes
    some of them from run values (`sort_order_DEMO_WES.L001`), so there is
    nothing stable to look up and the runtime text is the explanation.
    """

    code: str
    message: str
    actualStepId: str | None = None
    actualStepLabel: str | None = None
    evidence: EvidenceRef


class CheckSummary(BaseModel):
    """The validation table, counted and filtered -- not turned into warnings.

    A WARN row says a step finished with warnings. It does not say which
    warning, and no diagnostic may be manufactured from it. `notable` is simply
    the non-PASS rows, kept verbatim.
    """

    total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    notable: list[RunCheck] = Field(default_factory=list)


class Limitation(BaseModel):
    """A scope statement the run's own structured fields establish.

    Every one of these is triggered by a specific field being a specific value,
    and `basis` names that field. None of them is a judgement about quality.
    """

    code: str
    statement: str
    basis: str


class RunExplanation(BaseModel):
    """Deterministic explanation of one run. Same input, same output."""

    contextKind: ContextKind
    status: str
    resultsAvailable: bool
    resultsUnavailableReason: str | None = None

    identity: RunIdentity
    checkSummary: CheckSummary
    diagnostics: list[DiagnosticExplanation] = Field(default_factory=list)
    failures: list[FailureExplanation] = Field(default_factory=list)

    # Passed through unchanged. Base-level and interval-level coverage keep
    # their own names; meaningful nulls stay null.
    coverage: RunCoverage | None = None
    variantCalling: RunVariantCalling | None = None

    limitations: list[Limitation] = Field(default_factory=list)
    intendedUse: str | None = None
    sources: dict[str, str] = Field(default_factory=dict)


# --- assembly ---------------------------------------------------------------


def _step_label(step_id: str | None) -> str | None:
    if not step_id:
        return None
    entry = knowledge.step(step_id)
    return entry.label if entry else None


def _explain_diagnostics(
    context: RunDiagnosticContext,
) -> list[DiagnosticExplanation]:
    source = context.sources.get("warnings")
    items: list[DiagnosticExplanation] = []

    for warning in context.warnings:
        entry = knowledge.diagnostic(warning.code)
        items.append(
            DiagnosticExplanation(
                code=warning.code,
                # Runtime wins. The knowledge entry's relatedSteps is not
                # consulted here, by design.
                actualStepId=warning.stepId,
                actualStepLabel=_step_label(warning.stepId),
                message=warning.message,
                impact=warning.impact,
                canContinue=warning.canContinue,
                knowledgeAvailable=entry is not None,
                severity=entry.severity if entry else None,
                resolution=entry.resolution if entry else None,
                title=entry.title if entry else None,
                meaning=entry.meaning if entry else None,
                knowledgeStatus=entry.status if entry else None,
                evidence=EvidenceRef(
                    section="warnings",
                    source=source,
                    stepId=warning.stepId,
                    code=warning.code,
                ),
            )
        )

    # Stable sort: ordering never reshuffles items of equal rank, so the
    # pipeline's own order survives inside each group.
    items.sort(key=lambda item: _SEVERITY_ORDER[item.severity])
    return items


def _explain_failures(context: RunDiagnosticContext) -> list[FailureExplanation]:
    source = context.sources.get("failures")
    return [
        FailureExplanation(
            code=failure.code,
            message=failure.message,
            actualStepId=failure.stepId,
            actualStepLabel=_step_label(failure.stepId),
            evidence=EvidenceRef(
                section="failures",
                source=source,
                stepId=failure.stepId,
                code=failure.code,
            ),
        )
        for failure in context.failures
    ]


def _summarise_checks(context: RunDiagnosticContext) -> CheckSummary:
    counts: dict[str, int] = {}
    for check in context.checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    return CheckSummary(
        total=len(context.checks),
        counts=counts,
        notable=[check for check in context.checks if check.status != "PASS"],
    )


def _limitations(context: RunDiagnosticContext) -> list[Limitation]:
    """Scope statements, each tied to one structured field.

    These are fixed sentences selected by a field's value -- never a judgement
    about whether a number is good. `basis` records which field selected each
    one so the statement can be checked against the run.
    """
    out: list[Limitation] = []

    if context.outcome.analysisOutputProduced is False:
        out.append(
            Limitation(
                code="NO_ANALYSIS_OUTPUT",
                # Says only what the field establishes. It used to add "이 실행은
                # 사전 점검만 수행했고", which infers the run mode -- and the flag
                # does not carry that. A --check-only run sets it False
                # (result_reader._read_precheck), but so does a *full* run whose
                # raw VCF is missing: _read_full derives it from
                # core_summary.core_complete, and core_summary.json is written by
                # write_final_report before finalization can fail. Calling that
                # run a precheck would be simply wrong.
                statement="이 실행은 분석 산출물(BAM·VCF)을 만들지 않았습니다.",
                basis="outcome.analysisOutputProduced",
            )
        )

    variant = context.variantCalling
    if variant is not None and variant.filteringApplied is False:
        out.append(
            Limitation(
                code="UNFILTERED_VARIANTS",
                statement=(
                    "변이 결과에 품질 필터가 적용되지 않았습니다. "
                    f"현재 결과 지점은 {variant.coreEndpoint or '알 수 없음'}이며, "
                    "확정된 변이 목록이 아니라 후보 기록입니다."
                ),
                basis="variantCalling.filteringApplied",
            )
        )

    coverage = context.coverage
    if coverage is not None and coverage.medianNote:
        out.append(
            Limitation(
                code="MEDIAN_NOT_MEASURED",
                # The pipeline's own reason, not a restatement.
                statement=f"깊이 중앙값은 측정되지 않았습니다 — {coverage.medianNote}",
                # The field actually tested, so the statement can be checked
                # against the run. medianTargetDepth is always null and would
                # not tell a reader which value selected this sentence.
                basis="coverage.medianNote",
            )
        )

    if context.intendedUse:
        out.append(
            Limitation(
                code="INTENDED_USE",
                statement=context.intendedUse,
                basis="intendedUse",
            )
        )

    if context.contextKind == "in_progress":
        out.append(
            Limitation(
                code="RUN_IN_PROGRESS",
                # "아직 끝나지 않아", not "진행 중": in_progress covers `queued`
                # too, and a run that has not started yet is not running.
                statement="이 실행은 아직 끝나지 않아 결과가 확정되지 않았습니다.",
                basis="contextKind",
            )
        )

    return out


def build_run_explanation(context: RunDiagnosticContext) -> RunExplanation:
    """Explain one run from an already-assembled context.

    This function reads no database, no run directory and no API. Assembling
    the facts is run_context's job; combining them with meaning is this one's.
    Keeping them apart is what lets the merge rules above be tested on their
    own.
    """
    return RunExplanation(
        contextKind=context.contextKind,
        status=context.outcome.status,
        resultsAvailable=context.resultsAvailable,
        resultsUnavailableReason=context.resultsUnavailableReason,
        identity=context.identity,
        checkSummary=_summarise_checks(context),
        diagnostics=_explain_diagnostics(context),
        failures=_explain_failures(context),
        # Passed through. Re-deriving coverage numbers here would create a
        # second place where base-level and interval-level values could be
        # confused; there is no reason to touch them.
        coverage=context.coverage,
        variantCalling=context.variantCalling,
        limitations=_limitations(context),
        intendedUse=context.intendedUse,
        sources=context.sources,
    )


__all__ = [
    "CheckSummary",
    "DiagnosticExplanation",
    "EvidenceRef",
    "FailureExplanation",
    "Limitation",
    "RunExplanation",
    "build_run_explanation",
]
