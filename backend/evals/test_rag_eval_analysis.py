"""Regression guard for the analysis-step document search evaluation (development log 65).

Synthetic manuals and synthetic curated excerpts only; no model, no network.
The cases are provisional (AI-drafted, unreviewed): these tests pin the
ROUTING contract -- right command, right manual, silence otherwise -- not a
claim about ranking quality on real manual text.
"""

from __future__ import annotations

import json

import pytest

from evals.rag_eval import analysis


@pytest.fixture(scope="module")
def report():
    return analysis.run()


def test_cases_are_provisional_and_state_their_basis():
    cases = analysis.load_cases()
    assert len(cases) >= 20
    assert all(c["review"]["status"] == "unreviewed" and c["basis"] for c in cases)
    assert {c["category"] for c in cases} == {"positive", "abstain"}


def test_every_input_is_the_command_main_sh_runs(report):
    s = report["summary"]
    assert s["inputAccuracy"] == 1.0, [r["id"] for r in report["rows"] if not r["inputMatch"]]


def test_answerable_failures_land_in_their_commands_section(report):
    s = report["summary"]
    assert s["answerableQueries"] >= 15
    assert s["recallAt1"] == 1.0 and s["mrr"] == 1.0


def test_silence_where_nothing_applies_and_no_cross_tool_hits(report):
    s = report["summary"]
    assert s["abstainAccuracy"] == 1.0, s["falsePositiveRuns"]
    assert s["curatedHits"] == 0
    assert s["candidatesOutsideSection"] == 0


def test_a_lane_label_never_leaks_the_sample(report):
    assert report["summary"]["sampleLeaks"] == 0
    assert analysis.SAMPLE not in json.dumps(report["summary"])


def test_the_ablation_reproduces_the_state_before():
    before = analysis.run(ablate=True)["summary"]
    assert before["recallAt1"] == 0.0
    assert before["inputAccuracy"] < 0.5
    assert before["abstainAccuracy"] == 1.0
