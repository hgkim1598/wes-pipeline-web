"""The evaluators themselves, checked with stub output only.

Zero model calls. Run explicitly, because pytest.ini's `testpaths = app/tests`
does not reach this directory:

    .venv/Scripts/python.exe -m pytest evals/test_evaluators.py

An evaluator that cannot fail is decoration, so each test here pairs a passing
input with a failing one. The two that matter most are the negation case (a
correct sentence that contains a "forbidden" phrase must PASS) and the vacuous
case (a relation nothing exercised must NOT be reported as a pass).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import evaluators

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXPECTATIONS = Path(__file__).resolve().parent / "expectations"


def _statement(text: str, refs: list[str]) -> dict:
    return {"statement": text, "evidenceRefs": refs}


def _synthesis(**groups) -> dict:
    base = {
        "summary": groups.pop("summary", "요약입니다."),
        "importantFindings": [],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }
    base.update(groups)
    return base


def _ok(synthesis: dict) -> dict:
    return {"available": True, "errorCategory": None, "synthesis": synthesis}


# --- A. numbers --------------------------------------------------------------


def test_numbers_from_the_run_pass():
    facts = {"variantCalling": {"rawVariantRecords": 52379}}
    result = evaluators.check_numbers(["변이 후보 기록 52,379건이 있습니다."], facts)
    assert result.outcome == "pass"


def test_a_number_the_run_never_recorded_fails():
    facts = {"variantCalling": {"rawVariantRecords": 52379}}
    result = evaluators.check_numbers(["약 61,204건이 검출되었습니다."], facts)
    assert result.outcome == "fail"
    assert "61,204" in result.detail


def test_thousands_separators_and_decimals_normalise():
    """`52,379` == `52379`, and `10.9967` must not be accepted as `10.997`."""
    facts = {"coverage": {"meanTargetDepth": 10.9967}, "n": 52379}
    assert evaluators.check_numbers(["52,379 · 10.9967"], facts).outcome == "pass"
    assert evaluators.check_numbers(["10.997"], facts).outcome == "fail"


def test_numbers_inside_pipeline_messages_are_known():
    """The model may quote a message verbatim; that is not invention."""
    facts = {"diagnostics": [{"message": "7.2115% of target bases have zero coverage"}]}
    assert evaluators.check_numbers(["7.2115%가 0×입니다."], facts).outcome == "pass"


def test_breadth_thresholds_live_in_dict_keys():
    """The bug the first baseline exposed.

    `coverage.breadth` is `{"30X": 2.6709}` -- the thresholds 30/50/100 exist
    only as keys. Walking values alone flagged a correctly quoted sentence
    ("30X 2.6709%") as an invented number.
    """
    facts = {"coverage": {"breadth": {"30X": 2.6709, "100X": 0.0019}}}
    result = evaluators.check_numbers(
        ["30X 2.6709%, 100X 0.0019%로 기록되었습니다."], facts
    )
    assert result.outcome == "pass", result.detail


def test_small_counts_are_allowed():
    """"3개 항목" counts the model's own list, not the run."""
    facts = {"variantCalling": {"rawVariantRecords": 52379}}
    assert evaluators.check_numbers(["확인할 사항 3개"], facts).outcome == "pass"


# --- B. evidence relations ---------------------------------------------------


def test_qualified_variant_claim_passes():
    synthesis = _synthesis(
        importantFindings=[
            _statement(
                "52,379건의 후보 기록입니다.",
                ["run:variantCalling", "lim:UNFILTERED_VARIANTS"],
            )
        ]
    )
    result = evaluators.check_evidence_relation(
        synthesis,
        name="variant-qualified",
        trigger_refs=["run:variantCalling"],
        required_ref="lim:UNFILTERED_VARIANTS",
    )
    assert result.outcome == "pass"


def test_unqualified_variant_claim_fails():
    synthesis = _synthesis(
        importantFindings=[
            _statement("52,379개의 확정 변이입니다.", ["run:variantCalling"])
        ]
    )
    result = evaluators.check_evidence_relation(
        synthesis,
        name="variant-qualified",
        trigger_refs=["run:variantCalling"],
        required_ref="lim:UNFILTERED_VARIANTS",
    )
    assert result.outcome == "fail"


def test_a_correct_negation_is_not_punished():
    """The reason this is a citation check and not a phrase blacklist.

    "확정된 변이 목록이 아닙니다" contains the phrase a naive blacklist would
    ban, and it is exactly the sentence we want.
    """
    synthesis = _synthesis(
        importantFindings=[
            _statement(
                "52,379건은 후보 기록이며 확정된 변이 목록이 아닙니다.",
                ["run:variantCalling", "lim:UNFILTERED_VARIANTS"],
            )
        ]
    )
    result = evaluators.check_evidence_relation(
        synthesis,
        name="variant-qualified",
        trigger_refs=["run:variantCalling"],
        required_ref="lim:UNFILTERED_VARIANTS",
    )
    assert result.outcome == "pass"


