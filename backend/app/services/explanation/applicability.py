"""Does a registered sentence apply to THIS run? -- statement kinds and conditions.

Why (2026-11-21)
----------------
Knowledge and the pipeline's fixed impact lines are written once, for every run.
Some of them silently assume a later step ran. "Per-lane FastQC still runs" is
written at preflight; "개별 FastQC 리포트는 정상적으로 생성되었습니다" is the
knowledge meaning of the same code. In a run that failed at preflight neither is
true, yet both reached the screen and the model input, under the diagnostic's own
evidence id, and served answers repeated them. Nothing compared a sentence's
presupposition with the run's execution facts (run_ledger.py).

Two separate files, by design
-----------------------------
The sentences stay where they are (wes_diagnostics.json, ...). What each sentence
IS and WHEN it applies lives in config/knowledge/wes_statement_kinds.json -- the
policy is kept apart from the text it governs, in the way a policy engine keeps
rules apart from input (Open Policy Agent), but as a few declarative operators,
not a language. Every classified entry carries the first 12 hex digits of the
SHA-256 of the sentence it was decided for, so editing a sentence without
re-deciding its entry fails the suite (test_statement_kinds.py).

    kind       what the sentence is (seven kinds below)
    runClaim   does it state something about THIS run?
                 none                 no -- a general statement
                 impliedByOccurrence  yes, and true whenever the code was raised
                                      at all (it is only raised in that situation)
                 conditional          yes, and true only when `appliesWhen` holds
    appliesWhen  only on `conditional` entries

Condition language (appliesWhen/v1)
-----------------------------------
JSON, evaluated here, never executed. Every node is exactly one of:

    {"all": [node, ...]}     every child holds
    {"any": [node, ...]}     at least one child holds
    {"not": node}
    {"stepExecution": {"step": "<stepId>" | "$occurrence", "in": [<Execution>, ...]}}
    {"occurredAt": ["<stepId>", ...]}        where the run recorded this occurrence
    {"runStatus": {"in": ["failed", ...]}}

`$occurrence` is the step the run recorded this occurrence at. Logic is three
valued (Kleene): a step whose state is `unknown`, an occurrence with no step, a
run with no step list -- all give unknown, and unknown propagates unless the
other operand settles the result (false in `all`, true in `any`). A planned list
that does not contain the step gives false: the step will never run here.

An unsupported operator, an unknown state name or a malformed node is rejected
when the file is loaded (`validate_rule`). Evaluation of something that slipped
through returns unknown -- never applicable.

Outcome
-------
    applicable      included as before
    notApplicable   withheld: contradicts this run's records
    unknown         withheld: cannot be established from this run's records

Withheld means left out of the explanation of the run (the model input and the
screen's explanatory text) -- not deleted. Every decision, with its reason, is
on the explanation as `knowledgeDecisions`, so what was left out is visible.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ... import config
from . import knowledge
from .run_ledger import Execution, RunLedger

LANGUAGE = "appliesWhen/v1"

Kind = Literal[
    # A fact this run recorded. Knowledge never contains one; listed so the
    # vocabulary covers run text too.
    "observedFact",
    # How this pipeline behaves in general (what a step does, when a code is raised).
    "pipelineBehavior",
    # Tool, format or biology knowledge, true independent of this pipeline.
    "generalKnowledge",
    # A candidate explanation, never established by the run.
    "possibleCause",
    # A result statement that holds only under a condition about the run.
    "conditionalResult",
    # Something a person can look at or do.
    "checkOrAction",
    # Not settled; stated as such.
    "unconfirmed",
]
RunClaim = Literal["none", "impliedByOccurrence", "conditional"]
Decision = Literal["applicable", "notApplicable", "unknown"]

_EXECUTIONS: frozenset[str] = frozenset(Execution.__args__)  # type: ignore[attr-defined]
_RUN_STATUSES = frozenset(
    {"queued", "running", "completed", "completed_with_warnings", "failed", "cancelled"}
)
OPERATORS = ("all", "any", "not", "stepExecution", "occurredAt", "runStatus")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# --- the condition language -------------------------------------------------


def validate_rule(node: Any, where: str = "appliesWhen") -> list[str]:
    """Every problem with a rule, as readable strings. Empty means valid."""
    if not isinstance(node, dict) or len(node) != 1:
        return [f"{where}: a node must be an object with exactly one operator"]
    (op, arg), = node.items()
    if op not in OPERATORS:
        return [f"{where}: unsupported operator {op!r} (supported: {', '.join(OPERATORS)})"]
    if op in ("all", "any"):
        if not isinstance(arg, list) or not arg:
            return [f"{where}.{op}: needs a non-empty list"]
        return [e for i, child in enumerate(arg) for e in validate_rule(child, f"{where}.{op}[{i}]")]
    if op == "not":
        return validate_rule(arg, f"{where}.not")
    if op == "stepExecution":
        errors = []
        if not isinstance(arg, dict) or set(arg) != {"step", "in"}:
            return [f"{where}.stepExecution: needs exactly 'step' and 'in'"]
        if not isinstance(arg["step"], str) or not arg["step"]:
            errors.append(f"{where}.stepExecution.step: a step id or '$occurrence'")
        elif arg["step"] != "$occurrence" and knowledge.step(arg["step"]) is None:
            errors.append(f"{where}.stepExecution.step: unknown step {arg['step']!r}")
        states = arg["in"]
        if not isinstance(states, list) or not states:
            errors.append(f"{where}.stepExecution.in: a non-empty list of states")
        else:
            errors += [f"{where}.stepExecution.in: unknown state {s!r}" for s in states if s not in _EXECUTIONS]
        return errors
    if op == "occurredAt":
        if not isinstance(arg, list) or not arg:
            return [f"{where}.occurredAt: a non-empty list of step ids"]
        return [f"{where}.occurredAt: unknown step {s!r}" for s in arg if knowledge.step(str(s)) is None]
    # runStatus
    if not isinstance(arg, dict) or set(arg) != {"in"} or not isinstance(arg["in"], list) or not arg["in"]:
        return [f"{where}.runStatus: needs exactly 'in' with a non-empty list"]
    return [f"{where}.runStatus.in: unknown status {s!r}" for s in arg["in"] if s not in _RUN_STATUSES]


def _label(step_id: str) -> str:
    entry = knowledge.step(step_id)
    return f"{entry.label}({step_id})" if entry else step_id


_STATE_WORDS = {
    "ranCompleted": "완료", "ranWarning": "경고로 완료", "ranFailed": "실패",
    "skipped": "건너뜀", "running": "실행 중", "waiting": "대기 중",
    "notRunAfterFailure": "앞 단계 실패로 실행 안 됨", "notRunCancelled": "취소로 실행 안 됨",
    "notRunAfterStop": "요청 범위 밖이라 실행 안 됨", "unknown": "판정 불가",
    "notPlanned": "이 실행의 계획에 없음",
}


def evaluate(
    node: Any, ledger: RunLedger, occurrence: str | None, reasons: list[str]
) -> bool | None:
    """Three-valued result. Appends a Korean phrase for each leaf that was not true."""
    if not isinstance(node, dict) or len(node) != 1:
        reasons.append("해석할 수 없는 조건")
        return None
    (op, arg), = node.items()
    if op == "all":
        values = [evaluate(c, ledger, occurrence, reasons) for c in arg]
        return False if False in values else None if None in values else True
    if op == "any":
        sub: list[str] = []
        values = [evaluate(c, ledger, occurrence, sub) for c in arg]
        if True in values:
            return True
        reasons.extend(sub)
        return None if None in values else False
    if op == "not":
        inner = evaluate(arg, ledger, occurrence, [])
        if inner is True:
            reasons.append("부정 조건이 성립하지 않음")
        return None if inner is None else not inner
    if op == "stepExecution":
        step_id = occurrence if arg.get("step") == "$occurrence" else arg.get("step")
        if not step_id:
            reasons.append("이 기록이 어느 단계에서 나왔는지 기록되지 않음")
            return None
        state = ledger.execution_of(step_id)
        if state is None:
            reasons.append("이 실행의 단계 목록이 없어 단계 실행 여부를 알 수 없음")
            return None
        if state == "unknown":
            reasons.append(f"{_label(step_id)} 단계: 판정 불가")
            return None
        ok = state in arg.get("in", [])
        if not ok:
            reasons.append(f"{_label(step_id)} 단계: {_STATE_WORDS.get(state, state)}")
        return ok
    if op == "occurredAt":
        if occurrence is None:
            reasons.append("이 기록이 어느 단계에서 나왔는지 기록되지 않음")
            return None
        ok = occurrence in arg
        if not ok:
            reasons.append(f"{_label(occurrence)} 단계에서 기록됨")
        return ok
    if op == "runStatus":
        ok = ledger.runStatus in arg.get("in", [])
        if not ok:
            reasons.append(f"실행 상태: {ledger.runStatus}")
        return ok
    reasons.append(f"지원하지 않는 조건 {op!r}")
    return None


def decide(rule: Any, ledger: RunLedger, occurrence: str | None) -> tuple[Decision, str | None]:
    reasons: list[str] = []
    value = evaluate(rule, ledger, occurrence, reasons)
    if value is True:
        return "applicable", None
    reason = "; ".join(dict.fromkeys(reasons)) or None
    return ("notApplicable" if value is False else "unknown"), reason


# --- the classification file --------------------------------------------------


class StatementKind(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1)
    sha: str = Field(pattern=r"^[0-9a-f]{12}$")
    kind: Kind
    runClaim: RunClaim
    # How the kind was decided: "role" -- by the field it sits in (a check is a
    # checkOrAction); "manual" -- the sentence was read and decided individually.
    review: Literal["role", "manual"]
    appliesWhen: dict[str, Any] | None = None
    onUnmet: Literal["withhold"] = "withhold"
    note: str | None = None

    @model_validator(mode="after")
    def _condition_iff_conditional(self) -> "StatementKind":
        if (self.runClaim == "conditional") != (self.appliesWhen is not None):
            raise ValueError(f"{self.target}: appliesWhen is required exactly when runClaim is conditional")
        return self


class PipelineText(BaseModel):
    """One fixed impact line main.sh writes (or wrote) for a code."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: Kind
    runClaim: RunClaim
    appliesWhen: dict[str, Any] | None = None
    onUnmet: Literal["withhold"] = "withhold"
    # Where main.sh writes it, and whether the current main.sh still does.
    emittedBy: str = Field(min_length=1)
    status: Literal["current", "legacy"]
    note: str | None = None

    @model_validator(mode="after")
    def _condition_iff_conditional(self) -> "PipelineText":
        if (self.runClaim == "conditional") != (self.appliesWhen is not None):
            raise ValueError(f"{self.code}: appliesWhen is required exactly when runClaim is conditional")
        return self

    @property
    def target(self) -> str:
        return f"pipeline/{self.code}/{sha12(self.text)}"


