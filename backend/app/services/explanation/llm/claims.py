"""Gates 6 and 7: a sentence against the structured fact it talks about.

validation.py asks whether a number or a name appears anywhere in what the
model was shown. That loses the link between a value and what it measures, so
"평균 깊이는 1420배" passed: 1420 is in the payload -- as a step's elapsed
seconds. This module keeps the link, for a few facts the payload states as
structured fields, and only where a sentence's wording pins down which fact it
is about.

    gate 6  runFactMismatch    a named measurement carries another value; the
                               warning-step count, or a step said to have
                               warned, contradicts the step list
    gate 7  evidenceMismatch   a statement about a diagnostic-only topic
                               (dbSNP, NM/MD tags) cites none of that
                               diagnostic's evidence; a qualified fact is
                               stated and its qualification is cited nowhere

What this does NOT do
---------------------

It does not decide whether a sentence is true. Each rule fires only on a narrow
wording -- a subject phrase followed closely by a number in that subject's
unit, a step count written next to "경고" -- and stays silent otherwise. A
paraphrase it does not recognise passes, exactly as before. Silence is not a
verdict; the eval harness and a human reviewer still read the answer.

Every value compared comes from the payload at request time: the measured mean
depth, the steps whose status is "warning", the diagnostics this run raised and
the terms knowledge links to them. Nothing here holds a number of its own, so a
run without a coverage section, steps or a diagnostic simply has no rule for
it.

Why a rule is narrow on purpose
-------------------------------

- A number after a subject phrase counts only when it is written in that
  subject's unit and is not a threshold ("20배 미만"). "평균 깊이가 0보다 커도"
  states no depth.
- Anything about intervals ("구간") is skipped: the payload has interval-level
  and base-level figures that are both correct and easily confused, and telling
  them apart from a sentence is the kind of judgement this module refuses.
- Text in parentheses is ignored -- that is where answers gloss terms ("구간
  단위가 아니라 ...").
- `summary` carries no evidenceRefs, so gate 7 never reads it; gate 6 does.

Location
--------

Each finding names the items it came from ("summary", "importantFindings.3").
The rewrite request passes those on, and synthesis.py keeps every other item of
the first answer as it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import knowledge
from . import validation

GROUPS = ("importantFindings", "limitations", "nextChecks", "uncertainties")


@dataclass(frozen=True)
class Unit:
    """One piece of prose a reader sees, with where it sits and what it cites."""

    location: str
    text: str
    refs: frozenset[str]


def units(answer: dict[str, Any]) -> list[Unit]:
    """The summary and every statement of an already-validated answer."""
    out = [Unit("summary", str(answer.get("summary") or ""), frozenset())]
    for group in GROUPS:
        for index, item in enumerate(answer.get(group) or []):
            out.append(
                Unit(
                    f"{group}.{index}",
                    str(item.get("statement") or ""),
                    frozenset(item.get("evidenceRefs") or []),
                )
            )
    return out


_PARENS = re.compile(r"\([^()]*\)")
_CLAUSE_END = re.compile(r"(?<=[.!?])\s+|[;\n]")
# Within this many characters after the subject phrase, the first number is
# the one the phrase introduces. Farther than that, the sentence has usually
# moved on to something else.
_WINDOW = 20
_INTERVAL = "구간"
_THRESHOLD_AFTER = re.compile(r"^\s*(미만|이상|이하|초과|보다|을 넘|를 넘|까지)")


def _clauses(text: str) -> list[str]:
    return [c for c in _CLAUSE_END.split(_PARENS.sub(" ", text)) if c.strip()]


# --- gate 6a: a named measurement and its value ------------------------------


@dataclass(frozen=True)
class _Measure:
    """How a sentence names one measurement, and which payload fields hold the
    values it may carry, per unit. Values are read from the payload."""

    name: str
    section: str
    subject: re.Pattern[str]
    by_unit: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...]


_MEASURES: tuple[_Measure, ...] = (
    _Measure(
        name="평균 깊이",
        section="coverage",
        subject=re.compile(r"평균\s?(깊이|depth|커버리지)"),
        by_unit=((re.compile(r"^\s*(배|[xX×])"), ("meanTargetDepth",)),),
    ),
    _Measure(
        name="한 번도 읽히지 않은(0×) 염기",
        section="coverage",
        subject=re.compile(
            r"한\s?번도\s?(읽|덮)|읽(은|힌)\s?기록이\s?(한\s?번도\s?)?없"
            r"|(?<![\d.,])0\s?[xX×배](?!\d)|깊이가?\s?0인"
        ),
        by_unit=(
            (re.compile(r"^\s*%"), ("zeroCoverageBasesPct",)),
            (re.compile(r"^\s*(개|곳)"), ("zeroCoverageBases",)),
        ),
    ),
    _Measure(
        name="변이 후보 기록 수",
        section="variantCalling",
        subject=re.compile(r"변이\s?(후보\s?)?(기록|레코드)|후보\s?(기록|레코드)|레코드"),
        by_unit=((re.compile(r"^\s*(개|건)"), ("rawVariantRecords",)),),
    ),
)


def _value(section: dict[str, Any], field: str) -> str | None:
    value = section.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return validation.normalise_number(repr(value) if isinstance(value, float) else str(value))


def _measure_findings(unit: Unit, payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for measure in _MEASURES:
        section = payload.get(measure.section)
        if not isinstance(section, dict):
            continue
        for clause in _clauses(unit.text):
            for subject in measure.subject.finditer(clause):
                if _INTERVAL in clause[max(0, subject.start() - 6) : subject.start()]:
                    continue
                window = clause[subject.end() : subject.end() + _WINDOW]
                number = validation.NUMBER.search(window)
                if number is None or _INTERVAL in window[: number.start()]:
                    continue
                if any(m.subject.match(window, number.start()) for m in _MEASURES):
                    # "평균 깊이나 0× 비율": the number opens another subject.
                    continue
                rest = window[number.end() :] + clause[subject.end() + _WINDOW :]
                for unit_pattern, fields in measure.by_unit:
                    written = unit_pattern.match(rest)
                    if written is None:
                        continue
                    if _THRESHOLD_AFTER.match(rest[written.end() :]):
                        break
                    accepted = {v for f in fields if (v := _value(section, f)) is not None}
                    if not accepted:
                        break
                    stated = validation.normalise_number(number.group())
                    if stated not in accepted:
                        problems.append(
                            f"{measure.name}: written as {number.group()}, "
                            f"the data gives {', '.join(sorted(accepted))}"
                        )
                    break
    return problems


# --- gate 6b: warning steps --------------------------------------------------

_COUNT_WORDS = {
    "한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4,
    "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
    "열한": 11, "열두": 12,
}
_NUM = r"(\d+|" + "|".join(sorted(_COUNT_WORDS, key=len, reverse=True)) + r")"
_DONE = r"(기록된|끝난|난|발생한|나온|남은|있는|있었던)"
_COUNT_PATTERNS = (
    # "세 단계에서 경고", "3개 단계가 경고로 끝났습니다"
    re.compile(rf"(?<![가-힣\d.,]){_NUM}\s?(개\s?)?(의\s?)?단계(에서|가|는|이|도)?\s?(모두\s?)?경고"),
    # "경고로 끝난 단계는 모두 3개", "경고가 기록된 단계는 3단계"
    re.compile(rf"경고(가|로|를)?\s?{_DONE}\s?단계(는|가|은)?\s?(모두\s?|총\s?)?{_NUM}\s?(개|단계)"),
    # "경고 단계는 5개"
    re.compile(rf"경고\s?단계(는|가|은)?\s?(모두\s?|총\s?)?{_NUM}\s?(개|단계)"),
)
_NONE_CLAIM = re.compile(r"경고(가|는)?\s?(하나도\s?|전혀\s?)?(없었|없습|없이\s?(완료|끝))")
_NOT_A_CLAIM = re.compile(r"^.{0,15}(뜻|의미|것)(은|이)?\s?아니")
_NEGATED_AFTER = re.compile(r"^.{0,10}(없|않|아니)")
# Where a list of warned steps stops: what follows is about the others.
_LIST_STOP = re.compile(r"나머지|반면|외에|제외|정상|경고\s?없|없이|않")


def _count_of(token: str) -> int:
    return int(token) if token.isdigit() else _COUNT_WORDS[token]


def _step_labels() -> dict[str, str]:
    """label -> stepId, for every step knowledge names."""
    return {step.label: step.stepId for step in knowledge.all_steps()}


def _warning_findings(unit: Unit, payload: dict[str, Any]) -> list[str]:
    steps = (payload.get("steps") or {}).get("planned")
    if not isinstance(steps, list):
        return []
    warned = {s.get("stepId") for s in steps if s.get("status") == "warning"}
    labels = _step_labels()
    problems: list[str] = []
    for clause in _clauses(unit.text):
        for pattern in _COUNT_PATTERNS:
            for found in pattern.finditer(clause):
                token = next(g for g in found.groups() if g and (g.isdigit() or g in _COUNT_WORDS))
                if _count_of(token) != len(warned):
                    problems.append(
                        f"warning steps: written as {token}, the run has {len(warned)}"
                    )
        if warned:
            for found in _NONE_CLAIM.finditer(clause):
                if "단계" in clause:
                    # About a step ("정렬 단계는 경고 없이"), possibly by a
                    # shortened name that matches no label -- not the run.
                    continue
                if _NOT_A_CLAIM.match(clause[found.end() :]):
                    continue
                problems.append(f"warning steps: written as none, the run has {len(warned)}")
        for label, step_id in labels.items():
            if step_id in warned:
                continue
            adjacent = re.compile(
                re.escape(label) + r"(\s?단계)?(에서|은|는|가|이|도)?\s?(도\s?)?경고(가|로|를|와)?"
            )
            for found in adjacent.finditer(clause):
                if _NEGATED_AFTER.match(clause[found.end() :]):
                    continue
                problems.append(f"warning steps: {label} did not end with a warning")
        listing = re.search(rf"경고(가|로)?\s?{_DONE}\s?단계(는|은|가)", clause)
        if listing:
            tail = clause[listing.end() :]
            stop = _LIST_STOP.search(tail)
            tail = tail[: stop.start()] if stop else tail
            for label, step_id in labels.items():
                if step_id not in warned and label in tail:
                    problems.append(f"warning steps: {label} did not end with a warning")
    return sorted(set(problems))


def find_run_fact_mismatches(
    answer: dict[str, Any], payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Gate 6. One entry per item that contradicts a structured run fact."""
    out: list[dict[str, Any]] = []
    for unit in units(answer):
        problems = _measure_findings(unit, payload) + _warning_findings(unit, payload)
        if problems:
            out.append({"location": unit.location, "problems": problems})
    return out