def test_an_unexercised_relation_is_review_not_pass():
    """Vacuous truth must not look like a green check."""
    synthesis = _synthesis(
        importantFindings=[_statement("커버리지 이야기.", ["run:coverage"])]
    )
    result = evaluators.check_evidence_relation(
        synthesis,
        name="variant-qualified",
        trigger_refs=["run:variantCalling"],
        required_ref="lim:UNFILTERED_VARIANTS",
    )
    assert result.outcome == "needs_review"


def test_required_citation_present_and_absent():
    present = _synthesis(
        limitations=[_statement("연구·교육 목적입니다.", ["lim:INTENDED_USE"])]
    )
    absent = _synthesis(limitations=[_statement("무언가.", ["run:status"])])
    assert (
        evaluators.check_ref_cited(present, name="x", ref="lim:INTENDED_USE").outcome
        == "pass"
    )
    assert (
        evaluators.check_ref_cited(absent, name="x", ref="lim:INTENDED_USE").outcome
        == "fail"
    )


# --- D. internal field names -------------------------------------------------


def test_internal_field_names_in_prose_fail():
    """The NOTE the first baseline produced, as a check."""
    payload = {"variantCalling": {"rawVariantRecords": 52379}}
    result = evaluators.check_no_internal_names(
        ["rawVariantRecords는 52,379입니다."], payload
    )
    assert result.outcome == "fail"
    assert "rawVariantRecords" in result.detail


def test_natural_language_about_the_same_value_passes():
    payload = {"variantCalling": {"rawVariantRecords": 52379}}
    result = evaluators.check_no_internal_names(
        ["필터를 거치지 않은 변이 후보 기록은 52,379건입니다."], payload
    )
    assert result.outcome == "pass"


def test_ordinary_words_that_happen_to_be_keys_are_not_flagged():
    """`assembly` is a key AND a word canonical knowledge legitimately uses.

    wes_failures.json says "같은 assembly release에서 나왔음을 증명하지는
    않습니다". Banning every key would fail that correct sentence, which is the
    same trap as the "확정 변이" blacklist.
    """
    payload = {"variantCalling": {"assembly": "GRCh38"}, "grounding": {"scope": []}}
    result = evaluators.check_no_internal_names(
        ["모든 파일이 같은 assembly release에서 나왔음을 증명하지는 않습니다."],
        payload,
    )
    assert result.outcome == "pass"


def test_only_keys_the_model_actually_saw_count():
    """Not a maintained blacklist -- the payload decides."""
    result = evaluators.check_no_internal_names(
        ["someOtherThing은 무관합니다."], {"variantCalling": {"coreEndpoint": "x"}}
    )
    assert result.outcome == "pass"


# --- C. guardrail outcome ----------------------------------------------------


def test_a_tripped_guardrail_is_an_eval_failure():
    for category in ("unknownEvidenceRef", "invalidSynthesis"):
        result = evaluators.check_guardrails(
            {"available": False, "errorCategory": category}
        )
        assert result.outcome == "fail"
        assert category in result.detail


def test_a_provider_failure_is_also_a_failure_but_says_why():
    result = evaluators.check_guardrails(
        {"available": False, "errorCategory": "usageLimit"}
    )
    assert result.outcome == "fail"
    assert "provider" in result.detail


def test_a_clean_run_passes():
    assert evaluators.check_guardrails({"available": True}).outcome == "pass"


# --- human items never masquerade as passes ----------------------------------


def test_human_items_are_reported_as_needs_review():
    expectations = {
        "case": "x",
        "mustMention": [],
        "mustCite": [],
        "mustQualify": [],
        "humanReview": [{"name": "readability", "question": "읽기 쉬운가?"}],
    }
    report = evaluators.run_expectations(expectations, {}, _ok(_synthesis()))
    human = [r for r in report.results if r.kind == "human"]
    assert len(human) == 1
    assert human[0].outcome == "needs_review"
    # deterministic 통과가 곧 전체 통과가 아니다.
    assert report.ok is True
    assert report.needs_review


def test_guardrail_failure_leaves_human_items_unjudged():
    expectations = {
        "case": "x",
        "mustMention": [],
        "mustCite": [],
        "mustQualify": [],
        "humanReview": [{"name": "readability", "question": "읽기 쉬운가?"}],
    }
    report = evaluators.run_expectations(
        expectations, {}, {"available": False, "errorCategory": "timeout"}
    )
    assert not report.ok
    assert all(r.outcome == "needs_review" for r in report.results if r.kind == "human")


# --- open set, canary, and deliberate non-invocation ------------------------


def test_an_open_set_failure_code_has_no_grounding_and_still_works():
    """Case C's shape: a code main.sh composed from run values.

    `sort_order_<sample>.L001` is not in wes_failures.json and never will be.
    The payload must still carry the failure with its runtime message, and the
    evidence id must still be mintable -- otherwise the model could not cite
    the only thing that explains the run.
    """
    from app.services.explanation.deterministic import RunExplanation
    from app.services.explanation.llm import contract
    from app.services.explanation import knowledge

    fixture = json.loads(
        (FIXTURES / "execution_failed.json").read_text(encoding="utf-8")
    )
    code = fixture["failures"][0]["code"]
    assert knowledge.failure(code) is None, "조립 code에 curated 지식이 있으면 안 된다"

    payload, allowed = contract.build_payload(RunExplanation.model_validate(fixture))
    assert f"fail:{code}" in allowed
    assert payload["grounding"] == {}
    row = payload["failures"][0]
    assert row["code"] == code
    assert row["messageFromPipeline"]


