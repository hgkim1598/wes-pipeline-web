"""P1: curated checks per resource_bundle cause kind, and the prompt rules the
first real evaluation showed were missing.

Why these tests exist (evaluation 2026-11-16, two real failed runs, v3):
  * one run's agent never opened the failed step, so three of its four
    classified causes were never seen -- the tool rule said "if you can answer
    without it, answer without it";
  * that agent then said installing the missing tools would let the analysis
    start, copying a knowledge `effect` that is only true when a run has one
    failure;
  * the agent that did open the step could only offer "read the [ERROR] lines",
    because no check existed per classified cause.
"""

from __future__ import annotations

import re

import pytest

from app.schemas import ResourceBundleCause, ResourceBundleDiagnosis
from app.services import resource_bundle_causes as rules
from app.services.agent.privacy import Redactor
from app.services.agent.step_evidence import StepEvidence, cause_guidance
from app.services.explanation import knowledge
from app.services.explanation.llm import prompt

SYNTHETIC_SAMPLE = "SYNTHQX7"


def _rule_kinds() -> set[str]:
    return {rule.kind for rule in rules._RULES}


def _rule_roles() -> set[str]:
    fixed = {rule.role for rule in rules._RULES if rule.role is not None}
    return (fixed | set(rules._LABEL_ROLES.values())) - {rules.UNKNOWN}


def _diagnosis(*causes: tuple[str, str, str | None]) -> ResourceBundleDiagnosis:
    return ResourceBundleDiagnosis(
        state="parsed",
        source="pipeline_log",
        causes=[ResourceBundleCause(kind=k, resourceRole=r, tool=t) for k, r, t in causes],
        truncated=False,
        withheldTextCount=0,
    )


# --- the knowledge file matches the rule table --------------------------------


def test_every_rule_kind_has_checks_and_no_extra_kind_exists():
    assert {row.kind for row in knowledge.all_cause_kinds()} == _rule_kinds()


def test_every_named_role_has_checks_and_no_extra_role_exists():
    assert {row.role for row in knowledge.all_resource_roles()} == _rule_roles()


def test_unknown_kind_and_role_have_no_guidance():
    assert knowledge.cause_kind(rules.UNKNOWN) is None
    assert knowledge.resource_role(rules.UNKNOWN) is None


def _all_model_bound_strings() -> list[str]:
    out: list[str] = []
    for row in knowledge.all_cause_kinds():
        out.append(row.title)
        out += [c.statement for c in (*row.checks, *row.cautions)]
        # Remedies (log 17.4) go to the model too.
        out += [part for r in row.remedies for part in (r.statement, r.changes, r.approval)]
    for row in knowledge.all_resource_roles():
        out.append(row.title)
        out += [c.statement for c in row.checks]
    for guidance in cause_guidance(
        _diagnosis(*((k, r, None) for k in sorted(_rule_kinds()) for r in sorted(_rule_roles())))
    ):
        # Every string field of the serialized entry, keys included.
        out += [v for v in guidance.model_dump().values() if isinstance(v, str)]
        out += guidance.sources
        out += [part for r in guidance.remedies for part in (r.statement, r.changes, r.approval)]
    return out


def test_no_curated_string_has_a_shape_the_model_input_check_would_change():
    # A regression guard on the STATIC text: no path shape, no URL, nothing the
    # redactor would mask or withhold. It does not prove anything about a real
    # sample identifier overlapping this text; the next test is what keeps run
    # text out of this field.
    redactor = Redactor(literals=((SYNTHETIC_SAMPLE, "<sample>"),))
    changed = [s for s in _all_model_bound_strings() if redactor.release(s) != s]
    assert changed == []


