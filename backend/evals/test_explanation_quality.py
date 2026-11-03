"""The explanation-quality checker: its rules, its separation, and its labels.

    .venv/Scripts/python.exe -m pytest evals/test_explanation_quality.py

No model is called. Stored baselines are only read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import config
from app.services.explanation import knowledge

from . import evaluators, explanation_quality as q, real_runs

BASELINES = Path(__file__).resolve().parent / "baselines"
DAY2 = "2026-11-02_real_cba73e_v3_sonnet_d505c173885f6c9b.json"
DAY3 = "2026-11-02_real_cba73e_v3_sonnet_08c1f9035445420a.json"


def _answer(*statements: str, summary: str | None = None) -> dict:
    out: dict = {"importantFindings": [{"statement": s, "evidenceRefs": []} for s in statements]}
    if summary is not None:
        out["summary"] = summary
    return out


def _terms(synthesis: dict, required: set[str], checked: set[str] | None = None) -> q.QualityReport:
    return q.evaluate(
        synthesis,
        required=required,
        checked=checked or set(required),
        required_source="test",
        facts=None,
    )


def _term(report: q.QualityReport, unit: str, term: str) -> q.Finding:
    finding = report.find("term", unit, term)
    assert finding is not None, (unit, term, [f.to_json() for f in report.findings])
    return finding


F0 = "importantFindings[0]"
F1 = "importantFindings[1]"


# --- lexicon is tied to the knowledge, not a second glossary -----------------


def test_every_lexicon_term_is_a_registered_term():
    known = {t.id for t in knowledge.all_terms()}
    lexicon = q.load_lexicon()
    assert {r.termId for r in lexicon.terms} == known


def test_every_spelling_the_knowledge_registers_is_recognised():
    """A label, alias or mention in wes_terms.json that the checker cannot see
    would let that spelling through as 'term not used'."""
    lexicon = {r.termId: r for r in q.load_lexicon().terms}
    for term in knowledge.all_terms():
        rules = lexicon[term.id]
        surfaces = q.surface_pattern(s for g in rules.groups for s in g.surfaces)
        substitutes = [*rules.plainSubstitutes, *rules.reviewSubstitutes]
        for spelling in [term.label, *term.aliases, *term.mentions]:
            seen = surfaces.search(spelling) or any(re.search(p, spelling) for p in substitutes)
            assert seen, f"{term.id}: {spelling!r} is not recognised"


def test_every_rule_compiles():
    lexicon = q.load_lexicon()
    for rules in lexicon.terms:
        for pattern in [*rules.plainSubstitutes, *rules.reviewSubstitutes]:
            re.compile(pattern)
        for group in rules.groups:
            for pattern in group.accept:
                re.compile(pattern)
            for rule in group.reject:
                re.compile(rule.pattern)
                if rule.unless:
                    re.compile(rule.unless)
    for p in lexicon.internalPatterns:
        re.compile(p.regex)


# --- A. terms: the five situations the task names -----------------------------


def test_a_term_with_a_correct_bracket_explanation_passes():
    report = _terms(_answer("read(시퀀싱으로 읽은 짧은 DNA 조각)가 덮지 않은 위치입니다."), {"read"})
    assert _term(report, F0, "read").verdict == "PASS"


def test_an_explanation_before_the_bracketed_term_passes():
    report = _terms(_answer("read가 한 번도 덮지 않은(0×) 염기입니다."), {"zero-coverage"})
    assert _term(report, F0, "zero-coverage").verdict == "PASS"


def test_a_sentence_that_defines_the_term_passes():
    report = _terms(
        _answer("한 위치를 read가 몇 번 겹쳐 덮었는지를 깊이라고 하며, 평균 깊이는 11.0116배입니다."),
        {"depth"},
    )
    assert _term(report, F0, "depth").verdict == "PASS"


def test_plain_words_without_the_term_pass():
    report = _terms(_answer("target 안에서 한 번도 덮이지 않은 염기가 있습니다."), {"zero-coverage"})
    finding = _term(report, F0, "zero-coverage")
    assert (finding.verdict, finding.rule) == ("PASS", "conveyed_plain")


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("평균 깊이(target 염기 중 덮인 비율)는 11.0116배입니다.", "depth"),
        ("read(유전자 하나를 읽은 결과)입니다.", "read"),
        ("0×(그 위치에 변이가 없다는 뜻) 염기입니다.", "zero-coverage"),
        ("rsID(변이가 검출되었는지 표시하는 값)가 비어 있습니다.", "dbsnp-rsid"),
        ("target(유전체 전체)에서 계산했습니다.", "target"),
    ],
)
def test_an_explanation_that_states_a_misreading_fails(text, term):
    finding = _term(_terms(_answer(text), {term}), F0, term)
    assert (finding.verdict, finding.rule) == ("FAIL", "inaccurate_gloss")


def test_a_correct_explanation_written_as_a_negation_is_not_called_wrong():
    """The reject cue sits inside a negation. Not FAIL -- but not provably
    right either, so it goes to a person."""
    report = _terms(_answer("0×(변이가 없다는 뜻이 아니라 읽힌 근거가 없는 위치)입니다."), {"zero-coverage"})
    assert _term(report, F0, "zero-coverage").verdict == "REVIEW"


def test_a_misreading_outside_the_bracket_is_not_read_as_the_explanation():
    """'변이가 없다는 뜻은 아닙니다' is the correct warning, in the sentence."""
    report = _terms(
        _answer("read가 한 번도 덮지 않은(0×) 위치에 변이가 없다는 뜻은 아닙니다."), {"zero-coverage"}
    )
    assert _term(report, F0, "zero-coverage").verdict == "PASS"


def test_an_unknown_bracket_explanation_is_review_not_pass():
    report = _terms(_answer("깊이(커버리지의 세기)는 평균 11.0116배입니다."), {"depth"})
    finding = _term(report, F0, "depth")
    assert (finding.verdict, finding.rule) == ("REVIEW", "gloss_unverified")


def test_a_required_term_explained_nowhere_fails():
    report = _terms(_answer("평균 깊이는 11.0116배입니다.", "깊이 중앙값은 없습니다."), {"depth"})
    assert {_term(report, u, "depth").rule for u in (F0, F1)} == {"never_explained"}
    assert report.terms[0].verdict == "FAIL"


def test_a_term_explained_in_another_statement_is_review_not_fail():
    """The same bracket is not demanded at every occurrence (task 3-A)."""
    report = _terms(
        _answer("read(시퀀싱으로 읽은 짧은 DNA 조각)가 덮지 않았습니다.", "read 서열은 그대로입니다."),
        {"read"},
    )
    assert _term(report, F0, "read").verdict == "PASS"
    finding = _term(report, F1, "read")
    assert (finding.verdict, finding.rule) == ("REVIEW", "explained_elsewhere")


def test_an_unverified_definition_elsewhere_blocks_never_explained():
    """Found on a held-out baseline: depth was defined in words the cues did
    not know, and every other statement was then FAILed as never explained.

    Pinned to v1: v2 added this wording to the depth cues (HR09), so under v2
    the same sentence is an explanation -- asserted at the end."""
    answer = _answer("깊이는 한 위치를 읽은 서열이 평균 몇 번 겹치는지를 뜻합니다.", "깊이 중앙값은 없습니다.")
    report = q.evaluate(answer, required={"depth"}, checked={"depth"}, required_source="test",
                        facts=None, lexicon=q.load_lexicon("1"))
    assert _term(report, F0, "depth").rule == "possible_definition"
    finding = _term(report, F1, "depth")
    assert (finding.verdict, finding.rule) == ("REVIEW", "possibly_explained_elsewhere")
    v2 = _terms(answer, {"depth"})
    assert _term(v2, F0, "depth").rule == "explained"
    assert _term(v2, F1, "depth").rule == "explained_elsewhere"


def test_an_unexplained_term_that_is_not_required_is_never_fail():
    report = _terms(_answer("BAM 검증 결과를 봅니다."), required=set(), checked={"bam"})
    finding = _term(report, F0, "bam")
    assert (finding.verdict, finding.rule) == ("REVIEW", "unexplained_not_required")


def test_a_wrong_explanation_fails_even_for_a_term_that_is_not_required():
    report = _terms(_answer("BAM(변이 목록 파일)을 봅니다."), required=set(), checked={"bam"})
    assert _term(report, F0, "bam").verdict == "FAIL"


def test_a_required_term_never_used_is_review_not_pass():
    report = _terms(_answer("결과는 후보 기록입니다."), {"depth"})
    summary = report.terms[0]
    assert (summary.verdict, summary.rule) == ("REVIEW", "not_used")
    assert report.find("term", F0, "depth") is None


def test_a_step_name_is_not_a_use_of_the_term():
    """'BAM 정리·보정' is how the screen names step 04."""
    label = knowledge.step("04_processing")
    assert label is not None and "BAM" in label.label
    report = _terms(_answer(f"{label.label} 단계에서 경고가 났습니다."), required=set(), checked={"bam"})
    assert report.find("term", F0, "bam") is None


@pytest.mark.parametrize("text", ["20× 이상", "10X 기준", "20배 이상", "1.0× 이상"])
def test_a_depth_threshold_is_not_zero_coverage(text):
    report = _terms(_answer(f"{text}으로 덮인 염기 비율입니다."), {"zero-coverage"})
    assert report.find("term", F0, "zero-coverage") is None


def test_a_config_key_is_not_the_dbsnp_term():
    report = _terms(_answer("관리자가 dbsnp_vcf를 선언합니다."), {"dbsnp-rsid"})
    assert report.find("term", F0, "dbsnp-rsid") is None


def test_each_part_of_a_two_word_term_is_judged_separately():
    """d505: rsID explained, dbSNP not -- the unit is not explained."""
    report = _terms(_answer("공개 식별자인 rsID가 없습니다. dbSNP 파일이 없기 때문입니다."), {"dbsnp-rsid"})
    finding = _term(report, F0, "dbsnp-rsid")
    assert finding.verdict == "FAIL" and "dbSNP" in finding.detail


# --- B. internal expressions --------------------------------------------------


def _internal(text: str) -> dict[str, q.Finding]:
    report = q.evaluate(_answer(text), required=set(), checked=set(), required_source="t", facts=None)
    return {f.subject: f for f in report.findings if f.category == "internal"}


def test_a_server_path_fails_even_inside_a_korean_explanation():
    found = _internal("검증 보고서(00_input_validation/resource_validation.txt)를 봅니다.")
    assert found["server-path:00_input_validation/resource_validation.txt"].verdict == "FAIL"
    assert not any(s.startswith("step-id:") for s in found), "the path's step id is one finding"


def test_a_step_id_fails_and_is_not_downgraded():
    found = _internal("BAM 정리·보정(step_04_processing) 단계입니다.")
    assert found["step-id:step_04_processing"].verdict == "FAIL"


def test_a_config_key_fails_bare_and_is_review_with_a_korean_explanation():
    assert _internal("관리자가 dbsnp_vcf를 선언합니다.")["config-key:dbsnp_vcf"].verdict == "FAIL"
    assert _internal("점검 전용(check_only) 모드입니다.")["config-key:check_only"].verdict == "REVIEW"


def test_an_internal_phrase_fails_bare_and_is_review_with_a_korean_explanation():
    assert _internal("resource bundle에 선언합니다.")["internal-config:resource bundle"].verdict == "FAIL"
    glossed = _internal("resource bundle(참조 자료 묶음)에 선언합니다.")
    assert glossed["internal-config:resource bundle"].verdict == "REVIEW"


def test_tool_names_and_file_names_go_to_a_person():
    found = _internal("samtools calmd로 보정했고 resource_validation.txt에 [NOTE]가 있습니다.")
    assert {f.verdict for f in found.values()} == {"REVIEW"}
    assert set(found) == {
        "tool:samtools calmd",
        "file-name:resource_validation.txt",
        "log-marker:[NOTE]",
    }


def test_a_cli_flag_and_a_diagnostic_code_fail():
    found = _internal("NM_MD_REPAIRED는 --no-per-base 때문이 아닙니다.")
    assert found["cli-flag:--no-per-base"].verdict == "FAIL"
    assert found["diagnostic-code:NM_MD_REPAIRED"].verdict == "FAIL"


def test_the_same_expression_twice_in_one_statement_is_one_finding():
    found = q.evaluate(
        _answer("dbsnp_vcf가 없어 dbsnp_vcf를 선언해야 합니다."),
        required=set(), checked=set(), required_source="t", facts=None,
    )
    assert sum(1 for f in found.findings if f.subject == "config-key:dbsnp_vcf") == 1


@pytest.mark.parametrize(
    "text",
    [
        "NM/MD 태그가 보정되었습니다.",
        "GRCh38 기준입니다.",
        "mosdepth thresholds 출력을 확인할 수 있습니다.",
        "연구·교육 목적에 한합니다.",
        "평균 깊이는 11.0116배입니다.",
    ],
)
def test_ordinary_sentences_raise_no_internal_finding(text):
    assert _internal(text) == {}


# --- C. run facts: chosen by the run, not fixed ------------------------------


def _facts(**over) -> q.RunFacts:
    base = {
        "status": "completed_with_warnings",
        "steps": [
            {"stepId": "00_input_validation", "status": "completed"},
            {"stepId": "04_processing", "status": "warning"},
            {"stepId": "05_coverage_qc", "status": "warning"},
        ],
        "diagnostics": [
            {"code": "NM_MD_REPAIRED", "severity": "info", "resolution": "repaired", "stepLabel": "BAM 정리·보정"},
            {"code": "ZERO_COVERAGE_TARGET_BASES", "severity": "attention", "resolution": None, "stepLabel": "커버리지 검사"},
        ],
        "rawVariantRecords": 52294,
        "filteringApplied": False,
        "intendedUse": True,
    }
    base.update(over)
    return q.RunFacts.model_validate(base)


def _fact_findings(
    statements: list[tuple[str, list[str]]], facts: q.RunFacts, rules: str = q.DEFAULT_RULES
) -> dict[tuple[str, str | None], q.Finding]:
    synthesis = {"importantFindings": [{"statement": s, "evidenceRefs": r} for s, r in statements]}
    report = q.evaluate(
        synthesis, required=set(), checked=set(), required_source="t", facts=facts,
        lexicon=q.load_lexicon(rules),
    )
    return {(f.subject, f.unit): f for f in report.findings if f.category == "fact"}


def test_completion_is_checked_only_for_a_completed_run():
    done = _fact_findings([("모든 단계가 끝났습니다.", ["run:status"])], _facts())
    assert done[("all-steps-finished", None)].verdict == "PASS"
    failed = _facts(status="failed", steps=[{"stepId": "01_raw_qc", "status": "failed"}])
    found = _fact_findings([("품질 검사 단계에서 실패했습니다.", ["run:status"])], failed)
    assert ("all-steps-finished", None) not in found
    assert found[("no-false-completion", None)].verdict == "PASS"


def test_a_failed_run_called_complete_fails():
    failed = _facts(status="failed", steps=[{"stepId": "01_raw_qc", "status": "failed"}])
    found = _fact_findings([("모든 단계가 완료되었습니다.", ["run:status"])], failed)
    assert found[("no-false-completion", F0)].verdict == "FAIL"


def test_a_missing_completion_sentence_is_review_not_fail():
    found = _fact_findings([("결과를 볼 수 있습니다.", ["run:status"])], _facts())
    assert found[("all-steps-finished", None)].verdict == "REVIEW"


def test_warning_count_or_step_names():
    """v1 behaviour, kept reproducible. v2 replaces this rule (see below)."""
    counted = _fact_findings([("경고는 두 단계에서 났습니다.", [])], _facts(), rules="1")
    assert counted[("warning-count-or-steps", None)].rule == "count_stated"
    named = _fact_findings([("BAM 정리·보정과 커버리지 검사에서 주의가 기록됐습니다.", [])], _facts(), rules="1")
    assert named[("warning-count-or-steps", None)].rule == "steps_named"
    missing = _fact_findings([("결과를 볼 수 있습니다.", [])], _facts(), rules="1")
    assert missing[("warning-count-or-steps", None)].verdict == "REVIEW"


def test_a_warning_step_called_failed_fails_and_a_negation_does_not():
    found = _fact_findings([("커버리지 단계가 실패했습니다.", [])], _facts())
    assert found[("warning-not-failure", F0)].verdict == "FAIL"
    found = _fact_findings([("실패한 단계는 없습니다.", [])], _facts())
    assert found[("warning-not-failure", None)].verdict == "PASS"


def test_repaired_and_open_warnings_are_told_apart():
    ok = _fact_findings(
        [("NM/MD 태그를 자동으로 다시 계산했습니다.", ["dx:NM_MD_REPAIRED"]),
         ("0× 염기의 원인은 알 수 없습니다.", ["dx:ZERO_COVERAGE_TARGET_BASES"])],
        _facts(),
    )
    assert ok[("repaired:NM_MD_REPAIRED", None)].verdict == "PASS"
    assert ok[("open-not-called-repaired", None)].verdict == "PASS"
    bad = _fact_findings([("0× 문제는 자동으로 보정되었습니다.", ["dx:ZERO_COVERAGE_TARGET_BASES"])], _facts())
    assert bad[("open-not-called-repaired", F0)].verdict == "FAIL"
    negated = _fact_findings([("0× 문제는 보정되지 않았습니다.", ["dx:ZERO_COVERAGE_TARGET_BASES"])], _facts())
    assert negated[("open-not-called-repaired", None)].verdict == "PASS"


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ("52,294개의 기록은 후보 기록의 수입니다.", "PASS"),
        ("52294건은 확정된 변이가 아닙니다.", "PASS"),
        ("이번 실행에서 52,294개의 변이가 발견되었습니다.", "FAIL"),
        ("변이 기록은 52,294건입니다.", "REVIEW"),
    ],
)
def test_the_variant_count_is_framed_as_a_candidate(text, verdict):
    found = _fact_findings([(text, ["run:variantCalling"])], _facts())
    assert found[("candidate-count-framing", F0)].verdict == verdict


def test_the_candidate_rule_does_not_run_when_filtering_was_applied_or_unknown():
    for applied in (True, None):
        found = _fact_findings([("52,294개의 변이가 있습니다.", [])], _facts(filteringApplied=applied))
        assert not any(subject == "candidate-count-framing" for subject, _ in found)


def test_intended_use_is_checked_only_when_the_run_records_it():
    found = _fact_findings([("이 결과는 진단 결과가 아닙니다.", [])], _facts())
    assert found[("intended-use", None)].verdict == "PASS"
    found = _fact_findings([("결과입니다.", [])], _facts(intendedUse=False))
    assert ("intended-use", None) not in found


def test_run_facts_come_from_the_payload():
    payload = {
        "run": {"status": "completed"},
        "steps": {"planned": [{"stepId": "00_input_validation", "status": "completed"}]},
        "diagnostics": [{"code": "X_Y", "severity": "info", "resolution": None, "occurredAtStep": "입력 검증"}],
        "variantCalling": {"rawVariantRecords": 10, "filteringApplied": False},
        "intendedUse": {"statement": "research"},
    }
    facts = q.derive_run_facts(payload)
    assert facts.status == "completed" and facts.rawVariantRecords == 10
    assert facts.diagnostics[0].stepLabel == "입력 검증" and facts.intendedUse


# --- separation from the deterministic evaluation ----------------------------


def _stored(name: str) -> dict:
    return json.loads((BASELINES / name).read_text(encoding="utf-8"))


def test_the_quality_report_never_claims_to_affect_the_deterministic_verdict():
    block = q.evaluate_record(None, None, _stored(DAY3)["output"])
    assert block is not None and block["affectsDeterministic"] is False


def test_checking_an_answer_does_not_change_it():
    stored = _stored(DAY3)
    before = json.dumps(stored["output"], sort_keys=True)
    q.evaluate_record(None, None, stored["output"])
    assert json.dumps(stored["output"], sort_keys=True) == before


def test_run_expectations_is_unchanged_by_this_module():
    """The deterministic report has none of the quality checks in it, and a
    quality FAIL on the same answer leaves deterministicPassed as recorded."""
    stored = _stored(DAY3)
    names = {r["name"] for r in stored["evaluation"]["results"]}
    quality_subjects = {"all-steps-finished", "warning-count-or-steps", "candidate-count-framing"}
    assert not names & quality_subjects
    assert stored["evaluation"]["deterministicPassed"] is True
    block = q.evaluate_record(None, None, stored["output"])
    assert block is not None and block["counts"]["internal"]["FAIL"] > 0
    assert "explanation_quality" not in evaluators.__dict__


def test_the_application_never_imports_the_checker():
    app_dir = config.ROOT / "backend" / "app"
    for path in app_dir.rglob("*.py"):
        assert "explanation_quality" not in path.read_text(encoding="utf-8"), path


def test_a_skipped_case_records_no_quality_block_and_calls_no_model(monkeypatch):
    from . import run_eval

    def refuse(*_a, **_k):
        raise AssertionError("model called")

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", refuse)
    record = run_eval.evaluate("in_progress")
    assert record["explanationQuality"] is None


def test_a_record_with_output_carries_the_block_beside_the_evaluation(monkeypatch):
    from . import run_eval

    stored = _stored("2026-09-10_full_completed_with_warnings_sonnet_b72d23897664f9d4.json")

    class Result:
        def model_dump(self):
            return {"available": True, "errorCategory": None, "synthesis": stored["output"], "provenance": {}}

    monkeypatch.setattr(run_eval.synthesis, "build_run_synthesis", lambda *_a, **_k: Result())
    record = run_eval.evaluate("full_completed_with_warnings")
    assert record["explanationQuality"]["counts"]["internal"]["FAIL"] > 0
    # The quality FAILs above do not reach the deterministic verdict.
    assert record["evaluation"]["deterministicPassed"] == stored["evaluation"]["deterministicPassed"]
    assert all(r["name"] != "explanation-quality" for r in record["evaluation"]["results"])


# --- Day 2 and Day 3, the observed answers -----------------------------------


def _real(name: str) -> q.QualityReport:
    labels = q.load_labels()
    reports = q.reports_for_labels(labels)
    answer = next(a for a in labels.realAnswers if a.baseline == name)
    return reports[answer.id]


def test_day3_read_and_depth_are_never_explained_and_nm_md_is():
    terms = {t.termId: t for t in _real(DAY3).terms}
    assert (terms["read"].verdict, terms["read"].rule) == ("FAIL", "never_explained")
    assert (terms["depth"].verdict, terms["depth"].rule) == ("FAIL", "never_explained")
    assert terms["nm-md-tags"].verdict == "PASS"


def test_day2_explains_read_only_in_the_summary_and_never_dbsnp():
    terms = {t.termId: t for t in _real(DAY2).terms}
    assert terms["read"].verdict == "REVIEW" and terms["read"].unitsExplained == 1
    assert terms["dbsnp-rsid"].verdict == "FAIL"


def test_day3_exposes_internal_names_that_day2_wrote_in_korean():
    day2 = [f for f in _real(DAY2).findings if f.category == "internal" and f.verdict == "FAIL"]
    day3 = {f.subject for f in _real(DAY3).findings if f.category == "internal" and f.verdict == "FAIL"}
    assert day2 == []
    assert day3 == {
        "internal-config:resource bundle",
        "server-path:00_input_validation/resource_validation.txt",
        "config-key:dbsnp_vcf",
        "internal-config:ID column",
    }


def test_only_day2_states_the_warning_count():
    def verdict(report: q.QualityReport) -> str:
        finding = report.find("fact", None, "warning-count-or-steps")
        assert finding is not None
        return finding.verdict

    assert verdict(_real(DAY2)) == "PASS"
    assert verdict(_real(DAY3)) == "REVIEW"


# --- the labelled set --------------------------------------------------------


def test_real_answers_are_pointed_at_not_copied():
    labels = q.load_labels()
    raw = json.loads(q.LABELS_PATH.read_text(encoding="utf-8"))
    for answer in raw["realAnswers"]:
        assert set(answer) == {"id", "origin", "baseline", "runFacts", "case"}
    for answer in labels.realAnswers:
        unit_ids = {u.id for u in q.units(_stored(answer.baseline)["output"])}
        for item in labels.items:
            if item.answer == answer.id and item.unit is not None:
                assert item.unit in unit_ids, item.id


def test_synthetic_answers_are_marked_synthetic():
    labels = q.load_labels()
    real_ids = {a.id for a in labels.realAnswers}
    for answer in labels.syntheticAnswers:
        assert answer.origin == "synthetic" and answer.id.startswith("syn_")
        assert answer.id not in real_ids


def test_every_label_is_marked_ai_provisional_and_scored_as_such():
    labels = q.load_labels()
    assert {item.labelSource for item in labels.items} == {"ai_provisional"}
    scored = q.score_labels(labels, q.reports_for_labels(labels))
    assert scored["validatedByHuman"] is False
    assert "AI 임시 판정" in scored["note"]


def test_every_finding_on_a_real_answer_has_a_label():
    """A new finding on Day 2 or Day 3 is either a label gap or a false alarm;
    either way a person has to look, so it is not allowed to pass silently."""
    labels = q.load_labels()
    scored = q.score_labels(labels, q.reports_for_labels(labels))
    real_ids = {a.id for a in labels.realAnswers}
    assert [u for u in scored["unlabelledFindings"] if u["answer"] in real_ids] == []


def test_the_disagreements_with_the_labels_are_exactly_the_known_ones():
    """Regression, not a performance claim. Six are semantic expressions no
    string rule targets (misses); one is a correct negated gloss sent to a
    person. Any change to this list is a change in behaviour to look at."""
    labels = q.load_labels()
    scored = q.score_labels(labels, q.reports_for_labels(labels))
    assert sorted(m["id"] for m in scored["mismatches"]) == sorted(
        [
            "day2_d505:internal:importantFindings[5]:knowledge-wording:결과 지점",
            "day2_d505:internal:importantFindings[2]:field-translation:겹치지 않게 센 목표 염기",
            "day2_d505:internal:limitations[3]:knowledge-wording:구간 단위 지표를 염기 단위 사실로",
            "day2_d505:internal:nextChecks[4]:knowledge-wording:보정 전·후 검증 분류 지표",
            "day3_08c1:internal:importantFindings[1]:field-translation:겹치지 않는 염기",
            "day3_08c1:internal:limitations[2]:knowledge-wording:염기 단위 지표와 구간 단위 지표",
            "syn_zero_negated_gloss:term:summary:zero-coverage",
        ]
    )


def test_the_real_run_facts_snapshot_matches_the_payload():
    run = real_runs.REAL_RUNS["real_cba73e"]
    if not real_runs.capture_available(run):
        pytest.skip("capture not on this machine")
    labels = q.load_labels()
    with real_runs.materialise(run) as explanation:
        from app.services.explanation.llm import contract

        payload, _ = contract.build_payload(explanation)
    assert q.derive_run_facts(payload) == labels.runFacts["real_cba73e"]


# --- v2 rules ----------------------------------------------------------------
#
# What changed and why: rubric/explanation_checks_v2.md. v1 stays reproducible:
# the label set is scored with v1, and the tests above that pin v1 behaviour
# name it.


def _v2(synthesis: dict, *, required: frozenset[str] = frozenset(), checked: frozenset[str] = frozenset()) -> q.QualityReport:
    return q.evaluate(
        synthesis, required=set(required), checked=set(checked) | set(required),
        required_source="t", facts=None, lexicon=q.load_lexicon("2"),
    )


def _v2_internal(text: str) -> dict[str, q.Finding]:
    return {f.subject: f for f in _v2(_answer(text)).findings if f.category == "internal"}


def test_both_rule_versions_load_and_v2_is_the_default():
    assert q.load_lexicon("1").rulesVersion == "1"
    assert q.load_lexicon("2").rulesVersion == "2"
    assert q.DEFAULT_RULES == "2"
    assert q.load_lexicon("1").hardPhrases == [] and q.load_lexicon("1").stepNameVariants == []
    block = q.evaluate_record(None, None, _stored(DAY3)["output"], rules="1")
    assert block is not None and block["rules"] == "explanation_checks_v1"


def test_v2_keeps_every_v1_rule():
    """v2 adds; it does not silently drop a v1 cue or pattern."""
    v1, v2 = q.load_lexicon("1"), q.load_lexicon("2")
    terms2 = {t.termId: t for t in v2.terms}
    for t1 in v1.terms:
        t2 = terms2[t1.termId]
        assert set(t1.plainSubstitutes) <= set(t2.plainSubstitutes)
        assert set(t1.reviewSubstitutes) <= set(t2.reviewSubstitutes)
        groups2 = {g.name: g for g in t2.groups}
        for g1 in t1.groups:
            assert set(g1.surfaces) <= set(groups2[g1.name].surfaces)
            assert set(g1.accept) <= set(groups2[g1.name].accept)
    assert [p.model_dump() for p in v1.internalPatterns] == [p.model_dump() for p in v2.internalPatterns]
    assert [p.model_dump() for p in v1.internalPhrases] == [p.model_dump() for p in v2.internalPhrases]


def test_every_v2_rule_compiles_and_says_where_it_came_from():
    lexicon = q.load_lexicon("2")
    for phrase in lexicon.hardPhrases:
        re.compile(phrase.regex)
        for cue in phrase.explainedBy:
            re.compile(cue)
        assert phrase.basis and phrase.plainKorean
    for variant in lexicon.stepNameVariants:
        re.compile(variant.pattern)
        assert variant.basis


# A. wording a reader did not understand (human_review_v1 HR01·HR04 memos)


@pytest.mark.parametrize(
    ("text", "subject"),
    [
        ("target 중 겹치지 않는 염기의 9.2905%입니다.", "field-translation:겹치지 않는 염기"),
        ("겹치지 않게 센 목표 염기의 9.2905%입니다.", "field-translation:겹치지 않게 센 목표 염기"),
        ("3,387,168개가 read에 한 번도 덮이지 않았습니다.", "hard-wording:read에 한 번도 덮이"),
        ("염기 단위로 보면 9.2905%입니다.", "hard-wording:염기 단위"),
    ],
)
def test_wording_a_reader_did_not_understand_goes_to_a_person(text, subject):
    found = _v2_internal(text)
    assert found[subject].verdict == "REVIEW"


@pytest.mark.parametrize(
    "text",
    [
        # the plain rewrite the task gives as the direction
        "이번 분석에서 확인하려고 정한 DNA 위치 중 9.2905%는 DNA를 읽은 기록이 한 번도 없었습니다.",
        # the same words, unpacked in the same statement
        "겹치지 않는 염기(겹치는 target 구간을 합쳐 같은 위치를 한 번만 센 염기)의 9.2905%입니다.",
        "염기 단위, 즉 위치 하나하나를 센 값으로 9.2905%입니다.",
        "read(시퀀싱으로 읽은 짧은 DNA 조각)에 한 번도 덮이지 않은 위치가 있습니다.",
        # the active form the reader found easier is not targeted
        "target 구간 안에 read가 한 번도 덮지 않은 염기가 있습니다.",
        # merging overlaps, said plainly, is not the translated label
        "겹치는 target 구간은 합쳐서 같은 염기를 두 번 세지 않았습니다.",
        "구간이 아니라 염기 하나하나를 센 값입니다.",
    ],
)
def test_plain_or_unpacked_wording_raises_nothing(text):
    assert _v2_internal(text) == {}


def test_hard_wording_is_never_fail_and_is_not_in_v1():
    text = "겹치지 않는 염기의 9.2905%가 read에 덮이지 않았습니다. 염기 단위입니다."
    assert {f.verdict for f in _v2_internal(text).values()} == {"REVIEW"}
    v1 = q.evaluate(_answer(text), required=set(), checked=set(), required_source="t",
                    facts=None, lexicon=q.load_lexicon("1"))
    assert not any(f.subject.startswith(("field-translation:", "hard-wording:")) for f in v1.findings)


def test_the_plain_rewrite_counts_as_explaining_the_terms():
    """Accurate plain words without the term are a proper explanation (policy C)."""
    report = _v2(
        _answer("이번 분석에서 확인하려고 정한 DNA 위치 중 9.2905%는 DNA를 읽은 기록이 한 번도 없었습니다."),
        required=frozenset({"read", "target", "zero-coverage"}),
    )
    for term in ("read", "target", "zero-coverage"):
        finding = _term(report, F0, term)
        assert (finding.verdict, finding.rule) == ("PASS", "conveyed_plain"), term


# C. a term inside a step name written differently (HR05)


def test_a_term_inside_a_rewritten_step_name_is_review_in_v2_and_fail_in_v1():
    text = "11개 점검 중 3개 단계(BAM 처리, 커버리지 점검, 변이 검출)에서 경고가 기록되었습니다."
    finding = _term(_v2(_answer(text), required=frozenset({"bam"})), F0, "bam")
    assert (finding.verdict, finding.rule) == ("REVIEW", "step_name_variant")
    v1 = q.evaluate(_answer(text), required={"bam"}, checked={"bam"}, required_source="t",
                    facts=None, lexicon=q.load_lexicon("1"))
    assert _term(v1, F0, "bam").rule == "never_explained"


def test_a_term_used_outside_the_step_name_is_still_judged():
    text = "BAM 처리 단계에서 BAM의 태그가 다시 계산되었습니다."
    finding = _term(_v2(_answer(text), required=frozenset({"bam"})), F0, "bam")
    assert finding.rule == "never_explained"


def test_answer_level_and_unit_level_are_reported_apart():
    report = _v2(
        _answer("read(시퀀싱으로 읽은 짧은 DNA 조각)가 덮지 않았습니다.", "read 서열은 그대로입니다."),
        required=frozenset({"read"}),
    )
    (summary,) = report.terms
    assert summary.verdict == "REVIEW" and summary.explainedInAnswer is True
    unused = _v2(_answer("결과입니다."), required=frozenset({"depth"})).terms[0]
    assert unused.explainedInAnswer is None


# B. warning facts: step count and step names, apart


def _v2_facts(statements: list[tuple[str, str]], facts: q.RunFacts) -> dict[str, q.Finding]:
    """statements: (group, text). Keyed by subject -- one finding each."""
    synthesis: dict = {}
    for group, text in statements:
        if group == "summary":
            synthesis["summary"] = text
        else:
            synthesis.setdefault(group, []).append({"statement": text, "evidenceRefs": []})
    report = q.evaluate(synthesis, required=set(), checked=set(), required_source="t",
                        facts=facts, lexicon=q.load_lexicon("2"))
    return {f.subject: f for f in report.findings if f.category == "fact"}


def test_count_and_names_in_the_important_findings_pass():
    found = _v2_facts(
        [("importantFindings", "2개 단계(BAM 정리·보정, 커버리지 검사)에서 경고가 기록되었습니다.")], _facts()
    )
    assert (found["warning-step-count"].verdict, found["warning-step-count"].rule) == ("PASS", "stated")
    assert (found["warning-steps-named"].verdict, found["warning-steps-named"].rule) == ("PASS", "all_named")
    assert "warning-count-or-steps" not in found


def test_a_count_only_in_uncertainties_is_not_a_full_explanation():
    """Day 2: '경고로 기록된 세 단계' only in uncertainties (HR20)."""
    found = _v2_facts([("uncertainties", "경고로 기록된 두 단계의 세부 내용은 열어 보지 않았습니다.")], _facts())
    assert (found["warning-step-count"].verdict, found["warning-step-count"].rule) == ("REVIEW", "secondary_only")
    assert found["warning-steps-named"].rule == "not_named"


def test_a_warning_count_is_not_taken_as_the_step_count():
    """The record counts warning steps; one step can carry several diagnostics."""
    found = _v2_facts([("importantFindings", "경고 2건이 기록되었습니다.")], _facts())
    assert (found["warning-step-count"].verdict, found["warning-step-count"].rule) == ("REVIEW", "count_unit_unclear")


def test_names_without_a_count_and_a_partial_list_are_told_apart():
    named = _v2_facts([("summary", "BAM 정리·보정과 커버리지 검사에서 경고가 났습니다.")], _facts())
    assert named["warning-steps-named"].verdict == "PASS"
    assert named["warning-step-count"].rule == "not_found"
    partial = _v2_facts([("summary", "커버리지 검사에서 경고가 났습니다.")], _facts())
    assert partial["warning-steps-named"].rule == "partially_named"
    assert "BAM 정리·보정" in partial["warning-steps-named"].detail


def test_a_step_name_without_a_warning_word_is_not_counted_as_named():
    found = _v2_facts([("summary", "BAM 정리·보정과 커버리지 검사가 끝났습니다.")], _facts())
    assert found["warning-steps-named"].rule == "not_named"


def test_a_different_number_of_steps_is_not_the_warning_step_count():
    found = _v2_facts([("summary", "8개 단계가 모두 끝났고 경고가 있습니다.")], _facts())
    assert found["warning-step-count"].rule == "not_found"


def test_no_warning_step_means_no_warning_check():
    facts = _facts(steps=[{"stepId": "00_input_validation", "status": "completed"}])
    found = _v2_facts([("summary", "모든 단계가 끝났습니다.")], facts)
    assert "warning-step-count" not in found and "warning-steps-named" not in found


def test_warning_steps_come_from_the_check_summary_when_steps_are_absent():
    payload = {
        "run": {"status": "completed_with_warnings"},
        "checkSummary": {"notable": [
            {"name": "step_04_processing", "status": "WARN"},
            {"name": "step_99_unknown", "status": "WARN"},
            {"name": "step_05_coverage_qc", "status": "PASS"},
        ]},
    }
    facts = q.derive_run_facts(payload)
    assert facts.steps == [] and facts.checkWarnSteps == ["04_processing"]
    found = _v2_facts([("summary", "1개 단계(BAM 정리·보정)에서 경고가 났습니다.")], facts)
    assert found["warning-step-count"].verdict == "PASS"
    assert found["warning-steps-named"].verdict == "PASS"


# D. a measurement carries its meaning and whether it can be judged


def _measured(statements: list[str], value: float = 11.0116) -> q.Finding | None:
    report = q.evaluate(
        _answer(*statements), required=set(), checked=set(), required_source="t", facts=None,
        lexicon=q.load_lexicon("2"),
        measurements=[q.Measurement(metric="meanTargetDepth", value=value)],
    )
    return next((f for f in report.findings if f.subject == "measurement-meaning:meanTargetDepth"), None)


@pytest.mark.parametrize(
    ("statements", "rule"),
    [
        (["평균 깊이(각 위치를 read가 평균 몇 번 겹쳐 읽었는지)는 11.0116배이며, 판단 기준이 설정돼 있지 않아 충분한지는 알 수 없습니다."], "meaning_and_scope"),
        (["평균 깊이(각 위치를 read가 평균 몇 번 겹쳐 읽었는지)는 11.0116배입니다.", "11.0116배가 충분한지는 판단할 수 없습니다."], "split"),
        (["평균 깊이(각 위치를 read가 평균 몇 번 겹쳐 읽었는지)는 11.0116배입니다."], "no_scope"),
        (["평균 깊이는 11.0116배이며, 기준이 없어 높은지 낮은지 판단할 수 없습니다."], "no_meaning"),
        (["target 전체의 평균 깊이는 11.0116배로 기록되었습니다."], "no_meaning_no_scope"),
    ],
)
def test_a_measurement_is_checked_for_meaning_and_scope(statements, rule):
    finding = _measured(statements)
    assert finding is not None and finding.rule == rule
    assert finding.verdict == ("PASS" if rule == "meaning_and_scope" else "REVIEW")


def test_a_measurement_the_answer_does_not_state_is_not_required():
    assert _measured(["깊이 중앙값은 계산되지 않았습니다."]) is None
    assert _measured(["평균 깊이는 11.01배입니다."]) is None, "a rounded value is not this value"


def test_measurements_come_from_the_payload_and_are_v2_only():
    payload = {"coverage": {"meanTargetDepth": 11.0116, "zeroCoverageBasesPct": 9.2905, "medianTargetDepth": None}}
    assert [m.metric for m in q.derive_measurements(payload)] == ["meanTargetDepth", "zeroCoverageBasesPct"]
    report = q.evaluate(_answer("평균 깊이는 11.0116배입니다."), required=set(), checked=set(),
                        required_source="t", facts=None, lexicon=q.load_lexicon("1"),
                        measurements=q.derive_measurements(payload))
    assert not any(f.subject.startswith("measurement-meaning:") for f in report.findings)


# Day 2 and Day 3 under v2 -- regression, not a performance claim


def _real_v2(name: str) -> q.QualityReport:
    labels = q.load_labels()
    answer = next(a for a in labels.realAnswers if a.baseline == name)
    expectations = q._load_expectations(answer.case)
    block = expectations.get("beginnerRubricV2") or {}
    required = {t["termId"] for t in block.get("requiredTerms") or []}
    not_required = {t["termId"] for t in block.get("notRequired") or []}
    return q.evaluate(
        _stored(name)["output"], required=required, checked=required | not_required,
        required_source="t", facts=labels.runFacts[answer.runFacts], lexicon=q.load_lexicon("2"),
        # the real run's values (labels runFacts snapshot does not carry them)
        measurements=[q.Measurement(metric="meanTargetDepth", value=11.0116),
                      q.Measurement(metric="zeroCoverageBasesPct", value=9.2905)],
    )


def _fact_rule(report: q.QualityReport, subject: str) -> str | None:
    finding = next((f for f in report.findings if f.subject == subject), None)
    return finding.rule if finding else None


def test_day2_and_day3_no_longer_pass_the_warning_facts():
    """HR19 (Day 3) and HR20 (Day 2): neither names the warning steps; Day 2
    gives the count only in uncertainties. v1 passed Day 2 on that count."""
    day2, day3 = _real_v2(DAY2), _real_v2(DAY3)
    assert (_fact_rule(day2, "warning-step-count"), _fact_rule(day2, "warning-steps-named")) == (
        "secondary_only", "not_named")
    assert (_fact_rule(day3, "warning-step-count"), _fact_rule(day3, "warning-steps-named")) == (
        "not_found", "not_named")


def test_day2_and_day3_hard_wording_is_found_where_the_reader_stumbled():
    day3 = {f.subject for f in _real_v2(DAY3).findings if f.category == "internal" and f.verdict == "REVIEW"}
    assert {"field-translation:겹치지 않는 염기", "hard-wording:read에 한 번도 덮이", "hard-wording:염기 단위"} <= day3
    day2 = {f.subject for f in _real_v2(DAY2).findings if f.category == "internal"}
    assert "field-translation:겹치지 않게 센 목표 염기" in day2


def test_day3_depth_figure_comes_without_its_meaning():
    assert _fact_rule(_real_v2(DAY3), "measurement-meaning:meanTargetDepth") == "no_meaning_no_scope"
    assert _fact_rule(_real_v2(DAY2), "measurement-meaning:meanTargetDepth") == "no_meaning"
