"""One pipeline step, projected down to what a model may be told about it.

This is the whole WES half of the `get_step_detail` tool. It reads nothing
itself:

    step_reader.read(run_dir, planned, run_mode, step_id)   the existing reader
        |                                                   (id validation,
        |                                                    plan membership,
        |                                                    status, metrics,
        |                                                    checks, warnings)
        v
    StepEvidence                                            this module

The reader is called, not copied. Its two input gates -- STEP_ID_RE and
membership in the recorded plan -- are the same gates the HTTP endpoint relies
on, and they run before any path is assembled, so a model-supplied string never
reaches the filesystem. This module adds no second way in.

What it does add is subtraction. `step_reader.read()` answers "what happened in
this step" for a browser that already knows whose run it is looking at;
`StepEvidence` answers it for a prompt. Four things the reader returns are
therefore gone:

    inputs / outputs        run-relative paths. "06_variant_calling/
                            PATIENT_A.raw.vcf.gz" names the sample in the path
                            even when the sample_id column is null.
    artifacts               fileId, relativePath and displayName -- a download
                            address and a human-written name, both of which
                            embed the sample. Only the COUNT survives, which is
                            the part an explanation can actually use ("this
                            step registered three artifacts").
    startedAt / finishedAt  wall-clock stamps. elapsedSeconds is the duration
                            an explanation needs; the calendar time it happened
                            is not evidence about the pipeline.
    unsafe metrics          see privacy.Redactor.metrics.

Everything that does survive still goes through the redactor, because the
pipeline composes its own strings: a failure code observed in a real run is
`sort_order_DEMO_WES.L001`, which is a code with a lane unit -- and therefore a
sample name -- welded onto it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .. import step_reader
from .privacy import MetricValue, Redactor
from .run_scope import RunScope


# The prefix every step-level evidence id carries, alongside the `run:`, `dx:`,
# `fail:`, `lim:`, `src:`, `concept:` and `term:` prefixes contract.py already mints.
#
# The id is DERIVED from the step id, never supplied by a model: the server can
# therefore recompute it and check a citation against what the tool actually
# returned. An id the model composes on its own is not evidence of anything.
EVIDENCE_PREFIX = "step:"


def evidence_id(step_id: str) -> str:
    """The citable id for one step's evidence. Pure function of the step id."""
    return f"{EVIDENCE_PREFIX}{step_id}"


class UnreadableStep(Exception):
    """Base for the two refusals. Carries a message safe to show a model."""


class MalformedStepId(UnreadableStep):
    """The string is not a step id at all."""


class StepNotInThisRun(UnreadableStep):
    """A well-formed step id that this run never planned."""


class StepCheckEvidence(BaseModel):
    """One row of the step's own validation table, as the pipeline wrote it."""

    name: str
    # PASS / WARN / FAIL, main.sh's vocabulary. Uppercase here, unlike the
    # step-level `validationStatus` below, which main.sh writes lowercase.
    status: str = ""
    detail: str = ""


class StepWarningEvidence(BaseModel):
    """One warning this step recorded.

    `message` and `impact` are the pipeline's words for THIS occurrence, not
    general knowledge about the code: MULTIQC_MISSING is raised from two places
    with different impact text.
    """

    code: str = ""
    message: str = ""
    impact: str = ""
    canContinue: bool = False


class StepFailureEvidence(BaseModel):
    """One failure this step recorded. `code` is a free string, not an enum."""

    code: str = ""
    message: str = ""