def test_guidance_depends_only_on_the_classified_keys_never_on_run_text():
    # Same kind and role, different raw evidence (paths, a sample-like name, a
    # withheld string): the guidance must be byte-identical.
    def with_text(text):
        return ResourceBundleDiagnosis(
            state="parsed",
            source="report",
            causes=[ResourceBundleCause(kind="resource_missing_or_empty", resourceRole="target_bed",
                                        evidenceText=text)],
            truncated=False,
            withheldTextCount=0 if text else 1,
        )

    variants = [with_text(t) for t in (None, "<path> missing", f"{SYNTHETIC_SAMPLE} target_bed missing")]
    dumps = {tuple(g.model_dump_json() for g in cause_guidance(d)) for d in variants}
    assert len(dumps) == 1


def test_no_url_or_slash_reaches_the_model():
    offending = [s for s in _all_model_bound_strings() if "://" in s or "/" in s or "\\" in s]
    assert offending == []


# A LIMITED lexical guard: common Korean wordings that would turn a check into
# a repair. It cannot prove a sentence is read-only -- that stays an editorial
# review of wes_cause_kinds.json -- it only stops the obvious regressions.
_REPAIR_WORDS = re.compile(
    r"설치하세요|설치합니다|삭제|덮어|다시 실행|재실행|건너뛰|끄고|끕니다|수정합니다|바꿉니다"
    r"|생성합니다|만듭니다|추가합니다|변경합니다|교체합니다|옮깁니다|지웁니다"
)


def test_checks_contain_none_of_the_listed_repair_wordings():
    offending = [
        claim.statement
        for row in (*knowledge.all_cause_kinds(), *knowledge.all_resource_roles())
        for claim in row.checks
        if _REPAIR_WORDS.search(claim.statement)
    ]
    assert offending == []


def test_the_repair_word_guard_would_catch_a_repair():
    assert _REPAIR_WORDS.search("빠진 색인을 다시 실행해 만듭니다")
    assert _REPAIR_WORDS.search("검사를 건너뛰고 진행합니다")
    assert _REPAIR_WORDS.search("색인을 생성합니다")
    assert _REPAIR_WORDS.search("PATH에 추가합니다")


def test_every_cited_source_resolves():
    for row in (*knowledge.all_cause_kinds(), *knowledge.all_resource_roles()):
        for claim in (*row.checks, *getattr(row, "cautions", [])):
            for source_id in claim.sourceIds:
                assert knowledge.source(source_id) is not None, source_id


def test_an_unknown_source_is_refused(tmp_path, monkeypatch):
    bad = {
        "schemaVersion": "1.0",
        "causeKinds": [
            {"kind": "k", "title": "t", "checks": [{"statement": "s", "sourceIds": ["nope"]}]}
        ],
        "roles": [],
    }
    path = tmp_path / "wes_cause_kinds.json"
    import json

    path.write_text(json.dumps(bad), encoding="utf-8")
    from app import config

    monkeypatch.setattr(config, "CAUSE_KIND_KNOWLEDGE", path)
    knowledge.reload()
    try:
        with pytest.raises(knowledge.KnowledgeError, match="unknown source"):
            knowledge.cause_kind("k")
    finally:
        monkeypatch.undo()
        knowledge.reload()


# --- the lookup ---------------------------------------------------------------


def test_no_diagnosis_means_no_guidance():
    assert cause_guidance(None) == []


def test_a_cause_repeated_per_vcf_yields_one_entry():
    # The real b94559 shape: one tool failure recorded once per VCF checked.
    guidance = cause_guidance(
        _diagnosis(
            ("resource_missing_or_empty", "target_bed", None),
            ("resource_missing_or_empty", "coverage_bed", None),
            ("vcf_tool_unavailable", "unknown", "bcftools"),
            ("vcf_tool_unavailable", "unknown", "bcftools"),
        )
    )
    assert [(g.kind, g.resourceRole) for g in guidance] == [
        ("resource_missing_or_empty", "target_bed"),
        ("resource_missing_or_empty", "coverage_bed"),
        ("vcf_tool_unavailable", "unknown"),
    ]


