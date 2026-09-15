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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.ensure_dirs()
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = connect()
    with _LOCK:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


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