class _KindsDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    comment: list[str] = Field(default_factory=list, alias="_comment")
    schemaVersion: Literal["1"]
    conditionLanguage: Literal["appliesWhen/v1"]
    statements: list[StatementKind]
    pipelineTexts: list[PipelineText]


class StatementKindsError(ValueError):
    """The classification file contradicts itself or the rule language."""


@lru_cache(maxsize=1)
def _doc() -> tuple[dict[str, StatementKind], dict[tuple[str, str], PipelineText]]:
    path = config.KNOWLEDGE_DIR / "wes_statement_kinds.json"
    doc = _KindsDoc.model_validate(json.loads(path.read_text(encoding="utf-8")))
    statements: dict[str, StatementKind] = {}
    for row in doc.statements:
        if row.target in statements:
            raise StatementKindsError(f"duplicate target {row.target}")
        if row.appliesWhen is not None:
            errors = validate_rule(row.appliesWhen, row.target)
            if errors:
                raise StatementKindsError("; ".join(errors))
        statements[row.target] = row
    texts: dict[tuple[str, str], PipelineText] = {}
    for row in doc.pipelineTexts:
        key = (row.code, row.text)
        if key in texts:
            raise StatementKindsError(f"duplicate pipeline text for {row.code}")
        if row.appliesWhen is not None:
            errors = validate_rule(row.appliesWhen, row.target)
            if errors:
                raise StatementKindsError("; ".join(errors))
        texts[key] = row
    return statements, texts