def test_the_canary_inside_a_composed_code_is_not_a_leak():
    """The distinction Case C forces.

    The sample fragment lives *inside the failure code*, and that code is the
    evidence id the model must cite. A blanket substring check would call the
    correct behaviour a privacy failure.
    """
    from evals import run_eval

    fixture = json.loads(
        (FIXTURES / "execution_failed.json").read_text(encoding="utf-8")
    )
    assert "EVAL_SAMPLE_CANARY" in fixture["failures"][0]["code"]
    result = run_eval.privacy_check(fixture)
    assert result.outcome == "pass"
    assert "조립 code" in result.detail


def test_the_canary_anywhere_else_is_still_a_leak():
    """The check did not simply stop looking."""
    from evals import run_eval

    fixture = json.loads(
        (FIXTURES / "full_completed_with_warnings.json").read_text(encoding="utf-8")
    )
    # 검체 이름이 payload로 나가는 회귀를 흉내낸다.
    fixture["variantCalling"]["coreEndpoint"] = "raw VCF for EVAL_SAMPLE_CANARY"
    result = run_eval.privacy_check(fixture)
    assert result.outcome == "fail"


def test_a_skipped_case_reports_not_run_not_pass():
    """Deciding not to ask is not the same as asking and being refused."""
    expectations = {
        "case": "x",
        "mustMention": [],
        "mustCite": [{"name": "cites-something", "ref": "lim:RUN_IN_PROGRESS"}],
        "mustQualify": [],
        "humanReview": [{"name": "readability", "question": "읽기 쉬운가?"}],
    }
    report = evaluators.run_expectations(
        expectations,
        {},
        {"available": False, "errorCategory": None, "synthesis": None},
        {},
        model_invoked=False,
    )
    outcomes = {r.name: r.outcome for r in report.results}
    assert outcomes["cites-something"] == "not_run"
    assert outcomes["readability"] == "not_run"
    assert outcomes["runtime-guardrails"] == "not_run"
    # not_run은 실패가 아니다 -- 실행하지 않기로 한 것이므로.
    assert report.ok is True
    # 그렇다고 통과로 세지도 않는다.
    assert not [r for r in report.results if r.outcome == "pass"]


def test_a_provider_failure_is_not_recorded_as_skipped():
    """The states must stay distinguishable in the report."""
    expectations = {"case": "x", "mustMention": [], "mustCite": [], "mustQualify": [], "humanReview": []}
    failed = evaluators.run_expectations(
        expectations, {}, {"available": False, "errorCategory": "timeout"}, {}
    )
    assert not failed.ok
    assert [r for r in failed.results if r.outcome == "fail"]


def test_in_progress_expectations_do_not_demand_unseen_fields():
    """The model is never shown currentStep, progress, steps or finishedAt.

    Requiring them as a golden answer would make the case unpassable for a
    reason that has nothing to do with the model.
    """
    from app.services.explanation.deterministic import RunExplanation
    from app.services.explanation.llm import contract

    fixture = json.loads((FIXTURES / "in_progress.json").read_text(encoding="utf-8"))
    payload, _ = contract.build_payload(RunExplanation.model_validate(fixture))
    blob = json.dumps(payload, ensure_ascii=False)
    for absent in ("currentStep", "finishedAt", '"steps"'):
        assert absent not in blob

    expectations = json.loads(
        (EXPECTATIONS / "in_progress.json").read_text(encoding="utf-8")
    )
    text = json.dumps(expectations, ensure_ascii=False)
    assert "mustPreserve" not in text


# --- the shipped cases are self-consistent -----------------------------------


def test_shipped_expectations_reference_ids_the_payload_can_mint():
    """An expectation citing an id `build_payload` never issues can never pass.

    Checked against the fixture, so a knowledge or payload change that stops
    issuing an id is caught here -- for free, with no model call.
    """
    from app.services.explanation.deterministic import RunExplanation
    from app.services.explanation.llm import contract

    for name in (
        "full_completed_with_warnings",
        "precheck_failed",
        "execution_failed",
        "in_progress",
    ):
        fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        expectations = json.loads(
            (EXPECTATIONS / f"{name}.json").read_text(encoding="utf-8")
        )
        _payload, allowed = contract.build_payload(
            RunExplanation.model_validate(fixture)
        )
        for spec in expectations["mustCite"]:
            assert spec["ref"] in allowed, f"{name}: {spec['ref']} 는 발급되지 않는다"
        for spec in expectations["mustQualify"]:
            assert spec["mustAlsoCite"] in allowed, name
            for ref in spec["whenCiting"]:
                assert ref in allowed, f"{name}: {ref} 는 발급되지 않는다"


def test_shipped_fixtures_carry_no_sample_identifier():
    for name in (
        "full_completed_with_warnings",
        "precheck_failed",
        "execution_failed",
        "in_progress",
    ):
        blob = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
        for forbidden in ("SRR2962669", "DEMO_WES", "/home/", "vboxuser", "wes-2026"):
            assert forbidden not in blob, f"{name}: {forbidden}"


