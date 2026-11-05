"""Build the input, call a provider, validate what comes back.

The whole model-facing feature is this one function. It is a *small* agent: one
provider call in which the model may open at most two of this run's pipeline
steps through `get_step_detail`, and nothing else -- no memory, no second tool,
no write of any kind, and at most one rewrite (below). If it fails, the
deterministic explanation is still there and unchanged -- that is the property
the design is protecting, and every failure path here returns a value rather
than raising into the route.

Two fact sources, one rule
--------------------------

    initial   contract.build_payload(explanation)     what the model was handed
    fetched   the step evidence the tool RETURNED     what the model went and got

The second is read from the sink the MCP server wrote (see tools.py), never
from the model's own account of what it fetched. Then the two are merged and
every gate below sees one fact set. That is what makes a tool useful rather than
self-defeating: without the merge, a number the tool correctly returned would be
rejected as invented; with it, a number from a step nobody opened still is.

Validation is not a formality
-----------------------------

Seven gates, in order, and the model has to pass all of them:

    1. the CLI shapes the output against SYNTHESIS_JSON_SCHEMA
    2. Pydantic re-validates it here -- the CLI is not a trusted validator
    3. every evidenceRef must be an id the payload minted or a tool returned
    4. every number in the prose must appear in those same facts
    5. no property name from those facts may appear in the prose
    6. a named measurement, the warning-step count and a step said to have
       warned must agree with the payload's own fields (claims.py)
    7. a statement about a diagnostic-only topic cites that diagnostic's
       evidence, and a qualified fact has its qualification cited (claims.py)

Gates 4 and 5 ask whether a token is anywhere in the facts, so a real value
attached to the wrong subject passed them ("평균 깊이는 1420배": 1420 is a
step's elapsed seconds). Gates 6 and 7 keep the subject, but only for wordings
narrow enough to be sure of; claims.py says what they leave alone. They run
last, so every rejection the first five gates reported is reported the same.

Gates 1 and 2 only check shape; a well-formed object can still cite
`src:made-up-paper`, state a figure nobody measured, or hand a beginner
`basesInLowMeanDepthIntervalsPct` as if it were a word. Gates 3 to 5 are the
ones that look at content, and each rejects the **whole** response rather than
editing it: a response willing to invent one citation or one number has shown
what it is willing to do, and the sentences that happen to be sound have not
earned more trust than that.

Gates 4 and 5 were checks the eval harness already made against recorded
output. Finding a defect in review is worth less than refusing to serve it, so
the rules moved into `validation.py` and now run on every user request; the
eval keeps using the same functions.

One rewrite, when switched on
-----------------------------

With WES_SYNTHESIS_REPAIR on (config.SYNTHESIS_REPAIR; off by default), an
answer that gates 2 to 7 rejected is not discarded at once. `_check` has
already written down what each gate found -- which ids were not supplied,
which numbers the facts do not contain, which property names leaked, where the
shape is wrong -- and that, with the rejected answer and the same payload, goes
back to the same provider once (prompt.build_repair_prompt). The rewrite then
goes through `_check` again: the same functions, the same fact set and the
same allowed ids as the first answer, so nothing it says is credited that the
first answer could not have earned. It passes and is served, or it fails and
the request ends exactly as a rejected first answer always has.

    gates pass          -> served, one call
    gates reject, off   -> discarded, one call (the behaviour before this)
    gates reject, on    -> one rewrite -> gates again -> served or discarded
    provider fails      -> never retried, on or off: a timeout, a missing
                           login or a usage limit is not something a rewrite
                           can fix, and asking again spends allowance twice

Each finding carries `locations`, the items it was found in, and the rewrite
is asked to change only those. Every other item is then taken from the first
answer whatever the rewrite says there (`_splice`): a real rewrite asked to fix
one citation also reworded the summary and got a term wrong doing it. What the
reader gets is the first answer with the named items replaced, checked by every
gate. Whether a replaced item still means what it should is not provable here;
the gates check what they always check.

The rewrite is offered no tool. It is asked to correct sentences, not to look
anything up, and the step details the first call fetched are handed over as
data instead (they stay in the fact set either way). There is no third call:
the count is a constant of the control flow below, not a setting.

The eval-only explanation quality checker under evals/ plays no part in this,
and its PASS / REVIEW / FAIL never reaches this module. Only the runtime gates
decide whether a rewrite is asked for.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from .... import config
from ..deterministic import RunExplanation
from . import claims, contract, prompt, provider, tools, trace, validation

log = logging.getLogger(__name__)

# Read from config, not written here: swapping the model is an operational
# decision and must not require touching this layer or any schema. `None` means
# "whatever the installed CLI is configured to use".
#
# The model that actually ran is reported in provenance either way, so the
# response says what answered it even when nothing here chose.
DEFAULT_MODEL: str | None = config.SYNTHESIS_MODEL


class SynthesisProvenance(BaseModel):
    """Where this text came from. Safe to show a user.

    Deliberately excludes auth material, the prompt, CLI output and cost. Cost
    in particular is misleading here: the CLI reports a dollar figure even on a
    subscription call, where nothing is billed per request.
    """

    provider: str = "claude-code-cli"
    # Model ids the CLI reported using. Plural because it reports more than one:
    # the synthesis model plus a small model the CLI uses for its own overhead.
    models: list[str] = []
    generatedAt: str
    # Which deterministic view was summarised, so a synthesis can be matched to
    # the state it described.
    contextKind: str
    runStatus: str
    durationMs: int | None = None


class SynthesisResult(BaseModel):
    """Either a synthesis or a reason there is none. Never both, never neither.

    Modelled as one object rather than an exception so the route stays trivial
    and the frontend has a single shape to render.
    """

    available: bool
    synthesis: contract.RunSynthesis | None = None
    provenance: SynthesisProvenance | None = None
    # Stable machine-readable category. The frontend keys its message off this,
    # never off `errorMessage`.
    errorCategory: str | None = None
    errorMessage: str | None = None


# What the user is told, per category. Curated constants, never the provider's
# own text.
#
# This mapping exists because provider messages interpolate exceptions -- an
# OSError from a failed spawn carries the executable path, and stderr can carry
# the prompt. Forwarding `ProviderError.message` would leak those to the browser
# the first time an unexpected error type appeared. The detailed message is
# logged for the operator; the client gets a sentence it can act on.
_SAFE_MESSAGES: dict[str, str] = {
    "providerUnavailable": "AI 설명 기능을 사용할 수 없습니다. 서버에 Claude Code가 설치돼 있는지 확인하세요.",
    "notAuthenticated": "Claude Code에 로그인돼 있지 않습니다. 서버에서 로그인한 뒤 다시 시도하세요.",
    "meteredAuthPresent": "API key 인증이 감지되어 실행하지 않았습니다. 구독 로그인으로만 동작하도록 설정돼 있습니다.",
    "usageLimit": "Claude 사용량 한도에 도달했습니다. 한도가 회복된 뒤 다시 시도하세요.",
    "timeout": "AI 설명 생성이 제한 시간 안에 끝나지 않았습니다.",
    "providerFailed": "AI 설명 생성에 실패했습니다.",
    "malformedProviderResponse": "AI 응답을 읽을 수 없었습니다.",
    "invalidSynthesis": "생성된 설명이 예상한 형식과 달라 사용하지 않았습니다.",
    "unknownEvidenceRef": "생성된 설명이 제공되지 않은 근거를 인용해 폐기했습니다.",
    "unsupportedNumber": "생성된 설명에 실행 기록에 없는 수치가 있어 폐기했습니다.",
    "internalFieldName": "생성된 설명에 내부 필드 이름이 노출되어 폐기했습니다.",
    "runFactMismatch": "생성된 설명의 수치나 경고 단계가 실행 기록과 맞지 않아 폐기했습니다.",
    "evidenceMismatch": "생성된 설명이 내용과 맞지 않는 근거를 인용해 폐기했습니다.",
}

_FALLBACK_MESSAGE = "AI 설명을 생성하지 못했습니다."


def _unavailable(category: str, detail: str) -> SynthesisResult:
    """`detail` is for the log only. The response carries a curated message."""
    return SynthesisResult(
        available=False,
        errorCategory=category,
        errorMessage=_SAFE_MESSAGES.get(category, _FALLBACK_MESSAGE),
    )


def build_run_synthesis(
    explanation: RunExplanation,
    *,
    model: str | None = DEFAULT_MODEL,
    timeout_seconds: int = provider.DEFAULT_TIMEOUT_SECONDS,
    run_provider=None,
    on_tool_use: Callable[[tools.ToolUse], None] | None = None,
    on_trace: Callable[[trace.SynthesisTrace], None] | None = None,
    offer_tools: bool = True,
    repair: bool | None = None,
) -> SynthesisResult:
    """Summarise one already-built deterministic explanation.

    Takes the explanation rather than a job_id on purpose: this function does no
    I/O of its own, so the tests can hand it a fixture and the route keeps the
    single path from job_id to explanation that the deterministic endpoint
    already uses.

    `run_provider` is injected so tests never spawn a process. It is the seam a
    LangGraph node would occupy.

    `on_tool_use` is the observation seam, and the whole of it. The eval harness
    needs to know whether the agent searched and where, and that fact exists for
    a few milliseconds inside this function before the sink is deleted. Rather
    than persisting a trace or widening SynthesisResult -- which would put agent
    internals into an API response and then into the frontend -- a caller that
    wants to watch passes a callback. Neither observer changes what the caller
    gets back, and neither adds a field to any response.

    `on_trace` is the second observer, and the one production uses. It fires
    exactly once on every exit path -- success, guardrail rejection, provider
    failure -- with the execution record described in trace.py. The two
    observers carry different things on purpose: `on_tool_use` hands over the
    tool's RESULTS, which an eval needs in memory and which must never be
    stored; `on_trace` hands over only what may be kept.

    `run_provider` defaults to None and is resolved here rather than in the
    signature. A default of `provider.run_structured` would bind the function
    object once, at import time, so patching the module attribute afterwards
    would silently have no effect -- and a test that believes it stubbed the
    provider but did not would spend real usage while appearing to pass.

    `offer_tools=False` withholds the step detail tool, for evaluation only --
    the route never passes it. No tool channel is opened, no MCP config is
    handed to the provider, and the prompt drops the tool's instructions (see
    prompt.py). Everything else is the same call: the same payload, schema,
    gates and trace. With nothing fetched, the fact set is the payload alone,
    so a `step:` citation is rejected by gate 3 like any other invented id.

    `repair` is whether a gate-rejected answer gets its one rewrite (see the
    module docstring). None, the default and what the route passes, means
    config.SYNTHESIS_REPAIR. The eval harness passes False so its records stay
    single-generation measurements whatever the server is configured to do.
    """
    call = run_provider or provider.run_structured
    repair_enabled = config.SYNTHESIS_REPAIR if repair is None else repair
    payload, initial_refs = contract.build_payload(explanation)

    # Filled in as the call progresses, so a failure part-way through still
    # reports what had happened by then -- a provider timeout after the agent
    # opened a step is a different event from one that timed out immediately.
    opened: tuple[str, ...] = ()
    models: list[str] = []
    duration_ms: int | None = None
    num_turns: int | None = None
    # Provider calls made, counted before each call so a call that failed
    # still counts. 1 or 2, never more.
    attempts = 0
    first_rejection: str | None = None

    def emit(outcome: SynthesisResult) -> SynthesisResult:
        """Report the execution record, then return the result unchanged.

        Every `return` in this function goes through here, which is what makes
        "a trace exists for every attempt" a property of the control flow
        rather than a rule someone has to remember.
        """
        if on_trace is not None:
            on_trace(
                trace.SynthesisTrace(
                    models=tuple(models),
                    durationMs=duration_ms,
                    numTurns=num_turns,
                    openedStepIds=opened,
                    available=outcome.available,
                    errorCategory=outcome.errorCategory,
                    repairEnabled=repair_enabled,
                    attempts=attempts,
                    firstRejection=first_rejection,
                )
            )
        return outcome

    def served(synthesis: contract.RunSynthesis) -> SynthesisResult:
        return emit(
            SynthesisResult(
                available=True,
                synthesis=synthesis,
                provenance=SynthesisProvenance(
                    models=list(models),
                    generatedAt=datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    contextKind=explanation.contextKind,
                    runStatus=explanation.status,
                    durationMs=duration_ms,
                ),
            )
        )

    # The tool channel lives exactly as long as the call. Inside the block the
    # model may open up to two steps of THIS run; when it closes, the sink and
    # its temporary directory are gone. Without the tool there is no channel,
    # and `toolset` is None for the length of the same block.
    channel = (
        tools.step_detail_toolset(explanation.identity.jobId)
        if offer_tools
        else nullcontext(None)
    )
    with channel as toolset:
        attempts += 1
        try:
            result = call(
                user_prompt=prompt.build_user_prompt(
                    payload, offer_tools=offer_tools
                ),
                json_schema=contract.SYNTHESIS_JSON_SCHEMA,
                model=model,
                timeout_seconds=timeout_seconds,
                mcp_config=toolset.mcp_config if toolset is not None else None,
                allowed_tools=toolset.allowed_tools if toolset is not None else (),
            )
        except provider.ProviderError as exc:
            # Expected, not exceptional: the provider being unavailable is a
            # normal state of this feature, and the deterministic explanation is
            # unaffected.
            log.info("synthesis unavailable (%s): %s", exc.category, exc.message)
            # The tool may already have answered before the provider died, and
            # that is exactly what makes such a trace worth having -- for the
            # stored trace and for an observer alike.
            use = _observe(toolset)
            opened = use.openedStepIds
            if on_tool_use is not None:
                on_tool_use(use)
            return emit(_unavailable(exc.category, exc.message))

        # Read before the sink is removed. What the model fetched is only
        # knowable from what the server recorded answering -- never from the
        # response, which is the thing being checked.
        use = _observe(toolset)

    tool_evidence = list(use.evidence)

    # Initial payload + the tool results that were actually returned. From here
    # every gate sees one fact set, so a number from an opened step is quotable
    # and a number from a step nobody opened is still invented. Refused and
    # repeated calls are not in `tool_evidence`, so they credit nothing.
    facts, allowed_refs = tools.credit(payload, initial_refs, tool_evidence)

    opened = use.openedStepIds
    # A copy: a rewrite appends to it, and the provider's list is not ours.
    models = list(result.models)
    duration_ms = result.durationMs
    # The CLI's own turn count. It is NOT a tool-call count: an observed run
    # that opened no step reported two turns (the structured-output step takes
    # one, see prompt.py). How turns grow with tool calls has not been
    # measured, so nothing here derives one from the other -- callCount on the
    # tool observation is the count.
    num_turns = result.numTurns

    if on_tool_use is not None:
        # Handed out, never stored. What the observer does with it -- score it,
        # print it, drop it -- is not this function's business. Called once:
        # this path and the provider-failure path above are exclusive.
        on_tool_use(use)

    if tool_evidence:
        log.info(
            "synthesis used %d tool result(s): %s",
            len(tool_evidence),
            ", ".join(
                str(item.get("evidenceId")) for item in tool_evidence
            ),
        )

    first = _check(result.payload, facts, allowed_refs)
    if first.synthesis is not None:
        return served(first.synthesis)

    first_rejection = first.category
    if not repair_enabled:
        return emit(_rejected(first))

    # The one rewrite. Same provider, same model, same payload, same schema; no
    # tool channel (the `with` block above has closed it); the fact set and the
    # allowed ids are the first call's and are not recomputed. Nothing below
    # can loop: this is straight-line code with one more call in it.
    log.info(
        "synthesis rejected by %s; asking the provider for one rewrite",
        first.category,
    )
    attempts += 1
    try:
        rewrite = call(
            user_prompt=prompt.build_repair_prompt(
                payload,
                step_details=tool_evidence,
                previous_answer=result.payload,
                findings=list(first.findings),
            ),
            json_schema=contract.SYNTHESIS_JSON_SCHEMA,
            model=model,
            timeout_seconds=timeout_seconds,
            mcp_config=None,
            allowed_tools=(),
        )
    except provider.ProviderError as exc:
        # The same policy as a failed first call: an ordinary unavailable
        # result, and no further attempt.
        log.info("synthesis rewrite unavailable (%s): %s", exc.category, exc.message)
        return emit(_unavailable(exc.category, exc.message))

    for name in rewrite.models:
        if name not in models:
            models.append(name)
    duration_ms = _add(duration_ms, rewrite.durationMs)
    num_turns = _add(num_turns, rewrite.numTurns)

    second = _check(_splice(first, rewrite.payload), facts, allowed_refs)
    if second.synthesis is not None:
        log.info("synthesis rewrite passed every gate")
        return served(second.synthesis)
    log.warning("synthesis rewrite rejected by %s; discarded", second.category)
    return emit(_rejected(second))


def _add(total: int | None, more: int | None) -> int | None:
    """Two calls' counts added; an unreported count adds nothing."""
    if total is None:
        return more
    if more is None:
        return total
    return total + more