def statement_kind(target: str) -> StatementKind | None:
    return _doc()[0].get(target)


def all_statement_kinds() -> list[StatementKind]:
    return list(_doc()[0].values())


def pipeline_text(code: str, text: str) -> PipelineText | None:
    return _doc()[1].get((code, text))


def all_pipeline_texts() -> list[PipelineText]:
    return list(_doc()[1].values())


def reload() -> None:
    _doc.cache_clear()


# --- the inventory: every registered sentence, with a stable target ------------

_BUCKETS = ("possibleCauses", "scope", "checks", "actions")


def _grounding(prefix: str, grounding: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if grounding is None:
        return out
    for bucket in _BUCKETS:
        for i, claim in enumerate(getattr(grounding, bucket)):
            out.append((f"{prefix}/grounding/{bucket}/{i}", claim.statement))
            effect = getattr(claim, "effect", None)
            if effect:
                out.append((f"{prefix}/grounding/{bucket}/{i}/effect", effect))
    return out


def inventory() -> list[tuple[str, str]]:
    """(target, sentence) for every explanatory sentence the knowledge holds.

    Names (titles, labels, source titles) and verbatim document quotes are not
    sentences about anything and are left out; so are `_comment` blocks.
    """
    from ..agent import doc_retrieval  # lazy: agent imports explanation

    out: list[tuple[str, str]] = []
    for d in knowledge.all_diagnostics():
        out.append((f"diagnostics/{d.code}/meaning", d.meaning))
        out += _grounding(f"diagnostics/{d.code}", d.grounding)
    for f in knowledge.all_failures():
        out.append((f"failures/{f.code}/meaning", f.meaning))
        out += _grounding(f"failures/{f.code}", f.grounding)
    for c in knowledge.all_concepts():
        out.append((f"concepts/{c.id}/summary", c.summary))
        out += _grounding(f"concepts/{c.id}", c.grounding)
    for t in knowledge.all_terms():
        out.append((f"terms/{t.id}/plain", t.plain))
        out.append((f"terms/{t.id}/definition", t.definition.statement))
        out += [(f"terms/{t.id}/misreadings/{i}", m.statement) for i, m in enumerate(t.misreadings)]
    for s in knowledge.all_steps():
        out.append((f"steps/{s.stepId}/purpose", s.purpose))
    for k in knowledge.all_cause_kinds():
        out += [(f"causeKinds/{k.kind}/checks/{i}", c.statement) for i, c in enumerate(k.checks)]
        out += [(f"causeKinds/{k.kind}/cautions/{i}", c.statement) for i, c in enumerate(k.cautions)]
        for i, r in enumerate(k.remedies):
            out.append((f"causeKinds/{k.kind}/remedies/{i}", r.statement))
            out.append((f"causeKinds/{k.kind}/remedies/{i}/changes", r.changes))
    for r in knowledge.all_resource_roles():
        out += [(f"roles/{r.role}/checks/{i}", c.statement) for i, c in enumerate(r.checks)]
    for p in doc_retrieval.all_passages():
        out.append((f"docPassages/{p.id}/explains", p.explains))
        out.append((f"docPassages/{p.id}/limits", p.limits))
    return out


# --- decisions for one run -------------------------------------------------------


class KnowledgeDecision(BaseModel):
    """One sentence that would describe one recorded item of this run."""

    section: Literal["diagnostics", "failures"]
    index: int
    code: str
    # "meaning", "impact", or a grounding path such as "grounding.scope.0".
    part: str
    origin: Literal["knowledge", "pipelineText"]
    target: str | None
    kind: Kind | Literal["unregisteredPipelineText", "unclassified"]
    runClaim: RunClaim | Literal["unknown"]
    decision: Decision
    withheld: bool
    reason: str | None = None
    text: str


def _knowledge_part(
    section: str, index: int, code: str, part: str, target: str, text: str,
    ledger: RunLedger, occurrence: str | None,
) -> KnowledgeDecision:
    entry = statement_kind(target)
    if entry is None or entry.sha != sha12(text):
        # A sentence nobody classified (or classified for different words) is not
        # vouched for. The suite keeps this empty; at runtime it is withheld.
        return KnowledgeDecision(
            section=section, index=index, code=code, part=part, origin="knowledge",
            target=target, kind="unclassified", runClaim="unknown", decision="unknown",
            withheld=True, reason="분류되지 않은 지식 문장이라 이 실행에 맞는지 판단할 수 없습니다.",
            text=text,
        )
    if entry.appliesWhen is None:
        decision, reason = "applicable", None
    else:
        decision, reason = decide(entry.appliesWhen, ledger, occurrence)
    return KnowledgeDecision(
        section=section, index=index, code=code, part=part, origin="knowledge", target=target,
        kind=entry.kind, runClaim=entry.runClaim, decision=decision,
        withheld=decision != "applicable", reason=reason, text=text,
    )


def _grounding_parts(prefix: str, grounding: Any) -> list[tuple[str, str, str]]:
    """(part, target suffix, text) for every grounding sentence."""
    out = []
    for target, text in _grounding("", grounding):
        part = target.lstrip("/").replace("/", ".")
        out.append((part, target, text))
    return out


def decisions_for(diagnostics: list[Any], failures: list[Any], ledger: RunLedger) -> list[KnowledgeDecision]:
    """Every explanatory sentence attached to this run's diagnostics and failures."""
    out: list[KnowledgeDecision] = []
    for index, item in enumerate(diagnostics):
        occurrence = item.actualStepId
        entry = knowledge.diagnostic(item.code)
        if entry is not None:
            base = f"diagnostics/{item.code}"
            out.append(_knowledge_part("diagnostics", index, item.code, "meaning", f"{base}/meaning",
                                       entry.meaning, ledger, occurrence))
            recorded = getattr(item, "meaning", None)
            if recorded and recorded != entry.meaning:
                # An explanation recorded under an older knowledge file carries
                # that file's meaning. Nobody classified those words, so they are
                # not vouched for in this run -- the same rule as any unclassified
                # sentence (fixture precheck_failed carried the FastQC claim).
                out.append(KnowledgeDecision(
                    section="diagnostics", index=index, code=item.code, part="recordedMeaning",
                    origin="knowledge", target=f"{base}/meaning", kind="unclassified",
                    runClaim="unknown", decision="unknown", withheld=True,
                    reason="기록된 설명이 현재 지식 문장과 달라(이전 버전) 이 실행에 맞는지 판단할 수 없습니다.",
                    text=recorded,
                ))
            for part, suffix, text in _grounding_parts(base, entry.grounding):
                out.append(_knowledge_part("diagnostics", index, item.code, part, base + suffix,
                                           text, ledger, occurrence))
        if item.impact:
            out.append(_impact(index, item.code, item.impact, ledger, occurrence))
    for index, item in enumerate(failures):
        entry = knowledge.failure(item.code)
        if entry is None:
            continue
        base = f"failures/{item.code}"
        out.append(_knowledge_part("failures", index, item.code, "meaning", f"{base}/meaning",
                                   entry.meaning, ledger, item.actualStepId))
        for part, suffix, text in _grounding_parts(base, entry.grounding):
            out.append(_knowledge_part("failures", index, item.code, part, base + suffix,
                                       text, ledger, item.actualStepId))
    return out


def _impact(index: int, code: str, text: str, ledger: RunLedger, occurrence: str | None) -> KnowledgeDecision:
    entry = pipeline_text(code, text)
    if entry is None:
        return KnowledgeDecision(
            section="diagnostics", index=index, code=code, part="impact", origin="pipelineText",
            target=None, kind="unregisteredPipelineText", runClaim="unknown", decision="unknown",
            withheld=True,
            reason="등록되지 않은 파이프라인 문구라 이 실행에 맞는지 판단할 수 없습니다. 실행 기록에는 그대로 남아 있습니다.",
            text=text,
        )
    if entry.appliesWhen is None:
        decision, reason = "applicable", None
    else:
        decision, reason = decide(entry.appliesWhen, ledger, occurrence)
    return KnowledgeDecision(
        section="diagnostics", index=index, code=code, part="impact", origin="pipelineText",
        target=entry.target, kind=entry.kind, runClaim=entry.runClaim, decision=decision,
        withheld=decision != "applicable", reason=reason, text=text,
    )


__all__ = [
    "LANGUAGE",
    "OPERATORS",
    "KnowledgeDecision",
    "PipelineText",
    "StatementKind",
    "StatementKindsError",
    "all_pipeline_texts",
    "all_statement_kinds",
    "decide",
    "decisions_for",
    "evaluate",
    "inventory",
    "pipeline_text",
    "reload",
    "sha12",
    "statement_kind",
    "validate_rule",
]
