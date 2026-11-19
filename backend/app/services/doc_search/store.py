"""Persist a search as a trace and read it back -- the API only serves what was stored.

Two tables (app/db.py): doc_search_runs (one row per search) and
doc_search_hits (one row per returned item). What is stored is the search's
own vocabulary: kinds, tool and command, query words taken from already
redacted text, ids, ranks, structural relations, and the item's hash at the
time. No evidence sentence, no excerpt text, no path, no sample name.

Excerpts are resolved from the CURRENT corpus when the trace is read, and the
stored hash says whether it is still the same text (`sourceMatches`). A trace
of a corpus that has since changed or disappeared stays readable and says so,
instead of silently showing different text under an old search.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app import db
from app.services.agent import doc_retrieval

from . import engine, manual_corpus
from .models import (
    AgentRequestInfo,
    CorpusInfo,
    DocSearchRun,
    ExcludedObservation,
    HitUsage,
    SearchHit,
    SearchInput,
)

MAX_RUNS = 10

# Categories with which a gate discarded an answer that DID come back
# (services/explanation/llm/synthesis.py, gates 2-8). Any other category means
# no usable answer came back. Listed here rather than imported so this package
# keeps no import path to the model call (test_doc_search asserts that).
GATE_CATEGORIES = frozenset({
    "invalidSynthesis", "unknownEvidenceRef", "unsupportedNumber", "internalFieldName",
    "runFactMismatch", "evidenceMismatch", "sensitiveOutput", "docEvidenceMisuse",
})

# matchedBy values every released reader validates strictly (92c7e12 rejects any
# other value and fails the whole GET doc-search for the job, log 32). FROZEN:
# a new reason never enters `matched_by`; it is kept in `matched_by_full`.
LEGACY_MATCHED_BY = ("causeKindKey", "optionLookup", "fts5")


def _matched_by_columns(how: list[str]) -> tuple[str, str | None]:
    """(matched_by, matched_by_full): the readable-by-all subset, and the full list if it differs."""
    legacy = [m for m in how if m in LEGACY_MATCHED_BY]
    return json.dumps(legacy), (json.dumps(how) if legacy != how else None)


def _matched_by(row: Any) -> list[str]:
    full = row["matched_by_full"]  # column added on connect (db._ADDED_COLUMNS)
    return json.loads(full if full is not None else row["matched_by"])


_ERROR_MESSAGES = {
    "runRecordUnreadable": "실행 기록을 읽지 못해 검색하지 않았습니다.",
    "noCorpusAvailable": "검색할 공식 문서 자료가 이 서버에 없습니다.",
}


def save(job_id: str, record: engine.SearchRecord, *, purpose: str | None = None) -> str:
    search_id = uuid.uuid4().hex
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO doc_search_runs (search_id, job_id, created_at, method, duration_ms, "
            "corpora, inputs, excluded, result_count, error_category, model_called, purpose) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                search_id, job_id, db.now_iso(), record.method, record.duration_ms,
                json.dumps([c.model_dump() for c in record.corpora], ensure_ascii=False),
                json.dumps([i.model_dump() for i in record.inputs], ensure_ascii=False),
                json.dumps([e.model_dump() for e in record.excluded], ensure_ascii=False),
                len(record.hits), record.error_category, purpose,
            ),
        )
        conn.executemany(
            "INSERT INTO doc_search_hits (search_id, input_id, corpus, rank, evidence_id, relation, "
            "matched_by, matched_by_full, source_title, source_url, location, version, checked_on, "
            "item_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (search_id, h.input_id, h.corpus, h.rank, h.evidence_id, h.relation,
                 *_matched_by_columns(h.matched_by), h.source_title, h.source_url, h.location,
                 h.version, h.checked_on, h.item_sha256)
                for h in record.hits
            ],
        )
    return search_id


def _current_manual() -> manual_corpus.ManualCorpus | None:
    try:
        return manual_corpus.load(engine._manual_path())
    except manual_corpus.ManualCorpusError:
        return None


def _resolve(row: Any, manual: manual_corpus.ManualCorpus | None) -> dict[str, Any]:
    ref, stored = row["evidence_id"], row["item_sha256"]
    if row["corpus"] == "curated":
        try:
            p = doc_retrieval.by_evidence_id(ref)
        except Exception:  # noqa: BLE001 -- an unreadable store is "unknown", not a crash
            return {"excerpt": None, "sourceMatches": None}
        if p is None:
            return {"excerpt": None, "sourceMatches": False}
        same = hashlib.sha256(p.quote.encode("utf-8")).hexdigest() == stored
        return {"excerpt": p.quote, "note": p.explains, "limits": p.limits, "sourceMatches": same}
    if manual is None:
        return {"excerpt": None, "sourceMatches": None}
    chunk = manual.chunks.get(ref.removeprefix("manual:"))
    if chunk is None:
        return {"excerpt": None, "sourceMatches": False}
    return {"excerpt": chunk.body, "sourceMatches": chunk.body_sha256 == stored}


def _agent_request(search_id: str) -> tuple[AgentRequestInfo | None, dict[str, Any]]:
    """The linked request and per-id link rows, or (None, {}) when nothing is linked."""
    links = db.query_all(
        "SELECT * FROM agent_doc_evidence WHERE search_id = ? ORDER BY rowid", (search_id,)
    )
    if not links:
        return None, {}
    trace = db.query_one(
        "SELECT created_at, available, error_category FROM synthesis_traces WHERE trace_id = ?",
        (links[0]["trace_id"],),
    )
    if trace is None:
        return None, {}
    category = trace["error_category"]
    if trace["available"]:
        outcome = "answerServed"
    elif category in GATE_CATEGORIES:
        outcome = "answerRejected"
    else:
        outcome = "noAnswer"
    cited = [link["cited"] for link in links]
    info = AgentRequestInfo(
        requestedAt=trace["created_at"],
        outcome=outcome,
        errorCategory=category,
        candidateCount=sum(link["selected"] for link in links),
        inPayloadCount=sum(link["in_payload"] for link in links),
        citedCount=None if any(c is None for c in cited) else sum(cited),
    )
    return info, {link["evidence_id"]: link for link in links}


def _usage(link: Any | None) -> HitUsage:
    if link is None:
        return HitUsage()
    return HitUsage(
        selectedForAgent=bool(link["selected"]),
        selectionReason=link["selection_reason"],
        inAgentInput=bool(link["in_payload"]),
        citedInAnswer=None if link["cited"] is None else bool(link["cited"]),
    )


def _run(row: Any, hits: list[Any], manual) -> DocSearchRun:
    agent, links = _agent_request(row["search_id"])
    resolved = []
    for h in hits:
        resolved.append(SearchHit(
            inputId=h["input_id"], corpus=h["corpus"], rank=h["rank"], evidenceId=h["evidence_id"],
            relation=h["relation"], matchedBy=_matched_by(h),
            sourceTitle=h["source_title"], sourceUrl=h["source_url"], location=h["location"],
            version=h["version"], checkedOn=h["checked_on"], **_resolve(h, manual),
            usage=_usage(links.get(h["evidence_id"])),
        ))
    category = row["error_category"]
    return DocSearchRun(
        searchId=row["search_id"],
        purpose="agentRequest" if row["purpose"] == "agentRequest" else "userRequest",
        agentRequest=agent,
        createdAt=row["created_at"],
        method=row["method"],
        durationMs=row["duration_ms"],
        corpora=[CorpusInfo(**c) for c in json.loads(row["corpora"])],
        inputs=[SearchInput(**i) for i in json.loads(row["inputs"])],
        excludedObservations=[ExcludedObservation(**e) for e in json.loads(row["excluded"])],
        hits=resolved,
        resultCount=row["result_count"],
        errorCategory=category,
        errorMessage=_ERROR_MESSAGES.get(category) if category else None,
    )


def list_runs(job_id: str, limit: int = MAX_RUNS) -> list[DocSearchRun]:
    rows = db.query_all(
        "SELECT * FROM doc_search_runs WHERE job_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (job_id, limit),
    )
    if not rows:
        return []
    manual = _current_manual()
    out = []
    for row in rows:
        hits = db.query_all(
            "SELECT * FROM doc_search_hits WHERE search_id = ? ORDER BY rowid",
            (row["search_id"],),
        )
        out.append(_run(row, hits, manual))
    return out


def get_run(search_id: str) -> DocSearchRun | None:
    row = db.query_one("SELECT * FROM doc_search_runs WHERE search_id = ?", (search_id,))
    if row is None:
        return None
    hits = db.query_all(
        "SELECT * FROM doc_search_hits WHERE search_id = ? ORDER BY rowid",
        (search_id,),
    )
    return _run(row, hits, _current_manual())


__all__ = ["get_run", "list_runs", "save"]