def _observe(toolset: tools.Toolset | None) -> tools.ToolUse:
    """What the server recorded answering. Nothing, when no tool was offered."""
    if toolset is None:
        return tools.observe([], [])
    return tools.observe(toolset.evidence(), toolset.attempts())


@dataclass(frozen=True)
class _Verdict:
    """What gates 2 to 7 made of one structured output.

    `synthesis` is set only when every gate passed. Otherwise `category` is the
    first gate that rejected it, in gate order -- the same category a rejected
    answer has always been reported under -- and `findings` holds what every
    gate that could run found, in the same order, for the rewrite request.

    Findings carry model-written tokens (the ids, numbers and names the answer
    used) and ids the payload itself minted. Never a path, never an exception
    message, never a value of the input that the answer did not already
    contain.
    """

    synthesis: contract.RunSynthesis | None
    category: str | None
    findings: tuple[dict[str, Any], ...]
    # The answer as parsed, whether or not a later gate rejected it. None only
    # when the shape itself was wrong. The rewrite is spliced onto this.
    parsed: contract.RunSynthesis | None = None


def _check(
    raw: Any, facts: list[Any], allowed_refs: set[str]
) -> _Verdict:
    """Gates 2 to 7 on one structured output. Used for the first answer and the
    rewrite alike, which is what makes the rewrite's gates the same gates."""
    try:
        synthesis = contract.RunSynthesis.model_validate(raw)
    except ValidationError as exc:
        log.warning("synthesis failed validation: %s", exc)
        return _Verdict(
            synthesis=None,
            category="invalidSynthesis",
            findings=(
                {
                    "check": "invalidSynthesis",
                    "problem": "The answer does not match the required "
                    "structure. Each error gives where in the answer it is "
                    "and what is wrong there.",
                    "errors": _shape_errors(exc),
                },
            ),
        )

    findings: list[dict[str, Any]] = []
    answer = synthesis.model_dump()
    pieces = claims.units(answer)

    unknown = _unknown_refs(synthesis, allowed_refs)
    if unknown:
        # Whole response rejected, not just the offending statement. Dropping
        # one sentence would leave a response that invented a citation and
        # present the rest as if it were sound.
        log.warning("synthesis cited unknown evidence: %s", sorted(unknown))
        findings.append(
            {
                "check": "unknownEvidenceRef",
                "problem": "These evidenceRefs are not ids the data supplies.",
                "values": sorted(unknown),
                "locations": [u.location for u in pieces if u.refs & unknown],
                "allowedEvidenceIds": sorted(allowed_refs),
            }
        )

    # Gates 4 and 5 read the prose, so they need the statements rather than the
    # refs. `facts` is the fact source on purpose: it is exactly what the model
    # was shown -- the payload it was given plus the tool results it fetched --
    # so anything outside it is something it could not have been quoting. See
    # validation.py, which walks a list as readily as a dict.
    statements = _statements(synthesis)

    invented = validation.find_unsupported_numbers(statements, facts)
    if invented:
        # A citation can be checked by a reader; a number cannot. A figure that
        # was never measured is the most quietly damaging thing this feature
        # could produce, because it looks exactly like the ones that were.
        log.warning("synthesis stated unsupported numbers: %s", invented)
        findings.append(
            {
                "check": "unsupportedNumber",
                "problem": "These numbers are written in the answer but appear "
                "nowhere in the data. Remove each one, or write the figure "
                "exactly as the data gives it.",
                "values": invented,
                "locations": [
                    u.location
                    for u in pieces
                    if validation.find_unsupported_numbers([u.text], facts)
                ],
            }
        )

    exposed = validation.find_exposed_property_names(statements, facts)
    if exposed:
        # Not a safety failure but a contract failure: the reader was promised
        # ordinary Korean, and a schema identifier is not that. The prompt asks
        # for this; asking is not enforcing.
        log.warning("synthesis exposed internal property names: %s", exposed)
        findings.append(
            {
                "check": "internalFieldName",
                "problem": "These internal property names are written in "
                "sentences a reader sees. Say in plain Korean what each one "
                "refers to, without the name.",
                "values": exposed,
                "locations": [
                    u.location
                    for u in pieces
                    if validation.find_exposed_property_names([u.text], facts)
                ],
            }
        )

    # Gates 6 and 7 compare a sentence with the structured fact it names --
    # see claims.py. facts[0] is the payload: tools.credit puts it first.
    payload = facts[0] if facts and isinstance(facts[0], dict) else {}

    contradictions = claims.find_run_fact_mismatches(answer, payload)
    if contradictions:
        log.warning("synthesis contradicted run facts: %s", contradictions)
        findings.append(
            {
                "check": "runFactMismatch",
                "problem": "These items give a value or a count that the data "
                "records for something else, or not at all. Each problem says "
                "what was written and what the data gives.",
                "values": [p for c in contradictions for p in c["problems"]],
                "locations": [c["location"] for c in contradictions],
            }
        )

    mismatched = claims.find_evidence_mismatches(answer, payload, allowed_refs)
    if mismatched:
        log.warning("synthesis cited evidence that does not fit: %s", mismatched)
        findings.append(
            {
                "check": "evidenceMismatch",
                "problem": "These items cite evidence that does not fit what "
                "they say. Each problem names the ids that would fit.",
                "values": [p for m in mismatched for p in m["problems"]],
                "locations": [m["location"] for m in mismatched],
            }
        )

    if findings:
        return _Verdict(
            synthesis=None,
            category=findings[0]["check"],
            findings=tuple(findings),
            parsed=synthesis,
        )
    return _Verdict(synthesis=synthesis, category=None, findings=(), parsed=synthesis)