def test_role_checks_are_added_to_the_kind_checks():
    kind = knowledge.cause_kind("resource_missing_or_empty")
    role = knowledge.resource_role("target_bed")
    (entry,) = cause_guidance(_diagnosis(("resource_missing_or_empty", "target_bed", None)))
    assert entry.checks == [c.statement for c in (*kind.checks, *role.checks)]
    assert entry.cautions == [c.statement for c in kind.cautions]
    assert role.title in entry.title and kind.title in entry.title
    assert entry.sources, "every entry names where its checks come from"


def test_an_unknown_cause_is_skipped_not_guessed():
    assert cause_guidance(_diagnosis(("unknown", "unknown", None))) == []


def test_guidance_travels_in_the_step_evidence_model():
    assert "causeGuidance" in StepEvidence.model_fields


# --- the prompt rules ---------------------------------------------------------


def test_the_tool_rule_requires_opening_a_failed_step():
    assert "When a step recorded a failure" in prompt.CONSTRAINTS
    # The sentence that let the agent skip the failed step is gone.
    assert "if you can answer without it, answer without it" not in prompt.CONSTRAINTS


def test_failed_steps_come_before_warnings_and_an_unopened_failure_is_still_reported():
    assert "only after every failed step\nis open" in prompt.CONSTRAINTS
    assert "A failed step you could\nnot open" in prompt.CONSTRAINTS


def test_a_tool_timeout_is_not_described_as_a_missing_tool():
    # main.sh catches subprocess.SubprocessError, which includes TimeoutExpired,
    # under the same "unavailable" sentence (Codex P1 review, M1).
    entry = knowledge.cause_kind("vcf_tool_unavailable")
    text = " ".join(c.statement for c in entry.checks)
    assert "시간 초과" in text and "Errno 2" in text
    assert "VCF 파일 내용의 문제가 아니라" not in text


def test_cause_guidance_is_explained_only_where_the_tool_is():
    assert "causeGuidance" in prompt.CONSTRAINTS
    assert "causeGuidance" not in prompt.CONSTRAINTS_NO_TOOL


def test_both_variants_forbid_one_fix_unblocking_a_multi_failure_run():
    rule = "Each recorded failure\n  stops the run on its own"
    assert rule in prompt.CONSTRAINTS and rule in prompt.CONSTRAINTS_NO_TOOL


def test_required_tools_effect_no_longer_promises_the_analysis_starts():
    (action,) = knowledge.failure("required_tools").grounding.actions
    assert "다른 실패" in action.effect
    assert not action.effect.startswith("이 검사를 통과하면 분석이 시작됩니다")


# --- remedies: directions that change something (log 17.4) --------------------
#
# Cycle 2 re-fetched primary sources for each remedy and looked for counter-
# evidence (log 17.2, H2). Only the kinds below got one; the rest are left
# empty on purpose rather than filled with advice nobody sourced.

_KINDS_WITH_REMEDIES = {
    "vcf_index_missing", "reference_index_mismatch", "bwa_index_incomplete",
    "bwa_index_not_found", "contig_style_mismatch", "vcf_contig_length_mismatch",
    "vcf_contigs_absent", "checksum_mismatch", "vcf_tool_unavailable",
}


def test_exactly_the_sourced_kinds_carry_remedies():
    have = {row.kind for row in knowledge.all_cause_kinds() if row.remedies}
    assert have == _KINDS_WITH_REMEDIES


def test_every_remedy_says_what_it_changes_and_who_approves():
    for row in knowledge.all_cause_kinds():
        for remedy in row.remedies:
            assert remedy.changes.strip() and remedy.approval.strip(), row.kind
            assert remedy.sourceIds, row.kind


