"""설명 품질 검사 -- 개발·평가용. 실제 사용자 응답을 막지 않는다.

    python -m evals.explanation_quality --baseline <baseline 파일> [...]
    python -m evals.explanation_quality --score-labels

evaluators.py의 검사와 무엇이 다른가
-----------------------------------

evaluators.py는 "답변이 근거 안에 머물렀는가"를 본다 -- 숫자, 근거 ID, 필드
이름. 거기서 fail은 `deterministicPassed`를 false로 만들고, 같은 규칙 일부는
런타임 gate로도 돈다. 이 모듈은 "초보자가 읽을 수 있게 설명했는가"의 일부를
본다. 세 범주다.

    term       필수 용어를 쓴 항목에서 그 뜻을 설명했는가, 설명이 맞는가
    internal   설정 키·서버 경로·단계 ID 같은 내부 구현 정보가 드러났는가
    fact       Run 종류에 따라 꼭 전해야 할 사실을 글로 전했는가

결과는 PASS / FAIL / REVIEW다.

    PASS    문자열 규칙이 정상 조건을 확인했다
    FAIL    문자열 규칙이 위반을 찾았다
    REVIEW  문자열만으로 확정할 수 없다. 사람이나 추가 평가가 본다

이 결과는 `run_expectations()`의 보고서에 넣지 않는다. 넣으면 용어 설명 하나가
빠진 답변이 숫자·근거 검사를 모두 통과하고도 `deterministicPassed: false`가
된다. 기록에는 `explanationQuality`라는 별도 키로만 남고, 런타임은 이 모듈을
import하지 않는다(eval -> app 방향만 있다).

문자열 검사의 한계
------------------

evaluators.py 머리말이 말하듯, 문구 검사는 부정문에 약하다. 그래서 이 모듈은

- 확정할 수 있는 것만 PASS/FAIL로 내고 나머지는 REVIEW로 보낸다.
- 용어 설명의 정확성은 괄호 안의 설명만 본다. 문장 전체에서 "변이가 없"을
  찾으면 "변이가 없다는 뜻은 아닙니다"까지 걸리기 때문이다.
- 단서 목록(rubric/explanation_checks_v1.json)은 Day 2·Day 3 답변을 보며 만들었다.
  그 두 답변에 대한 일치도는 개발 데이터 위의 수치다.

규칙 버전
---------

    v1  rubric/explanation_checks_v1.json  -- 처음 규칙. v1 라벨 세트는 v1로만 채점한다
    v2  rubric/explanation_checks_v2.json  -- 기본값. 바뀐 점과 근거: explanation_checks_v2.md

두 버전은 같은 답변을 서로 다르게 채점한다. 개선 전·후 답변을 비교할 때는 양쪽 답변을
같은 버전으로 채점해야 한다(compare_versions.py). 한 버전의 점수를 다른 버전의 점수와
비교하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.explanation import knowledge

HERE = Path(__file__).resolve().parent
RulesVersion = Literal["1", "2"]
LEXICON_PATHS: dict[str, Path] = {
    "1": HERE / "rubric" / "explanation_checks_v1.json",
    "2": HERE / "rubric" / "explanation_checks_v2.json",
}
DEFAULT_RULES: RulesVersion = "2"
LEXICON_PATH = LEXICON_PATHS[DEFAULT_RULES]
LABELS_PATH = HERE / "quality_labels" / "explanation_quality_labels_v1.json"
BASELINES = HERE / "baselines"
EXPECTATIONS = HERE / "expectations"

GROUPS = ("importantFindings", "limitations", "nextChecks", "uncertainties")

Verdict = Literal["PASS", "FAIL", "REVIEW"]
Category = Literal["term", "internal", "fact"]
_RANK: dict[str, int] = {"PASS": 0, "REVIEW": 1, "FAIL": 2}

_HANGUL = re.compile(r"[가-힣]")


# --- lexicon -----------------------------------------------------------------


class RejectRule(BaseModel):
    pattern: str
    unless: str | None
    why: str


class SurfaceGroup(BaseModel):
    name: str
    surfaces: list[str] = Field(min_length=1)
    accept: list[str] = Field(min_length=1)
    reject: list[RejectRule]


class TermRules(BaseModel):
    termId: str
    basis: str
    groups: list[SurfaceGroup] = Field(min_length=1)
    plainSubstitutes: list[str]
    reviewSubstitutes: list[str]


class InternalPattern(BaseModel):
    id: str
    regex: str
    verdict: Literal["FAIL", "REVIEW"]
    downgradeWhenGlossed: bool
    why: str


class InternalPhrase(BaseModel):
    phrase: str
    kind: str
    verdict: Literal["FAIL", "REVIEW"]
    downgradeWhenGlossed: bool
    plainKorean: str | None
    why: str


class StepNameVariant(BaseModel):
    """A step name written differently from its wes_steps label (v2)."""

    pattern: str
    termId: str
    basis: str


class HardPhrase(BaseModel):
    """Wording a reader was observed not to understand (v2).

    Never FAIL: REVIEW when the same statement does not explain it, nothing
    when it does. `basis` says where it was observed.
    """

    id: str
    kind: Literal["field-translation", "hard-wording"]
    regex: str
    explainedBy: list[str] = Field(min_length=1)
    plainKorean: str
    basis: str
    why: str


class Lexicon(BaseModel):
    schemaVersion: str
    # Absent in the v1 file, which is kept exactly as it was.
    rulesVersion: RulesVersion = "1"
    terms: list[TermRules]
    definitionMarkers: list[str]
    internalPatterns: list[InternalPattern]
    internalPhrases: list[InternalPhrase]
    stepNameVariants: list[StepNameVariant] = Field(default_factory=list)
    hardPhrases: list[HardPhrase] = Field(default_factory=list)


def load_lexicon(rules: str = DEFAULT_RULES) -> Lexicon:
    if rules not in LEXICON_PATHS:
        raise ValueError(f"unknown rules version {rules!r}; known: {sorted(LEXICON_PATHS)}")
    path = LEXICON_PATHS[rules]
    lexicon = Lexicon.model_validate_json(path.read_text(encoding="utf-8"))
    if lexicon.rulesVersion != rules:
        raise ValueError(f"{path.name} declares rules {lexicon.rulesVersion!r}, not {rules!r}")
    known = {t.id for t in knowledge.all_terms()}
    for term_id in [r.termId for r in lexicon.terms] + [v.termId for v in lexicon.stepNameVariants]:
        if term_id not in known:
            raise ValueError(
                f"{path.name}: {term_id!r} is not a term in wes_terms.json"
            )
    return lexicon


def surface_pattern(surfaces: Iterable[str]) -> re.Pattern[str]:
    """One alternation, longest surface first, with ASCII word edges.

    "NM/MD 태그" must win over "NM", and "0×" must not match inside "10×" --
    hence the digit lookbehind for a surface that starts with a digit.
    """
    parts: list[str] = []
    for surface in sorted(set(surfaces), key=len, reverse=True):
        body = re.escape(surface)
        first, last = surface[0], surface[-1]
        if first.isascii() and first.isalnum():
            body = r"(?<![A-Za-z0-9_.,])" + body
        if last.isascii() and last.isalnum():
            body = body + r"(?![A-Za-z0-9_])"
        parts.append(body)
    return re.compile("|".join(parts))


# --- answer units ------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    """An independently shown piece of the answer: the summary or one statement."""

    id: str
    text: str
    refs: tuple[str, ...]


def units(synthesis: dict[str, Any]) -> list[Unit]:
    out: list[Unit] = []
    summary = synthesis.get("summary")
    if summary:
        out.append(Unit("summary", summary, ()))
    for group in GROUPS:
        for index, item in enumerate(synthesis.get(group) or []):
            statement = item.get("statement")
            if statement:
                out.append(
                    Unit(
                        f"{group}[{index}]",
                        statement,
                        tuple(item.get("evidenceRefs") or []),
                    )
                )
    return out


# --- findings ----------------------------------------------------------------


@dataclass
class Finding:
    category: Category
    subject: str
    unit: str | None
    verdict: Verdict
    rule: str
    detail: str
    excerpt: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "subject": self.subject,
            "unit": self.unit,
            "verdict": self.verdict,
            "rule": self.rule,
            "detail": self.detail,
            "excerpt": self.excerpt,
        }


@dataclass
class TermSummary:
    termId: str
    required: bool
    verdict: Verdict | None
    rule: str
    unitsExplained: int
    unitsUsed: int

    @property
    def explainedInAnswer(self) -> bool | None:
        """Answer-level, kept apart from the unit-level verdict: a term can be
        explained somewhere in the answer and still not read on its own in
        another statement. None when the term was not used at all."""
        return self.unitsExplained > 0 if self.unitsUsed else None

    def to_json(self) -> dict[str, Any]:
        return {
            "termId": self.termId,
            "required": self.required,
            "verdict": self.verdict,
            "rule": self.rule,
            "unitsExplained": self.unitsExplained,
            "unitsUsed": self.unitsUsed,
            "explainedInAnswer": self.explainedInAnswer,
        }


@dataclass
class QualityReport:
    requiredTermsSource: str
    requiredTermIds: list[str]
    findings: list[Finding] = field(default_factory=list)
    terms: list[TermSummary] = field(default_factory=list)
    rulesVersion: str = DEFAULT_RULES

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {
            c: {"PASS": 0, "FAIL": 0, "REVIEW": 0} for c in ("term", "internal", "fact")
        }
        for finding in self.findings:
            out[finding.category][finding.verdict] += 1
        return out

    def find(self, category: str, unit: str | None, subject: str) -> Finding | None:
        for finding in self.findings:
            if (
                finding.category == category
                and finding.unit == unit
                and finding.subject == subject
            ):
                return finding
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "explanation-quality",
            "rules": f"explanation_checks_v{self.rulesVersion}",
            # 이 블록의 FAIL은 deterministicPassed와 런타임 gate에 영향을 주지 않는다.
            "affectsDeterministic": False,
            "requiredTerms": {
                "source": self.requiredTermsSource,
                "termIds": self.requiredTermIds,
            },
            "counts": self.counts(),
            "terms": [t.to_json() for t in self.terms],
            "findings": [f.to_json() for f in self.findings],
        }


def _excerpt(text: str, start: int, end: int, pad: int = 18) -> str:
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


# --- A. terms ----------------------------------------------------------------
#
# A term is judged per unit, because the screen shows statements one by one
# (beginner_v2 B2). Within a unit one explanation is enough; the same bracket is
# not demanded at every occurrence. Across units the rule is softer than B2's
# score: a term explained in another unit but not in this one is REVIEW -- that
# is a question of whether this statement reads on its own, which a person
# decides. A required term explained nowhere in the answer is FAIL.

# Unit-level states, before the answer-level context is known.
_EXPLAINED = "explained"
_PLAIN = "conveyed_plain"
_REVIEW_SUB = "review_substitute"
_GLOSS_UNVERIFIED = "gloss_unverified"
_POSSIBLE_DEF = "possible_definition"
_UNEXPLAINED = "unexplained"
_INACCURATE = "inaccurate_gloss"
_STEP_VARIANT = "step_name_variant"


def _glosses(text: str, start: int, end: int) -> list[str]:
    """Bracketed explanation attached to one occurrence, either side.

    after   "read(시퀀싱으로 읽은 짧은 DNA 조각)"
    before  "read가 한 번도 덮지 않은(0×)", "정렬 파일(BAM)"

    Only text with Hangul counts: "(0×)" after a term is not an explanation.
    """
    out: list[str] = []
    after = re.match(r"\s?\(([^()]*)\)", text[end:])
    if after and _HANGUL.search(after.group(1)):
        out.append(after.group(1))
    before = text[:start].rstrip()
    rest = text[end:].lstrip()
    if before.endswith("(") and rest.startswith(")"):
        lead = re.split(r"[,.;:·]\s*", before[:-1])[-1][-30:]
        if _HANGUL.search(lead):
            out.append(lead)
    return out


def mask_step_labels(text: str) -> str:
    """Blank out step names, keeping every offset.

    "BAM 정리·보정" is the name of a step as the screen shows it, not a use of
    the word BAM -- counting it made a step name an unexplained term. The names
    come from wes_steps.json, the registry the screen reads too.
    """
    for step in knowledge.all_steps():
        text = text.replace(step.label, "□" * len(step.label))
    return text


def mask_step_variants(
    text: str, variants: list[StepNameVariant]
) -> tuple[str, dict[str, tuple[int, int]]]:
    """v2: blank out step names written differently ('BAM 처리'), keeping offsets.

    Returns the masked text and, per term whose word sat inside such a name,
    where the first one was. Unlike an exact label, a variant is not certain to
    be a step name, so the caller reports it as REVIEW instead of dropping it.
    """
    seen: dict[str, tuple[int, int]] = {}
    for variant in variants:
        for match in list(re.finditer(variant.pattern, text)):
            seen.setdefault(variant.termId, match.span())
            text = text[: match.start()] + "□" * (match.end() - match.start()) + text[match.end() :]
    return text, seen


def _judge_group(
    text: str, group: SurfaceGroup, markers: list[re.Pattern[str]]
) -> tuple[str, str, str] | None:
    """(state, detail, excerpt) for one surface group in one unit, or None.

    `text` has step names masked; excerpts can show the mask, never a name.
    """
    pattern = surface_pattern(group.surfaces)
    hits = list(pattern.finditer(text))
    if not hits:
        return None

    glosses: list[str] = []
    for hit in hits:
        glosses.extend(_glosses(text, hit.start(), hit.end()))
    first = _excerpt(text, hits[0].start(), hits[0].end())

    for gloss in glosses:
        for rule in group.reject:
            if re.search(rule.pattern, gloss) and not (
                rule.unless and re.search(rule.unless, gloss)
            ):
                return _INACCURATE, f"{group.name} 설명이 부정확: {rule.why}", gloss

    for cue in group.accept:
        found = re.search(cue, text)
        if found:
            return _EXPLAINED, f"{group.name} 설명 있음", _excerpt(
                text, found.start(), found.end()
            )

    if glosses:
        return (
            _GLOSS_UNVERIFIED,
            f"{group.name}에 괄호 설명이 있으나 알려진 표현과 맞지 않아 정확성 확인 필요",
            glosses[0],
        )

    for hit in hits:
        tail = text[hit.end() : hit.end() + 50]
        if any(marker.search(tail) for marker in markers):
            return (
                _POSSIBLE_DEF,
                f"{group.name}를 문장 안에서 정의하는 것으로 보이나 확인 필요",
                first,
            )
    return _UNEXPLAINED, f"{group.name} 설명 없음", first


def _matches_any(patterns: Iterable[str], text: str) -> re.Match[str] | None:
    for cue in patterns:
        found = re.search(cue, text)
        if found:
            return found
    return None


def check_terms(
    unit_list: list[Unit],
    lexicon: Lexicon,
    required: set[str],
    checked: set[str],
) -> tuple[list[Finding], list[TermSummary]]:
    markers = [re.compile(m) for m in lexicon.definitionMarkers]
    masked: dict[str, str] = {}
    in_variant: dict[str, dict[str, tuple[int, int]]] = {}
    for unit in unit_list:
        text, terms_in_variant = mask_step_variants(
            mask_step_labels(unit.text), lexicon.stepNameVariants
        )
        masked[unit.id] = text
        in_variant[unit.id] = terms_in_variant
    findings: list[Finding] = []
    summaries: list[TermSummary] = []

    for rules in lexicon.terms:
        if rules.termId not in checked:
            continue
        is_required = rules.termId in required

        # unit id -> group name -> (state, detail, excerpt)
        states: dict[str, dict[str, tuple[str, str, str]]] = {}
        for unit in unit_list:
            text = masked[unit.id]
            per_group: dict[str, tuple[str, str, str]] = {}
            for group in rules.groups:
                judged = _judge_group(text, group, markers)
                if judged is not None:
                    per_group[group.name] = judged
            if not per_group:
                plain = _matches_any(rules.plainSubstitutes, text)
                review = _matches_any(rules.reviewSubstitutes, text)
                if plain:
                    excerpt = _excerpt(unit.text, plain.start(), plain.end())
                    per_group["*"] = (_PLAIN, "용어 없이 쉬운 말로 전달", excerpt)
                elif review:
                    excerpt = _excerpt(unit.text, review.start(), review.end())
                    per_group["*"] = (
                        _REVIEW_SUB,
                        "용어 대신 쓴 말이 초보자에게 뜻을 전하는지 확인 필요",
                        excerpt,
                    )
                elif rules.termId in in_variant[unit.id]:
                    start, end = in_variant[unit.id][rules.termId]
                    per_group["*"] = (
                        _STEP_VARIANT,
                        "단계 이름을 바꿔 쓴 표현 안의 용어로 보임 -- 개념 설명이 필요한 문장인지 확인 필요",
                        _excerpt(unit.text, start, end),
                    )
            if per_group:
                states[unit.id] = per_group

        # A plain substitute explains the concept, so it counts for every group.
        # An unverified gloss or definition elsewhere is not proof of an
        # explanation, but it is enough to stop "never explained" from being
        # certain -- the first held-out check failed exactly there.
        explained_somewhere: set[str] = set()
        maybe_explained: set[str] = set()
        for per_group in states.values():
            for name, (state, _d, _e) in per_group.items():
                if state == _EXPLAINED:
                    explained_somewhere.add(name)
                if state == _PLAIN:
                    explained_somewhere.update(g.name for g in rules.groups)
                if state in (_GLOSS_UNVERIFIED, _POSSIBLE_DEF):
                    maybe_explained.add(name)

        unit_verdicts: list[Verdict] = []
        explained_units = 0
        for unit in unit_list:
            per_group = states.get(unit.id)
            if not per_group:
                continue
            worst: tuple[Verdict, str, str, str] | None = None
            for name, (state, detail, excerpt) in per_group.items():
                verdict, rule = _unit_verdict(
                    state, name in explained_somewhere, name in maybe_explained, is_required
                )
                if rule == "explained_elsewhere":
                    detail = f"{name}: 이 항목에서는 설명 없음, 다른 항목에서 설명함"
                elif rule == "possibly_explained_elsewhere":
                    detail = f"{name}: 이 항목에서는 설명 없음, 다른 항목의 설명은 확인 필요"
                elif rule == "never_explained":
                    detail = f"{name}: 답변 어디에서도 설명하지 않음"
                elif rule == "unexplained_not_required":
                    detail = f"{name}: 설명 없음(필수 용어 아님 -- 읽기 어려움은 R1에서 본다)"
                if worst is None or _RANK[verdict] > _RANK[worst[0]]:
                    worst = (verdict, rule, detail, excerpt)
            assert worst is not None
            verdict, rule, detail, excerpt = worst
            if verdict == "PASS":
                explained_units += 1
            unit_verdicts.append(verdict)
            findings.append(
                Finding("term", rules.termId, unit.id, verdict, rule, detail, excerpt)
            )

        summaries.append(
            _term_summary(rules.termId, is_required, unit_verdicts, explained_units, findings)
        )

    return findings, summaries


def _unit_verdict(
    state: str, explained_elsewhere: bool, maybe_elsewhere: bool, required: bool
) -> tuple[Verdict, str]:
    if state in (_EXPLAINED, _PLAIN):
        return "PASS", state
    if state == _INACCURATE:
        return "FAIL", state
    if state in (_REVIEW_SUB, _GLOSS_UNVERIFIED, _POSSIBLE_DEF, _STEP_VARIANT):
        return "REVIEW", state
    # _UNEXPLAINED
    if explained_elsewhere:
        return "REVIEW", "explained_elsewhere"
    if maybe_elsewhere:
        return "REVIEW", "possibly_explained_elsewhere"
    if required:
        return "FAIL", "never_explained"
    return "REVIEW", "unexplained_not_required"


def _term_summary(
    term_id: str,
    required: bool,
    verdicts: list[Verdict],
    explained_units: int,
    findings: list[Finding],
) -> TermSummary:
    if not verdicts:
        # B2: not using the term and still conveying the fact is fine -- but
        # whether the fact got across is not something a string can show.
        return TermSummary(
            term_id,
            required,
            "REVIEW" if required else None,
            "not_used",
            0,
            0,
        )
    worst = max(verdicts, key=lambda v: _RANK[v])
    rules = {f.rule for f in findings if f.subject == term_id and f.verdict == worst}
    rule = sorted(rules)[0] if rules else worst.lower()
    return TermSummary(term_id, required, worst, rule, explained_units, len(verdicts))


# --- B. internal expressions -------------------------------------------------


def _is_glossed(text: str, start: int, end: int) -> bool:
    """Korean explanation right next to it: "보고서(x.txt)" or "x(참조 자료 묶음)"."""
    after = re.match(r"\s?\(([^()]*)\)", text[end:])
    if after and _HANGUL.search(after.group(1)):
        return True
    before = text[:start].rstrip()
    if before.endswith("(") and text[end:].lstrip().startswith(")"):
        lead = before[:-1].rstrip("'\" ")
        return bool(lead) and bool(_HANGUL.match(lead[-1]))
    return False


def check_internal(unit_list: list[Unit], lexicon: Lexicon) -> list[Finding]:
    findings: list[Finding] = []
    for unit in unit_list:
        taken: list[tuple[int, int]] = []

        def free(start: int, end: int) -> bool:
            return all(end <= s or start >= e for s, e in taken)

        rules: list[tuple[str, re.Pattern[str], Verdict, bool, str]] = []
        for p in lexicon.internalPatterns:
            rules.append((p.id, re.compile(p.regex), p.verdict, p.downgradeWhenGlossed, p.why))
        for ph in lexicon.internalPhrases:
            pattern = re.compile(re.escape(ph.phrase), re.IGNORECASE)
            why = ph.why if not ph.plainKorean else f"{ph.why} (쉬운 말: {ph.plainKorean})"
            rules.append(
                (f"{ph.kind}:{ph.phrase}", pattern, ph.verdict, ph.downgradeWhenGlossed, why)
            )

        seen: set[str] = set()
        for rule_id, pattern, verdict, downgrade, why in rules:
            for hit in pattern.finditer(unit.text):
                if not free(hit.start(), hit.end()):
                    continue
                taken.append((hit.start(), hit.end()))
                # The same expression twice in one statement is one finding,
                # as in beginner_v2 R2.
                subject = f"{rule_id.split(':')[0]}:{hit.group(0)}"
                if subject in seen:
                    continue
                seen.add(subject)
                final: Verdict = verdict
                rule = rule_id
                detail = why
                if verdict == "FAIL" and downgrade and _is_glossed(
                    unit.text, hit.start(), hit.end()
                ):
                    final = "REVIEW"
                    detail = f"한국어 설명이 붙어 있음 -- 원문 표기가 꼭 필요한지 확인 필요. {why}"
                findings.append(
                    Finding(
                        "internal",
                        subject,
                        unit.id,
                        final,
                        rule,
                        detail,
                        _excerpt(unit.text, hit.start(), hit.end()),
                    )
                )

        # v2: wording a reader was observed not to understand. Explained in the
        # same statement -> no finding; otherwise a person looks. Never FAIL:
        # the same words can be fine in a sentence that unpacks them.
        for phrase in lexicon.hardPhrases:
            explained = any(re.search(cue, unit.text) for cue in phrase.explainedBy)
            for hit in re.finditer(phrase.regex, unit.text):
                if explained or not free(hit.start(), hit.end()):
                    continue
                taken.append((hit.start(), hit.end()))
                subject = f"{phrase.kind}:{hit.group(0)}"
                if subject in seen:
                    continue
                seen.add(subject)
                findings.append(
                    Finding(
                        "internal",
                        subject,
                        unit.id,
                        "REVIEW",
                        f"{phrase.kind}:{phrase.id}",
                        f"{phrase.why} (쉬운 말: {phrase.plainKorean})",
                        _excerpt(unit.text, hit.start(), hit.end()),
                    )
                )
    return findings


# --- C. run facts ------------------------------------------------------------
#
# Which facts an answer must carry depends on the run, so they are derived from
# the payload the model was given -- never from the answer. Only what the
# existing checks do not already cover:
#
#     mustCite      a warning's dx: id is cited somewhere      (existing)
#     mustQualify   variant count cites lim:UNFILTERED_VARIANTS (existing)
#     here          the text says it: all steps finished, how many warnings,
#                   repaired vs still open, candidate not confirmed, RUO


class DiagnosticFact(BaseModel):
    code: str
    severity: str | None
    resolution: str | None
    stepLabel: str | None


class StepFact(BaseModel):
    stepId: str
    status: str


class RunFacts(BaseModel):
    status: str | None
    steps: list[StepFact]
    diagnostics: list[DiagnosticFact]
    rawVariantRecords: int | None
    filteringApplied: bool | None
    intendedUse: bool
    # Steps that the check summary marks WARN, by step id. Only used when the
    # payload has no `steps` section (a frozen fixture); v2 only. Default empty
    # so snapshots written before this field still compare equal.
    checkWarnSteps: list[str] = Field(default_factory=list)


def _check_warn_steps(payload: dict[str, Any]) -> list[str]:
    """Step ids from checkSummary.notable rows named `step_<stepId>` with WARN.

    Only names that resolve to a registered step count -- a row that does not is
    not guessed at.
    """
    out: list[str] = []
    for row in (payload.get("checkSummary") or {}).get("notable") or []:
        name = str(row.get("name") or "")
        if row.get("status") == "WARN" and name.startswith("step_"):
            step_id = name[len("step_") :]
            if knowledge.step(step_id) is not None:
                out.append(step_id)
    return out


class Measurement(BaseModel):
    """A number the run reports, whose meaning a statement should carry (v2)."""

    metric: Literal["meanTargetDepth", "zeroCoverageBasesPct"]
    value: float


def derive_measurements(payload: dict[str, Any]) -> list[Measurement]:
    coverage = payload.get("coverage") or {}
    out: list[Measurement] = []
    for metric in ("meanTargetDepth", "zeroCoverageBasesPct"):
        value = coverage.get(metric)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(Measurement(metric=metric, value=float(value)))
    return out


def derive_run_facts(payload: dict[str, Any]) -> RunFacts:
    run = payload.get("run") or {}
    steps = (payload.get("steps") or {}).get("planned") or []
    variant = payload.get("variantCalling") or {}
    return RunFacts(
        checkWarnSteps=_check_warn_steps(payload),
        status=run.get("status"),
        steps=[StepFact(stepId=s["stepId"], status=s["status"]) for s in steps],
        diagnostics=[
            DiagnosticFact(
                code=d["code"],
                severity=d.get("severity"),
                resolution=d.get("resolution"),
                stepLabel=d.get("occurredAtStep"),
            )
            for d in payload.get("diagnostics") or []
        ],
        rawVariantRecords=variant.get("rawVariantRecords"),
        filteringApplied=variant.get("filteringApplied"),
        intendedUse=bool(payload.get("intendedUse")),
    )


_KOREAN_COUNT = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟"}
_NEGATION_NEAR = r"(않|못|아니|아닙|아님|없)"
_COMPLETED = {"completed", "completed_with_warnings"}


def _number_pattern(n: int) -> re.Pattern[str]:
    plain = str(n)
    grouped = f"{n:,}"
    alternatives = sorted({re.escape(plain), re.escape(grouped)}, key=len, reverse=True)
    return re.compile(r"(?<![\d,.])(?:" + "|".join(alternatives) + r")(?!\d|,\d|\.\d)")


def _any_unit(unit_list: list[Unit], pattern: str) -> tuple[Unit, re.Match[str]] | None:
    compiled = re.compile(pattern)
    for unit in unit_list:
        found = compiled.search(unit.text)
        if found:
            return unit, found
    return None


def _prominent(unit: Unit) -> bool:
    """What the screen leads with: the summary and the important findings."""
    return unit.id == "summary" or unit.id.startswith("importantFindings[")


_WARNING_WORD = re.compile(r"경고|주의")


def check_warning_facts_v2(unit_list: list[Unit], facts: RunFacts) -> list[Finding]:
    """v2: how many steps warned, and which -- two checks, not one.

    v1 passed on either a count or the names, found anywhere. v2 asks for both,
    in the summary or an important finding; a mention only in `uncertainties`
    (or another secondary group) is not a full explanation and goes to a person.

    What the record counts is warning STEPS. It does not record a number of
    warnings: one step can carry several diagnostics, and a diagnostic of
    severity info is not obviously a "warning". So "경고 3건" is not taken as
    the step count -- it is sent to a person as a possible mix-up. Nothing here
    is FAIL: a string search cannot prove that a paraphrase is absent.
    """
    warned = [s.stepId for s in facts.steps if s.status == "warning"] or list(facts.checkWarnSteps)
    if not warned:
        return []
    k = len(warned)
    words = f"{k}|{_KOREAN_COUNT.get(k, str(k))}"
    step_count = re.compile(rf"(?<![\d.,가-힣])({words})\s?(개)?(의)?\s?단계")
    item_count = re.compile(
        rf"경고(가|는)?\s?({words})\s?(건|개|가지)|(?<![\d.,가-힣])({words})\s?(건|가지)(의)?\s?경고"
    )
    findings: list[Finding] = []

    def first(pattern: re.Pattern[str], prominent: bool) -> tuple[Unit, re.Match[str]] | None:
        for unit in unit_list:
            if _prominent(unit) != prominent or not _WARNING_WORD.search(unit.text):
                continue
            found = pattern.search(unit.text)
            if found:
                return unit, found
        return None

    lead = first(step_count, True)
    later = first(step_count, False)
    # A warning count, where no step count is said in the same place or before.
    items = first(item_count, True) or (None if later else first(item_count, False))
    if lead:
        unit, found = lead
        findings.append(Finding("fact", "warning-step-count", unit.id, "PASS", "stated",
                                f"경고로 끝난 단계 수({k})를 요약·주요 발견에 씀",
                                _excerpt(unit.text, found.start(), found.end())))
    elif items:
        unit, found = items
        findings.append(Finding("fact", "warning-step-count", unit.id, "REVIEW", "count_unit_unclear",
                                f"'경고 {k}건'처럼 씀. 실행 기록은 경고로 끝난 단계 {k}개를 기록하며, 한 단계에 "
                                "진단이 여러 개일 수 있어 경고 건수와 같다고 볼 수 없음 -- 단계 수인지 확인 필요",
                                _excerpt(unit.text, found.start(), found.end())))
    elif later:
        unit, found = later
        findings.append(Finding("fact", "warning-step-count", unit.id, "REVIEW", "secondary_only",
                                f"경고로 끝난 단계 수({k})가 {unit.id}에만 있음 -- 요약·주요 발견에는 없음",
                                _excerpt(unit.text, found.start(), found.end())))
    else:
        findings.append(Finding("fact", "warning-step-count", None, "REVIEW", "not_found",
                                f"경고로 끝난 단계가 {k}개라는 문구를 찾지 못함 -- 다른 표현인지 확인 필요"))

    labels = {sid: step.label for sid in warned if (step := knowledge.step(sid)) is not None}
    if len(labels) < k:
        findings.append(Finding("fact", "warning-steps-named", None, "REVIEW", "labels_unknown",
                                "경고 단계 중 이름을 알 수 없는 단계가 있어 확인 필요"))
        return findings
    where: dict[str, str] = {}
    for sid, label in labels.items():
        for unit in unit_list:
            if label in unit.text and _WARNING_WORD.search(unit.text):
                if _prominent(unit) or sid not in where:
                    where[sid] = "lead" if _prominent(unit) else "later"
                if where[sid] == "lead":
                    break
    missing = [labels[s] for s in warned if s not in where]
    later_only = [labels[s] for s in warned if where.get(s) == "later"]
    if not missing and not later_only:
        findings.append(Finding("fact", "warning-steps-named", None, "PASS", "all_named",
                                "경고로 끝난 단계 이름을 모두 요약·주요 발견에 씀"))
    elif not missing:
        findings.append(Finding("fact", "warning-steps-named", None, "REVIEW", "secondary_only",
                                f"요약·주요 발견에 없는 경고 단계: {', '.join(later_only)}"))
    elif len(missing) < k:
        findings.append(Finding("fact", "warning-steps-named", None, "REVIEW", "partially_named",
                                f"이름을 찾지 못한 경고 단계: {', '.join(missing)} -- 바꿔 쓴 이름인지 확인 필요"))
    else:
        findings.append(Finding("fact", "warning-steps-named", None, "REVIEW", "not_named",
                                f"경고로 끝난 단계({', '.join(labels[s] for s in warned)}) 이름을 찾지 못함"))
    return findings


# What each measurement is, in words the term lexicon already accepts, and
# what it means for there to be no standard to judge it by.
_MEASUREMENT_TERM = {"meanTargetDepth": "depth", "zeroCoverageBasesPct": "zero-coverage"}
_NO_STANDARD = re.compile(
    r"(기준|임계값?)[^.]{0,25}(없|않)"
    r"|(높은지|낮은지|충분한지|적절한지)[^.]{0,30}(판단할 수 없|알 수 없|말할 수 없)"
)


def _value_pattern(value: float) -> re.Pattern[str]:
    # The value exactly as the payload carries it: the prompt forbids rounding.
    text = str(int(value)) if value == int(value) else str(value)
    return re.compile(rf"(?<![\d.]){re.escape(text)}(?![\d])")


def check_measurements(
    unit_list: list[Unit], measurements: list[Measurement], lexicon: Lexicon
) -> list[Finding]:
    """v2: a stated measurement carries what it measures and whether it can be judged.

    Per measurement, over the statements that state its value: PASS when one
    statement says both what the number measures (the term's accept cues or
    plain substitutes) and that no standard exists to judge it; REVIEW
    otherwise, naming what is missing or that the two were split across
    statements. A value the answer never states raises nothing -- it is not
    required to appear. Never FAIL.
    """
    rules = {r.termId: r for r in lexicon.terms}
    findings: list[Finding] = []
    for m in measurements:
        term = rules.get(_MEASUREMENT_TERM[m.metric])
        if term is None:
            continue
        meaning = [c for g in term.groups for c in g.accept] + term.plainSubstitutes
        number = _value_pattern(m.value)
        stated = [u for u in unit_list if number.search(u.text)]
        if not stated:
            continue
        has_meaning = [u for u in stated if any(re.search(c, u.text) for c in meaning)]
        has_scope = [u for u in stated if _NO_STANDARD.search(u.text)]
        both = [u for u in has_meaning if u in has_scope]
        found = number.search(stated[0].text)
        assert found is not None
        excerpt = _excerpt(stated[0].text, found.start(), found.end())
        subject = f"measurement-meaning:{m.metric}"
        if both:
            findings.append(Finding("fact", subject, None, "PASS", "meaning_and_scope",
                                    "같은 항목에 무엇을 잰 값인지와 판단 기준 유무를 씀", excerpt))
        elif has_meaning and has_scope:
            findings.append(Finding("fact", subject, None, "REVIEW", "split",
                                    "뜻과 판단 기준 유무가 서로 다른 항목에 있음", excerpt))
        elif has_meaning:
            findings.append(Finding("fact", subject, None, "REVIEW", "no_scope",
                                    "판단 기준이 있는지(없다면 무엇을 판단할 수 없는지)를 같은 값과 함께 쓰지 않음", excerpt))
        elif has_scope:
            findings.append(Finding("fact", subject, None, "REVIEW", "no_meaning",
                                    "이 값이 무엇을 잰 것인지 쉬운 말로 쓰지 않음", excerpt))
        else:
            findings.append(Finding("fact", subject, None, "REVIEW", "no_meaning_no_scope",
                                    "이 값이 무엇을 잰 것인지와 판단 기준 유무를 모두 쓰지 않음", excerpt))
    return findings


def check_facts(unit_list: list[Unit], facts: RunFacts, rules: str = "1") -> list[Finding]:
    findings: list[Finding] = []
    step_statuses = [s.status for s in facts.steps]
    failed_steps = [s for s in facts.steps if s.status == "failed"]
    warned_steps = [s for s in facts.steps if s.status == "warning"]
    # v2 also takes WARN steps from the check summary when `steps` is absent.
    warned_any = bool(warned_steps) or (rules != "1" and bool(facts.checkWarnSteps))

    completion = r"모든 (계획 )?단계|전체 단계|끝까지"
    if facts.steps:
        completion += rf"|{len(facts.steps)}개(의)? (계획 )?단계"

    # C1. every step finished (only when the record says so)
    if (
        facts.status in _COMPLETED
        and facts.steps
        and all(s in ("completed", "warning") for s in step_statuses)
    ):
        hit = _any_unit(unit_list, completion)
        if hit:
            unit, found = hit
            findings.append(
                Finding("fact", "all-steps-finished", None, "PASS", "stated",
                        "모든 단계가 끝났다고 씀", _excerpt(unit.text, found.start(), found.end()))
            )
        else:
            findings.append(
                Finding("fact", "all-steps-finished", None, "REVIEW", "not_found",
                        f"{len(facts.steps)}개 단계가 모두 끝났다는 문구를 찾지 못함 -- 다른 표현인지 확인 필요")
            )

    # C1'. a run that did not finish must not be described as finished
    if facts.status not in _COMPLETED or failed_steps:
        claim = _any_unit(unit_list, rf"(?:{completion})[^.]{{0,12}}(끝났|완료(되|했))")
        negated = claim and re.search(_NEGATION_NEAR, claim[0].text[claim[1].end() : claim[1].end() + 8])
        if claim and not negated:
            unit, found = claim
            findings.append(
                Finding("fact", "no-false-completion", unit.id, "FAIL", "claims_completion",
                        "끝나지 않은 실행을 모두 끝났다고 씀", _excerpt(unit.text, found.start(), found.end()))
            )
        else:
            findings.append(
                Finding("fact", "no-false-completion", None, "PASS", "no_claim",
                        "끝나지 않은 실행을 끝났다고 쓴 문구 없음(문자열 기준)")
            )

    # C2 (v2). how many steps warned, and which -- see check_warning_facts_v2
    if rules != "1":
        findings.extend(check_warning_facts_v2(unit_list, facts))

    # C2 (v1). how many warnings, or which steps -- the existence of each is mustCite's
    if rules == "1" and warned_steps:
        k = len(warned_steps)
        count = rf"({k}|{_KOREAN_COUNT.get(k, str(k))})\s?(건|개|가지|곳)?(의)?\s?(경고|단계)"
        hit = None
        for unit in unit_list:
            found = re.search(count, unit.text)
            if found and "경고" in unit.text:
                hit = (unit, found)
                break
        labels = {
            d.stepLabel
            for d in facts.diagnostics
            if d.stepLabel and d.severity is not None
        }
        named = bool(labels) and all(
            any(label in unit.text for unit in unit_list) for label in labels
        )
        if hit:
            unit, found = hit
            findings.append(
                Finding("fact", "warning-count-or-steps", None, "PASS", "count_stated",
                        f"경고 {k}건(또는 경고 단계 수)을 씀", _excerpt(unit.text, found.start(), found.end()))
            )
        elif named:
            findings.append(
                Finding("fact", "warning-count-or-steps", None, "PASS", "steps_named",
                        "경고가 난 단계 이름을 모두 씀")
            )
        else:
            findings.append(
                Finding("fact", "warning-count-or-steps", None, "REVIEW", "not_found",
                        f"경고가 {k}건이라는 것이나 경고 단계 이름을 찾지 못함. 각 경고의 인용 여부는 "
                        "mustCite가 보며, 경고 단계를 구분했는지는 사람 검토(step-scope)가 본다")
            )

    # C2'. a warning step is not a failed step
    if warned_any and not failed_steps:
        claim = _any_unit(unit_list, r"실패한 단계|단계(가|에서|는|도)? 실패|실패 단계(가|는)? (있|\d)")
        negated = claim and re.search(_NEGATION_NEAR, claim[0].text[claim[1].start() : claim[1].end() + 12])
        if claim and not negated:
            unit, found = claim
            findings.append(
                Finding("fact", "warning-not-failure", unit.id, "FAIL", "warning_called_failure",
                        "경고 단계를 실패로 씀", _excerpt(unit.text, found.start(), found.end()))
            )
        else:
            findings.append(
                Finding("fact", "warning-not-failure", None, "PASS", "no_claim",
                        "경고 단계를 실패라고 쓴 문구 없음(문자열 기준)")
            )

    # C3. repaired vs still open
    repaired = {d.code for d in facts.diagnostics if d.resolution == "repaired"}
    open_codes = {
        d.code for d in facts.diagnostics if d.resolution is None and d.severity is not None
    }
    repair_words = r"보정|재계산|다시 계산|고쳐|바로잡"
    for code in sorted(repaired):
        citing = [u for u in unit_list if f"dx:{code}" in u.refs]
        said = [u for u in citing if re.search(repair_words, u.text)]
        if said:
            found = re.search(repair_words, said[0].text)
            assert found is not None
            findings.append(
                Finding("fact", f"repaired:{code}", None, "PASS", "repair_stated",
                        "자동 보정된 문제를 보정됐다고 씀", _excerpt(said[0].text, found.start(), found.end()))
            )
        else:
            findings.append(
                Finding("fact", f"repaired:{code}", None, "REVIEW",
                        "cited_without_repair_word" if citing else "not_cited",
                        "자동 보정됐다는 문구를 인용 항목에서 찾지 못함 -- 다른 표현인지 확인 필요")
            )
    if open_codes:
        claim_words = r"(자동으로 )?(보정|해결|복구)(되었|됐|했)|조치(할|가) 필요(가|는)? 없"
        violations: list[Finding] = []
        for unit in unit_list:
            cited_open = {r[3:] for r in unit.refs if r.startswith("dx:")} & open_codes
            cited_repaired = {r[3:] for r in unit.refs if r.startswith("dx:")} & repaired
            if not cited_open or cited_repaired:
                continue
            found = re.search(claim_words, unit.text)
            if found and not re.search(_NEGATION_NEAR, unit.text[found.start() : found.end() + 6]):
                violations.append(
                    Finding("fact", "open-not-called-repaired", unit.id, "FAIL", "open_called_repaired",
                            f"보정되지 않은 경고({', '.join(sorted(cited_open))})를 해결됐다고 씀",
                            _excerpt(unit.text, found.start(), found.end()))
                )
        findings.extend(violations)
        if not violations:
            findings.append(
                Finding("fact", "open-not-called-repaired", None, "PASS", "no_claim",
                        "보정되지 않은 경고를 해결됐다고 쓴 문구 없음(문자열 기준)")
            )

    # C4. candidate count is not a confirmed count
    if facts.filteringApplied is False and facts.rawVariantRecords is not None:
        number = _number_pattern(facts.rawVariantRecords)
        framing = r"후보|확정(된)? 변이(의 수| 목록| 수)?(가|이)? 아(니|닙|님)|확정되지 않"
        n_text = r"(?:\d[\d,]*)"
        bare = rf"{n_text}\s?(개|건)(의)?\s?(변이|variant)|변이(가)?\s?{n_text}"
        mentioned = [u for u in unit_list if number.search(u.text)]
        for unit in mentioned:
            found = number.search(unit.text)
            assert found is not None
            excerpt = _excerpt(unit.text, found.start(), found.end())
            if re.search(framing, unit.text):
                findings.append(
                    Finding("fact", "candidate-count-framing", unit.id, "PASS", "framed_as_candidate",
                            "변이 수를 후보로 씀", excerpt)
                )
            elif re.search(bare, unit.text):
                findings.append(
                    Finding("fact", "candidate-count-framing", unit.id, "FAIL", "count_as_variants",
                            "필터 전 기록 수를 변이 수처럼 씀", excerpt)
                )
            else:
                findings.append(
                    Finding("fact", "candidate-count-framing", unit.id, "REVIEW", "unclear",
                            "후보라는 말이 같은 항목에 없음 -- 확정 변이처럼 읽히는지 확인 필요", excerpt)
                )

    # C5. research and education only (text; mustCite checks the citation)
    if facts.intendedUse:
        ruo = r"진단(용| 결과| 목적| 용도)?(이|가|은|는)? 아(니|닙|님)|진단에 (쓸|사용할) 수 없|연구[·・ ]?(및 )?교육"
        hit = _any_unit(unit_list, ruo)
        if hit:
            unit, found = hit
            findings.append(
                Finding("fact", "intended-use", None, "PASS", "stated",
                        "연구·교육용이며 진단이 아니라고 씀", _excerpt(unit.text, found.start(), found.end()))
            )
        else:
            findings.append(
                Finding("fact", "intended-use", None, "REVIEW", "not_found",
                        "연구·교육용·진단 아님 문구를 찾지 못함 -- 다른 표현인지 확인 필요")
            )

    return findings


# --- entry point -------------------------------------------------------------


def required_terms(
    expectations: dict[str, Any] | None, payload: dict[str, Any] | None
) -> tuple[set[str], set[str], str]:
    """(required, checked, source) -- never derived from the answer.

    The case spec's beginner_v2 block wins when there is one; otherwise every
    term the payload carried is required. Terms not required are still checked,
    but an unexplained one is REVIEW, never FAIL.
    """
    offered = {t["evidenceId"][5:] for t in (payload or {}).get("terms") or []}
    block = (expectations or {}).get("beginnerRubricV2")
    if block and block.get("requiredTerms"):
        required = {t["termId"] for t in block["requiredTerms"]}
        status = block.get("status", "unknown")
        source = f"case spec beginnerRubricV2.requiredTerms ({status})"
    elif payload is not None:
        required = set(offered)
        source = "payload terms (usedWhen)"
    else:
        required = set()
        source = "none -- payload도 사례 spec도 없어 필수 용어를 정하지 않음"
    checked = required | offered
    if payload is None:
        checked |= {t.id for t in knowledge.all_terms()}
    return required, checked, source


def evaluate(
    synthesis: dict[str, Any],
    *,
    required: set[str],
    checked: set[str],
    required_source: str,
    facts: RunFacts | None,
    lexicon: Lexicon | None = None,
    measurements: list[Measurement] | None = None,
) -> QualityReport:
    lexicon = lexicon or load_lexicon()
    rules = lexicon.rulesVersion
    unit_list = units(synthesis)
    report = QualityReport(
        requiredTermsSource=required_source,
        requiredTermIds=sorted(required),
        rulesVersion=rules,
    )
    term_findings, summaries = check_terms(unit_list, lexicon, required, checked)
    report.findings.extend(term_findings)
    report.terms = summaries
    report.findings.extend(check_internal(unit_list, lexicon))
    if facts is not None:
        report.findings.extend(check_facts(unit_list, facts, rules))
    if rules != "1" and measurements:
        report.findings.extend(check_measurements(unit_list, measurements, lexicon))
    return report


def evaluate_record(
    expectations: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    synthesis: dict[str, Any] | None,
    rules: str = DEFAULT_RULES,
) -> dict[str, Any] | None:
    """What a new eval record stores under `explanationQuality`. None without output."""
    if not synthesis:
        return None
    required, checked, source = required_terms(expectations, payload)
    facts = derive_run_facts(payload) if payload is not None else None
    return evaluate(
        synthesis,
        required=required,
        checked=checked,
        required_source=source,
        facts=facts,
        lexicon=load_lexicon(rules),
        measurements=derive_measurements(payload) if payload is not None else None,
    ).to_json()


# --- labelled set ------------------------------------------------------------
#
# Agreement with labels, so the checker itself can be measured. Every label in
# the current set is an AI provisional label: the numbers it gives are agreement
# with an AI reading, not validated performance, and are reported that way.


class LabelItem(BaseModel):
    id: str
    answer: str
    category: Category
    unit: str | None
    subject: str
    expected: Verdict
    labelSource: Literal["human", "ai_provisional"]
    note: str


class SyntheticAnswer(BaseModel):
    id: str
    origin: Literal["synthetic"]
    runFacts: str | None
    requiredTerms: list[str]
    checkedTerms: list[str]
    synthesis: dict[str, Any]


class RealAnswer(BaseModel):
    id: str
    origin: Literal["real"]
    baseline: str
    runFacts: str
    case: str


class LabelSet(BaseModel):
    schemaVersion: str
    rulesVersion: str
    runFacts: dict[str, RunFacts]
    realAnswers: list[RealAnswer]
    syntheticAnswers: list[SyntheticAnswer]
    items: list[LabelItem]


def load_labels(path: Path = LABELS_PATH) -> LabelSet:
    return LabelSet.model_validate_json(path.read_text(encoding="utf-8"))


def _load_expectations(case: str) -> dict[str, Any]:
    return json.loads((EXPECTATIONS / f"{case}.json").read_text(encoding="utf-8"))


def labels_rules(labels: LabelSet) -> str:
    """The rules version a label set was written against ('explanation_checks_v1' -> '1')."""
    prefix = "explanation_checks_v"
    if not labels.rulesVersion.startswith(prefix):
        raise ValueError(f"unknown label rulesVersion {labels.rulesVersion!r}")
    return labels.rulesVersion[len(prefix) :]


def reports_for_labels(labels: LabelSet, lexicon: Lexicon | None = None) -> dict[str, QualityReport]:
    """Labels are scored with the rules they were written for, unless told otherwise.

    The v1 set was labelled against v1; scoring it with v2 by default would turn
    every behaviour change into a 'disagreement' and blur what the labels mean.
    """
    lexicon = lexicon or load_lexicon(labels_rules(labels))
    out: dict[str, QualityReport] = {}
    for real in labels.realAnswers:
        stored = json.loads((BASELINES / real.baseline).read_text(encoding="utf-8"))
        expectations = _load_expectations(real.case)
        block = expectations.get("beginnerRubricV2") or {}
        required = {t["termId"] for t in block.get("requiredTerms") or []}
        not_required = {t["termId"] for t in block.get("notRequired") or []}
        out[real.id] = evaluate(
            stored["output"],
            required=required,
            checked=required | not_required,
            required_source=f"case spec beginnerRubricV2.requiredTerms ({block.get('status')})",
            facts=labels.runFacts[real.runFacts],
            lexicon=lexicon,
        )
    for synthetic in labels.syntheticAnswers:
        out[synthetic.id] = evaluate(
            synthetic.synthesis,
            required=set(synthetic.requiredTerms),
            checked=set(synthetic.checkedTerms) | set(synthetic.requiredTerms),
            required_source="synthetic answer spec",
            facts=labels.runFacts[synthetic.runFacts] if synthetic.runFacts else None,
            lexicon=lexicon,
        )
    return out


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def score_labels(labels: LabelSet, reports: dict[str, QualityReport]) -> dict[str, Any]:
    """Confusion counts and FAIL-detection precision/recall, per slice.

    Positive class = FAIL (a violation). A REVIEW prediction is an abstention:
    it is neither a detection nor a miss, and is counted on its own. A labelled
    item with no finding at all is predicted "NONE" -- for an expected FAIL that
    is a miss. Findings with no label are listed: each is either a label gap or
    a false alarm, and a person decides which.
    """
    origin = {a.id: "real" for a in labels.realAnswers}
    origin.update({a.id: "synthetic" for a in labels.syntheticAnswers})

    rows: list[dict[str, Any]] = []
    labelled: set[tuple[str, str, str | None, str]] = set()
    for item in labels.items:
        report = reports[item.answer]
        finding = report.find(item.category, item.unit, item.subject)
        predicted = finding.verdict if finding else "NONE"
        labelled.add((item.answer, item.category, item.unit, item.subject))
        rows.append(
            {
                "id": item.id,
                "origin": origin[item.answer],
                "category": item.category,
                "expected": item.expected,
                "predicted": predicted,
                "labelSource": item.labelSource,
            }
        )

    unlabelled = [
        {"answer": answer_id, **f.to_json()}
        for answer_id, report in reports.items()
        for f in report.findings
        if (answer_id, f.category, f.unit, f.subject) not in labelled
    ]

    def summarise(selected: list[dict[str, Any]]) -> dict[str, Any]:
        tp = sum(1 for r in selected if r["expected"] == "FAIL" and r["predicted"] == "FAIL")
        fp = sum(1 for r in selected if r["expected"] != "FAIL" and r["predicted"] == "FAIL")
        fn = sum(
            1 for r in selected if r["expected"] == "FAIL" and r["predicted"] in ("PASS", "NONE")
        )
        abstained_on_fail = sum(
            1 for r in selected if r["expected"] == "FAIL" and r["predicted"] == "REVIEW"
        )
        precision = _ratio(tp, tp + fp)
        recall_strict = _ratio(tp, tp + fn + abstained_on_fail)
        f1 = (
            round(2 * precision * recall_strict / (precision + recall_strict), 3)
            if precision and recall_strict
            else None
        )
        confusion: dict[str, dict[str, int]] = {}
        for r in selected:
            confusion.setdefault(r["expected"], {})
            confusion[r["expected"]][r["predicted"]] = confusion[r["expected"]].get(r["predicted"], 0) + 1
        return {
            "n": len(selected),
            "agreement": _ratio(sum(1 for r in selected if r["expected"] == r["predicted"]), len(selected)),
            "reviewPredicted": sum(1 for r in selected if r["predicted"] == "REVIEW"),
            "failPrecision": precision,
            # REVIEW on an expected FAIL counts against recall here: the checker
            # did not detect it, it only handed it to a person.
            "failRecall": recall_strict,
            "failF1": f1,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "failSentToReview": abstained_on_fail,
            "confusion": confusion,
        }

    slices: dict[str, Any] = {"all": summarise(rows)}
    for key in ("real", "synthetic"):
        slices[key] = summarise([r for r in rows if r["origin"] == key])
    for category in ("term", "internal", "fact"):
        slices[f"real/{category}"] = summarise(
            [r for r in rows if r["origin"] == "real" and r["category"] == category]
        )
        slices[f"synthetic/{category}"] = summarise(
            [r for r in rows if r["origin"] == "synthetic" and r["category"] == category]
        )

    human = sum(1 for r in rows if r["labelSource"] == "human")
    return {
        "labelSources": {"human": human, "ai_provisional": len(rows) - human},
        "validatedByHuman": human == len(rows) and human > 0,
        "note": (
            "정답은 모두 AI 임시 판정이다. 아래 수치는 'AI 판정과의 일치도'이며 사람이 검증한 "
            "검사기 성능이 아니다. 단서 목록을 만든 개발 데이터(d505·08c1) 위의 수치이고 표본이 작다."
            if human == 0
            else "일부 정답만 사람이 확정했다. labelSource별로 나눠 읽는다."
        ),
        "slices": slices,
        "mismatches": [r for r in rows if r["expected"] != r["predicted"]],
        "unlabelledFindings": unlabelled,
    }


# --- CLI ---------------------------------------------------------------------


def _payload_for_case(case: str) -> dict[str, Any] | None:
    """The payload this case gives a model, built without calling one.

    A real run is restored into a temporary copy (the capture is opened
    read-only); without the capture there is no payload and facts are skipped.
    """
    from app.services.explanation.deterministic import RunExplanation
    from app.services.explanation.llm import contract

    from . import agent_cases, real_runs

    if case in real_runs.REAL_RUNS:
        run = real_runs.REAL_RUNS[case]
        if not real_runs.capture_available(run):
            return None
        with real_runs.materialise(run) as explanation:
            payload, _ = contract.build_payload(explanation)
        return payload
    if case in agent_cases.CASES:
        with agent_cases.materialise(agent_cases.CASES[case]) as explanation:
            payload, _ = contract.build_payload(explanation)
        return payload
    fixture = HERE / "fixtures" / f"{case}.json"
    if fixture.is_file():
        explanation = RunExplanation.model_validate_json(fixture.read_text(encoding="utf-8"))
        payload, _ = contract.build_payload(explanation)
        return payload
    return None


def print_quality(name: str, block: dict[str, Any] | None) -> None:
    print(f"\n=== {name} -- 설명 품질 (개발·평가용, deterministic 판정과 별개) ===")
    if block is None:
        print("  출력 없음 -- 검사하지 않음")
        return
    print(f"  규칙: {block['rules']}")
    print(f"  필수 용어 출처: {block['requiredTerms']['source']}")
    counts = block["counts"]
    for category in ("term", "internal", "fact"):
        c = counts[category]
        print(f"  {category:8} PASS {c['PASS']:3}  FAIL {c['FAIL']:3}  REVIEW {c['REVIEW']:3}")
    for term in block["terms"]:
        flag = "필수" if term["required"] else "참고"
        print(
            f"  용어 {term['termId']:14} [{flag}] {term['verdict'] or '-':6} "
            f"{term['rule']:26} 설명된 항목 {term['unitsExplained']}/{term['unitsUsed']}"
        )
    for finding in block["findings"]:
        if finding["verdict"] == "PASS":
            continue
        unit = finding["unit"] or "(전체)"
        print(
            f"  [{finding['verdict']:6}] {finding['category']:8} {unit:22} "
            f"{finding['subject'][:30]:30} {finding['detail'][:60]}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="설명 품질 검사 (모델 호출 없음, 파일을 쓰지 않음)")
    parser.add_argument("--baseline", action="append", default=[], help="baselines/ 아래 파일 이름")
    parser.add_argument("--score-labels", action="store_true", help="라벨 세트와의 일치도")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    parser.add_argument(
        "--rules", choices=sorted(LEXICON_PATHS), default=DEFAULT_RULES,
        help="--baseline 채점에 쓸 규칙 버전 (라벨 세트는 자기 버전으로 채점)",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    for name in args.baseline:
        stored = json.loads((BASELINES / name).read_text(encoding="utf-8"))
        case = stored.get("case")
        expectations_path = EXPECTATIONS / f"{case}.json"
        expectations = (
            json.loads(expectations_path.read_text(encoding="utf-8"))
            if expectations_path.is_file()
            else None
        )
        payload = _payload_for_case(case) if case else None
        block = evaluate_record(expectations, payload, stored.get("output"), rules=args.rules)
        if args.json:
            print(json.dumps({"baseline": name, "explanationQuality": block}, ensure_ascii=False, indent=2))
        else:
            print_quality(name, block)
            if payload is None:
                print("  (payload를 만들 수 없어 Run 사실 검사는 건너뜀)")

    if args.score_labels:
        labels = load_labels()
        scored = score_labels(labels, reports_for_labels(labels))
        print(json.dumps(scored, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