def _splice(first: _Verdict, rewrite: Any) -> Any:
    """The rewrite, with every item the findings did not name taken from the
    first answer.

    The rewrite is asked to change only the listed items (prompt.py), and
    asking is not enforcing: a real rewrite that fixed one citation also
    reworded the summary, and got NM/MD wrong doing it. Here an unlisted item
    cannot change. A group with a listed item keeps its unlisted positions
    from the first answer when the rewrite kept the group's length; when the
    length changed (a listed item was dropped) the rewrite's group is used as
    it is. The result is checked by every gate, like any answer.

    Nothing is spliced when the first answer had the wrong shape -- there is no
    item to keep -- or when the rewrite does not parse; then the rewrite goes
    to the gates as it came, and fails or passes on its own.
    """
    if first.parsed is None:
        return rewrite
    try:
        new = contract.RunSynthesis.model_validate(rewrite).model_dump()
    except ValidationError:
        return rewrite
    old = first.parsed.model_dump()
    listed = {loc for f in first.findings for loc in f.get("locations") or []}
    merged: dict[str, Any] = {
        "summary": new["summary"] if "summary" in listed else old["summary"]
    }
    for group in claims.GROUPS:
        marked = {i for i in range(max(len(old[group]), len(new[group]))) if f"{group}.{i}" in listed}
        if not marked:
            merged[group] = old[group]
        elif len(new[group]) == len(old[group]):
            merged[group] = [
                new[group][i] if i in marked else old[group][i]
                for i in range(len(old[group]))
            ]
        else:
            merged[group] = new[group]
    return merged


