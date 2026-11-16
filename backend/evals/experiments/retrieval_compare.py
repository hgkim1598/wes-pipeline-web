"""Offline comparison: exact-key lookup vs BM25 for mapping a failure line to
a cause-kind knowledge entry (development log 17, Cycle 2).

No model, no network, no new dependency. Run:

    python -m evals.experiments.retrieval_compare

Methods
    A   the rule table (resource_bundle_causes.classify) -> exact key, or abstain
    B1  BM25 over the 16 knowledge entries' own text (title, checks, cautions)
    B2  B1 plus the kind id and role written as words -- partly copies A's
        vocabulary, so it is an ablation, not a fair competitor
    C   A, falling back to B1 only when A abstains

BM25 is written here (k1=1.2, b=0.75, the SQLite FTS5 defaults) because the
corpus is 16 documents and rank_bm25 is not installed. Tokens: lower-cased
ASCII alphanumeric runs, plus Hangul character bigrams (a crude stand-in for a
morphological analyser -- see the log).

The abstain threshold for B is chosen on the dev split only; heldout queries
are reported with that threshold and never used to pick it.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.services import resource_bundle_causes
from app.services.explanation import knowledge

QUERIES = Path(__file__).with_name("retrieval_queries.json")
K1, B = 1.2, 0.75
_ASCII = re.compile(r"[a-z0-9]+")
_HANGUL = re.compile(r"[가-힣]+")


def tokens(text: str) -> list[str]:
    text = text.lower()
    out = _ASCII.findall(text)
    for run in _HANGUL.findall(text):
        out.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return out


@dataclass
class Bm25:
    ids: list[str]
    docs: list[Counter]
    lengths: list[int]
    df: Counter

    @classmethod
    def build(cls, corpus: dict[str, str]) -> "Bm25":
        ids = list(corpus)
        docs = [Counter(tokens(corpus[i])) for i in ids]
        df: Counter = Counter()
        for doc in docs:
            df.update(doc.keys())
        return cls(ids, docs, [sum(d.values()) for d in docs], df)

    def scores(self, query: str) -> list[tuple[str, float]]:
        n = len(self.docs)
        avg = sum(self.lengths) / n
        q = tokens(query)
        ranked = []
        for doc_id, doc, length in zip(self.ids, self.docs, self.lengths):
            score = 0.0
            for term in q:
                tf = doc.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg))
            ranked.append((doc_id, score))
        return sorted(ranked, key=lambda pair: (-pair[1], pair[0]))


def corpus(with_ids: bool) -> dict[str, str]:
    docs = {}
    for entry in knowledge.all_cause_kinds():
        parts = [entry.title]
        parts += [c.statement for c in entry.checks]
        parts += [c.statement for c in entry.cautions]
        if with_ids:
            parts.append(entry.kind.replace("_", " "))
        docs[entry.kind] = " ".join(parts)
    return docs


def rule_kind(text: str) -> str | None:
    kind = resource_bundle_causes.classify(text).kind
    return None if kind == resource_bundle_causes.UNKNOWN else kind


def bm25_kind(index: Bm25, text: str, threshold: float) -> tuple[str | None, list[str]]:
    ranked = index.scores(text)
    top_id, top = ranked[0]
    order = [doc_id for doc_id, score in ranked if score > 0]
    return (top_id if top > threshold else None), order


def _judge(predicted: str | None, expect: list[str]) -> bool:
    return predicted is None if not expect else predicted in expect


def run(threshold: float | None = None) -> dict:
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    b1, b2 = Bm25.build(corpus(False)), Bm25.build(corpus(True))
    if threshold is None:
        threshold = choose_threshold(b1, [q for q in queries if q["split"] == "dev"])
    rows = []
    for q in queries:
        a = rule_kind(q["text"])
        p1, order1 = bm25_kind(b1, q["text"], threshold)
        p2, _ = bm25_kind(b2, q["text"], threshold)
        c = a if a is not None else p1
        rank = next((i + 1 for i, d in enumerate(order1) if d in q["expect"]), None)
        rows.append({
            "id": q["id"], "source": q["source"], "split": q["split"],
            "A": _judge(a, q["expect"]), "B1": _judge(p1, q["expect"]),
            "B2": _judge(p2, q["expect"]), "C": _judge(c, q["expect"]),
            "rrB1": 0.0 if rank is None else 1 / rank,
            "C_wrong_confident": bool(c is not None and c not in q["expect"]),
        })
    return {"threshold": threshold, "rows": rows}


def choose_threshold(index: Bm25, dev: list[dict]) -> float:
    """The B1 abstain threshold that maximises dev accuracy (ties -> lower)."""
    candidates = sorted({0.0} | {s for q in dev for _, s in index.scores(q["text"])[:1]})
    best, best_acc = 0.0, -1.0
    for t in candidates:
        acc = sum(_judge(bm25_kind(index, q["text"], t)[0], q["expect"]) for q in dev) / len(dev)
        if acc > best_acc:
            best, best_acc = t, acc
    return best


def summary(result: dict) -> list[tuple]:
    out = []
    for split in ("dev", "heldout", "all"):
        for source in ("gold", "variant", "negative"):
            rows = [r for r in result["rows"] if r["source"] == source
                    and (split == "all" or r["split"] == split)]
            if not rows:
                continue
            n = len(rows)
            out.append((split, source, n,
                        *(sum(r[m] for r in rows) for m in ("A", "B1", "B2", "C")),
                        round(sum(r["rrB1"] for r in rows) / n, 2) if source != "negative" else None,
                        sum(r["C_wrong_confident"] for r in rows)))
    return out


def main() -> None:
    result = run()
    print(f"B abstain threshold (chosen on dev only): {result['threshold']:.3f}")
    print("split    source    n   A  B1  B2   C  MRR(B1)  C_wrong_confident")
    for split, source, n, a, b1, b2, c, mrr, wrong in summary(result):
        print(f"{split:8} {source:8} {n:3} {a:3} {b1:3} {b2:3} {c:3}  {mrr!s:7}  {wrong}")


if __name__ == "__main__":
    main()
