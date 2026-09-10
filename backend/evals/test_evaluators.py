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


# --- the shipped cases are self-consistent -----------------------------------


def test_shipped_expectations_reference_ids_the_payload_can_mint():
    """An expectation citing an id `build_payload` never issues can never pass.

    Checked against the fixture, so a knowledge or payload change that stops
    issuing an id is caught here -- for free, with no model call.
    """
    from app.services.explanation.deterministic import RunExplanation
    from app.services.explanation.llm import contract

    for name in ("full_completed_with_warnings", "precheck_failed"):
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
    for name in ("full_completed_with_warnings", "precheck_failed"):
        blob = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
        for forbidden in ("SRR2962669", "/home/", "vboxuser", "wes-2026"):
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
