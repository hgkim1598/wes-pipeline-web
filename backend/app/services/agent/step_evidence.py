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

from pydantic import BaseModel, Field, model_serializer

from ... import config
from ...schemas import ResourceBundleDiagnosis
from .. import resource_bundle_diagnosis, step_reader
from ..explanation import knowledge
from . import doc_retrieval
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


class StepRemedy(BaseModel):
    """A remedy direction (log 17.4): it CHANGES something, so it says what and
    who must approve. Static curated text, like the checks; the agent can only
    propose it -- there is no write tool."""

    statement: str
    changes: str
    approval: str
    # Titles of the sources behind THIS remedy (the entry's `sources` merges
    # every claim's). Without it a bcftools-backed step could be presented as a
    # GATK recommendation (Codex U2-U4 round 1). Titles only, like `sources`.
    sources: list[str] = Field(default_factory=list)


class StepDocPassage(BaseModel):
    """One verified official-document excerpt about this KIND of cause (log 18).

    `evidenceId` is minted from the passage id, and tools.credit() makes it
    citable only because the server returned it. `source` is the title from
    wes_sources.json; the URL stays server-side, like every `sources` title, and
    the UI resolves the id to a link.
    """

    evidenceId: str
    source: str
    heading: str
    # Verbatim, in the document's language. `explains` is this project's
    # Korean reading of it and must not go beyond it; `limits` says what the
    # excerpt cannot tell about a particular run.
    quote: str
    explains: str
    limits: str


# Sent with every non-empty officialDocs list. Static text, part of the data
# contract rather than the prompt, so the v3 prompt hash does not change when
# the excerpts are switched on and v3 / v3rag differ in exactly one thing.
DOC_NOTE = (
    "officialDocs are excerpts from tool manuals and format specifications about "
    "this KIND of failure. They explain what the message means and what the tool "
    "requires; they do not show what happened in this run -- the records above do. "
    "Cite a doc evidenceId only for what its excerpt says, never present a command "
    "from an excerpt as something that was run, and offer nothing for a cause that "
    "has no excerpt."
)


