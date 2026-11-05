"""Gates 6 and 7: a sentence against the structured fact it is about.

Before these gates, every case marked "used to pass" below was served: the
number gate asks only whether a digit string is somewhere in the payload, and
the evidence gate asks only whether a cited id is one the payload supplied.

Two layers of test:

  through build_run_synthesis   the gates are wired in, in order, with the
                                curated message; the fixture is the finished
                                full run every synthesis test uses
  claims.* on a real-shaped     each rule, on the values of the real run
  payload                       cba73e (mean depth 11.0116, 0x 9.2905 %, three
                                warning steps, dbSNP not configured)

What a correct answer looks like is tested as much as what a wrong one does:
a rule that blocks a correct sentence is a defect, not extra safety.
"""

from __future__ import annotations

import pytest

from app.services.explanation import deterministic, run_context
from app.services.explanation.llm import claims, provider
from app.services.explanation.llm import synthesis as llm_synthesis

from .test_tool_using_synthesis import FULL_PLAN, JOB_ID


@pytest.fixture
def explanation(client, make_job, run):
    """The finished full run: mean depth 85.2, 5.8 % of bases in low-depth
    intervals, 48,210 raw variant records, no step ended with a warning."""
    job = make_job(JOB_ID, run_mode="full", planned=FULL_PLAN, sample_id="DEMO01")
    run(job).as_completed_full()
    context = run_context.build_run_diagnostic_context(job)
    return deterministic.build_run_explanation(context)


def _answer(*items: tuple[str, list[str]], summary: str = "실행이 끝났습니다.") -> dict:
    return {
        "summary": summary,
        "importantFindings": [{"statement": s, "evidenceRefs": r} for s, r in items],
        "limitations": [
            {"statement": "변이 결과는 필터가 적용되지 않은 후보 기록입니다.",
             "evidenceRefs": ["lim:UNFILTERED_VARIANTS"]}
        ],
        "nextChecks": [],
        "uncertainties": [],
    }


def _serve(explanation, answer: dict):
    def fake(**_ignored):
        return provider.ProviderResult(payload=answer, models=["test-model"])

    return llm_synthesis.build_run_synthesis(explanation, run_provider=fake, repair=False)


# --- wired in: what used to be served is now discarded ----------------------


@pytest.mark.parametrize(
    "statement, refs",
    [
        # 5.8 is in the payload -- as the share of bases in low-depth intervals.
        ("평균 깊이는 5.8배입니다.", ["run:coverage"]),
        ("한 번도 읽히지 않은 염기는 5.8%입니다.", ["run:coverage"]),
        # 12 was let through as a small ordinal.
        ("변이 후보 기록은 12개입니다.", ["run:variantCalling", "lim:UNFILTERED_VARIANTS"]),
        # No step of this run ended with a warning.
        ("세 단계에서 경고가 기록됐습니다.", ["run:steps"]),
    ],
)
def test_a_statement_contradicting_a_run_fact_is_discarded(explanation, statement, refs):
    result = _serve(explanation, _answer((statement, refs)))
    assert result.available is False
    assert result.errorCategory == "runFactMismatch"
    assert result.errorMessage == llm_synthesis._SAFE_MESSAGES["runFactMismatch"]


def test_a_variant_count_with_its_qualification_cited_nowhere_is_discarded(explanation):
    answer = _answer(("변이 후보 기록은 48,210개입니다.", ["run:variantCalling"]))
    answer["limitations"] = []
    result = _serve(explanation, answer)
    assert result.available is False
    assert result.errorCategory == "evidenceMismatch"


def test_the_same_facts_written_correctly_are_served(explanation):
    answer = _answer(
        ("평균 깊이는 85.2배입니다.", ["run:coverage"]),
        ("한 번도 읽히지 않은 염기는 0.9%, 311,111개입니다.", ["run:coverage"]),
        ("변이 후보 기록은 48,210개이며 확정된 변이가 아닙니다.",
         ["run:variantCalling", "lim:UNFILTERED_VARIANTS"]),
        ("평균 깊이가 20배 미만인 구간의 염기는 5.8%입니다.", ["run:coverage"]),
        ("경고로 끝난 단계는 없습니다.", ["run:steps"]),
    )
    result = _serve(explanation, answer)
    assert result.available is True, result.errorCategory


def test_the_new_gates_run_after_the_old_ones(explanation):
    # An invented number and a contradiction: the category is the old one, so
    # a rejection reported before these gates is reported the same way now.
    answer = _answer(("평균 깊이는 999배입니다.", ["run:coverage"]))
    assert _serve(explanation, answer).errorCategory == "unsupportedNumber"


# --- the rules, on the values of the real run cba73e -------------------------

