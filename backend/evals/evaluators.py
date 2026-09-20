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
            "results": [
                {
                    "name": r.name,
                    "outcome": r.outcome,
                    "kind": r.kind,
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }


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
) -> EvalReport:
    """Apply one case's expectations to one synthesis result.

    `payload` is optional only so older callers keep working; when it is given
    the internal-name check runs against the exact keys the model saw.

    `model_invoked=False` means the case was deliberately not sent to a model.
    Then there is no output to score: the output-dependent checks are reported
    as `not_run`, not as passes and not as failures. Deciding not to ask is not
    the same as asking and being refused.
    """
    report = EvalReport(case=expectations.get("case", "unknown"))

    if not model_invoked:
        # 모델을 부르지 않았다. 출력에 의존하는 검사는 전부 not_run이다 --
        # deterministic 계약 검사(privacy 등)는 호출부가 따로 붙인다.
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

    report.results.append(check_numbers(statements, fixture))

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
