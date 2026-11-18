"""Official-document excerpts for a classified cause: the local RAG (log 18).

Two kinds of evidence, never mixed
----------------------------------

The run's own records (the resource check's sentences, classified by the rule
table) say WHAT failed. The excerpts here say what such a failure MEANS and
what the tool requires. So retrieval starts from a cause kind the rule table
already assigned and searches only the passages filed under that kind:

    classified kind --(exact key)--> candidate passages --(FTS5 rank)--> top N
    unknown kind    --> nothing

An excerpt therefore cannot propose a cause. That is the lesson of the offline
BM25 experiment (log 17.2): free search found more sentences but named the
wrong cause with confidence 8 times in 48 queries. Here free search is not on
the agent's path at all; `search_all` exists only for the comparison in
evals/experiments/doc_retrieval_compare.py.

Ranking inside a kind uses SQLite FTS5 (standard library, in memory, built
from the JSON at first use) against the cause's evidence sentence, so the
excerpt that matches the actual message comes first. Passages that match no
word still follow in file order: every passage under a kind was curated for
that kind, so "no word overlap" is not "irrelevant".

Titles and links come from wes_sources.json through `sourceId`, never from the
passage itself -- one place decides what a source is called and where it is.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.services.explanation import knowledge

log = logging.getLogger(__name__)

# At most this many excerpts per cause. 5 is every passage any kind has today:
# with 21 passages a cut at 3 dropped the tabix input requirement (sorted, bgzip)
# because the error sentence shares no word with it -- word overlap with the
# MESSAGE is not importance for the CHECK. So at this size the key filter does
# the selecting and FTS5 only orders (log 18). The cap keeps a future, larger
# store from turning the tool result into a manual.
MAX_PASSAGES_PER_CAUSE = 5

EVIDENCE_PREFIX = "doc:"


class DocPassage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    sourceId: str
    heading: str = Field(min_length=1)
    causeKinds: list[str] = Field(min_length=1)
    quote: str = Field(min_length=1)
    quoteNote: str | None = None
    explains: str = Field(min_length=1)
    limits: str = Field(min_length=1)
    toolVersion: str = Field(min_length=1)
    checkedOn: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    license: str = Field(min_length=1)

    @property
    def evidence_id(self) -> str:
        return f"{EVIDENCE_PREFIX}{self.id}"


class _PassagesDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    comment: list[str] = Field(default_factory=list, alias="_comment")
    passages: list[DocPassage]


class PassageStoreError(ValueError):
    """The passage file contradicts the rest of the knowledge."""


@lru_cache(maxsize=1)
def _store() -> dict[str, DocPassage]:
    doc = _PassagesDoc.model_validate_json(
        config.DOC_PASSAGE_KNOWLEDGE.read_text(encoding="utf-8")
    )
    kinds = {row.kind for row in knowledge.all_cause_kinds()}
    out: dict[str, DocPassage] = {}
    for passage in doc.passages:
        if passage.id in out:
            raise PassageStoreError(f"duplicate passage id {passage.id!r}")
        if knowledge.source(passage.sourceId) is None:
            raise PassageStoreError(f"{passage.id}: unknown sourceId {passage.sourceId!r}")
        unknown = set(passage.causeKinds) - kinds
        if unknown:
            raise PassageStoreError(f"{passage.id}: unknown cause kinds {sorted(unknown)}")
        out[passage.id] = passage
    return out


def all_passages() -> list[DocPassage]:
    return list(_store().values())


def passage(passage_id: str) -> DocPassage | None:
    return _store().get(passage_id)


def by_evidence_id(ref: str) -> DocPassage | None:
    if not ref.startswith(EVIDENCE_PREFIX):
        return None
    return passage(ref[len(EVIDENCE_PREFIX):])


def source_title(item: DocPassage) -> str:
    return knowledge.source(item.sourceId).title  # resolved at load


def source_url(item: DocPassage) -> str:
    return knowledge.source(item.sourceId).locator


# --- full-text index ---------------------------------------------------------

# Words that say nothing about which excerpt fits ("the reference ... is").
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the "
    "this to was with not no but".split()
)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def match_query(text: str) -> str | None:
    """An FTS5 OR-query of the plain words in `text`, or None if it has none.

    Every token is quoted, so nothing in the evidence sentence can become FTS
    syntax (NEAR, column filters, `*`): the sentence is data, not a query.
    """
    seen: list[str] = []
    for word in _WORD.findall(text.lower()):
        if word not in _STOP and word not in seen:
            seen.append(word)
    if not seen:
        return None
    return " OR ".join(f'"{word}"' for word in seen[:32])


@lru_cache(maxsize=1)
def _index() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE VIRTUAL TABLE passages USING fts5(pid UNINDEXED, body)")
    conn.executemany(
        "INSERT INTO passages (pid, body) VALUES (?, ?)",
        [(p.id, f"{p.heading} {p.quote}") for p in all_passages()],
    )
    return conn


def _scores(text: str) -> dict[str, float]:
    """passage id -> FTS5 bm25 score (lower is better) for passages that match."""
    query = match_query(text)
    if query is None:
        return {}
    try:
        rows = _index().execute(
            "SELECT pid, bm25(passages) FROM passages WHERE passages MATCH ?", (query,)
        ).fetchall()
    except sqlite3.Error as exc:
        # A Python build without FTS5 (log 29). FTS5 only ORDERS here -- the
        # cause-kind key does the selecting -- so the excerpts keep their file
        # order, exactly as when no word matches. Logged, never raised: the
        # run page's search and the step tool must not fail over an ordering.
        log.warning("excerpt ranking unavailable: %s: %s", type(exc).__name__, exc)
        return {}
    return {pid: score for pid, score in rows}


def retrieve(kind: str, evidence_text: str, limit: int = MAX_PASSAGES_PER_CAUSE) -> list[DocPassage]:
    """The excerpts filed under `kind`, best match to the evidence first.

    An unknown or unfiled kind gets nothing -- there is no fallback to free
    search, because a fallback is exactly where a wrong cause comes from.
    """
    candidates = [p for p in all_passages() if kind in p.causeKinds]
    if not candidates:
        return []
    scores = _scores(evidence_text)
    order = {p.id: i for i, p in enumerate(candidates)}
    ranked = sorted(
        candidates,
        key=lambda p: (p.id not in scores, scores.get(p.id, 0.0), order[p.id]),
    )
    return ranked[:limit]


def search_all(text: str) -> list[tuple[str, float]]:
    """Free FTS5 search over every passage, best first. EXPERIMENT ONLY.

    Not called on the agent's path; see the module docstring.
    """
    return sorted(_scores(text).items(), key=lambda item: item[1])


__all__ = [
    "EVIDENCE_PREFIX",
    "MAX_PASSAGES_PER_CAUSE",
    "DocPassage",
    "PassageStoreError",
    "all_passages",
    "by_evidence_id",
    "match_query",
    "passage",
    "retrieve",
    "search_all",
    "source_title",
    "source_url",
]
