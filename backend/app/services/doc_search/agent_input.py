"""Which returned documents may go into the agent's request, and the payload section for them (log 27).

No model here. The input is a search that has already run AND been stored, so
every decision below can be linked to a stored hit:

    stored search (engine.run_search -> store.save)        every returned hit
        |
        |  candidate rule -- structural, never a score:
        |    curated  filedUnderCauseKind   -> candidate (the store files it under this kind)
        |    manual   sameCommandSection    -> candidate (the section of the command the pipeline ran)
        |    manual   other / general       -> not a candidate; stays visible in the search trace
        |  caps: MAX_PER_INPUT per recorded failure, MAX_TOTAL per request, one entry per id
        |  the text is re-read and hash-compared; changed or missing text is not sent
        |  an excerpt holding one of this job's identifiers is not sent
        v
    AgentDocInput(section for contract.build_payload, one Selection per distinct id)

Why the rule is structural: on the lab questions that match this service's
input, hits outside the command's section were almost never the relevant ones
(log 27, measured, small sample). The rule says where a text sits in the
manual; it does not say the text explains the failure, and the note sent with
the section says so to the model.

What leaves the machine: excerpt text of public documentation, its title,
location and version, and per failure the step id, the failure kind and the
command display -- pipeline vocabulary, no identifiers. The query words (taken
from the redacted evidence sentence) are NOT sent: they are a search detail.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from app.services.agent import doc_retrieval
from app.services.agent.privacy import Redactor

from . import engine, manual_corpus

log = logging.getLogger(__name__)

MAX_PER_INPUT = 3
MAX_TOTAL = 6

CANDIDATE_RELATIONS = frozenset({"filedUnderCauseKind", "sameCommandSection"})

REASON_RELATION = "실행된 명령의 매뉴얼 절이 아니어서 Agent 입력 후보에서 제외했습니다."
# lexicon.py (log 62): the kind was guessed from wording, not classified.
REASON_WORDING = "원인이 분류되지 않은 문장에서 표현으로만 추정한 문서라 Agent 입력 후보에서 제외했습니다."
REASON_INPUT_CAP = "실패 기록 하나당 최대 {n}개까지만 Agent 입력에 넣습니다."
REASON_TOTAL_CAP = "요청 하나당 최대 {n}개까지만 Agent 입력에 넣습니다."
REASON_TEXT_CHANGED = "검색 이후 문서 본문이 바뀌어 Agent 입력에 넣지 않았습니다."
REASON_TEXT_MISSING = "문서 본문을 다시 읽지 못해 Agent 입력에 넣지 않았습니다."
REASON_IDENTIFIER = "본문에 이 실행의 식별자와 같은 문자열이 있어 Agent 입력에 넣지 않았습니다."

# Data, not prompt text: the v3 prompt hash stays the same with the section on
# or off (the same arrangement as step_evidence.DOC_NOTE).
SECTION_NOTE = (
    "officialDocs are excerpts of public tool documentation, returned by a search keyed on "
    "this run's recorded failure kind and the command the pipeline ran. They are general "
    "knowledge about the tool and are not records of this run: what happened is in run, "
    "checkSummary, diagnostics, failures, limitations and steps. A document's relation says "
    "where the excerpt sits (filed under this failure kind, or in the manual section of the "
    "command that ran), not that it explains this failure. Cite a document evidenceId only "
    "for what its excerpt says. An importantFindings or limitations item is about this run "
    "and must cite a record of this run; it may cite a document beside that record, never "
    "instead of it. "
    "Never present a command or option from an excerpt as something that was run."
)


@dataclass(frozen=True)
class Selection:
    """One decision per distinct returned evidence id."""

    evidence_id: str
    corpus: str
    selected: bool
    reason: str | None


@dataclass(frozen=True)
class AgentDocInput:
    section: dict[str, Any] | None  # None when nothing was selected
    selections: tuple[Selection, ...]

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(s.evidence_id for s in self.selections if s.selected)


def _current_manual() -> manual_corpus.ManualCorpus | None:
    try:
        return manual_corpus.load(engine._manual_path())
    except manual_corpus.ManualCorpusError:
        return None


def _text(hit: engine.HitRecord, manual: manual_corpus.ManualCorpus | None) -> tuple[str | None, dict[str, Any]]:
    """(current text, extra fields) or (None, {}) when it cannot be read."""
    if hit.corpus == "curated":
        try:
            p = doc_retrieval.by_evidence_id(hit.evidence_id)
        except Exception:  # noqa: BLE001 -- an unreadable store means "not sent"
            return None, {}
        if p is None:
            return None, {}
        return p.quote, {"explains": p.explains, "limits": p.limits, "checkedOn": p.checkedOn}
    if manual is None:
        return None, {}
    chunk = manual.chunks.get(hit.evidence_id.removeprefix("manual:"))
    return (chunk.body if chunk else None), {}


def build(record: engine.SearchRecord, redactor: Redactor) -> AgentDocInput:
    inputs = {i.inputId: i for i in record.inputs}
    manual = _current_manual()
    decisions: dict[str, Selection] = {}
    items: dict[str, dict[str, Any]] = {}
    per_input: dict[str, int] = {}

    def decide(hit: engine.HitRecord, reason: str | None) -> None:
        previous = decisions.get(hit.evidence_id)
        if previous is not None and (previous.selected or reason is not None):
            return  # first decision stands, except that "selected" wins over a refusal
        # Re-inserted so the selected ids keep the order of the payload items.
        decisions.pop(hit.evidence_id, None)
        decisions[hit.evidence_id] = Selection(hit.evidence_id, hit.corpus, reason is None, reason)

    for hit in record.hits:
        failure = inputs.get(hit.input_id)
        link = {
            "inputId": hit.input_id,
            "stepId": failure.stepId if failure else None,
            "failureKind": failure.kind if failure else None,
            "command": failure.command.display if failure and failure.command else None,
        }
        if hit.evidence_id in items:
            # Already going in for another failure: say it relates to this one too.
            if per_input.get(hit.input_id, 0) < MAX_PER_INPUT and hit.relation in CANDIDATE_RELATIONS:
                items[hit.evidence_id]["forFailures"].append(link)
                per_input[hit.input_id] = per_input.get(hit.input_id, 0) + 1
            continue
        if hit.relation not in CANDIDATE_RELATIONS:
            decide(hit, REASON_WORDING if hit.relation == "suggestedByWording" else REASON_RELATION)
            continue
        if per_input.get(hit.input_id, 0) >= MAX_PER_INPUT:
            decide(hit, REASON_INPUT_CAP.format(n=MAX_PER_INPUT))
            continue
        if len(items) >= MAX_TOTAL:
            decide(hit, REASON_TOTAL_CAP.format(n=MAX_TOTAL))
            continue
        text, extra = _text(hit, manual)
        if text is None:
            decide(hit, REASON_TEXT_MISSING)
            continue
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != hit.item_sha256:
            decide(hit, REASON_TEXT_CHANGED)
            continue
        if redactor.contains_literal(text):
            decide(hit, REASON_IDENTIFIER)
            continue
        decide(hit, None)
        per_input[hit.input_id] = per_input.get(hit.input_id, 0) + 1
        entry: dict[str, Any] = {
            "evidenceId": hit.evidence_id,
            "kind": "curatedExcerpt" if hit.corpus == "curated" else "toolManual",
            "source": hit.source_title,
            "location": hit.location,
            "version": hit.version,
            "relation": hit.relation,
            "forFailures": [link],
            "excerpt": text,
        }
        if extra.get("checkedOn"):
            entry["checkedOn"] = extra["checkedOn"]
        if extra.get("explains"):
            entry["explains"] = extra["explains"]
        if extra.get("limits"):
            entry["limits"] = extra["limits"]
        items[hit.evidence_id] = entry

    selections = tuple(decisions.values())
    section = {"note": SECTION_NOTE, "items": list(items.values())} if items else None
    return AgentDocInput(section=section, selections=selections)


__all__ = [
    "AgentDocInput", "CANDIDATE_RELATIONS", "MAX_PER_INPUT", "MAX_TOTAL", "SECTION_NOTE",
    "Selection", "build",
]