# LIMITED guard, like the one on checks: a remedy may NAME a dangerous shortcut
# only to rule it out. It cannot prove a sentence is safe.
# Negation is judged per sentence (Codex U2-U4 round 1: a "않" in an unrelated
# sentence used to exempt the whole statement). Still lexical: a sentence that
# negates something else while doing the dangerous thing would pass.
_DANGEROUS = re.compile(r"끄|disable|덮어|건너뛰|우회|손으로 고|하나만 복사")
_NEGATED = re.compile(r"지 않|말고|안 됩니다")
# After "다." always (Korean sentence end, even with no space or a closing quote
# next -- Codex round 2), and after other end punctuation followed by space.
# Not after every period: ".tbi", ".dict" and "5GB" must not split.
_SENTENCE_END = re.compile(r"(?<=다\.)|(?<=[.!?])\s+")


def _unsafe(statement: str) -> bool:
    return any(
        _DANGEROUS.search(sentence) and not _NEGATED.search(sentence)
        for sentence in _SENTENCE_END.split(statement)
    )


def test_a_remedy_names_a_dangerous_shortcut_only_to_rule_it_out():
    offending = [
        r.statement for row in knowledge.all_cause_kinds() for r in row.remedies if _unsafe(r.statement)
    ]
    assert offending == []


def test_the_remedy_guard_catches_the_shortcuts_it_lists():
    assert _unsafe("사전 검증을 끄고 진행합니다.")
    assert _unsafe("기대값을 방금 계산된 값으로 덮어씁니다.")
    assert not _unsafe("방금 계산된 값으로 기대값을 덮어쓰지 않습니다.")
    # A negation in another sentence does not excuse the dangerous one.
    assert _unsafe("사전 검증을 끄고 진행합니다. 원본은 삭제하지 않습니다.")
    # ...also with no space, or a closing quote, after the negated sentence.
    assert _unsafe("원본은 삭제하지 않습니다.검증을 끄고 진행합니다.")
    assert _unsafe("원본은 “변경하지 않습니다.” 검증을 끄고 진행합니다.")
    # The two shortcuts the index-pair case is about.
    assert _unsafe(".dict를 손으로 고쳐 .fai에 맞춥니다.")
    assert _unsafe("다른 색인에서 .sa 하나만 복사해 채웁니다.")
    assert not _unsafe("다른 색인에서 빠진 파일 하나만 복사해 채우지 않습니다.")


def test_remedies_travel_apart_from_checks():
    [with_remedy] = cause_guidance(_diagnosis(("vcf_index_missing", "known_sites", None)))
    assert with_remedy.remedies
    assert not set(r.statement for r in with_remedy.remedies) & set(with_remedy.checks)
    assert all(r.changes and r.approval for r in with_remedy.remedies)
    # Each remedy names its own sources, not the entry's merged list.
    [remedy] = with_remedy.remedies
    expected = [knowledge.source(i).title for i in knowledge.cause_kind("vcf_index_missing").remedies[0].sourceIds]
    assert remedy.sources == expected
    assert set(remedy.sources) < set(with_remedy.sources)
    [without] = cause_guidance(_diagnosis(("resource_missing_or_empty", "target_bed", None)))
    assert without.remedies == []


def test_the_remedy_rule_is_only_where_the_tool_is():
    assert "`remedies`" in prompt.CONSTRAINTS
    assert "`remedies`" not in prompt.CONSTRAINTS_NO_TOOL
    assert "never say it will make the run succeed" in prompt.CONSTRAINTS


def test_no_curated_statement_uses_the_internal_config_name():
    # Log 17.2 (H3): the P1 wording put "resource bundle" into an answer.
    # Scope: the curated statements and titles. A SOURCE title ("main.sh —
    # resource bundle ...") still names it; it labels a code file and is a
    # recorded remaining case, not covered here.
    statements = []
    for row in knowledge.all_cause_kinds():
        statements += [row.title, *(c.statement for c in (*row.checks, *row.cautions))]
        statements += [p for r in row.remedies for p in (r.statement, r.changes, r.approval)]
    for row in knowledge.all_resource_roles():
        statements += [row.title, *(c.statement for c in row.checks)]
    assert [s for s in statements if "resource bundle" in s.lower()] == []
