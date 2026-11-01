"""What a synthesis must satisfy, checked without a model.

Only three checks live here, and each one exists because a *specific* failure
was observed or is specifically cheap to catch:

    numbers      the model may not invent or reshape a measurement
    evidence     a claim about a qualified fact must cite that qualification
    guardrail    a run that tripped a runtime guard is not a pass

Everything else is a human judgement and is reported as `needs_review` rather
than silently counted as a pass. That distinction is the whole point: a suite
that quietly passes what it cannot check is worse than no suite.

Why not text matching
---------------------

The obvious evaluator -- forbid the phrase "확정 변이" -- fails on the sentence
we most want to see:

    "...후보 기록이며, 확정된 변이 목록이 아닙니다."

The correct answer contains the banned phrase inside a negation. A blacklist
would fail it. So the semantic expectations are reduced to **structure**
instead: if a statement discusses the variant count, it must cite
`lim:UNFILTERED_VARIANTS`. Citations are machine-checkable and immune to
negation, hedging and word order.

The one place text is inspected is number extraction, where negation does not
apply -- a digit is a digit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# eval -> app. Never the reverse: the request path must not depend on a test
# harness. The shared rules live in the application because the runtime enforces
# them on every synthesis; this module only scores what they find.
from app.services.explanation.llm import validation

# not_run: 모델을 부르지 않아 채점할 출력이 없다. pass도 fail도 아니다.
Outcome = Literal["pass", "fail", "needs_review", "not_run"]


@dataclass
class CheckResult:
    """One expectation, evaluated."""

    name: str
    outcome: Outcome
    detail: str = ""
    # Human rubric entries carry no verdict until a person fills one in.
    kind: Literal["deterministic", "human"] = "deterministic"
    # Numbers an aggregate needs and a detail string cannot carry reliably --
    # step-selection precision and recall. None for every check that has none,
    # and then absent from the JSON, so records of the frozen cases keep the
    # shape their baselines were written in.
    metrics: dict[str, Any] | None = None


@dataclass
class EvalReport:
    case: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if r.outcome == "fail"]

    @property
    def needs_review(self) -> list[CheckResult]:
        return [r for r in self.results if r.outcome == "needs_review"]

    @property
    def ok(self) -> bool:
        """No deterministic failure. Human items are NOT counted as passes."""
        return not self.failed

    def to_json(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "deterministicPassed": self.ok,
            "results": [_result_json(r) for r in self.results],
        }


def _result_json(r: CheckResult) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": r.name,
        "outcome": r.outcome,
        "kind": r.kind,
        "detail": r.detail,
    }
    if r.metrics is not None:
        out["metrics"] = r.metrics
    return out


# --- A. numbers --------------------------------------------------------------
#
# The rules themselves now live in the application, not here:
#
#     app/services/explanation/llm/validation.py
#
# They were moved because the runtime enforces them too -- a synthesis that
# states an unrecorded number is refused before a user sees it, rather than
# being noticed later in a review. Two copies of the same rule would drift, and
# the copy that mattered would be the one nobody re-read.
#
# What stays here is the scoring: turning a finding into a CheckResult with a
# name and a Korean detail line is an eval concern and has no place in the
# request path. The import direction is eval -> app, never the reverse.

collect_known_numbers = validation.collect_known_numbers
collect_property_names = validation.collect_property_names


def check_numbers(
    statements: list[str], facts: dict[str, Any], allow_small_ordinals: bool = True
) -> CheckResult:
    """No number in the output that the run did not record.

    `facts` is the fixture here, not the payload. That is the source the
    recorded baselines were scored against, so it is left as it was; the
    runtime gate deliberately uses the payload instead, and validation.py says
    why.
    """
    invented = validation.find_unsupported_numbers(
        statements, facts, allow_small_ordinals=allow_small_ordinals
    )
    if invented:
        return CheckResult(
            name="numbers-preserved",
            outcome="fail",
            detail=f"run에 없는 숫자: {invented}",
        )
    return CheckResult(
        name="numbers-preserved",
        outcome="pass",
        detail=f"{len(validation.collect_known_numbers(facts))}개 사실 숫자와 대조",
    )


# --- B. evidence relations ---------------------------------------------------


def check_evidence_relation(
    synthesis: dict[str, Any],
    *,
    name: str,
    trigger_refs: list[str],
    required_ref: str,
) -> CheckResult:
    """A statement citing any `trigger_refs` must also cite `required_ref`.

    This is how a semantic rule becomes structural. "Do not call 52,379 a
    confirmed variant list" is hard to check in prose and trivial to check as:
    a statement that cites `run:variantCalling` must also cite
    `lim:UNFILTERED_VARIANTS`.

    Vacuous truth is reported, not hidden: if nothing cited the trigger at all,
    the relation was never exercised and the result is `needs_review` rather
    than a pass.
    """
    triggered = 0
    violations: list[str] = []

    for group in (
        "importantFindings",
        "limitations",
        "nextChecks",
        "uncertainties",
    ):
        for item in synthesis.get(group) or []:
            refs = set(item.get("evidenceRefs") or [])
            if not refs & set(trigger_refs):
                continue
            triggered += 1
            if required_ref not in refs:
                violations.append(item.get("statement", "")[:70])

    if triggered == 0:
        return CheckResult(
            name=name,
            outcome="needs_review",
            detail=f"{trigger_refs} 를 인용한 문장이 없어 관계가 검증되지 않음",
        )
    if violations:
        return CheckResult(
            name=name,
            outcome="fail",
            detail=f"{required_ref} 없이 서술: {violations}",
        )
    return CheckResult(
        name=name, outcome="pass", detail=f"{triggered}개 문장이 관계를 지킴"
    )


def check_ref_cited(
    synthesis: dict[str, Any], *, name: str, ref: str
) -> CheckResult:
    """This evidence id must be cited somewhere.

    Used for facts a reader must not leave without -- the automatic repair, the
    intended-use boundary. It says nothing about *how* it was described; that
    is a human judgement.
    """
    for group in (
        "importantFindings",
        "limitations",
        "nextChecks",
        "uncertainties",
    ):
        for item in synthesis.get(group) or []:
            if ref in (item.get("evidenceRefs") or []):
                return CheckResult(name=name, outcome="pass", detail=f"{ref} 인용됨")
    return CheckResult(
        name=name, outcome="fail", detail=f"{ref} 를 인용한 문장이 없음"
    )


def check_mentions(statements: list[str], needles: list[str], *, name: str):
    """Required literals appear somewhere in the output.

    Only for values, never for phrasing -- `52379` must be mentioned, but how
    it is described is not this check's business.
    """
    joined = " ".join(statements)
    compact = joined.replace(",", "")
    missing = [n for n in needles if n not in joined and n.replace(",", "") not in compact]
    if missing:
        return CheckResult(
            name=name, outcome="fail", detail=f"언급되지 않음: {missing}"
        )
    return CheckResult(name=name, outcome="pass", detail=f"{len(needles)}개 모두 언급")


# --- D. internal names in user-facing prose ---------------------------------

def check_no_internal_names(
    statements: list[str], payload: Any, *, name: str = "no-internal-field-names"
) -> CheckResult:
    """User-facing prose must not quote the payload's property names.

    The first baseline was accurate and still hard to read: the model wrote
    `basesInLowMeanDepthIntervalsPct` and `rawVariantRecords` in sentences
    meant for a beginner. It had been told to -- an earlier prompt rule said to
    "describe it with the field's own wording".

    The rule (camelCase only, derived from the payload's own keys) is in
    validation.py and is enforced at runtime as well. Only the scoring is here.
    """
    known = validation.camel_case_property_names(payload)
    if not known:
        return CheckResult(name=name, outcome="pass", detail="camelCase 키 없음")

    found = validation.find_exposed_property_names(statements, payload)
    if found:
        return CheckResult(
            name=name,
            outcome="fail",
            detail=f"사용자 문장에 내부 필드명: {found}",
        )
    return CheckResult(
        name=name, outcome="pass", detail=f"{len(known)}개 키 중 노출 0"
    )


# --- E. tool selection -------------------------------------------------------
#
# A different question from everything above, and the reason it is a separate
# pair of checks rather than another clause in one of them:
#
#     the checks above   did the ANSWER stay inside its evidence?
#     these two          did the agent GO AND GET the right evidence?
#
# An answer can be perfectly grounded and still be thin because the agent never
# opened the step that explains the failure; that costs nothing in the checks
# above and is exactly what these two see.
#
# The observation comes from `tools.observe()`, i.e. from what the MCP server
# recorded answering. A model's own claim that it consulted a step is not
# evidence that it did, and is never read here.
#
# How much a case needs the tool `[설계판단]`
# -----------------------------------------
#
#     required    the case cannot be explained without a fact only the tool
#                 returns. Not using it is a missed call.
#     forbidden   the payload already answers everything. Using it is a false
#                 call.
#     optional    the payload is enough, and opening the step is also a
#                 defensible reading. Whether the tool was called is NOT
#                 scored -- only recorded -- and which steps were opened still
#                 is, if any were.
#
# `optional` exempts exactly one check, tool-use. Every check on the answer
# itself -- guardrails, numbers, citations, human review -- runs as for any
# other case. Not needing the tool is not the same as not needing to be right.
#
# The two agent cases that used to say `true` were re-read against the payload
# they actually produce, and both carry their key facts in it already (the
# failed check row reaches checkSummary.notable; the warning's impact line
# reaches diagnostics). Calling the tool mandatory there scored a habit, not a
# need. `true` / `false` are still accepted and mean required / forbidden.

ToolNeed = Literal["required", "optional", "forbidden"]
# A mapping rather than a tuple so the lookup returns the Literal type itself.
_TOOL_NEEDS: dict[str, ToolNeed] = {
    "required": "required",
    "optional": "optional",
    "forbidden": "forbidden",
}


def tool_need(expectations: dict[str, Any]) -> ToolNeed:
    """The case's `expectedToolUse`, normalised.

    Exists because a plain truth test is wrong here: the string "forbidden" is
    truthy, so `if expectations["expectedToolUse"]` would read it as "needs the
    tool". Every reader of the field goes through this instead. An unknown
    value raises rather than falling into one of the three.
    """
    raw = expectations.get("expectedToolUse")
    if raw is True:
        return "required"
    if raw is False:
        return "forbidden"
    if isinstance(raw, str) and raw in _TOOL_NEEDS:
        return _TOOL_NEEDS[raw]
    raise ValueError(
        f"expectedToolUse must be one of {sorted(_TOOL_NEEDS)} or a bool, got {raw!r}"
    )


def acceptable_step_sets(expectations: dict[str, Any]) -> list[frozenset[str]]:
    """Every step selection this case accepts as correct.

    `acceptableStepSets` when the case has more than one defensible answer --
    the failed-step case accepts {04} and also {04, 00}, which is what a rule
    "on failure, also read input validation" selects. Without it the case's
    single `expectedStepIds` is the only answer, which is exactly the strict
    set equality this check applied before the field existed.
    """
    raw = expectations.get("acceptableStepSets")
    if raw is None:
        return [frozenset(expectations.get("expectedStepIds") or [])]
    return [frozenset(steps) for steps in raw]


def _core_and_allowed(
    sets: list[frozenset[str]],
) -> tuple[frozenset[str], frozenset[str]]:
    """core = in every accepted set (must open); allowed = in any (may open)."""
    core = frozenset.intersection(*sets) if sets else frozenset()
    allowed = frozenset().union(*sets) if sets else frozenset()
    return core, allowed


def _selection_metrics(
    opened: set[str], core: frozenset[str], allowed: frozenset[str]
) -> dict[str, Any]:
    """Recall against what must be opened, precision against what may be.

    None where the ratio has no denominator, rather than 0 or 1: "opened
    nothing" has no precision, and a case with no core step has no recall.
    """
    return {
        "openedStepIds": sorted(opened),
        "coreStepIds": sorted(core),
        "allowedStepIds": sorted(allowed),
        "recall": len(opened & core) / len(core) if core else None,
        "precision": len(opened & allowed) / len(opened) if opened else None,
    }


def _fmt_sets(sets: list[frozenset[str]]) -> str:
    return " | ".join(str(sorted(s)) for s in sets)


def check_tool_use(
    expectations: dict[str, Any], tool_use: dict[str, Any] | None
) -> CheckResult:
    """Did the agent use the tool when the case needed it, and not when not?

    Both directions fail for a required or forbidden case. Not fetching the one
    thing that would explain the run leaves the reader where they started;
    fetching when the payload already answers spends a turn, widens what the
    model can talk about, and is a habit that gets worse with more tools.

    An optional case is reported `not_run`: whether the call happened is
    written in the detail and in `metrics`, so it can be counted, but it is
    neither a pass nor a fail.
    """
    need = tool_need(expectations)
    used = bool((tool_use or {}).get("toolUsed"))
    opened = list((tool_use or {}).get("openedStepIds") or [])

    if need == "optional":
        return CheckResult(
            name="tool-use",
            outcome="not_run",
            detail=(
                f"Tool 사용이 선택인 case라 호출 여부는 채점하지 않음 · "
                f"{'호출함: ' + str(opened) if used else '호출 안 함'}"
            ),
            metrics={"toolUsed": used},
        )
    if need == "required" and not used:
        return CheckResult(
            name="tool-use",
            outcome="fail",
            detail="step 상세가 필요한 case인데 Tool을 호출하지 않음",
        )
    if need == "forbidden" and used:
        return CheckResult(
            name="tool-use",
            outcome="fail",
            detail=f"payload만으로 답할 수 있는 case인데 step을 열었음: {opened}",
        )
    if need == "required":
        return CheckResult(
            name="tool-use", outcome="pass", detail=f"필요한 case에서 호출함: {opened}"
        )
    return CheckResult(
        name="tool-use", outcome="pass", detail="불필요한 호출 없음"
    )


def _selection_not_scored(
    name: str, need: ToolNeed, opened: set[str]
) -> CheckResult | None:
    """The not_run cases shared by both selection checks, or None to score.

    A forbidden case has no selection to judge, and an optional case in which
    nothing was opened has none either. Calling either a pass would inflate the
    suite with checks that cannot fail.
    """
    if need == "forbidden":
        return CheckResult(
            name=name, outcome="not_run", detail="Tool 사용을 기대하지 않는 case"
        )
    if need == "optional" and not opened:
        return CheckResult(
            name=name,
            outcome="not_run",
            detail="Tool 사용이 선택인 case에서 step을 열지 않음",
        )
    return None


def check_step_selection(
    expectations: dict[str, Any], tool_use: dict[str, Any] | None
) -> CheckResult:
    """Is the set of opened steps one of the selections this case accepts?

    Set equality against each accepted set, not containment `[설계판단]`. The
    budget is two steps, so an extra step is not free: a step outside every
    accepted set is one the run's own evidence did not point at, and treating
    that as a pass would make "chose the right place" mean "included the right
    place somewhere".

    Precision and recall ride along in `metrics` as supporting numbers; the
    outcome is decided by membership alone. A missing core step is also
    reported on its own by check_step_core, so a failure here can be told
    apart: wrong extra step, or the essential one missed.
    """
    name = "tool-step-selection"
    need = tool_need(expectations)
    opened = set((tool_use or {}).get("openedStepIds") or [])

    skipped = _selection_not_scored(name, need, opened)
    if skipped is not None:
        return skipped

    sets = acceptable_step_sets(expectations)
    core, allowed = _core_and_allowed(sets)
    metrics = _selection_metrics(opened, core, allowed)

    if not opened:
        return CheckResult(
            name=name,
            outcome="fail",
            detail=f"연 step이 없음. 허용: {_fmt_sets(sets)}",
            metrics=metrics,
        )
    if frozenset(opened) in sets:
        return CheckResult(
            name=name,
            outcome="pass",
            detail=f"허용 조합과 일치: {sorted(opened)}",
            metrics=metrics,
        )
    missing = sorted(core - opened)
    extra = sorted(opened - allowed)
    return CheckResult(
        name=name,
        outcome="fail",
        detail=(
            f"허용 {_fmt_sets(sets)} · 열림 {sorted(opened)} · "
            f"핵심 누락 {missing} · 허용 밖 {extra}"
        ),
        metrics=metrics,
    )


def check_step_core(
    expectations: dict[str, Any], tool_use: dict[str, Any] | None
) -> CheckResult:
    """Did the agent open every step that all accepted answers contain?

    A separate record from check_step_selection on purpose. "Opened 04 and an
    extra 05" and "never opened 04" both fail selection, but only the second
    leaves the explanation without its evidence. This check fails only for that
    one.

    `not_run` when no core step is defined -- e.g. a case that accepts the
    empty selection -- because then nothing is essential.
    """
    name = "tool-step-core"
    need = tool_need(expectations)
    opened = set((tool_use or {}).get("openedStepIds") or [])

    skipped = _selection_not_scored(name, need, opened)
    if skipped is not None:
        return skipped

    core, _allowed = _core_and_allowed(acceptable_step_sets(expectations))
    if not core:
        return CheckResult(
            name=name, outcome="not_run", detail="모든 허용 조합에 공통인 step이 없음"
        )
    missing = sorted(core - opened)
    if missing:
        return CheckResult(
            name=name, outcome="fail", detail=f"핵심 step을 열지 않음: {missing}"
        )
    return CheckResult(
        name=name, outcome="pass", detail=f"핵심 step을 모두 열었음: {sorted(core)}"
    )


# --- C. runtime guardrail outcome --------------------------------------------


def check_guardrails(result: dict[str, Any]) -> CheckResult:
    """A tripped guardrail is a failed evaluation, not a skipped one.

    The guards are not re-implemented here -- `build_run_synthesis` already ran
    them. This only reads the verdict. A response discarded for citing evidence
    that was never supplied is exactly the quality failure an eval exists to
    surface.
    """
    if result.get("available"):
        return CheckResult(
            name="runtime-guardrails", outcome="pass", detail="발동 없음"
        )
    category = result.get("errorCategory") or "unknown"
    quality = {"unknownEvidenceRef", "invalidSynthesis"}
    if category in quality:
        return CheckResult(
            name="runtime-guardrails",
            outcome="fail",
            detail=f"모델 출력이 guardrail에 걸림: {category}",
        )
    # provider 쪽 사고(로그인·한도·timeout)는 모델 품질 문제가 아니다.
    return CheckResult(
        name="runtime-guardrails",
        outcome="fail",
        detail=f"provider 실패로 평가 불가: {category}",
    )


# --- statements --------------------------------------------------------------


def all_statements(synthesis: dict[str, Any]) -> list[str]:
    """Every sentence the model wrote, summary included."""
    out: list[str] = []
    summary = synthesis.get("summary")
    if summary:
        out.append(summary)
    for group in (
        "importantFindings",
        "limitations",
        "nextChecks",
        "uncertainties",
    ):
        for item in synthesis.get(group) or []:
            statement = item.get("statement")
            if statement:
                out.append(statement)
    return out


# --- expectations -> checks --------------------------------------------------


def run_expectations(
    expectations: dict[str, Any],
    fixture: dict[str, Any],
    result: dict[str, Any],
    payload: dict[str, Any] | None = None,
    model_invoked: bool = True,
    tool_use: dict[str, Any] | None = None,
    fetched_facts: list[Any] | None = None,
    tools_offered: bool = True,
) -> EvalReport:
    """Apply one case's expectations to one synthesis result.

    `payload` is optional only so older callers keep working; when it is given
    the internal-name check runs against the exact keys the model saw.

    `tool_use` is what the MCP server recorded during the call, as
    `tools.observe()` shapes it. The three tool checks run only for a case
    whose expectations declare `expectedToolUse`, so the four original cases
    score exactly as they did before. An `optional` case exempts the tool-use
    check alone; everything that scores the answer runs as usual.

    `fetched_facts` is what the tool RETURNED, and it belongs to the number
    check: an agent that opened a step was shown that step's measurements, so
    quoting one is not invention. Without it the first agent eval reported a
    correctly fetched `18.4` as a made-up number -- the same trap the runtime
    gate avoids by scoring against payload + tool results. Omitted for the four
    frozen cases, whose fact source stays the fixture exactly as recorded.

    `model_invoked=False` means the case was deliberately not sent to a model.
    Then there is no output to score: the output-dependent checks are reported
    as `not_run`, not as passes and not as failures. Deciding not to ask is not
    the same as asking and being refused.

    `tools_offered=False` is the no-tool variant (V1). The model had no tool,
    so whether it used one is not a question: the three tool checks are
    `not_run`. Scoring them would let a `forbidden` case pass for a model that
    never had the choice. Everything that scores the answer still runs.
    """
    report = EvalReport(case=expectations.get("case", "unknown"))

    if not model_invoked:
        # 모델을 부르지 않았다. 출력에 의존하는 검사는 전부 not_run이다 --
        # deterministic 계약 검사(privacy 등)는 호출부가 따로 붙인다.
        if "expectedToolUse" in expectations:
            # Tool 사용 여부도 모델이 결정하는 것이므로 마찬가지다.
            for name in ("tool-use", "tool-step-selection", "tool-step-core"):
                report.results.append(
                    CheckResult(name=name, outcome="not_run", detail="모델 호출 안 함")
                )
        for name in ("runtime-guardrails", "numbers-preserved", "no-internal-field-names"):
            report.results.append(
                CheckResult(name=name, outcome="not_run", detail="모델 호출 안 함")
            )
        for spec in expectations.get("mustCite", []):
            report.results.append(
                CheckResult(
                    name=spec["name"], outcome="not_run", detail="모델 호출 안 함"
                )
            )
        for spec in expectations.get("humanReview", []):
            report.results.append(
                CheckResult(
                    name=spec["name"],
                    outcome="not_run",
                    detail=spec["question"],
                    kind="human",
                )
            )
        return report

    if "expectedToolUse" in expectations and not tools_offered:
        for name in ("tool-use", "tool-step-selection", "tool-step-core"):
            report.results.append(
                CheckResult(
                    name=name, outcome="not_run", detail="Tool 미제공 variant"
                )
            )
    elif "expectedToolUse" in expectations:
        # Scored BEFORE the guardrail early-return on purpose: how the agent
        # searched is knowable even when its answer was discarded, and losing
        # that would hide the most useful half of an agent failure.
        report.results.append(check_tool_use(expectations, tool_use))
        report.results.append(check_step_selection(expectations, tool_use))
        report.results.append(check_step_core(expectations, tool_use))

    guard = check_guardrails(result)
    report.results.append(guard)
    if guard.outcome == "fail":
        # 출력이 없으므로 나머지는 평가할 수 없다. 통과로 위장하지 않는다.
        for spec in expectations.get("humanReview", []):
            report.results.append(
                CheckResult(
                    name=spec["name"],
                    outcome="needs_review",
                    detail="synthesis 없음",
                    kind="human",
                )
            )
        return report

    synthesis = result.get("synthesis") or {}
    statements = all_statements(synthesis)

    facts: Any = [fixture, *fetched_facts] if fetched_facts else fixture
    report.results.append(check_numbers(statements, facts))

    if payload is not None:
        report.results.append(check_no_internal_names(statements, payload))

    mention = expectations.get("mustMention") or []
    if mention:
        report.results.append(
            check_mentions(statements, mention, name="must-mention")
        )

    for spec in expectations.get("mustCite", []):
        report.results.append(
            check_ref_cited(synthesis, name=spec["name"], ref=spec["ref"])
        )

    for spec in expectations.get("mustQualify", []):
        report.results.append(
            check_evidence_relation(
                synthesis,
                name=spec["name"],
                trigger_refs=spec["whenCiting"],
                required_ref=spec["mustAlsoCite"],
            )
        )

    for spec in expectations.get("humanReview", []):
        report.results.append(
            CheckResult(
                name=spec["name"],
                outcome="needs_review",
                detail=spec["question"],
                kind="human",
            )
        )

    return report
