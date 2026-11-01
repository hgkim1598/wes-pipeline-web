"""Build the input, call a provider, validate what comes back.

The whole model-facing feature is this one function. It is a *small* agent: one
provider call in which the model may open at most two of this run's pipeline
steps through `get_step_detail`, and nothing else -- no retries, no memory, no
second tool, no write of any kind. If it fails, the deterministic explanation is
still there and unchanged -- that is the property the design is protecting, and
every failure path here returns a value rather than raising into the route.

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

Five gates, in order, and the model has to pass all of them:

    1. the CLI shapes the output against SYNTHESIS_JSON_SCHEMA
    2. Pydantic re-validates it here -- the CLI is not a trusted validator
    3. every evidenceRef must be an id the payload minted or a tool returned
    4. every number in the prose must appear in those same facts
    5. no property name from those facts may appear in the prose

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
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError

from .... import config
from ..deterministic import RunExplanation
from . import contract, prompt, provider, tools, trace, validation

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
    """
    call = run_provider or provider.run_structured
    payload, initial_refs = contract.build_payload(explanation)

    # Filled in as the call progresses, so a failure part-way through still
    # reports what had happened by then -- a provider timeout after the agent
    # opened a step is a different event from one that timed out immediately.
    opened: tuple[str, ...] = ()
    models: list[str] = []
    duration_ms: int | None = None
    num_turns: int | None = None

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
                )
            )
        return outcome

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
    models = result.models
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

    try:
        synthesis = contract.RunSynthesis.model_validate(result.payload)
    except ValidationError as exc:
        log.warning("synthesis failed validation: %s", exc)
        return emit(
            _unavailable(
                "invalidSynthesis",
                "the generated explanation did not match the expected structure.",
            )
        )

    unknown = _unknown_refs(synthesis, allowed_refs)
    if unknown:
        # Whole response rejected, not just the offending statement. Dropping
        # one sentence would leave a response that invented a citation and
        # present the rest as if it were sound.
        log.warning("synthesis cited unknown evidence: %s", sorted(unknown))
        return emit(
            _unavailable(
                "unknownEvidenceRef",
                "the generated explanation referred to evidence that was not "
                "supplied, so it was discarded.",
            )
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
        return emit(
            _unavailable(
                "unsupportedNumber",
                f"the generated explanation stated numbers not present in the "
                f"supplied data: {invented}",
            )
        )

    exposed = validation.find_exposed_property_names(statements, facts)
    if exposed:
        # Not a safety failure but a contract failure: the reader was promised
        # ordinary Korean, and a schema identifier is not that. The prompt asks
        # for this; asking is not enforcing.
        log.warning("synthesis exposed internal property names: %s", exposed)
        return emit(
            _unavailable(
                "internalFieldName",
                f"the generated explanation exposed internal property names: "
                f"{exposed}",
            )
        )

    return emit(
        SynthesisResult(
            available=True,
            synthesis=synthesis,
            provenance=SynthesisProvenance(
                models=result.models,
                generatedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                contextKind=explanation.contextKind,
                runStatus=explanation.status,
                durationMs=result.durationMs,
            ),
        )
    )


def _observe(toolset: tools.Toolset | None) -> tools.ToolUse:
    """What the server recorded answering. Nothing, when no tool was offered."""
    if toolset is None:
        return tools.observe([], [])
    return tools.observe(toolset.evidence(), toolset.attempts())


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
