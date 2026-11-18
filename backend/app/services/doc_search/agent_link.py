"""Search -> request payload -> verified citation, as stored facts (log 27).

Called by POST /synthesis only when config.AGENT_DOC_EVIDENCE is on:

    prepare(job_id)   run a fresh search for this run, store it with
                      purpose='agentRequest', decide the candidates
                      (agent_input.build). Any failure returns None and the
                      request goes on without documents, exactly as with the
                      flag off.
    link(trace_id)    after the request, one agent_doc_evidence row per
                      distinct returned id: selected (and why not), placed in
                      the payload (from the trace, i.e. the payload actually
                      built), cited (only for a served answer; NULL otherwise).

Why a fresh search per request and not the latest stored one: the stored one
may predate a corpus change or be missing, and reusing it would make the
trace say "the request was built from search X" when the text sent was read
now. A fresh search costs milliseconds (log 26: ~1 ms FTS) and makes the
link exact. Reproducibility is kept by the stored search and hashes, not by
reuse.

This module never sees the prompt or the answer text: it receives the trace
object, whose document fields are ids.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from app import db
from app.services.agent.privacy import Redactor

from . import agent_input, engine, store

log = logging.getLogger(__name__)

PURPOSE = "agentRequest"


@dataclass(frozen=True)
class Prepared:
    search_id: str
    input: agent_input.AgentDocInput


def prepare(job_id: str, redactor: Redactor) -> Prepared | None:
    try:
        row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        if row is None:
            return None
        record = engine.run_search(row)
        built = agent_input.build(record, redactor)
        search_id = store.save(job_id, record, purpose=PURPOSE)
    except Exception as exc:  # noqa: BLE001 -- documents are optional; the request is not
        log.warning("document search for an agent request failed: %s", type(exc).__name__)
        return None
    return Prepared(search_id=search_id, input=built)


def link(trace_id: str | None, prepared: Prepared, trace: Any) -> None:
    """Store the per-document facts. A missing trace leaves the search unlinked."""
    if trace_id is None or trace is None:
        log.warning("agent request trace not stored; document search left unlinked")
        return
    in_payload = set(trace.docEvidenceIds)
    cited = None if trace.citedDocEvidenceIds is None else set(trace.citedDocEvidenceIds)
    rows = [
        (
            trace_id, prepared.search_id, s.evidence_id, int(s.selected), s.reason,
            int(s.evidence_id in in_payload),
            None if cited is None else int(s.evidence_id in cited),
        )
        for s in prepared.input.selections
    ]
    try:
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO agent_doc_evidence (trace_id, search_id, evidence_id, selected, "
                "selection_reason, in_payload, cited) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except sqlite3.Error as exc:
        # Like trace.record: observability must not fail the user's request.
        log.warning("could not store agent document links: %s", type(exc).__name__)


__all__ = ["PURPOSE", "Prepared", "link", "prepare"]