def test_the_canary_never_reaches_the_payload():
    """The fixture keeps a fake sample name so the allowlist can be observed."""
    from app.services.explanation.deterministic import RunExplanation
    from app.services.explanation.llm import contract

    fixture = json.loads(
        (FIXTURES / "full_completed_with_warnings.json").read_text(encoding="utf-8")
    )
    assert "EVAL_SAMPLE_CANARY" in json.dumps(fixture)  # fixture에는 있고
    payload, _ = contract.build_payload(RunExplanation.model_validate(fixture))
    assert "EVAL_SAMPLE_CANARY" not in json.dumps(payload)  # payload에는 없다


def test_rescoring_a_skipped_baseline_does_not_call_it_a_provider_failure():
    """The one distinction the skipped record exists to keep.

    `--rescore` replays stored output through the current checks. A baseline
    recorded with no model call has no output, and scoring it as if it did
    turns "we never called" into "the provider failed" -- which would make a
    real outage indistinguishable from a deliberate skip. Caught in review
    after the live path already handled it correctly.
    """
    from . import run_eval

    matches = sorted(run_eval.BASELINES.glob("*_in_progress_*.json"))
    assert matches, "in_progress baseline이 없습니다"
    stored = json.loads(matches[-1].read_text(encoding="utf-8"))
    assert stored["invocationStatus"] == "skipped"

    outcomes = {r["outcome"] for r in stored["evaluation"]["results"]}
    assert "fail" not in outcomes, stored["evaluation"]["results"]
    assert "not_run" in outcomes

    guardrails = next(
        r for r in stored["evaluation"]["results"] if r["name"] == "runtime-guardrails"
    )
    assert guardrails["outcome"] == "not_run"
    assert "실패" not in guardrails["detail"]


# --- E. tool selection -------------------------------------------------------
#
# A different question from every test above: not "was the answer grounded",
# but "did the agent go and get the right evidence". Stub observations only --
# the shape `tools.observe()` produces, never a model call.


def _use(*step_ids: str) -> dict:
    """An observation as the runtime hands it over."""
    return {
        "toolUsed": bool(step_ids),
        "openedStepIds": list(step_ids),
        "toolEvidenceIds": [f"step:{s}" for s in step_ids],
    }


def test_tool_expected_and_used_passes():
    result = evaluators.check_tool_use(
        {"expectedToolUse": True}, _use("04_processing")
    )
    assert result.outcome == "pass"


def test_tool_expected_and_not_used_fails():
    """The failure that matters most: the agent never went to look."""
    result = evaluators.check_tool_use({"expectedToolUse": True}, _use())
    assert result.outcome == "fail"
    assert "호출하지 않음" in result.detail


def test_tool_forbidden_and_not_used_passes():
    result = evaluators.check_tool_use({"expectedToolUse": False}, _use())
    assert result.outcome == "pass"


def test_tool_forbidden_but_used_fails():
    """Opening a step for no reason is a finding, not a free extra."""
    result = evaluators.check_tool_use(
        {"expectedToolUse": False}, _use("99_finalization")
    )
    assert result.outcome == "fail"
    assert "99_finalization" in result.detail


def test_a_missing_observation_is_read_as_no_tool_use():
    """An older record, or a call that never reported: absence is not use."""
    assert evaluators.check_tool_use({"expectedToolUse": False}, None).outcome == "pass"
    assert evaluators.check_tool_use({"expectedToolUse": True}, None).outcome == "fail"


def test_the_expected_step_passes():
    result = evaluators.check_step_selection(
        {"expectedToolUse": True, "expectedStepIds": ["04_processing"]},
        _use("04_processing"),
    )
    assert result.outcome == "pass"


def test_a_different_step_fails():
    result = evaluators.check_step_selection(
        {"expectedToolUse": True, "expectedStepIds": ["04_processing"]},
        _use("01_raw_qc"),
    )
    assert result.outcome == "fail"
    assert "04_processing" in result.detail


def test_several_expected_steps_pass_in_any_order():
    """Order is the agent's business; the set is what was asked for."""
    result = evaluators.check_step_selection(
        {"expectedToolUse": True, "expectedStepIds": ["01_raw_qc", "04_processing"]},
        _use("04_processing", "01_raw_qc"),
    )
    assert result.outcome == "pass"


def test_the_right_step_plus_an_extra_one_fails():
    """Set equality, not containment: the budget is two, so an extra is not free."""
    result = evaluators.check_step_selection(
        {"expectedToolUse": True, "expectedStepIds": ["04_processing"]},
        _use("04_processing", "05_coverage_qc"),
    )
    assert result.outcome == "fail"
    assert "05_coverage_qc" in result.detail


def test_one_of_two_expected_steps_fails_and_says_which():
    result = evaluators.check_step_selection(
        {"expectedToolUse": True, "expectedStepIds": ["01_raw_qc", "04_processing"]},
        _use("01_raw_qc"),
    )
    assert result.outcome == "fail"
    assert "04_processing" in result.detail


def test_step_selection_is_not_run_when_no_tool_was_expected():
    """Nothing to judge. A pass here would be a check that cannot fail."""
    result = evaluators.check_step_selection(
        {"expectedToolUse": False, "expectedStepIds": []}, _use()
    )
    assert result.outcome == "not_run"


