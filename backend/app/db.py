"""SQLite metadata store.

This database holds orchestration metadata only: which job exists, where its run
directory is, and which OS process is driving it. It never holds analysis
results and it is never the authority on pipeline progress — that always comes
from the JSON documents main.sh writes under the run directory.

stdlib sqlite3 is enough for a single-process, single-worker backend, so there
is no ORM here on purpose.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from . import config

# check_same_thread=False because the FastAPI request threads and the worker
# thread share one connection; _LOCK serialises every access.
_conn: sqlite3.Connection | None = None
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    profile_id        TEXT NOT NULL,
    capture_kit_id    TEXT,
    -- The biological sample name the submission carried. Nullable: rows created
    -- before this column existed cannot have one, and it is never back-filled
    -- by re-parsing the generated samplesheet.
    sample_id         TEXT,
    status            TEXT NOT NULL,      -- backend orchestration state
    run_dir           TEXT NOT NULL,
    config_path       TEXT NOT NULL,
    samplesheet_path  TEXT NOT NULL,
    run_mode          TEXT NOT NULL,      -- check_only | full
    planned_steps     TEXT NOT NULL,      -- JSON array
    original_options  TEXT NOT NULL,      -- JSON object, verbatim from the UI
    unsupported_options TEXT NOT NULL,    -- JSON array of option keys not sent to main.sh
    command           TEXT,               -- argv actually executed
    pid               INTEGER,
    pgid              INTEGER,
    exit_code         INTEGER,
    error             TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- One row per model-backed synthesis request. Observability only: nothing in
-- the request path reads it back, and no API returns it.
--
-- A separate table rather than columns on `jobs` because the cardinality is
-- different: one job can be explained many times, and the answer differs every
-- time. Folding it into `jobs` would keep only the most recent attempt and put
-- model metadata into a row this module's own docstring reserves for
-- orchestration state.
--
-- What may be stored here is deliberately narrow -- see
-- services/explanation/llm/trace.py. No prompt, no model reasoning, no tool
-- result content, no sample name, no path.
CREATE TABLE IF NOT EXISTS synthesis_traces (
    trace_id        TEXT PRIMARY KEY,
    -- Internal linkage only. Never sent to a model, never in an API response.
    job_id          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    models          TEXT NOT NULL,      -- JSON array of model ids the CLI reported
    duration_ms     INTEGER,
    num_turns       INTEGER,
    -- JSON array of pipeline step ids the agent actually opened. [] means the
    -- tool was never used, which is a fact worth keeping, not a missing value.
    opened_step_ids TEXT NOT NULL,
    available       INTEGER NOT NULL,   -- 1 when the user was shown a synthesis
    error_category  TEXT                -- NULL when available
);

CREATE INDEX IF NOT EXISTS idx_synthesis_traces_job
    ON synthesis_traces (job_id, created_at);

-- Official-document searches (services/doc_search, log 26). NOT a model trace:
-- no model runs on this path, and model_called is stored as 0 to say so in the
-- row itself. Kept apart from synthesis_traces so "the search returned it" can
-- never be read as "the agent used it". Stored: kinds, tool/command, query
-- words from already-redacted text, ids, ranks, structural relations, hashes.
-- No evidence sentence, no excerpt, no path, no sample name. Additive only:
-- CREATE ... IF NOT EXISTS leaves every existing table and row untouched.
CREATE TABLE IF NOT EXISTS doc_search_runs (
    search_id      TEXT PRIMARY KEY,
    job_id         TEXT NOT NULL,      -- internal linkage, never in a response
    created_at     TEXT NOT NULL,
    method         TEXT NOT NULL,
    duration_ms    INTEGER,
    corpora        TEXT NOT NULL,      -- JSON: what was searchable, versions, hashes
    inputs         TEXT NOT NULL,      -- JSON: one query per recorded failure
    excluded       TEXT NOT NULL,      -- JSON: recorded observations not searched, with reason
    result_count   INTEGER NOT NULL,
    error_category TEXT,
    model_called   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_doc_search_runs_job
    ON doc_search_runs (job_id, created_at);

CREATE TABLE IF NOT EXISTS doc_search_hits (
    search_id    TEXT NOT NULL,
    input_id     TEXT NOT NULL,
    corpus       TEXT NOT NULL,        -- curated | manual
    rank         INTEGER NOT NULL,     -- 1-based within (input, corpus)
    evidence_id  TEXT NOT NULL,        -- doc:<id> | manual:<chunk id>
    relation     TEXT NOT NULL,        -- structural, see doc_search/models.py
    matched_by   TEXT NOT NULL,        -- JSON array
    source_title TEXT NOT NULL,
    source_url   TEXT,
    location     TEXT NOT NULL,
    version      TEXT,
    checked_on   TEXT,
    item_sha256  TEXT NOT NULL,        -- the returned text's hash at search time
    PRIMARY KEY (search_id, input_id, corpus, rank)
);

-- Which returned document went into which agent request, and was it cited
-- (services/doc_search/agent_link.py, log 27). One row per distinct evidence
-- id of the search a synthesis request was built from. Ids, decisions and
-- 0/1 only: no excerpt, no prompt, no path, no sample name.
--   selected   the structural candidate rule kept it (0 + selection_reason if not)
--   in_payload the request payload actually built carried it
--   cited      1/0 only when an answer was SERVED (every gate passed);
--              NULL = unknown: no answer, or an answer the gates rejected
-- Whether the model READ a document is not a column: nothing observes it.
CREATE TABLE IF NOT EXISTS agent_doc_evidence (
    trace_id         TEXT NOT NULL,    -- synthesis_traces.trace_id
    search_id        TEXT NOT NULL,    -- doc_search_runs.search_id
    evidence_id      TEXT NOT NULL,
    selected         INTEGER NOT NULL,
    selection_reason TEXT,
    in_payload       INTEGER NOT NULL,
    cited            INTEGER,
    PRIMARY KEY (trace_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_doc_evidence_search
    ON agent_doc_evidence (search_id);

CREATE TABLE IF NOT EXISTS uploads (
    upload_id         TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_filename   TEXT NOT NULL,
    sample_id         TEXT,
    slot_id           TEXT,
    expected_size     INTEGER,
    chunk_dir         TEXT NOT NULL,
    final_path        TEXT,
    completed         INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
"""