def _shape_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Where and what, without the input value Pydantic would otherwise echo."""
    return [
        {
            "location": ".".join(str(part) for part in error["loc"]) or "(answer)",
            "message": error["msg"],
        }
        for error in exc.errors(
            include_url=False, include_input=False, include_context=False
        )
    ]


def _rejected(verdict: _Verdict) -> SynthesisResult:
    """The unavailable result a gate rejection has always produced."""
    category = verdict.category or "invalidSynthesis"
    return _unavailable(category, f"rejected by {category}")


def _statement_groups(
    synthesis: contract.RunSynthesis,
) -> tuple[list[contract.SynthesisStatement], ...]:
    """The four cited groups, in one place so a new group cannot be missed.

    `summary` is not here: it carries no refs of its own by design. It IS user
    prose, so _statements() adds it separately -- a number invented in the
    summary is exactly as wrong as one invented in a finding.
    """
    return (
        synthesis.importantFindings,
        synthesis.limitations,
        synthesis.nextChecks,
        synthesis.uncertainties,
    )


def _unknown_refs(
    synthesis: contract.RunSynthesis, allowed: set[str]
) -> set[str]:
    """Every cited id that this payload did not mint."""
    seen: set[str] = set()
    for group in _statement_groups(synthesis):
        for item in group:
            seen.update(item.evidenceRefs)
    return seen - allowed


def _statements(synthesis: contract.RunSynthesis) -> list[str]:
    """Every sentence a user would read, including the summary."""
    texts = [synthesis.summary]
    for group in _statement_groups(synthesis):
        texts.extend(item.statement for item in group)
    return texts


__all__ = [
    "DEFAULT_MODEL",
    "SynthesisProvenance",
    "SynthesisResult",
    "build_run_synthesis",
]