ALLOWED = {
    "run:status", "run:steps", "run:coverage", "run:variantCalling",
    "dx:ZERO_COVERAGE_TARGET_BASES", "dx:NM_MD_REPAIRED", "dx:DBSNP_NOT_CONFIGURED",
    "lim:UNFILTERED_VARIANTS", "term:dbsnp-rsid", "term:nm-md-tags",
    "src:main-sh-dbsnp", "src:sam-tags-spec",
}

PAYLOAD = {
    "steps": {
        "evidenceId": "run:steps",
        "planned": [
            {"stepId": "00_input_validation", "status": "completed", "elapsedSeconds": 35},
            {"stepId": "01_raw_qc", "status": "completed", "elapsedSeconds": 63},
            {"stepId": "02_preprocessing", "status": "completed", "elapsedSeconds": 0},
            {"stepId": "03_alignment", "status": "completed", "elapsedSeconds": 1675},
            {"stepId": "04_processing", "status": "warning", "elapsedSeconds": 1118},
            {"stepId": "05_coverage_qc", "status": "warning", "elapsedSeconds": 85},
            {"stepId": "06_variant_calling", "status": "warning", "elapsedSeconds": 1420},
            {"stepId": "99_finalization", "status": "completed", "elapsedSeconds": 2},
        ],
    },
    "coverage": {
        "evidenceId": "run:coverage",
        "meanTargetDepth": 11.0116,
        "zeroCoverageBases": 3387168,
        "zeroCoverageBasesPct": 9.2905,
        "lowMeanDepthThresholdX": 20.0,
        "basesInLowMeanDepthIntervalsPct": 89.7873,
        "basesInFullyUncoveredIntervalsPct": 7.241,
    },
    "variantCalling": {
        "evidenceId": "run:variantCalling",
        "rawVariantRecords": 52294,
        "filteringApplied": False,
    },
    "grounding": {
        "dx:DBSNP_NOT_CONFIGURED": {"scope": [{"statement": "-", "sourceIds": ["main-sh-dbsnp"]}]},
        "dx:NM_MD_REPAIRED": {"scope": [{"statement": "-", "sourceIds": ["sam-tags-spec"]}]},
    },
    "terms": [
        {"evidenceId": "term:dbsnp-rsid", "definition": {"sourceIds": []}},
        {"evidenceId": "term:nm-md-tags", "definition": {"sourceIds": []}},
    ],
}


def _one(statement: str, refs: list[str], *, where: str = "importantFindings") -> dict:
    answer = {"summary": "끝났습니다.", "importantFindings": [], "limitations": [],
              "nextChecks": [], "uncertainties": []}
    if where == "summary":
        answer["summary"] = statement
    else:
        answer[where] = [{"statement": statement, "evidenceRefs": refs}]
    # The variant-count qualification is cited, so only the rule under test fires.
    answer["limitations"].append(
        {"statement": "필터 미적용 후보입니다.", "evidenceRefs": ["lim:UNFILTERED_VARIANTS"]}
    )
    return answer


def _facts(answer: dict) -> list[dict]:
    return claims.find_run_fact_mismatches(answer, PAYLOAD)


def _evidence(answer: dict) -> list[dict]:
    return claims.find_evidence_mismatches(answer, PAYLOAD, ALLOWED)


@pytest.mark.parametrize(
    "statement",
    [
        "평균 깊이는 1420배입니다.",          # a step's elapsed seconds
        "평균 깊이는 20배입니다.",            # the low-depth threshold
        "평균 깊이는 약 11배입니다.",         # rounded: the prompt forbids it
        "0배 base는 89.7873%입니다.",        # low-depth-interval share
        "한 번도 읽히지 않은 염기는 7.241%입니다.",  # interval-level figure as base-level
        "변이 후보 기록은 12개입니다.",
    ],
)
def test_a_measurement_carrying_another_value_is_found(statement):
    found = _facts(_one(statement, ["run:coverage"]))
    assert [f["location"] for f in found] == ["importantFindings.0"]


@pytest.mark.parametrize(
    "statement",
    [
        "평균 깊이는 11.0116배입니다.",
        "평균 깊이는 11.01160X입니다.",
        "0× 위치는 9.2905%, 3,387,168개입니다.",
        "읽은 기록이 한 번도 없는 위치가 염기 단위(구간 단위가 아니라 위치를 하나씩 센 값)로 9.2905%입니다.",
        "변이 후보 기록은 52,294개입니다.",
        "평균 깊이가 0보다 커도 한 번도 읽히지 않은 위치가 있을 수 있습니다.",
        "평균 깊이가 20배 미만인 구간의 염기는 89.7873%입니다.",
        "평균 깊이 20.0X(기준값) 미만인 구간이 있습니다.",
        "한 번도 읽히지 않은 구간에 속한 염기는 7.241%입니다.",
        "10X 이상 읽힌 위치는 51.6134%입니다.",
        "11.0116배라는 평균 깊이나 0× 비율이 충분한지는 판단할 수 없습니다.",
        "구간별 평균 깊이는 산출물에 있습니다.",
    ],
)
def test_a_measurement_written_correctly_or_not_at_all_is_not_found(statement):
    assert _facts(_one(statement, ["run:coverage"])) == []