# --- gate 7: evidence that fits the claim ------------------------------------

# A fact that must not be stated without its qualification: the limitation
# code, and the payload section the qualified figures live in. Active only when
# the payload carries both -- a run whose variants were filtered has no such
# limitation and no rule. The eval harness keeps the stricter per-statement
# form (mustQualify); the runtime asks only that the answer cite it somewhere,
# because a statement that already says "후보 기록" without the citation is
# not a wrong statement.
_QUALIFIERS: dict[str, str] = {"UNFILTERED_VARIANTS": "variantCalling"}


def _mask_steps(text: str) -> str:
    for label in _step_labels():
        text = text.replace(label, " ")
    return text


def _topic_terms(payload: dict[str, Any], allowed: set[str]) -> list[tuple[list[str], set[str], str]]:
    """(cues, accepted refs, topic) for each term that knowledge ties only to
    diagnostics or failures -- never to a section -- and that this run raised.
    A statement using such a word is about that diagnostic, so one of its ids,
    the term's own id or a source behind them must be among the citations."""
    grounding = payload.get("grounding") or {}
    out: list[tuple[list[str], set[str], str]] = []
    for entry in payload.get("terms") or []:
        ref = entry.get("evidenceId")
        if not isinstance(ref, str) or not ref.startswith("term:"):
            continue
        term = knowledge.term(ref[len("term:") :])
        if term is None or term.usedWhen.sections:
            continue
        owners = {f"dx:{c}" for c in term.usedWhen.diagnostics} | {
            f"fail:{c}" for c in term.usedWhen.failures
        }
        owners &= allowed
        if not owners:
            continue
        accepted = set(owners) | {ref}
        for owner in owners:
            for bucket in ("possibleCauses", "scope", "checks", "actions"):
                for claim in (grounding.get(owner) or {}).get(bucket) or []:
                    accepted |= {f"src:{s}" for s in claim.get("sourceIds") or []}
        for claim in [entry.get("definition") or {}, *(entry.get("misreadings") or [])]:
            accepted |= {f"src:{s}" for s in claim.get("sourceIds") or []}
        cues = [part.strip() for part in term.label.split(" / ")] + list(term.aliases)
        out.append((cues, accepted & allowed, term.label))
    return out