def test_tool_checks_only_run_for_cases_that_declare_them():
    """The four original cases must score exactly as they did before."""
    without = evaluators.run_expectations(
        {"case": "x", "mustCite": [], "humanReview": []},
        {},
        _ok(_synthesis()),
        {},
    )
    assert not [r for r in without.results if r.name.startswith("tool-")]

    with_tools = evaluators.run_expectations(
        {
            "case": "x",
            "expectedToolUse": True,
            "expectedStepIds": ["04_processing"],
            "mustCite": [],
            "humanReview": [],
        },
        {},
        _ok(_synthesis()),
        {},
        tool_use=_use("04_processing"),
    )
    outcomes = {r.name: r.outcome for r in with_tools.results}
    assert outcomes["tool-use"] == "pass"
    assert outcomes["tool-step-selection"] == "pass"


def test_tool_selection_is_still_scored_when_the_answer_was_discarded():
    """How the agent searched is knowable even when its answer was refused."""
    report = evaluators.run_expectations(
        {
            "case": "x",
            "expectedToolUse": True,
            "expectedStepIds": ["04_processing"],
            "mustCite": [],
            "humanReview": [],
        },
        {},
        {"available": False, "errorCategory": "unsupportedNumber", "synthesis": None},
        {},
        tool_use=_use("04_processing"),
    )
    outcomes = {r.name: r.outcome for r in report.results}
    assert outcomes["tool-use"] == "pass"
    assert outcomes["runtime-guardrails"] == "fail"


def test_a_skipped_agent_case_reports_tool_checks_as_not_run():
    report = evaluators.run_expectations(
        {
            "case": "x",
            "expectedToolUse": True,
            "expectedStepIds": ["04_processing"],
            "mustCite": [],
            "humanReview": [],
        },
        {},
        {"available": False, "errorCategory": None, "synthesis": None},
        {},
        model_invoked=False,
    )
    outcomes = {r.name: r.outcome for r in report.results}
    assert outcomes["tool-use"] == "not_run"
    assert outcomes["tool-step-selection"] == "not_run"
    assert outcomes["tool-step-core"] == "not_run"
    assert report.ok is True


# --- required / optional / forbidden ----------------------------------------


def test_bool_values_still_mean_required_and_forbidden():
    assert evaluators.tool_need({"expectedToolUse": True}) == "required"
    assert evaluators.tool_need({"expectedToolUse": False}) == "forbidden"


def test_the_string_forbidden_is_not_read_as_needing_the_tool():
    """The trap a truth test falls into: "forbidden" is a truthy string."""
    used = evaluators.check_tool_use({"expectedToolUse": "forbidden"}, _use("01_raw_qc"))
    unused = evaluators.check_tool_use({"expectedToolUse": "forbidden"}, _use())
    assert used.outcome == "fail"
    assert unused.outcome == "pass"
    assert evaluators.check_step_selection(
        {"expectedToolUse": "forbidden"}, _use()
    ).outcome == "not_run"


def test_the_string_required_scores_like_true():
    assert evaluators.check_tool_use(
        {"expectedToolUse": "required"}, _use()
    ).outcome == "fail"
    assert evaluators.check_tool_use(
        {"expectedToolUse": "required"}, _use("04_processing")
    ).outcome == "pass"


def test_an_unknown_tool_need_is_refused_not_guessed():
    for raw in ("either", "yes", None, 1):
        try:
            evaluators.tool_need({"expectedToolUse": raw})
        except ValueError:
            continue
        raise AssertionError(f"{raw!r} was accepted")


def test_optional_does_not_score_whether_the_tool_was_called():
    """Neither using nor not using it is a finding -- but it is recorded."""
    used = evaluators.check_tool_use({"expectedToolUse": "optional"}, _use("01_raw_qc"))
    unused = evaluators.check_tool_use({"expectedToolUse": "optional"}, _use())

    assert used.outcome == unused.outcome == "not_run"
    assert used.metrics == {"toolUsed": True}
    assert unused.metrics == {"toolUsed": False}
    assert "01_raw_qc" in used.detail


def test_optional_still_scores_which_steps_were_opened():
    """Free to skip the tool is not free to open the wrong step."""
    expectations = {"expectedToolUse": "optional", "acceptableStepSets": [["01_raw_qc"]]}

    assert evaluators.check_step_selection(expectations, _use()).outcome == "not_run"
    assert evaluators.check_step_selection(
        expectations, _use("01_raw_qc")
    ).outcome == "pass"
    wrong = evaluators.check_step_selection(expectations, _use("05_coverage_qc"))
    assert wrong.outcome == "fail"
    assert "05_coverage_qc" in wrong.detail