@pytest.mark.parametrize(
    "statement, where",
    [
        ("경고 단계는 5개입니다.", "importantFindings"),
        ("12개 단계에서 경고가 기록됐습니다.", "importantFindings"),
        ("다섯 단계에서 경고가 기록됐습니다.", "summary"),
        ("이 실행은 경고 없이 완료됐습니다.", "summary"),
        ("경고는 없었습니다.", "importantFindings"),
        ("참조 유전체 정렬 단계에서 경고가 발생했습니다.", "importantFindings"),
        ("경고가 기록된 단계는 입력 검증, 커버리지 검사, 변이 검출입니다.", "importantFindings"),
    ],
)
def test_a_wrong_warning_step_claim_is_found(statement, where):
    found = _facts(_one(statement, ["run:steps"], where=where))
    expected = "summary" if where == "summary" else "importantFindings.0"
    assert [f["location"] for f in found] == [expected]


@pytest.mark.parametrize(
    "statement",
    [
        "세 단계에서 경고가 기록됐습니다.",
        "3개 단계가 경고로 끝났습니다.",
        "경고로 끝난 단계는 모두 3개 단계이며, BAM 정리·보정 단계, 커버리지 검사 단계, 변이 검출 단계입니다.",
        "경고가 기록된 단계는 BAM 정리·보정, 커버리지 검사, 변이 검출의 3단계입니다.",
        "8단계가 모두 끝났고, 그중 3단계에서 경고가 기록됐습니다.",
        "정렬 단계는 경고 없이 끝났습니다.",
        "경고가 없다는 뜻은 아닙니다.",
        "경고가 기록된 단계는 BAM 정리·보정, 커버리지 검사, 변이 검출이고 나머지 입력 검증 등은 정상입니다.",
    ],
)
def test_a_correct_warning_step_claim_is_not_found(statement):
    assert _facts(_one(statement, ["run:steps"])) == []


@pytest.mark.parametrize(
    "statement, refs",
    [
        ("dbSNP가 설정되지 않아 rsID가 없습니다.", ["run:coverage"]),
        ("NM/MD 태그가 자동 보정됐습니다.", ["run:coverage"]),
    ],
)
def test_a_diagnostic_topic_citing_unrelated_evidence_is_found(statement, refs):
    assert [f["location"] for f in _evidence(_one(statement, refs))] == ["importantFindings.0"]


@pytest.mark.parametrize(
    "statement, refs",
    [
        ("dbSNP가 설정되지 않았습니다.", ["dx:DBSNP_NOT_CONFIGURED"]),
        ("rsID는 공개 식별 번호입니다.", ["term:dbsnp-rsid"]),
        ("NM/MD 태그는 SAM 명세의 보조 태그입니다.", ["src:sam-tags-spec"]),
        # "BAM" inside a step label is the step, not a topic.
        ("경고가 기록된 단계는 BAM 정리·보정입니다.", ["run:steps"]),
    ],
)
def test_a_diagnostic_topic_citing_its_own_evidence_is_not_found(statement, refs):
    assert _evidence(_one(statement, refs)) == []


def test_the_summary_is_not_read_for_citations():
    # It carries no evidenceRefs by design, so there is nothing to compare.
    assert _evidence(_one("dbSNP가 설정되지 않았습니다.", [], where="summary")) == []


def test_a_qualified_fact_with_its_qualification_cited_anywhere_is_not_found():
    # The real B_r2 shape: one statement cites only the count's section, the
    # qualification is cited by another. Correct, and not blocked at runtime.
    answer = _one("52,294개 후보 기록 중 확정될 변이 수는 데이터에 없습니다.",
                  ["run:variantCalling"], where="uncertainties")
    assert _evidence(answer) == []


def test_a_qualified_fact_with_its_qualification_cited_nowhere_is_found_where_stated():
    answer = _one("변이 후보 기록은 52,294개입니다.", ["run:variantCalling"])
    answer["limitations"] = []
    answer["summary"] = "변이 후보 기록 52,294개가 나왔습니다."
    assert sorted(f["location"] for f in _evidence(answer)) == ["importantFindings.0", "summary"]


def test_a_run_without_the_section_has_no_rule():
    answer = _one("평균 깊이는 1420배입니다. 경고 단계는 5개입니다.", ["run:coverage"])
    assert claims.find_run_fact_mismatches(answer, {}) == []
    assert claims.find_evidence_mismatches(answer, {}, ALLOWED) == []
