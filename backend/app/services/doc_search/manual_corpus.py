"""The optional full-manual corpus: chunk JSONL from the wes-rag-lab experiment.

One file = one fetched snapshot of one official manual. Every line is a chunk
with its own `body_sha256` and the `source_sha256` of the HTML it was cut from,
so provenance is checkable here, not trusted:

    a chunk whose body does not hash to its body_sha256   -> excluded, counted
    a chunk from a different snapshot than the first one   -> excluded, counted

Section membership comes from the chunk's `context` (the manual's own heading
path, e.g. "COMMANDS AND OPTIONS > bcftools view [ OPTIONS ] file.vcf.gz"). It
is what lets a hit be labelled "same command section" or "other command
section" without inventing a relevance score.

Search is SQLite FTS5 (standard library, in memory) -- the same engine as the
curated excerpts and the lab's A1 baseline. The lab measured a local embedding
model (MiniLM) higher on hit@5 (0.75 vs 0.60, 20 test questions, not
significant); it is not used here because it would add torch and a model to the
backend for a difference the lab could not establish (technical notes 15).
`Retriever` in engine.py is the seam where it would plug in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.services.agent.doc_retrieval import match_query

log = logging.getLogger(__name__)

_SECTION_COMMAND = re.compile(r"\b([a-z][a-z0-9]*) ([a-z][a-z0-9+-]*) \[")
_TITLE_TOOL = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\(")


class ManualCorpusError(ValueError):
    """The configured file could not be read as a chunk corpus."""


@dataclass(frozen=True)
class ManualChunk:
    chunk_id: str
    anchor: str
    url: str
    context: str
    body: str
    body_sha256: str
    section_command: str | None


@dataclass
class ManualCorpus:
    tool: str
    title: str
    version: str | None
    source_url: str | None
    source_sha256: str
    chunks: dict[str, ManualChunk]
    order: list[str]
    excluded: int
    _conn: sqlite3.Connection = field(repr=False)

    def search(self, terms: list[str], limit: int) -> list[str]:
        """Chunk ids, best bm25 first; ties broken by file order (as in the lab)."""
        query = match_query(" ".join(terms))
        if query is None:
            return []
        rows = self._conn.execute(
            "SELECT cid FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks), rowid LIMIT ?",
            (query, limit),
        ).fetchall()
        return [cid for (cid,) in rows]

    def option_lookup(self, subcommand: str, options: tuple[str, ...]) -> list[str]:
        """Chunks in `subcommand`'s own section that list one of `options`.

        Structural, not textual relevance: FTS drops one-letter options such
        as `-h` (lab note T11), and an option means something only inside the
        command it belongs to.
        """
        if not options:
            return []
        pats = [re.compile(r"(?<![\w-])" + re.escape(opt) + r"(?=[,\s=]|$)", re.M) for opt in options]
        return [
            cid for cid in self.order
            if self.chunks[cid].section_command == subcommand
            and any(p.search(self.chunks[cid].body) for p in pats)
        ]


def _section_command(context: str, tool: str) -> str | None:
    for m in _SECTION_COMMAND.finditer(context):
        if m.group(1) == tool:
            return m.group(2)
    return None


def _read_meta(path: Path, sha: str) -> dict:
    meta = path.with_name(f"{sha}.meta.json")
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=2)
def _load(path_str: str, mtime_ns: int) -> ManualCorpus:  # mtime keys the cache
    path = Path(path_str)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ManualCorpusError(f"cannot read the manual corpus: {type(exc).__name__}") from exc
    raw = []
    for line in lines:
        if not line.strip():
            continue
        try:
            raw.append(json.loads(line))
        except ValueError as exc:
            raise ManualCorpusError("a line of the manual corpus is not JSON") from exc
    if not raw:
        raise ManualCorpusError("the manual corpus is empty")

    snapshot = str(raw[0].get("source_sha256") or "")
    meta = _read_meta(path, snapshot)
    title = str(meta.get("title") or raw[0].get("source_id") or "manual")
    m = _TITLE_TOOL.match(title)
    tool = (m.group(1) if m else str(raw[0].get("source_id", "")).split("-")[0]).lower()

    chunks: dict[str, ManualChunk] = {}
    order: list[str] = []
    excluded = 0
    for row in raw:
        body = str(row.get("body") or "")
        ok = (
            row.get("source_sha256") == snapshot
            and isinstance(row.get("chunk_id"), str)
            and row["chunk_id"] not in chunks
            and hashlib.sha256(body.encode("utf-8")).hexdigest() == row.get("body_sha256")
        )
        if not ok:
            excluded += 1
            continue
        context = str(row.get("context") or "")
        chunk = ManualChunk(
            chunk_id=row["chunk_id"],
            anchor=str(row.get("anchor") or ""),
            url=str(row.get("url") or ""),
            context=context,
            body=body,
            body_sha256=row["body_sha256"],
            section_command=_section_command(context, tool),
        )
        chunks[chunk.chunk_id] = chunk
        order.append(chunk.chunk_id)

    # The in-memory index needs SQLite's FTS5 module, which a Python build may
    # lack (log 29). Without it the corpus is "unavailable", like an unreadable
    # file -- never an unhandled 500 on the run page. sqlite's message names the
    # missing module ("no such module: fts5") and holds no path; it goes to the
    # log only, the user sees the generic REASON_MANUAL_ERROR.
    try:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("CREATE VIRTUAL TABLE chunks USING fts5(cid UNINDEXED, body)")
        conn.executemany(
            "INSERT INTO chunks (cid, body) VALUES (?, ?)",
            [(cid, f"{chunks[cid].context}\n{chunks[cid].body}") for cid in order],
        )
    except sqlite3.Error as exc:
        log.warning("manual corpus search index unavailable: %s: %s", type(exc).__name__, exc)
        raise ManualCorpusError("the manual corpus search index could not be built") from exc
    url = chunks[order[0]].url.split("#", 1)[0] if order else None
    return ManualCorpus(
        tool=tool,
        title=title,
        version=(meta.get("version_text") or None),
        source_url=url,
        source_sha256=snapshot,
        chunks=chunks,
        order=order,
        excluded=excluded,
        _conn=conn,
    )


def load(path: Path | None) -> ManualCorpus | None:
    """None when not configured; ManualCorpusError when configured but unreadable."""
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as exc:
        raise ManualCorpusError("the configured manual corpus does not exist") from exc
    return _load(str(path), mtime)


def clear_cache() -> None:
    _load.cache_clear()


__all__ = ["ManualChunk", "ManualCorpus", "ManualCorpusError", "clear_cache", "load"]
