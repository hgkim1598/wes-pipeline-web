"""Stored AI explanations: numbered versions of answers that passed every gate.

Development log 66. Before this, a served explanation lived only in the browser
tab that asked for it; a reload lost it, and nothing could say later what had
been shown. This keeps exactly that -- what was shown -- and nothing more.

What is stored, and what is not
-------------------------------

    stored      the RunSynthesis that was served, after every gate passed and
                after one more identifier / path check right here; its
                provenance; the hash of the redacted payload it was built from;
                the hash of the run record as read for that request; the
                document search the request carried, if any
    not stored  a rejected answer (its trace says which gate), a failed call,
                the payload, the prompt, anything the model reasoned

Every request is a new version. Version n+1 names version n in `supersedes`;
version n is never rewritten. Deleting a version clears its body and keeps the
row, so the history still says that something was served, when, by which
model, and from which input -- just not what it said. Numbers are not reused.

Storing is off unless WES_SYNTHESIS_STORE_ANSWERS=1 (config.py): how long an
explanation of one sample's run may be kept is a user decision that has not
been made, and the default may not make it.

"Run record changed"
--------------------

`run_record_sha256` is the hash of the run diagnostic context -- the facts read
from the run's own documents and its job row -- not of the deterministic
explanation built from them. A release that only rewords an explanation does
not mark every stored answer as stale; a run whose documents changed does.

Failing to store must not fail the request
------------------------------------------

Like trace.record: the user already has the answer on screen. A database error
here is logged (type only) and recorded on the trace as `storeFailed`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from .... import config, db
from ...agent import run_scope
from ...agent.privacy import _DIGEST, Redactor
from ..run_context import RunDiagnosticContext
from . import claims, doc_citations, validation
from .contract import RunSynthesis
from .synthesis import SynthesisProvenance, SynthesisResult
from .trace import SynthesisTrace

log = logging.getLogger(__name__)

# The shape of `body_json`. Bump it when RunSynthesis changes in a way an older
# body could not be read back as.
CONTRACT_VERSION = "run-synthesis/1"

STORED = "stored"
REFUSED_SENSITIVE = "refusedSensitive"
STORE_FAILED = "storeFailed"


# --- digests -------------------------------------------------------------------


def _sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_digest(context: RunDiagnosticContext) -> str:
    """The run record as read for one request, as a hash."""
    return _sha256(context.model_dump(mode="json"))


def redactor_for(context: RunDiagnosticContext) -> Redactor:
    """The run's own identifiers -- the same literals the payload was redacted with."""
    identity = context.identity
    return run_scope.redactor_for_row(
        {"sample_id": identity.sampleId, "run_id": identity.runId, "job_id": identity.jobId}
    )


# --- writing -------------------------------------------------------------------


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _sensitive_kinds(body: dict[str, Any], redactor: Redactor) -> list[str]:
    """Kinds only, never the value.

    The output gate's detector (paths, e-mail, the run's own identifiers), plus
    the payload redaction's digest rule: a checksum is never part of an
    explanation, and this is the last look before the text is kept. Every
    string is read, evidence refs included -- stricter than the gate, which
    reads prose; a false refusal costs a stored copy, never the answer shown.
    """
    kinds: set[str] = set()
    for text in _strings(body):
        kinds.update(validation.find_sensitive_output(text, redactor.contains_literal))
        if _DIGEST.search(text):
            kinds.add("digest")
    return sorted(kinds)


def _mark(trace_id: str, outcome: str) -> None:
    try:
        db.execute("UPDATE synthesis_traces SET answer_store = ? WHERE trace_id = ?", (outcome, trace_id))
    except sqlite3.Error as exc:
        log.warning("could not mark synthesis trace: %s", type(exc).__name__)


