"""The official-document search eval (evals/rag_eval): its metrics, its case file, and
the public synthetic baseline.

No model, no network, no database. The baseline assertions below are a
REGRESSION guard against today's behaviour on unreviewed synthetic cases built
from main.sh's own message templates -- not a claim of retrieval quality. See
evals/rag_eval/README.md for what the numbers can and cannot say.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from .rag_eval import metrics
from .rag_eval import run as rag


# --- metrics ---------------------------------------------------------------------


def test_first_relevant_rank_is_one_based_and_none_when_absent():
    assert metrics.first_relevant_rank(["a", "b", "c"], lambda x: x == "b") == 2
    assert metrics.first_relevant_rank(["a", "b"], lambda x: x == "z") is None
    assert metrics.first_relevant_rank([], lambda x: True) is None


@pytest.mark.parametrize("rank,k,expected", [(1, 1, 1), (2, 1, 0), (3, 3, 1), (None, 5, 0)])
def test_recall_at_k(rank, k, expected):
    assert metrics.recall_at_k(rank, k) == expected


def test_recall_at_k_rejects_a_meaningless_k():
    with pytest.raises(ValueError):
        metrics.recall_at_k(1, 0)


def test_reciprocal_rank():
    assert metrics.reciprocal(1) == 1.0
    assert metrics.reciprocal(4) == 0.25
    assert metrics.reciprocal(None) == 0.0


def test_an_empty_denominator_is_not_measured_rather_than_zero_or_one():
    summary = metrics.summarize([], [])
    assert summary["mrr"] is None
    assert summary["recallAt"]["1"] is None
    assert summary["abstainAccuracy"] is None


def test_summarize_averages_over_the_right_populations():
    summary = metrics.summarize([1, 2, None], [True, False])
    assert summary["recallAt"]["1"] == pytest.approx(1 / 3)
    assert summary["recallAt"]["3"] == pytest.approx(2 / 3)
    assert summary["mrr"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert summary["abstainAccuracy"] == 0.5


def test_ndcg_rewards_the_best_passage_first():
    grades = {"a": 2, "b": 1, "c": 0}
    assert metrics.ndcg_at_k(["a", "b", "c"], grades, 3) == pytest.approx(1.0)
    assert metrics.ndcg_at_k(["c", "b", "a"], grades, 3) < metrics.ndcg_at_k(["b", "a", "c"], grades, 3) < 1.0
    assert metrics.ndcg_at_k(["x"], {"x": 0}, 3) is None
    with pytest.raises(ValueError):
        metrics.ndcg_at_k(["a"], grades, 0)


# --- the case file -----------------------------------------------------------------


def _cases():
    return json.loads(rag.CASES.read_text(encoding="utf-8"))["cases"]


def test_the_public_cases_load():
    cases = rag.load_cases()
    assert {c["category"] for c in cases} == set(rag.CATEGORIES)


def test_no_case_is_marked_reviewed_without_a_reviewer():
    # Review is the user's decision; nothing here may confirm ground truth.
    for case in _cases():
        if case["review"]["status"] != "unreviewed":
            assert case["review"]["reviewer"] and case["review"]["date"]


@pytest.mark.parametrize("mutate,message", [
    (lambda c: c[1].update(id=c[0]["id"]), "duplicate"),
    (lambda c: c[0].update(category="maybe"), "category"),
    (lambda c: c[0]["review"].update(status="accepted"), "reviewer"),
    (lambda c: c[0]["expected"].update(relevant_kinds=[]), "relevant"),
    (lambda c: c[0].update(basis=""), "basis"),
    (lambda c: c[0].update(run={}), "run needs"),
    (lambda c: c[0].update(design="clever"), "design"),
    (lambda c: c[0]["expected"].update(grades_local={"x": 3}), "grades_local"),
    (lambda c: c[0]["expected"].pop("grade_basis"), "grade_basis"),
])
def test_a_malformed_case_file_is_an_error(mutate, message):
    cases = copy.deepcopy(_cases())
    mutate(cases)
    with pytest.raises(ValueError, match=message):
        rag.validate_cases(cases)


def test_the_public_cases_carry_no_real_identifiers():
    text = rag.CASES.read_text(encoding="utf-8")
    assert "/home/" not in text and "vboxuser" not in text
    assert not re.search(r"PATIENT|SRR\d+|C:\\\\Users", text)


# --- the baseline on the public synthetic corpus ----------------------------------


@pytest.fixture(scope="module")
def baseline():
    return rag.run("synthetic")


def test_every_case_is_scored(baseline):
    assert baseline["summary"]["cases"] == len(_cases())
    assert all(r["errorCategory"] is None for r in baseline["results"])


def test_the_search_never_returns_a_passage_about_another_cause(baseline):
    # The one negative with hits (ind-bed-contig-absent) gets passages of its
    # own kind that do not help; no case gets a passage of a different kind.
    others = [r for r in baseline["results"] if r["id"] != "ind-bed-contig-absent"]
    assert sum(r["wrongKindHits"] for r in others) == 0


def test_the_search_stays_silent_where_the_rule_table_decides(baseline):
    # coverage gaps and rule-level negatives: nothing returned
    assert baseline["byDesign"]["rule_replicating"]["abstainAccuracy"] == 1.0


def test_every_template_cause_becomes_the_expected_query(baseline):
    misses = [r["id"] for r in baseline["results"]
              if r["design"] != "phrasing_variant" and not r["inputKindsMatch"]]
    assert misses == []


def test_regression_floor_for_template_sentences(baseline):
    # Today's value on the synthetic corpus for main.sh's own templates. A drop
    # is a classification or filing regression; it says nothing about ranking.
    for design in ("rule_replicating", "independent_ranking"):
        assert baseline["byDesign"][design]["recallAt"]["5"] == 1.0, design


def test_known_gaps_are_reported_not_hidden(baseline):
    # Recorded as measured, not tuned away (log 61): reworded sentences are not
    # classified (no fuzzy fallback by design), and a BED contig error retrieves
    # BED passages that do not address it.
    assert baseline["byDesign"]["phrasing_variant"]["recallAt"]["5"] == 0.0
    contig = next(r for r in baseline["results"] if r["id"] == "ind-bed-contig-absent")
    assert not contig["abstained"]


def test_where_a_file_lives_never_changes_the_order(baseline):
    assert baseline["pathStability"]["cases"] > 0
    assert baseline["pathStability"]["changed"] == []


def test_the_metric_is_not_vacuous(monkeypatch):
    # The same run judged against a cause it does not have scores zero.
    case = copy.deepcopy(next(c for c in _cases() if c["id"] == "pos-checksum"))
    case["expected"]["relevant_kinds"] = ["bed_content_invalid"]
    with rag.corpus(rag.SYNTHETIC_CORPUS):
        result = rag.evaluate_case(case, score_preferred=False)
    assert result["queries"][0]["firstRelevantRank"] is None
    assert result["wrongKindHits"] == result["hitCount"] > 0


def test_the_eval_restores_the_search_configuration():
    from app import config
    before = (config.DOC_PASSAGE_KNOWLEDGE, config.DOC_MANUAL_CHUNKS, config.RUNS_ROOT)
    rag.run("synthetic")
    assert (config.DOC_PASSAGE_KNOWLEDGE, config.DOC_MANUAL_CHUNKS, config.RUNS_ROOT) == before