# Columns added after the first release.
#
# CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so a
# database created before a column was introduced never gains it. This map is
# applied on every connect() and is the whole migration story here: there is no
# version table and no migration framework, which matches the rest of this
# module (stdlib sqlite3, no ORM).
#
# Only NULLable columns may be listed. ALTER TABLE ADD COLUMN is a metadata-only
# change in SQLite -- it does not rewrite or copy the table, and existing rows
# read back as NULL -- so it cannot lose data. Anything that needs a rewrite
# (dropping, retyping, adding NOT NULL) does not belong here and needs a real
# decision.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "jobs": {"sample_id": "TEXT"},
    # The synthesis repair record (services/explanation/llm/trace.py). NULL on
    # a row from before it: that request was a single generation.
    "synthesis_traces": {
        "repair_enabled": "INTEGER",
        "attempts": "INTEGER",
        "first_rejection": "TEXT",
    },
    # Why a document search ran (log 27): 'agentRequest' for one a synthesis
    # request made for itself. NULL = the run page's button, and every row
    # from before the column existed.
    "doc_search_runs": {"purpose": "TEXT"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _apply_column_upgrades(conn: sqlite3.Connection) -> None:
    """Add any missing NULLable column, leaving existing rows untouched."""
    for table, columns in _ADDED_COLUMNS.items():
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.ensure_dirs()
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _apply_column_upgrades(_conn)
        _conn.commit()
    return _conn


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = connect()
    with _LOCK:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Several statements as one transaction, under the same lock as execute().

    The connection is shared with the worker thread, so a transaction opened
    without _LOCK is not ours alone: the worker's commit would commit our
    half-written rows, and our rollback could undo its uncommitted update
    (development log 29). Inside the lock nobody else has a statement
    pending, so commit and rollback cover exactly the statements issued here.

    _LOCK is not re-entrant: do not call execute/query_* inside the block --
    use the yielded connection.
    """
    conn = connect()
    with _LOCK:
        with conn:  # commit on success, rollback on any exception
            yield conn


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    conn = connect()
    with _LOCK:
        return conn.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = connect()
    with _LOCK:
        return conn.execute(sql, params).fetchall()


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    execute(
        f"UPDATE jobs SET {assignments} WHERE job_id = ?",
        (*fields.values(), job_id),
    )


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