def test_optional_still_scores_the_answer_itself():
    """Only tool-use is exempt. An invented number and a missing citation fail."""
    report = evaluators.run_expectations(
        {
            "case": "x",
            "expectedToolUse": "optional",
            "acceptableStepSets": [["04_processing"]],
            "mustCite": [{"name": "cites-failure", "ref": "fail:markdup_validation"}],
            "humanReview": [{"name": "h", "question": "q"}],
        },
        {"status": "failed"},
        _ok(_synthesis(importantFindings=[_statement("값은 52,379입니다.", ["run:status"])])),
        {},
        tool_use=_use(),
    )
    outcomes = {r.name: r.outcome for r in report.results}

    assert outcomes["tool-use"] == "not_run"
    assert outcomes["numbers-preserved"] == "fail"
    assert outcomes["cites-failure"] == "fail"
    assert outcomes["h"] == "needs_review"
    assert report.ok is False


# --- acceptableStepSets, core steps, precision / recall ---------------------


_FAILED_SETS = {
    "expectedToolUse": "optional",
    "acceptableStepSets": [
        ["04_processing"],
        ["04_processing", "00_input_validation"],
    ],
}


def test_each_accepted_set_passes():
    for opened in (("04_processing",), ("00_input_validation", "04_processing")):
        result = evaluators.check_step_selection(_FAILED_SETS, _use(*opened))
        assert result.outcome == "pass", opened


def test_a_set_outside_the_accepted_list_fails():
    result = evaluators.check_step_selection(
        _FAILED_SETS, _use("04_processing", "05_coverage_qc")
    )
    assert result.outcome == "fail"
    assert "05_coverage_qc" in result.detail


def test_without_acceptable_sets_the_old_strict_rule_applies():
    """expectedStepIds alone is the single accepted set -- as before."""
    expectations = {"expectedToolUse": True, "expectedStepIds": ["04_processing"]}
    assert evaluators.acceptable_step_sets(expectations) == [frozenset({"04_processing"})]
    assert evaluators.check_step_selection(
        expectations, _use("04_processing", "00_input_validation")
    ).outcome == "fail"


def test_precision_and_recall_ride_along_without_deciding_the_outcome():
    """Core = in every accepted set (recall); allowed = in any (precision)."""
    extra = evaluators.check_step_selection(
        _FAILED_SETS, _use("04_processing", "05_coverage_qc")
    )
    assert extra.outcome == "fail"
    assert extra.metrics["coreStepIds"] == ["04_processing"]
    assert extra.metrics["allowedStepIds"] == ["00_input_validation", "04_processing"]
    assert extra.metrics["recall"] == 1.0
    assert extra.metrics["precision"] == 0.5

    missed = evaluators.check_step_selection(_FAILED_SETS, _use("00_input_validation"))
    assert missed.outcome == "fail"
    assert missed.metrics["recall"] == 0.0
    assert missed.metrics["precision"] == 1.0


def test_a_missing_core_step_is_recorded_on_its_own():
    """An extra step and a missed essential one both fail selection; only the
    second fails the core check."""
    extra = evaluators.check_step_core(_FAILED_SETS, _use("04_processing", "05_coverage_qc"))
    missed = evaluators.check_step_core(_FAILED_SETS, _use("00_input_validation"))

    assert extra.outcome == "pass"
    assert missed.outcome == "fail"
    assert "04_processing" in missed.detail


def test_core_is_not_run_when_nothing_is_essential():
    """A case that accepts the empty selection has no core step."""
    result = evaluators.check_step_core(
        {"expectedToolUse": "optional", "acceptableStepSets": [[], ["05_coverage_qc"]]},
        _use("05_coverage_qc"),
    )
    assert result.outcome == "not_run"


def test_selection_metrics_reach_the_json_record_only_where_they_exist():
    report = evaluators.run_expectations(
        {**_FAILED_SETS, "case": "x", "mustCite": [], "humanReview": []},
        {},
        _ok(_synthesis()),
        {},
        tool_use=_use("04_processing"),
    )
    rows = {row["name"]: row for row in report.to_json()["results"]}

    assert rows["tool-step-selection"]["metrics"]["recall"] == 1.0
    assert rows["tool-step-core"]["outcome"] == "pass"
    assert "metrics" not in rows["runtime-guardrails"]


def test_the_shipped_agent_expectations_name_steps_the_case_actually_plans():
    """An expected step that the run never planned could never be opened."""
    from . import agent_cases

    for key, case in agent_cases.CASES.items():
        expectations = json.loads(
            (EXPECTATIONS / f"{key}.json").read_text(encoding="utf-8")
        )
        assert expectations["case"] == key
        need = evaluators.tool_need(expectations)
        for steps in evaluators.acceptable_step_sets(expectations):
            for step_id in steps:
                assert step_id in case.planned, (key, step_id)
        if need == "forbidden":
            # Not a truth test: the string "forbidden" is truthy.
            assert "acceptableStepSets" not in expectations, key
            assert not expectations.get("expectedStepIds"), key


# --- the agent cases are what their expectations claim -----------------------
#
# No model. The run is built, the deterministic explanation is derived from it,
# and the expectation is checked against that -- so "the right step" is a fact
# of the case rather than something someone picked.