class StepEvidence(BaseModel):
    """The allowlist. A field that is not here is not sent, by construction."""

    # What a statement resting on this step must cite, in the same shape the
    # payload's own ids use. It travels WITH the data the model reads, so the
    # model copies an id it was given rather than inventing one -- and the
    # server, which minted it from the step id, can verify that.
    evidenceId: str
    stepId: str
    # pending / running are backend-derived: main.sh writes a step document
    # only when a step ends, so neither state exists on disk.
    status: str
    # None while the step is pending or running -- not 0, which would read as
    # "finished successfully".
    exitCode: int | None = None
    # The pipeline's own measurement for a finished step; measured from the
    # STARTED row for the running one. Never an estimate of what remains.
    elapsedSeconds: int = 0

    # The step as a whole: pass / warn / fail, lowercase, or "" when the step
    # has not finished.
    validationStatus: str = ""
    checks: list[StepCheckEvidence] = Field(default_factory=list)

    # Keys are main.sh's metric identifiers (mapped_pct, percent_duplication).
    # Only the ones privacy.Redactor.metrics admits.
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    # How many metrics this step recorded that were not safe to send. Reported
    # so a reader can tell "this step measured nothing" from "some of what it
    # measured was withheld".
    withheldMetricCount: int = 0

    warnings: list[StepWarningEvidence] = Field(default_factory=list)
    failures: list[StepFailureEvidence] = Field(default_factory=list)

    # Count only. Names, paths and download ids are deliberately absent.
    artifactCount: int = 0
    # main.sh's own judgement that the pipeline could continue past this step.
    nextStepReady: bool = False


def read_step_evidence(scope: RunScope, step_id: Any) -> StepEvidence:
    """Read one step of the scoped run and project it for a model.

    `step_id` is typed Any on purpose: it arrives from outside and is passed to
    step_reader.read(), which rejects anything that is not a well-formed step
    id before touching the filesystem. Re-checking it here would be a second
    implementation of the same rule, and the two could drift.
    """
    try:
        detail = step_reader.read(
            scope.run_dir, list(scope.planned_steps), scope.run_mode, step_id
        )
    except ValueError as exc:
        raise MalformedStepId(
            "not a step id: a step id looks like '04_processing'"
        ) from exc
    except step_reader.StepNotPlanned as exc:
        # The plan is the useful thing to say back, and it is safe to say: step
        # ids are the pipeline's own vocabulary and carry nothing about the
        # sample. Same reasoning as the 404 body in api/steps.py.
        raise StepNotInThisRun(
            f"this run did not plan step '{step_id}'. "
            f"planned steps: {', '.join(scope.planned_steps)}"
        ) from exc

    return _project(detail, scope.redactor)


def _project(detail: dict[str, Any], redactor: Redactor) -> StepEvidence:
    """Copy the allowed fields across, scrubbing every string on the way."""
    validation = detail.get("validation") or {}
    metrics, withheld = redactor.metrics(detail.get("metrics") or {})

    return StepEvidence(
        evidenceId=evidence_id(detail["stepId"]),
        # Not scrubbed: it was validated against the recorded plan, so it is
        # one of the pipeline's own step ids.
        stepId=detail["stepId"],
        status=detail["status"],
        exitCode=detail["exitCode"],
        elapsedSeconds=detail["elapsedSeconds"],
        validationStatus=redactor.text(validation.get("status")),
        checks=[
            StepCheckEvidence(
                name=redactor.text(row.get("name")),
                status=redactor.text(row.get("status")),
                detail=redactor.text(row.get("detail")),
            )
            for row in validation.get("results") or []
        ],
        metrics=metrics,
        withheldMetricCount=withheld,
        warnings=[
            StepWarningEvidence(
                code=redactor.text(row.get("code")),
                message=redactor.text(row.get("message")),
                impact=redactor.text(row.get("impact")),
                canContinue=row.get("canContinue") is True,
            )
            for row in detail.get("warnings") or []
        ],
        failures=[
            StepFailureEvidence(
                code=redactor.text(row.get("code")),
                message=redactor.text(row.get("message")),
            )
            for row in detail.get("failures") or []
        ],
        artifactCount=len(detail.get("artifacts") or []),
        nextStepReady=detail.get("nextStepReady") is True,
    )


__all__ = [
    "EVIDENCE_PREFIX",
    "MalformedStepId",
    "StepCheckEvidence",
    "StepEvidence",
    "StepFailureEvidence",
    "StepNotInThisRun",
    "StepWarningEvidence",
    "UnreadableStep",
    "evidence_id",
    "read_step_evidence",
]