def find_evidence_mismatches(
    answer: dict[str, Any], payload: dict[str, Any], allowed: set[str]
) -> list[dict[str, Any]]:
    """Gate 7. One entry per item whose citations do not fit what it says."""
    found: dict[str, list[str]] = {}
    statements = [u for u in units(answer) if u.location != "summary"]

    for cues, accepted, topic in _topic_terms(payload, allowed):
        for unit in statements:
            text = _mask_steps(unit.text)
            if any(cue in text for cue in cues) and not unit.refs & accepted:
                found.setdefault(unit.location, []).append(
                    f"talks about {topic} but cites none of: {', '.join(sorted(accepted))}"
                )

    cited = set().union(*(u.refs for u in statements)) if statements else set()
    for code, section_name in _QUALIFIERS.items():
        lim = f"lim:{code}"
        section = payload.get(section_name)
        if lim not in allowed or not isinstance(section, dict) or lim in cited:
            continue
        section_ref = section.get("evidenceId")
        values = {
            v for k in section if (v := _value(section, k)) is not None
            and not validation.is_small_ordinal(v)
        }
        for unit in units(answer):
            numbers = {validation.normalise_number(t) for t in validation.NUMBER.findall(unit.text)}
            if section_ref in unit.refs or numbers & values:
                found.setdefault(unit.location, []).append(
                    f"states what {section_ref} qualifies without {lim} cited anywhere; "
                    f"add {lim} to this item's evidenceRefs"
                )
    return [{"location": loc, "problems": problems} for loc, problems in found.items()]


__all__ = [
    "GROUPS",
    "Unit",
    "find_evidence_mismatches",
    "find_run_fact_mismatches",
    "units",
]
