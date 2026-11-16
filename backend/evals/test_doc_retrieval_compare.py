"""The offline excerpt comparison keeps the property the design rests on (log 18).

Not a benchmark: 48 synthetic queries are too few to generalise
(Voorhees & Buckley). What is pinned is structural -- the agent's path (H)
never returns an excerpt about a different cause, and agrees with plain key
lookup (A) on every query.
"""

from __future__ import annotations

from .experiments import doc_retrieval_compare as cmp
import pytest
from app.tests.doc_corpus_fixture import synthetic_passages

pytestmark = [
    pytest.mark.usefixtures("synthetic_passages"),
    pytest.mark.skipif(not cmp.QUERIES.is_file(), reason="private frozen query set is absent"),
]


@pytest.fixture(autouse=True)
def reset_comparison_index(monkeypatch):
    monkeypatch.setattr(cmp, "_BM25", None)


def test_the_agents_path_never_returns_an_excerpt_about_another_cause():
    rows = cmp.run()["rows"]
    assert [r["id"] for r in rows if r["H"] == "wrong"] == []


def test_the_agents_path_judges_every_query_like_key_lookup():
    rows = cmp.run()["rows"]
    assert [r["id"] for r in rows if r["H"] != r["A"]] == []


def test_negative_queries_get_nothing_on_the_agents_path():
    rows = cmp.run()["rows"]
    assert {r["H"] for r in rows if r["source"] == "negative"} == {"abstain"}


def test_thresholds_are_chosen_on_dev_only(monkeypatch):
    """Changing a heldout query must not move a threshold."""
    import json

    before_run = cmp.run()
    before = before_run["thresholds"]
    changed = json.loads(cmp.QUERIES.read_text(encoding="utf-8"))
    for q in changed["queries"]:
        if q["split"] == "heldout":
            q["text"] = "tabix bgzip checksum dictionary bwtsw mandatory"

    class _Fake:
        def read_text(self, encoding):
            return json.dumps(changed)

    monkeypatch.setattr(cmp, "QUERIES", _Fake())
    after = cmp.run()
    assert after["thresholds"] == before
    # ...and the change did reach the heldout rows, so the check is not vacuous:
    # some heldout outcome differs from the run on the real queries.
    old = {r["id"]: r["B"] for r in before_run["rows"] if r["split"] == "heldout"}
    new = {r["id"]: r["B"] for r in after["rows"] if r["split"] == "heldout"}
    assert old != new
