"""Retrieval metrics for the official-document search eval. Pure functions, no I/O.

A *query* here is one search input the engine built from a run (one recorded
cause), with the passages it returned in rank order. Relevance is decided by
the caller (for this eval: the passage is filed under an expected cause kind).

    recall_at_k   1 if any relevant passage is in the top k, else 0
    reciprocal    1 / rank of the first relevant passage, 0 if none
    abstained     True when nothing came back

Averages are taken over queries that should find something (positives) for
Recall@k and MRR, and over cases that should find nothing for abstain accuracy.
An empty denominator gives None, never 0 or 1: "not measured" is not a score.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence


def first_relevant_rank(ranked: Sequence[str], is_relevant: Callable[[str], bool]) -> int | None:
    """1-based rank of the first relevant item, or None."""
    for index, item in enumerate(ranked, start=1):
        if is_relevant(item):
            return index
    return None


def recall_at_k(rank: int | None, k: int) -> int:
    if k < 1:
        raise ValueError("k must be >= 1")
    return int(rank is not None and rank <= k)


def reciprocal(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def ndcg_at_k(ranked: Sequence[str], grades: dict[str, int], k: int) -> float | None:
    """Normalised discounted cumulative gain with graded relevance (0..2).

    Items absent from `grades` count as 0. None when no item has a positive
    grade: an ideal ranking of nothing is not a score.
    """
    import math

    if k < 1:
        raise ValueError("k must be >= 1")

    def dcg(gains: Sequence[int]) -> float:
        return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains[:k]))

    ideal = dcg(sorted((g for g in grades.values() if g > 0), reverse=True))
    if ideal == 0:
        return None
    return dcg([grades.get(item, 0) for item in ranked]) / ideal


def summarize(positive_ranks: Sequence[int | None], abstain_correct: Sequence[bool],
              ks: Sequence[int] = (1, 3, 5)) -> dict:
    """The headline numbers from per-query ranks and per-case abstain outcomes."""
    return {
        "positiveQueries": len(positive_ranks),
        "recallAt": {str(k): mean([recall_at_k(r, k) for r in positive_ranks]) for k in ks},
        "mrr": mean([reciprocal(r) for r in positive_ranks]),
        "abstainCases": len(abstain_correct),
        "abstainAccuracy": mean([1.0 if ok else 0.0 for ok in abstain_correct]),
    }


__all__ = ["first_relevant_rank", "mean", "ndcg_at_k", "recall_at_k", "reciprocal", "summarize"]