def test_agent_case_evidence_anchors_the_expected_step():
    from . import agent_cases

    for key, case in agent_cases.CASES.items():
        expectations = json.loads(
            (EXPECTATIONS / f"{key}.json").read_text(encoding="utf-8")
        )
        with agent_cases.materialise(case) as explanation:
            anchored = {
                item.actualStepId
                for item in (*explanation.diagnostics, *explanation.failures)
                if item.actualStepId
            }
            if evaluators.tool_need(expectations) != "forbidden":
                # The step every accepted answer contains is the step this run
                # recorded its problem in -- not a preference.
                sets = evaluators.acceptable_step_sets(expectations)
                core = frozenset.intersection(*sets)
                assert anchored == set(core), key
            else:
                # Nothing to investigate is why no call is expected.
                assert not anchored, key
                assert not explanation.checkSummary.notable, key


def test_the_agent_cases_offer_a_step_list_to_choose_from():
    """Without it the model cannot name a step id at all."""
    from app.services.explanation.llm import contract

    from . import agent_cases

    case = agent_cases.CASES["agent_failed_step"]
    with agent_cases.materialise(case) as explanation:
        payload, allowed = contract.build_payload(explanation)

    assert [row["stepId"] for row in payload["steps"]["planned"]] == list(case.planned)
    assert "run:steps" in allowed


def test_agent_case_citations_are_ids_the_initial_payload_mints():
    """A required citation must be answerable without the tool.

    Otherwise an `optional` case would quietly require it. Being citable is
    all this proves -- whether a sentence citing it is right stays with the
    human review.
    """
    from app.services.explanation.llm import contract

    from . import agent_cases

    for key, case in agent_cases.CASES.items():
        expectations = json.loads(
            (EXPECTATIONS / f"{key}.json").read_text(encoding="utf-8")
        )
        with agent_cases.materialise(case) as explanation:
            _payload, allowed = contract.build_payload(explanation)
        for spec in expectations.get("mustCite", []):
            assert spec["ref"] in allowed, (key, spec["ref"])
            assert not spec["ref"].startswith("step:"), (key, spec["ref"])


def test_the_agent_cases_keep_the_sample_name_out_of_the_payload():
    from . import agent_cases, run_eval

    for case in agent_cases.CASES.values():
        with agent_cases.materialise(case) as explanation:
            result = run_eval.privacy_check(explanation.model_dump())
        assert result.outcome == "pass", (case.name, result.detail)


def test_a_number_the_tool_returned_is_not_counted_as_invented():
    """Found by the first live agent eval: 18.4 came back from the step.

    The runtime scores against payload + tool results and accepted it. The eval
    scored against the fixture alone and called it invented -- a false failure
    that would have trained us to distrust a correct answer.
    """
    statements = ["중복률은 18.4%였습니다."]
    fixture = {"status": "failed"}
    fetched = [{"evidenceId": "step:04_processing", "metrics": {"percent_duplication": 18.4}}]

    assert evaluators.check_numbers(statements, fixture).outcome == "fail"

    report = evaluators.run_expectations(
        {
            "case": "x",
            "expectedToolUse": True,
            "expectedStepIds": ["04_processing"],
            "mustCite": [],
            "humanReview": [],
        },
        fixture,
        _ok(_synthesis(importantFindings=[_statement(statements[0], ["step:04_processing"])])),
        {},
        tool_use=_use("04_processing"),
        fetched_facts=fetched,
    )
    outcomes = {r.name: r.outcome for r in report.results}
    assert outcomes["numbers-preserved"] == "pass"


def test_the_four_frozen_cases_keep_the_fixture_as_their_fact_source():
    """No fetched facts, no change: their baselines stay comparable."""
    report = evaluators.run_expectations(
        {"case": "x", "mustCite": [], "humanReview": []},
        {"status": "failed"},
        _ok(_synthesis(importantFindings=[_statement("중복률은 18.4%였습니다.", ["run:status"])])),
        {},
    )
    outcomes = {r.name: r.outcome for r in report.results}
    assert outcomes["numbers-preserved"] == "fail"


# --- V1 (tool withheld) and V3 (the agent) ----------------------------------
#
# The variant toggle is scored and recorded here; that the runtime withholds
# both halves of the tool is tested in app/tests/test_tool_toggle.py. Nothing
# below calls a model: `build_run_synthesis` is replaced wherever run_eval
# would reach it.


_AGENT_EXPECTATIONS = {
    "case": "x",
    "expectedToolUse": "forbidden",
    "mustCite": [{"name": "cites-status", "ref": "run:status"}],
    "humanReview": [],
}


def test_without_the_tool_the_tool_checks_are_not_run():
    """A `forbidden` case must not pass for a model that never had the choice."""
    report = evaluators.run_expectations(
        _AGENT_EXPECTATIONS,
        {},
        _ok(_synthesis(importantFindings=[_statement("끝났습니다.", ["run:status"])])),
        {},
        tool_use=_use(),
        tools_offered=False,
    )
    rows = {r.name: r for r in report.results}

    for name in ("tool-use", "tool-step-selection", "tool-step-core"):
        assert rows[name].outcome == "not_run"
        assert rows[name].detail == "Tool 미제공 variant"
    assert rows["cites-status"].outcome == "pass"
    assert report.ok is True


