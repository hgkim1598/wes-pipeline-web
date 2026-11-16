"""Offline comparison: which official excerpts does each method return? (log 18)

No model. Same 48 queries as retrieval_compare.py, frozen in Cycle 2 BEFORE the
passages existed, so the passages could not be tuned to them. A query is judged
on the TOP excerpt a method returns:

    relevant   the excerpt is filed under one of the query's expected kinds
    wrong      an excerpt came back but it is about another kind
               (for a negative query, anything returned is wrong)
    abstain    nothing came back (correct only for a negative query)

Methods
    A    rule table -> exact kind -> that kind's excerpts (file order)
    B    SQLite FTS5 over every excerpt, no kind filter, abstain threshold
    C    hand-written BM25 (retrieval_compare.Bm25) over every excerpt, threshold
    H    the agent's path: rule table -> kind -> FTS5 order inside the kind

Thresholds for B and C are chosen on the dev split only. D (vector), E
(hybrid) and F (graph) are not run: see the research doc, section 8.

Run:  python -m evals.experiments.doc_retrieval_compare
"""

from __future__ import annotations

import json
from collections.abc import Callable

from app.services.agent import doc_retrieval
from app.services import resource_bundle_causes

from .retrieval_compare import QUERIES, Bm25

Returner = Callable[[str], list[str]]


def _kinds(passage_id: str) -> set[str]:
    return set(doc_retrieval.passage(passage_id).causeKinds)


def _rule_kind(text: str) -> str | None:
    kind = resource_bundle_causes.classify(text).kind
    return None if kind == resource_bundle_causes.UNKNOWN else kind


def method_a(text: str) -> list[str]:
    kind = _rule_kind(text)
    if kind is None:
        return []
    return [p.id for p in doc_retrieval.all_passages() if kind in p.causeKinds]


def method_h(text: str) -> list[str]:
    kind = _rule_kind(text)
    return [] if kind is None else [p.id for p in doc_retrieval.retrieve(kind, text)]


def _fts_ranked(text: str) -> list[tuple[str, float]]:
    # FTS5 bm25 is lower-is-better; flip so every method is higher-is-better.
    return [(pid, -score) for pid, score in doc_retrieval.search_all(text)]


_BM25: Bm25 | None = None


def _bm25_ranked(text: str) -> list[tuple[str, float]]:
    global _BM25
    if _BM25 is None:
        _BM25 = Bm25.build({p.id: f"{p.heading} {p.quote}" for p in doc_retrieval.all_passages()})
    return [(pid, s) for pid, s in _BM25.scores(text) if s > 0]


def thresholded(ranked: Callable[[str], list[tuple[str, float]]], threshold: float) -> Returner:
    def run(text: str) -> list[str]:
        return [pid for pid, score in ranked(text) if score > threshold]
    return run


def judge(returned: list[str], expect: list[str]) -> str:
    if not returned:
        return "abstain"
    if expect and _kinds(returned[0]) & set(expect):
        return "relevant"
    return "wrong"


def correct(outcome: str, expect: list[str]) -> bool:
    return outcome == "relevant" or (outcome == "abstain" and not expect)


def choose_threshold(ranked, dev: list[dict]) -> float:
    """Maximise dev correctness; ties go to the HIGHER threshold (abstain more)."""
    candidates = sorted({0.0} | {s for q in dev for _, s in ranked(q["text"])[:1]})
    best, best_ok = 0.0, -1
    for t in candidates:
        ok = sum(correct(judge(thresholded(ranked, t)(q["text"]), q["expect"]), q["expect"]) for q in dev)
        if ok >= best_ok:
            best, best_ok = t, ok
    return best


def run() -> dict:
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    dev = [q for q in queries if q["split"] == "dev"]
    t_b = choose_threshold(_fts_ranked, dev)
    t_c = choose_threshold(_bm25_ranked, dev)
    methods: dict[str, Returner] = {
        "A": method_a,
        "B": thresholded(_fts_ranked, t_b),
        "C": thresholded(_bm25_ranked, t_c),
        "H": method_h,
    }
    rows = []
    for q in queries:
        row = {"id": q["id"], "source": q["source"], "split": q["split"]}
        for name, method in methods.items():
            row[name] = judge(method(q["text"]), q["expect"])
        rows.append(row)
    return {"thresholds": {"B": t_b, "C": t_c}, "rows": rows}


def summary(result: dict) -> list[tuple]:
    out = []
    for source in ("gold", "variant", "negative"):
        rows = [r for r in result["rows"] if r["source"] == source]
        for name in ("A", "B", "C", "H"):
            outcomes = [r[name] for r in rows]
            out.append((source, name, len(rows), outcomes.count("relevant"),
                        outcomes.count("wrong"), outcomes.count("abstain")))
    return out


def main() -> None:
    result = run()
    print("thresholds (dev only):", {k: round(v, 3) for k, v in result["thresholds"].items()})
    print(f"{'source':9}{'method':7}{'n':>3}{'relevant':>10}{'wrong':>7}{'abstain':>9}")
    for source, name, n, rel, wrong, abstain in summary(result):
        print(f"{source:9}{name:7}{n:>3}{rel:>10}{wrong:>7}{abstain:>9}")


if __name__ == "__main__":
    main()
