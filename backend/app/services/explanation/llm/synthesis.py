"""Build the input, call a provider, validate what comes back.

The whole model-facing feature is this one function. It is deliberately not an
agent: one call, no tools, no retries, no memory. If it fails, the deterministic
explanation is still there and unchanged -- that is the property the design is
protecting, and every failure path here returns a value rather than raising into
the route.

Validation is not a formality
-----------------------------

Three gates, in order, and the model has to pass all of them:

    1. the CLI shapes the output against SYNTHESIS_JSON_SCHEMA
    2. Pydantic re-validates it here -- the CLI is not a trusted validator
    3. every evidenceRef must be an id this payload actually minted

Gate 3 is the one that matters. Gates 1 and 2 only check shape; a well-formed
object can still cite `src:made-up-paper`. Rejecting the whole response on a
bad ref is intentional: a response that cites something that does not exist has
demonstrated it is willing to invent, and the rest of it cannot be trusted more
than that.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError

from .... import config
from ..deterministic import RunExplanation
from . import contract, prompt, provider

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
) -> SynthesisResult:
    """Summarise one already-built deterministic explanation.

    Takes the explanation rather than a job_id on purpose: this function does no
    I/O of its own, so the tests can hand it a fixture and the route keeps the
    single path from job_id to explanation that the deterministic endpoint
    already uses.

    `run_provider` is injected so tests never spawn a process. It is the seam a
    LangGraph node would occupy.

    It defaults to None and is resolved here rather than in the signature. A
    default of `provider.run_structured` would bind the function object once, at
    import time, so patching the module attribute afterwards would silently have
    no effect -- and a test that believes it stubbed the provider but did not
    would spend real usage while appearing to pass.
    """
    call = run_provider or provider.run_structured
    payload, allowed_refs = contract.build_payload(explanation)

    try:
        result = call(
            user_prompt=prompt.build_user_prompt(payload),
            json_schema=contract.SYNTHESIS_JSON_SCHEMA,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except provider.ProviderError as exc:
        # Expected, not exceptional: the provider being unavailable is a normal
        # state of this feature, and the deterministic explanation is unaffected.
        log.info("synthesis unavailable (%s): %s", exc.category, exc.message)
        return _unavailable(exc.category, exc.message)

    try:
        synthesis = contract.RunSynthesis.model_validate(result.payload)
    except ValidationError as exc:
        log.warning("synthesis failed validation: %s", exc)
        return _unavailable(
            "invalidSynthesis",
            "the generated explanation did not match the expected structure.",
        )

    unknown = _unknown_refs(synthesis, allowed_refs)
    if unknown:
        # Whole response rejected, not just the offending statement. Dropping
        # one sentence would leave a response that invented a citation and
        # present the rest as if it were sound.
        log.warning("synthesis cited unknown evidence: %s", sorted(unknown))
        return _unavailable(
            "unknownEvidenceRef",
            "the generated explanation referred to evidence that was not "
            "supplied, so it was discarded.",
        )

    return SynthesisResult(
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


def _unknown_refs(
    synthesis: contract.RunSynthesis, allowed: set[str]
) -> set[str]:
    """Every cited id that this payload did not mint."""
    seen: set[str] = set()
    for group in (
        synthesis.importantFindings,
        synthesis.limitations,
        synthesis.nextChecks,
        synthesis.uncertainties,
    ):
        for item in group:
            seen.update(item.evidenceRefs)
    return seen - allowed


__all__ = [
    "DEFAULT_MODEL",
    "SynthesisProvenance",
    "SynthesisResult",
    "build_run_synthesis",
]