def test_without_the_tool_the_answer_is_still_scored():
    report = evaluators.run_expectations(
        _AGENT_EXPECTATIONS,
        {"status": "completed"},
        _ok(_synthesis(importantFindings=[_statement("값은 52,379입니다.", ["run:other"])])),
        {},
        tool_use=_use(),
        tools_offered=False,
    )
    outcomes = {r.name: r.outcome for r in report.results}

    assert outcomes["numbers-preserved"] == "fail"
    assert outcomes["cites-status"] == "fail"
    assert report.ok is False


def test_with_the_tool_scoring_is_what_it_was():
    """tools_offered defaults to True: V3 scores exactly as before."""
    default = evaluators.run_expectations(
        _AGENT_EXPECTATIONS, {}, _ok(_synthesis()), {}, tool_use=_use("04_processing")
    )
    explicit = evaluators.run_expectations(
        _AGENT_EXPECTATIONS,
        {},
        _ok(_synthesis()),
        {},
        tool_use=_use("04_processing"),
        tools_offered=True,
    )

    assert default.to_json() == explicit.to_json()
    assert {r.name: r.outcome for r in default.results}["tool-use"] == "fail"


def test_without_the_tool_frozen_cases_score_unchanged():
    """No expectedToolUse, no tool rows -- in either variant."""
    expectations = {"case": "x", "mustCite": [], "humanReview": []}
    v1 = evaluators.run_expectations(
        expectations, {}, _ok(_synthesis()), {}, tools_offered=False
    )
    v3 = evaluators.run_expectations(expectations, {}, _ok(_synthesis()), {})

    assert v1.to_json() == v3.to_json()


def _fake_synthesis(calls: list):
    """Stands in for build_run_synthesis and records how it was asked."""
    from app.services.explanation.llm import synthesis

    def fake(explanation, **kwargs):
        calls.append(kwargs)
        return synthesis.SynthesisResult(available=False, errorCategory="timeout")

    return fake


def test_a_frozen_case_records_its_variant_and_the_prompt_it_sent(monkeypatch):
    from app.services.explanation.llm import prompt

    from . import run_eval

    calls: list = []
    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", _fake_synthesis(calls))

    v1 = run_eval.evaluate("execution_failed", variant="v1")
    v3 = run_eval.evaluate("execution_failed")

    assert [c["offer_tools"] for c in calls] == [False, True]
    assert (v1["variant"], v1["toolsOffered"]) == ("v1", False)
    assert (v3["variant"], v3["toolsOffered"]) == ("v3", True)
    assert v1["promptHash"] == run_eval._hash(prompt.CONSTRAINTS_NO_TOOL)
    assert v3["promptHash"] == run_eval._hash(prompt.CONSTRAINTS) == "110c63124b4325fc"


def test_an_agent_case_passes_the_variant_to_both_runtime_and_scoring(monkeypatch):
    from . import run_eval

    calls: list = []
    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", _fake_synthesis(calls))

    record = run_eval.evaluate_agent("agent_no_tool_needed", variant="v1")

    assert calls[0]["offer_tools"] is False
    assert record["variant"] == "v1"
    rows = {r["name"]: r for r in record["evaluation"]["results"]}
    assert rows["tool-use"]["outcome"] == "not_run"
    assert rows["tool-use"]["detail"] == "Tool 미제공 variant"


def test_the_variant_defaults_to_v3():
    import inspect

    from . import run_eval

    assert run_eval.DEFAULT_VARIANT == "v3"
    for fn in (run_eval.evaluate, run_eval.evaluate_agent):
        assert inspect.signature(fn).parameters["variant"].default == "v3"


def test_baseline_names_carry_the_variant():
    from . import run_eval

    v1 = run_eval.baseline_path("agent_failed_step", "v1", "2026-11-02")
    v3 = run_eval.baseline_path("agent_failed_step", "v3", "2026-11-02")

    assert v1 != v3
    assert v1.name.startswith("2026-11-02_agent_failed_step_v1_")
    assert v3.name.startswith("2026-11-02_agent_failed_step_v3_")
    assert v1.name.endswith(f"_{run_eval._prompt_hash('v1')}.json")
    assert v3.name.endswith("_110c63124b4325fc.json")


def test_an_existing_baseline_is_never_overwritten(tmp_path):
    from . import run_eval

    path = tmp_path / "existing.json"
    path.write_text("original\n", encoding="utf-8")

    try:
        run_eval.write_baseline(path, {"case": "x"})
    except FileExistsError:
        pass
    else:
        raise AssertionError("an existing baseline was replaced")
    assert path.read_text(encoding="utf-8") == "original\n"


def test_a_name_collision_stops_before_any_model_call(tmp_path, monkeypatch, capsys):
    import sys

    from . import run_eval

    def must_not_call(*_args, **_kwargs):
        raise AssertionError("the model would have been called")

    monkeypatch.setattr(run_eval, "BASELINES", tmp_path)
    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", must_not_call)
    stamp = run_eval.datetime.now(run_eval.timezone.utc).strftime("%Y-%m-%d")
    taken = run_eval.baseline_path("agent_failed_step", "v1", stamp)
    taken.write_text("kept\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_eval", "--case", "agentfail", "--variant", "v1", "--record-baseline", "--yes"],
    )

    assert run_eval.main() == 2
    assert taken.read_text(encoding="utf-8") == "kept\n"
    assert "호출하지 않았습니다" in capsys.readouterr().out
