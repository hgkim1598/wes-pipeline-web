"""The two Cycle 3 synthetic cases are what their answer keys say (no model).

The generic agent-case tests in test_evaluators.py already cover them through
agent_cases.CASES (anchored step, citable mustCite, planned steps, no sample
name). These pin what each case exists for: what the step tool shows the agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.agent import run_scope, step_evidence

from . import agent_cases, run_eval

EXPECTATIONS = Path(__file__).parent / "expectations"
NEW = ("agent_resource_unclassified", "agent_resource_index_pair")


def _step_view(name: str) -> dict:
    with agent_cases.materialise(agent_cases.CASES[name]):
        scope = run_scope.for_job(agent_cases.RUN_ID)
        return step_evidence.read_step_evidence(scope, "00_input_validation").model_dump()


def test_the_unrecognised_sentence_reaches_the_agent_as_unknown_with_no_guidance():
    view = _step_view("agent_resource_unclassified")
    causes = view["resourceBundleDiagnosis"]["causes"]
    assert [(c["kind"], c["resourceRole"]) for c in causes] == [
        ("vcf_contig_length_mismatch", "dbsnp_vcf"),
        ("unknown", "unknown"),
    ]
    # The agent sees the record itself, so it can quote it rather than guess.
    assert causes[1]["evidenceText"] == agent_cases.UNCLASSIFIED_LINE
    # Guidance only for what a rule classified: nothing to borrow a cause from.
    assert [g["kind"] for g in view["causeGuidance"]] == ["vcf_contig_length_mismatch"]


def test_the_index_pair_gets_two_guidance_entries_each_with_a_bounded_remedy():
    view = _step_view("agent_resource_index_pair")
    guidance = {g["kind"]: g for g in view["causeGuidance"]}
    assert set(guidance) == {"bwa_index_incomplete", "reference_index_mismatch"}
    for entry in guidance.values():
        assert entry["checks"], entry["kind"]
        assert entry["remedies"], entry["kind"]
        for remedy in entry["remedies"]:
            assert remedy["changes"].strip() and remedy["approval"].strip(), entry["kind"]
    # The tempting shortcut for this pair is ruled out in the guidance itself.
    assert any(".dict" in c and "손으로" in c for c in guidance["reference_index_mismatch"]["cautions"])


def test_the_new_cases_have_their_own_group_and_leave_agent_unchanged():
    assert set(run_eval.SYNTH_CASES.values()) == set(NEW)
    assert not set(NEW) & set(run_eval.AGENT_CASES.values())
    assert len(run_eval.AGENT_CASES) == 4


def test_the_case_builders_and_the_step_output_carry_no_answer_key():
    """Narrow on purpose (Codex U2-U4 round 1): the builders name no path to
    the answer keys, and the step tool's output holds no review question. It
    does NOT inspect the assembled model request. (run_eval._evaluate_run loads
    the key before the call but hands build_run_synthesis only the explanation
    -- read in the code, not tested here.)"""
    source = Path(agent_cases.__file__).read_text(encoding="utf-8")
    # Docstrings may use the word; what must not appear is a way to the files.
    for reference in ('"expectations"', "expectations/", "EXPECTATIONS", "json.load"):
        assert reference not in source, reference
    for name in NEW:
        key = json.loads((EXPECTATIONS / f"{name}.json").read_text(encoding="utf-8"))
        assert key["case"] == name
        view = json.dumps(_step_view(name), ensure_ascii=False)
        for item in key["humanReview"]:
            assert item["question"] not in view
            assert item["name"] not in view