class StepCauseGuidance(BaseModel):
    """Curated read-only checks for one classified resource_bundle cause (P1).

    Looked up by exact key -- the cause's kind and resource role -- in
    config/knowledge/wes_cause_kinds.json. Static text written for this
    project, not anything the run produced, so it is not redacted; a test keeps
    every sentence unchanged by the model-input redactor instead. `sources` are
    titles only: the URLs stay in wes_sources.json.
    """

    kind: str
    resourceRole: str
    title: str
    checks: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    # Separate from `checks` on purpose: a look and a change are never one list.
    remedies: list[StepRemedy] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    # Only when config.DOC_RAG is on; absent from the JSON otherwise (see
    # read_step_evidence), so the v3 tool result is byte-for-byte unchanged.
    officialDocs: list[StepDocPassage] | None = None
    docNote: str | None = None

    @model_serializer(mode="wrap")
    def _omit_unset_docs(self, handler):
        data = handler(self)
        for key in ("officialDocs", "docNote"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


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

    # Why resource_bundle failed, for 00_input_validation only (P0-1). The same
    # model, built by the same projection with the same redactor, as the public
    # step detail -- already redacted and subject to its disclosure rule, so it
    # is copied across as it is rather than scrubbed a second time.
    resourceBundleDiagnosis: ResourceBundleDiagnosis | None = None
    # One entry per distinct (kind, role) among those causes that has curated
    # checks. Empty when there is no diagnosis or no cause kind is known.
    causeGuidance: list[StepCauseGuidance] = Field(default_factory=list)


def cause_guidance(
    diagnosis: ResourceBundleDiagnosis | None, *, with_docs: bool | None = None
) -> list[StepCauseGuidance]:
    """Exact-key lookup of curated checks for each distinct classified cause.

    A duplicated cause (the same tool failing once per VCF) yields ONE entry, so
    the guidance never looks like more problems than the diagnosis lists.

    `with_docs` (default: config.DOC_RAG) adds the official excerpts filed under
    the entry's kind, ranked against that cause's own evidence sentence. A kind
    with no guidance entry -- `unknown` included -- gets no excerpts either.
    """
    if diagnosis is None:
        return []
    if with_docs is None:
        with_docs = config.DOC_RAG
    out: list[StepCauseGuidance] = []
    seen: set[tuple[str, str]] = set()
    for cause in diagnosis.causes:
        key = (cause.kind, cause.resourceRole)
        if key in seen:
            continue
        seen.add(key)
        kind = knowledge.cause_kind(cause.kind)
        if kind is None:
            continue
        role = knowledge.resource_role(cause.resourceRole)
        claims = [*kind.checks, *(role.checks if role else [])]
        source_ids = list(
            dict.fromkeys(
                i for claim in [*claims, *kind.cautions, *kind.remedies] for i in claim.sourceIds
            )
        )
        out.append(
            StepCauseGuidance(
                kind=cause.kind,
                resourceRole=cause.resourceRole,
                title=kind.title if role is None else f"{kind.title}: {role.title}",
                checks=[claim.statement for claim in claims],
                cautions=[claim.statement for claim in kind.cautions],
                remedies=[
                    StepRemedy(
                        statement=r.statement,
                        changes=r.changes,
                        approval=r.approval,
                        sources=[knowledge.source(i).title for i in r.sourceIds if knowledge.source(i)],
                    )
                    for r in kind.remedies
                ],
                sources=[knowledge.source(i).title for i in source_ids if knowledge.source(i)],
            )
        )
        if with_docs:
            docs = [
                StepDocPassage(
                    evidenceId=p.evidence_id,
                    source=doc_retrieval.source_title(p),
                    heading=p.heading,
                    quote=p.quote,
                    explains=p.explains,
                    limits=p.limits,
                )
                for p in doc_retrieval.retrieve(cause.kind, cause.evidenceText or "")
            ]
            if docs:
                out[-1].officialDocs = docs
                out[-1].docNote = DOC_NOTE
    return out


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

    diagnosis = resource_bundle_diagnosis.diagnose(
        scope.run_dir, detail["stepId"], detail["validation"]["results"], scope.redactor
    )
    return _project(detail, scope.redactor, diagnosis)


def _project(
    detail: dict[str, Any],
    redactor: Redactor,
    diagnosis: ResourceBundleDiagnosis | None = None,
) -> StepEvidence:
    """Copy the allowed fields across, scrubbing every string on the way.

    `release`, not `text`: a string that still looks like part of a path after
    the patterns has that word replaced, or is withheld whole (fail-closed).
    """
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
        validationStatus=redactor.release(validation.get("status")),
        checks=[
            StepCheckEvidence(
                name=redactor.release(row.get("name")),
                status=redactor.release(row.get("status")),
                detail=redactor.release(row.get("detail")),
            )
            for row in validation.get("results") or []
        ],
        metrics=metrics,
        withheldMetricCount=withheld,
        warnings=[
            StepWarningEvidence(
                code=redactor.release(row.get("code")),
                message=redactor.release(row.get("message")),
                impact=redactor.release(row.get("impact")),
                canContinue=row.get("canContinue") is True,
            )
            for row in detail.get("warnings") or []
        ],
        failures=[
            StepFailureEvidence(
                code=redactor.release(row.get("code")),
                message=redactor.release(row.get("message")),
            )
            for row in detail.get("failures") or []
        ],
        artifactCount=len(detail.get("artifacts") or []),
        nextStepReady=detail.get("nextStepReady") is True,
        resourceBundleDiagnosis=diagnosis,
        causeGuidance=cause_guidance(diagnosis),
    )


__all__ = [
    "EVIDENCE_PREFIX",
    "MalformedStepId",
    "StepCauseGuidance",
    "StepRemedy",
    "StepDocPassage",
    "DOC_NOTE",
    "StepCheckEvidence",
    "StepEvidence",
    "StepFailureEvidence",
    "StepNotInThisRun",
    "StepWarningEvidence",
    "UnreadableStep",
    "cause_guidance",
    "evidence_id",
    "read_step_evidence",
]
