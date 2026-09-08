"""Assemble one run's *runtime facts* into a single normalised context.

This is the "what actually happened in this run" half of the explanation layer.
It contains no meaning: severity, resolution and the beginner-facing text live
in the shared knowledge source (``explanation/knowledge.py``) and are merged in
a later step, not here. Keeping them apart is what lets a later explanation say
"this warning is informational" without that judgement being baked into the
record of what the pipeline observed.

Nothing here calls the HTTP API. The same readers the API routes use are called
directly, so there is one source of truth per fact:

    db.jobs row              identity, orchestration status, timestamps
    run_status_reader        reconciled status, progress, per-step state
    result_reader            checks / warnings / failures / coverage / variants
    step documents           per-step warnings and failures when no result exists

Four context kinds, because a missing section means different things
--------------------------------------------------------------------

``/results`` is not available for every run: ``_read_full`` needs
``core_summary.json``, which only finalization writes. A run that failed at
03_alignment therefore has no results at all -- and that is exactly the run an
explanation is most needed for.

So the context records which kind of run it describes:

    full         finalization completed; the full result document exists
    precheck     --check-only; a real verdict, but no analysis output ever
    failed       terminal without a result document
    in_progress  still running; a result document may yet appear

Downstream must never have to guess why ``coverage`` is None. For a precheck it
is *never* produced; for a failed run the pipeline did not get there; for an
in-progress run it may arrive later. ``contextKind`` plus
``resultsUnavailableReason`` say which.

Deliberately excluded
---------------------

logTail, absolute server paths, artifact contents, run directory listings,
environment and secrets. ``logTail`` in particular is the one place this API
leaks server paths (``/home/vboxuser/...``); sanitised log evidence is a
separate, later concern.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ... import db
from .. import result_reader, run_status_reader, worker

ContextKind = Literal["full", "precheck", "failed", "in_progress"]

# Backend orchestration state -> reported status, used only when the pipeline
# has written no run_status.json of its own. Mirrors api/jobs.py._FALLBACK_STATUS;
# imported rather than redefined would couple a service to an API module, and the
# two are asserted equal in the tests.
_FALLBACK_STATUS = {
    worker.QUEUED: "queued",
    worker.RUNNING: "running",
    worker.CANCELLING: "running",
    worker.CANCELLED: "cancelled",
    worker.EXEC_FAILED: "failed",
    worker.DONE: "failed",
}

_TERMINAL_FAILURE = ("failed", "cancelled")


class JobNotFound(Exception):
    """No job row with this id."""


# --- sections ---------------------------------------------------------------


class RunIdentity(BaseModel):
    """Who this run is. Entirely from the jobs row."""

    jobId: str
    runId: str
    # Null on rows created before the column existed. Never back-filled.
    sampleId: str | None = None
    profileId: str
    captureKitId: str | None = None
    # check_only | full. A check_only run produces no BAM or VCF at all.
    runMode: str


class RunOutcome(BaseModel):
    """How the run ended, and how far it got."""

    status: str
    # main.sh's own vocabulary. Kept for diagnosis; not for user-facing text.
    pipelineStatus: str | None = None
    # Share of planned steps that reached a terminal state. NOT elapsed time.
    progress: int = 0
    currentStep: str | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    error: str | None = None
    # None when no result document exists, i.e. "not known from here" rather
    # than "no output was produced".
    analysisOutputProduced: bool | None = None
    elapsedSeconds: int | None = None


class RunStepState(BaseModel):
    """One planned step's outcome. `pending` and `running` are derived by the
    backend: main.sh writes a step document only when a step finishes."""

    stepId: str
    status: str
    elapsedSeconds: int = 0


class RunCheck(BaseModel):
    """One row of a validation table. PASS / WARN / FAIL as written."""

    name: str
    status: str
    detail: str = ""


class RunWarning(BaseModel):
    """One diagnostic event as this run recorded it.

    `message` and `impact` are the pipeline's own text for *this occurrence*.
    They are not general knowledge: MULTIQC_MISSING is raised from two places
    with different impact text, so the meaning of a code and what it meant here
    are separate things.
    """

    stepId: str | None = None
    code: str = ""
    message: str
    impact: str = ""
    canContinue: bool = False


class RunFailure(BaseModel):
    """One recorded failure.

    `code` is a free string, not an enum. main.sh composes some of them from
    run values -- an observed one is `sort_order_DEMO_WES.L001` -- so it can be
    matched but never exhaustively enumerated.
    """

    stepId: str | None = None
    code: str = ""
    message: str


class RunCoverage(BaseModel):
    """mosdepth-derived numbers, in the units the pipeline separated them into.

    Base level and interval level are different measurements and are not
    interchangeable: an interval whose mean depth is above 0 can still contain
    0x bases, so basesInFullyUncoveredIntervalsPct is always <=
    zeroCoverageBasesPct. Both are carried with their own names.

    Nulls are meaningful. `zeroCoverageBases` is null on runs recorded before
    the pipeline emitted it -- the percentage can be derived from 1X breadth,
    the count cannot. `medianTargetDepth` is *always* null because mosdepth runs
    with --no-per-base, and `medianNote` carries the pipeline's own reason.
    Neither may be replaced with 0.
    """

    meanTargetDepth: float | None = None
    targetNonoverlapBases: int | None = None
    breadth: dict[str, float] = Field(default_factory=dict)

    zeroCoverageBases: int | None = None
    zeroCoverageBasesPct: float | None = None

    lowMeanDepthThresholdX: float | None = None
    lowMeanDepthIntervals: int | None = None
    basesInLowMeanDepthIntervals: int | None = None
    basesInLowMeanDepthIntervalsPct: float | None = None
    fullyUncoveredIntervals: int | None = None
    basesInFullyUncoveredIntervals: int | None = None
    basesInFullyUncoveredIntervalsPct: float | None = None

    medianTargetDepth: None = None
    medianNote: str | None = None


class RunVariantCalling(BaseModel):
    """Core variant-calling result, with the limits that qualify it.

    `filteringApplied` and `coreEndpoint` are not decoration. Without them a
    record count reads as a final variant list; with them it reads as what it
    is. Any later explanation needs both to state the scope honestly.
    """

    sample: str | None = None
    assembly: str | None = None
    rawVariantRecords: int | None = None
    filteringApplied: bool = False
    coreEndpoint: str = ""
    rawVcfRelative: str | None = None
    gvcfRelative: str | None = None


class RunDiagnosticContext(BaseModel):
    """Everything a later explanation layer may treat as fact about one run."""

    contextKind: ContextKind
    resultsAvailable: bool
    # Why the result document was not used. None when it was.
    resultsUnavailableReason: str | None = None

    identity: RunIdentity
    outcome: RunOutcome
    steps: list[RunStepState] = Field(default_factory=list)

    # The final validation table. Separate from `warnings` on purpose: a WARN
    # row says a step finished with warnings, a warning says which one and why.
    # Neither is derivable from the other, so both are carried.
    checks: list[RunCheck] = Field(default_factory=list)
    warnings: list[RunWarning] = Field(default_factory=list)
    failures: list[RunFailure] = Field(default_factory=list)

    # None means this kind of run has no such section, not that it is empty.
    coverage: RunCoverage | None = None
    variantCalling: RunVariantCalling | None = None
    optionalSteps: dict[str, str] = Field(default_factory=dict)

    # The pipeline's own scope statement, e.g. "research and education only;
    # not a diagnostic result". Carried verbatim so nothing downstream has to
    # invent the boundary.
    intendedUse: str | None = None

    # section -> which reader produced it. Not a provenance framework; enough
    # that a later reader can tell run-level facts from step-level ones.
    sources: dict[str, str] = Field(default_factory=dict)


# --- assembly ---------------------------------------------------------------


def _step_documents_facts(
    run_dir: Path, step_ids: list[str]
) -> tuple[list[RunWarning], list[RunFailure], dict[str, list[RunCheck]]]:
    """Warnings, failures and check rows straight from step documents.

    Used when no result document exists. The step's own document is the only
    structured source then -- `/api/jobs/{id}` flattens warnings and failures
    into one list of strings, which loses both the distinction and the fields.

    `stepId` is filled in from the document actually read. The documents leave
    it null (only result_reader populates it), and recording which file a fact
    came from is not a distortion of the fact.
    """
    warnings: list[RunWarning] = []
    failures: list[RunFailure] = []
    checks: dict[str, list[RunCheck]] = {}

    for step_id in step_ids:
        doc = run_status_reader.read_step_document(run_dir, step_id)
        if doc is None:
            continue
        for raw in result_reader.warnings_of(doc.get("warnings")):
            raw["stepId"] = step_id
            warnings.append(RunWarning(**raw))
        for raw in result_reader.failures_of(doc.get("failures")):
            raw["stepId"] = step_id
            failures.append(RunFailure(**raw))
        rows = [RunCheck(**row) for row in result_reader.checks_of(doc)]
        if rows:
            checks[step_id] = rows
    return warnings, failures, checks


def _outcome_without_results(
    row: Any, adapted: dict[str, Any] | None
) -> tuple[RunOutcome, str]:
    """Status and progress when there is no result document.

    Same reconciliation GET /api/jobs/{id} performs, so the two never disagree:
    the pipeline's own run_status.json wins, and a cancel the backend recorded
    but the pipeline could not overrides it.
    """
    if adapted is None:
        status = _FALLBACK_STATUS.get(row["status"], "failed")
        error = row["error"]
        if status == "failed" and not error:
            error = "the pipeline exited without writing a run status document"
        return (
            RunOutcome(
                status=status,
                progress=0,
                startedAt=row["started_at"],
                finishedAt=row["finished_at"],
                error=error,
            ),
            "db.jobs",
        )

    status = adapted["status"]
    if row["status"] == worker.CANCELLED and status != "cancelled":
        status = "cancelled"
    return (
        RunOutcome(
            status=status,
            pipelineStatus=adapted["pipelineStatus"],
            progress=adapted["progress"],
            currentStep=adapted["currentStep"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            error=adapted["error"] or row["error"],
        ),
        "run_status_reader",
    )


def build_run_diagnostic_context(job_id: str) -> RunDiagnosticContext:
    """Normalise one run's runtime facts.

    Raises JobNotFound for an unknown id. A malformed pipeline document
    propagates as result_reader.MalformedPipelineDocument: a data fault is
    reported, never quietly turned into a thinner-looking context.
    """
    row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        raise JobNotFound(job_id)

    run_dir = Path(row["run_dir"])
    planned: list[str] = db.loads(row["planned_steps"], [])

    identity = RunIdentity(
        jobId=row["job_id"],
        runId=row["run_id"],
        sampleId=row["sample_id"],
        profileId=row["profile_id"],
        captureKitId=row["capture_kit_id"],
        runMode=row["run_mode"],
    )

    adapted = run_status_reader.read(run_dir, planned, row["run_mode"])
    steps = [
        RunStepState(
            stepId=state["stepId"],
            status=state["status"],
            elapsedSeconds=state["elapsedSeconds"],
        )
        for state in (adapted["steps"] if adapted else [])
    ]

    sources: dict[str, str] = {"identity": "db.jobs"}

    try:
        result = result_reader.read(run_dir)
    except result_reader.ResultsNotReady as exc:
        return _without_results(
            row, identity, adapted, steps, sources, run_dir, planned, str(exc)
        )

    # --- a result document exists: full or precheck --------------------------
    outcome, outcome_source = _outcome_without_results(row, adapted)
    outcome.analysisOutputProduced = result["analysisOutputProduced"]
    outcome.elapsedSeconds = result["elapsedSeconds"]
    sources["outcome"] = outcome_source
    sources["steps"] = "run_status_reader"
    for section in ("checks", "warnings", "failures"):
        sources[section] = "result_reader"

    coverage = result["coverage"]
    variant_calling = result["variantCalling"]
    if coverage is not None:
        sources["coverage"] = "result_reader"
    if variant_calling is not None:
        sources["variantCalling"] = "result_reader"

    return RunDiagnosticContext(
        contextKind="precheck" if result["resultType"] == "precheck" else "full",
        resultsAvailable=True,
        identity=identity,
        outcome=outcome,
        steps=steps,
        checks=[RunCheck(**row_) for row_ in result["checks"]],
        warnings=[RunWarning(**row_) for row_ in result["warnings"]],
        failures=[RunFailure(**row_) for row_ in result["failures"]],
        coverage=RunCoverage(**coverage) if coverage is not None else None,
        variantCalling=(
            RunVariantCalling(**variant_calling)
            if variant_calling is not None
            else None
        ),
        optionalSteps=result["optionalSteps"],
        intendedUse=result["intendedUse"],
        sources=sources,
    )


def _without_results(
    row: Any,
    identity: RunIdentity,
    adapted: dict[str, Any] | None,
    steps: list[RunStepState],
    sources: dict[str, str],
    run_dir: Path,
    planned: list[str],
    reason: str,
) -> RunDiagnosticContext:
    """The failed / in-progress path.

    No result document exists, so every fact comes from the jobs row, the run
    status document and the individual step documents. coverage,
    variantCalling, optionalSteps and intendedUse stay unset -- the pipeline
    never produced them, and inventing an empty shape would read as "measured,
    found nothing".
    """
    outcome, outcome_source = _outcome_without_results(row, adapted)
    sources["outcome"] = outcome_source
    sources["steps"] = "run_status_reader" if adapted else "db.jobs"

    warnings, failures, checks_by_step = _step_documents_facts(run_dir, planned)
    if warnings or failures or checks_by_step:
        sources["warnings"] = "step documents"
        sources["failures"] = "step documents"
        if checks_by_step:
            # Step-level validation rows, not a run-level validation table.
            # The marker says so, because a later reader must not treat these
            # as final_validation.tsv.
            sources["checks"] = "step documents: " + ", ".join(sorted(checks_by_step))

    kind: ContextKind = (
        "failed" if outcome.status in _TERMINAL_FAILURE else "in_progress"
    )

    return RunDiagnosticContext(
        contextKind=kind,
        resultsAvailable=False,
        resultsUnavailableReason=reason,
        identity=identity,
        outcome=outcome,
        steps=steps,
        checks=[row_ for rows in checks_by_step.values() for row_ in rows],
        warnings=warnings,
        failures=failures,
        coverage=None,
        variantCalling=None,
        optionalSteps={},
        intendedUse=None,
        sources=sources,
    )


def as_json(context: RunDiagnosticContext) -> str:
    """Stable JSON for tests and for eyeballing what an LLM would receive."""
    return json.dumps(context.model_dump(), ensure_ascii=False, indent=2)


__all__ = [
    "ContextKind",
    "JobNotFound",
    "RunCheck",
    "RunCoverage",
    "RunDiagnosticContext",
    "RunFailure",
    "RunIdentity",
    "RunOutcome",
    "RunStepState",
    "RunVariantCalling",
    "RunWarning",
    "as_json",
    "build_run_diagnostic_context",
]