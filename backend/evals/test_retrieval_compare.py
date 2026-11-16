"""The offline retrieval comparison (development log 17) stays reproducible.

Not a quality bar for BM25 -- the experiment's result is recorded in the log,
not asserted as a target. What is pinned: the query set is the one the result
was read from, and the property the decision rests on (the rule table never
gives a confidently wrong kind on this set) still holds.
"""

from __future__ import annotations

import hashlib
import pytest

from .experiments import retrieval_compare as rc

# Frozen before the first run. Editing the queries after seeing results would
# make the recorded comparison meaningless; change this only with a new log entry.
QUERY_SET_SHA16 = "dfab84bb08e0a54a"
needs_queries = pytest.mark.skipif(
    not rc.QUERIES.is_file(), reason="private frozen query set is absent"
)


@needs_queries
def test_the_query_set_is_the_frozen_one():
    digest = hashlib.sha256(rc.QUERIES.read_bytes()).hexdigest()[:16]
    assert digest == QUERY_SET_SHA16


@needs_queries
def test_every_gold_line_is_one_the_rule_table_matches():
    # Gold lines are written from the rule patterns; if one stops matching,
    # either the rule table or the query set changed.
    result = rc.run()
    assert all(r["A"] for r in result["rows"] if r["source"] == "gold")


@needs_queries
def test_the_rule_table_never_answers_a_wrong_kind_on_this_set():
    result = rc.run()
    for row in result["rows"]:
        # A either names an acceptable kind or abstains: on a variant, abstaining
        # counts as a miss (A False) but never as a confident wrong answer.
        if row["source"] == "variant":
            assert not row["A"]
        else:
            assert row["A"]


@needs_queries
def test_the_threshold_is_chosen_without_heldout_queries():
    # Same threshold whether or not heldout rows exist in the scored set.
    import json

    queries = json.loads(rc.QUERIES.read_text(encoding="utf-8"))["queries"]
    dev = [q for q in queries if q["split"] == "dev"]
    index = rc.Bm25.build(rc.corpus(False))
    assert rc.choose_threshold(index, dev) == rc.run()["threshold"]


def test_hangul_is_tokenised_into_bigrams_and_ascii_into_words():
    assert rc.tokens("VCF 색인") == ["vcf", "색인"]
    assert rc.tokens("체크섬이") == ["체크", "크섬", "섬이"]
