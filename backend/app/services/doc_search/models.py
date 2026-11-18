"""API shapes for the document search trace (GET/POST /api/jobs/{id}/doc-search).

Separate from synthesis_traces on purpose: that table records a MODEL call
(which models answered, which steps the agent opened). This one records a
SEARCH that ran without any model. A reader must never be able to mistake
"the search returned this excerpt" for "the agent used this excerpt", so the
usage block below states the unrecorded facts as null, field by field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CorpusId = Literal["curated", "manual"]
Relation = Literal[
    # curated: the excerpt is filed under this cause kind in wes_doc_passages.json
    "filedUnderCauseKind",
    # manual: where the chunk sits in the manual, relative to the recorded command
    "sameCommandSection",
    "otherCommandSection",
    "generalSection",
]
MatchedBy = Literal["causeKindKey", "optionLookup", "fts5"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObservedCommand(_Model):
    tool: str
    subcommand: str | None = None
    options: list[str] = Field(default_factory=list)
    display: str
    # Where in the pipeline code this command is run. A fact about the check.
    recordedBy: str


class CorpusSkip(_Model):
    corpus: CorpusId
    reason: str


class SearchInput(_Model):
    """One recorded failure, turned into a query. Built from the run, not guessed."""

    inputId: str
    origin: Literal["resourceBundleCause", "stepCheck"]
    stepId: str
    # Resource cause kind (rule table) or step-check family (never a full check
    # name: labelled names carry file names).
    kind: str
    tool: str | None = None
    ruleId: str | None = None
    occurrences: int = 1
    command: ObservedCommand | None = None
    # The words the full-text query used: from the tool, the command and the
    # already-redacted evidence sentence. No path, no sample name can survive
    # (placeholders are dropped, only plain words are kept).
    queryTerms: list[str] = Field(default_factory=list)
    skipped: list[CorpusSkip] = Field(default_factory=list)


class ExcludedObservation(_Model):
    """A recorded failure or warning that did not become a query, and why."""

    stepId: str
    kind: str
    reason: str


class CorpusInfo(_Model):
    corpusId: CorpusId
    title: str
    available: bool
    itemCount: int = 0
    # Items dropped at load because their recorded hash did not match.
    excludedItems: int = 0
    version: str | None = None
    # First 12 hex of the snapshot hash (manual) -- identifies the exact text.
    snapshot: str | None = None
    officialStatus: str
    note: str | None = None


class HitUsage(_Model):
    """What is recorded about this returned item. null = not recorded / unknown.

    For a search from the run page (purpose userRequest) only the first is
    known. For a search an agent request made for itself (log 27):

      selectedForAgent  the structural candidate rule kept it (agent_input.py)
      selectionReason   why not, when it was not kept
      inAgentInput      the request payload actually built carried it
      citedInAnswer     True/False only when an answer passed every gate and
                        was served; null when there was no answer or the
                        gates rejected it -- unknown, not "not cited"
      readByModel       always null: nothing observable records it
    """

    returnedBySearch: Literal[True] = True
    selectedForAgent: bool | None = None
    selectionReason: str | None = None
    inAgentInput: bool | None = None
    readByModel: None = None
    citedInAnswer: bool | None = None


class SearchHit(_Model):
    inputId: str
    corpus: CorpusId
    rank: int  # 1-based, within this input and corpus
    evidenceId: str  # doc:<id> (curated) or manual:<chunk id>
    relation: Relation
    matchedBy: list[MatchedBy]
    sourceTitle: str
    sourceUrl: str | None = None
    location: str  # heading (curated) or the manual's section path
    version: str | None = None
    checkedOn: str | None = None
    # Resolved from the CURRENT corpus at read time; null when it is gone.
    excerpt: str | None = None
    note: str | None = None  # curated: what the excerpt explains (Korean)
    limits: str | None = None  # curated: what it does not tell about this run
    # Does the current corpus still hold the exact text this search returned?
    sourceMatches: bool | None = None
    usage: HitUsage = Field(default_factory=HitUsage)


class AgentRequestInfo(_Model):
    """The synthesis request a search was made for (log 27). From synthesis_traces."""

    requestedAt: str
    # answerServed: every gate passed. answerRejected: an answer came back and
    # a gate discarded it. noAnswer: no usable answer came back at all.
    outcome: Literal["answerServed", "answerRejected", "noAnswer"]
    errorCategory: str | None = None
    candidateCount: int
    inPayloadCount: int
    # null unless the answer was served.
    citedCount: int | None = None


class DocSearchRun(_Model):
    searchId: str
    # userRequest: the run page's button. agentRequest: made by a synthesis
    # request for its own input (log 27).
    purpose: Literal["userRequest", "agentRequest"] = "userRequest"
    # null for a user search, and for an agent search whose request record
    # could not be stored (then nothing links them, and nothing is claimed).
    agentRequest: AgentRequestInfo | None = None
    createdAt: str
    method: str
    modelCalled: Literal[False] = False
    durationMs: int | None = None
    corpora: list[CorpusInfo]
    inputs: list[SearchInput]
    excludedObservations: list[ExcludedObservation]
    hits: list[SearchHit]
    resultCount: int
    errorCategory: str | None = None
    errorMessage: str | None = None


class DocSearchList(_Model):
    runs: list[DocSearchRun]


__all__ = [
    "AgentRequestInfo",
    "CorpusInfo",
    "CorpusSkip",
    "DocSearchList",
    "DocSearchRun",
    "ExcludedObservation",
    "HitUsage",
    "ObservedCommand",
    "SearchHit",
    "SearchInput",
]