def store(
    job_id: str,
    trace_id: str | None,
    result: SynthesisResult,
    trace_record: SynthesisTrace | None,
    *,
    redactor: Redactor,
    run_record_sha256: str,
    doc_search_id: str | None,
) -> str | None:
    """Store one served answer as the run's next version.

    Returns `stored`, `refusedSensitive`, `storeFailed`, or None when no store
    was attempted (storing off, nothing served, or no trace to link it to).
    """
    if not config.SYNTHESIS_STORE_ANSWERS:
        return None
    if not result.available or result.synthesis is None or result.provenance is None:
        return None
    if trace_id is None or trace_record is None or trace_record.inputSha256 is None:
        # A version must say which request produced it; without the trace it cannot.
        log.warning("served answer not stored: its trace was not recorded")
        return None

    body = result.synthesis.model_dump(mode="json")
    kinds = _sensitive_kinds(body, redactor)
    if kinds:
        log.warning("served answer not stored: it holds %s", kinds)
        _mark(trace_id, REFUSED_SENSITIVE)
        return REFUSED_SENSITIVE

    for attempt in (1, 2):
        try:
            with db.transaction() as conn:
                previous = conn.execute(
                    "SELECT answer_id, version FROM synthesis_answers WHERE job_id = ?"
                    " ORDER BY version DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
                conn.execute(
                    """INSERT INTO synthesis_answers
                       (answer_id, trace_id, job_id, version, supersedes, created_at, models,
                        contract_version, input_sha256, run_record_sha256, doc_search_id,
                        provenance_json, body_json, status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "ans_" + secrets.token_hex(12),
                        trace_id,
                        job_id,
                        1 if previous is None else previous["version"] + 1,
                        None if previous is None else previous["answer_id"],
                        db.now_iso(),
                        json.dumps(list(result.provenance.models)),
                        CONTRACT_VERSION,
                        trace_record.inputSha256,
                        run_record_sha256,
                        doc_search_id,
                        result.provenance.model_dump_json(),
                        json.dumps(body, ensure_ascii=False),
                        "served",
                    ),
                )
                conn.execute(
                    "UPDATE synthesis_traces SET answer_store = ? WHERE trace_id = ?",
                    (STORED, trace_id),
                )
            return STORED
        except sqlite3.IntegrityError:
            # Within this process the per-run request guard (api/synthesis.py)
            # and db._LOCK already serialise writers, so this is the safety net
            # for a second process that read the same highest version: once
            # more, with the new highest. A duplicate trace_id fails twice and
            # ends as storeFailed, which is what it is.
            if attempt == 2:
                break
        except sqlite3.Error as exc:
            log.warning("could not store served answer: %s", type(exc).__name__)
            break
    _mark(trace_id, STORE_FAILED)
    return STORE_FAILED


def stored_version(trace_id: str) -> int | None:
    """The version the answer of this request became, if it was stored."""
    row = db.query_one("SELECT version FROM synthesis_answers WHERE trace_id = ?", (trace_id,))
    return None if row is None else int(row["version"])


def delete(job_id: str, version: int) -> bool:
    """Clear one version's body; keep its row. False when there is no such version."""
    row = db.query_one(
        "SELECT answer_id FROM synthesis_answers WHERE job_id = ? AND version = ?", (job_id, version)
    )
    if row is None:
        return False
    db.execute(
        "UPDATE synthesis_answers SET body_json = NULL, deleted_at = COALESCE(deleted_at, ?)"
        " WHERE answer_id = ?",
        (db.now_iso(), row["answer_id"]),
    )
    return True


# --- reading -------------------------------------------------------------------


class StoredDocEvidence(BaseModel):
    """One document of the search the request was built from, and what became of it.

    searched != delivered != cited. Whether the model READ it is not observable
    and not claimed.
    """

    evidenceId: str
    title: str | None = None
    selected: bool
    selectionReason: str | None = None
    inPayload: bool
    # None when the answer was not verified -- never the case for a stored one,
    # but the column allows it and "unknown" must not read as "not cited".
    cited: bool | None = None


class StoredAnswerSummary(BaseModel):
    version: int
    createdAt: str
    models: list[str]
    contractVersion: str
    status: str
    deleted: bool
    supersedesVersion: int | None = None
    # First 12 hex characters of the input hash, for display only.
    inputDigest: str
    # None for the first version: there is nothing to compare with.
    inputChangedFromPrevious: bool | None = None
    # None when the current run record could not be read.
    recordChanged: bool | None = None
    docSearchLinked: bool
    contextKind: str | None = None
    runStatus: str | None = None


class StoredAnswer(StoredAnswerSummary):
    # None once deleted. docEvidence stays: it is the agent_doc_evidence record
    # of the request (ids and 0/1 flags, also summarised by the document
    # search's agentRequest), not part of the deleted text.
    synthesis: RunSynthesis | None = None
    provenance: SynthesisProvenance | None = None
    docEvidence: list[StoredDocEvidence] = []
    citedDocIds: list[str] = []
    # Document ids the stored body cites that the request did not carry. The
    # gates make this empty for anything served; non-empty means a row was
    # written some other way and must not be trusted.
    citationsOutsidePayload: list[str] = []


class StoredAnswerList(BaseModel):
    storing: bool
    # Highest version that still has its body; None when there is none. A
    # deleted newer version therefore makes an older one "latest" -- the list
    # still shows the deleted one, marked, so nothing is silently skipped.
    latestVersion: int | None = None
    versions: list[StoredAnswerSummary]


def _rows(job_id: str) -> list[sqlite3.Row]:
    return db.query_all(
        "SELECT * FROM synthesis_answers WHERE job_id = ? ORDER BY version", (job_id,)
    )


def _summary(row: sqlite3.Row, previous: sqlite3.Row | None, by_id: dict[str, int],
             current_record: str | None) -> dict[str, Any]:
    provenance = db.loads(row["provenance_json"], {})
    return {
        "version": row["version"],
        "createdAt": row["created_at"],
        "models": db.loads(row["models"], []),
        "contractVersion": row["contract_version"],
        "status": row["status"],
        "deleted": row["deleted_at"] is not None,
        "supersedesVersion": by_id.get(row["supersedes"]) if row["supersedes"] else None,
        "inputDigest": row["input_sha256"][:12],
        "inputChangedFromPrevious": (
            None if previous is None else previous["input_sha256"] != row["input_sha256"]
        ),
        "recordChanged": (
            None if current_record is None else current_record != row["run_record_sha256"]
        ),
        "docSearchLinked": row["doc_search_id"] is not None,
        "contextKind": provenance.get("contextKind"),
        "runStatus": provenance.get("runStatus"),
    }


def list_versions(job_id: str, current_record: str | None) -> StoredAnswerList:
    rows = _rows(job_id)
    by_id = {row["answer_id"]: row["version"] for row in rows}
    summaries = [
        StoredAnswerSummary(**_summary(row, rows[i - 1] if i else None, by_id, current_record))
        for i, row in enumerate(rows)
    ]
    live = [row["version"] for row in rows if row["body_json"] is not None]
    return StoredAnswerList(
        storing=config.SYNTHESIS_STORE_ANSWERS,
        latestVersion=max(live) if live else None,
        versions=list(reversed(summaries)),
    )


def _doc_evidence(row: sqlite3.Row) -> list[StoredDocEvidence]:
    links = db.query_all(
        "SELECT * FROM agent_doc_evidence WHERE trace_id = ? ORDER BY rowid", (row["trace_id"],)
    )
    out = []
    for link in links:
        hit = db.query_one(
            "SELECT source_title FROM doc_search_hits WHERE search_id = ? AND evidence_id = ?"
            " ORDER BY rank LIMIT 1",
            (link["search_id"], link["evidence_id"]),
        )
        out.append(
            StoredDocEvidence(
                evidenceId=link["evidence_id"],
                title=hit["source_title"] if hit is not None else None,
                selected=bool(link["selected"]),
                selectionReason=link["selection_reason"],
                inPayload=bool(link["in_payload"]),
                cited=None if link["cited"] is None else bool(link["cited"]),
            )
        )
    return out


def get_version(job_id: str, version: int, current_record: str | None) -> StoredAnswer | None:
    rows = _rows(job_id)
    by_id = {row["answer_id"]: row["version"] for row in rows}
    for i, row in enumerate(rows):
        if row["version"] != version:
            continue
        body = db.loads(row["body_json"], None)
        evidence = _doc_evidence(row)
        cited = list(doc_citations.cited_doc_refs(body, claims.GROUPS)) if body else []
        delivered = {d.evidenceId for d in evidence if d.inPayload}
        return StoredAnswer(
            **_summary(row, rows[i - 1] if i else None, by_id, current_record),
            synthesis=RunSynthesis(**body) if body else None,
            provenance=SynthesisProvenance(**db.loads(row["provenance_json"], {})),
            docEvidence=evidence,
            citedDocIds=cited,
            citationsOutsidePayload=[ref for ref in cited if ref not in delivered],
        )
    return None


__all__ = [
    "CONTRACT_VERSION", "StoredAnswer", "StoredAnswerList", "StoredAnswerSummary",
    "StoredDocEvidence", "delete", "get_version", "list_versions", "record_digest",
    "redactor_for", "store", "stored_version",
]
