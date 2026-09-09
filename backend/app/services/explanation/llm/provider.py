"""The only place that knows a subprocess is involved.

Everything above this file works with a payload in and a dict out. That is the
whole point of the boundary: `synthesis.py` builds the input, validates the
output, and never learns that a CLI exists. When a LangGraph node replaces this
call, it implements the same two-line contract and nothing above it changes.

This is deliberately not a provider framework. There is one provider, and a
registry of one entry is indirection without a second implementation to justify
it. The seam is the function signature, not a class hierarchy.

Cost safety
-----------

The user's constraint is zero additional API spend, so this runs Claude Code
under its **subscription** login and must never fall through to a metered API
key. Two independent gates enforce that, both before the process starts:

    1. ANTHROPIC_API_KEY present in the backend's environment  -> refuse
    2. `claude auth status` does not report a subscription     -> refuse

Gate 1 alone is not enough: the key could come from a settings file or an
apiKeyHelper. Gate 2 alone is not enough either -- the environment variable
takes precedence at request time and would silently win. Neither gate ever
reads or logs the key's value; gate 1 checks presence only.

`--bare` is deliberately NOT used. Its own help text says Anthropic auth is
then "strictly ANTHROPIC_API_KEY or apiKeyHelper (OAuth and keychain are never
read)" -- i.e. the one flag that would force the metered path. It looks
attractive (it skips hooks and CLAUDE.md discovery) and is exactly wrong here.

Verified against the installed CLI
----------------------------------

Claude Code 2.1.117. The flags and the response shape below were confirmed by
running it, not assumed:

    --output-format json   ->  one JSON envelope on stdout
    --json-schema <schema> ->  the parsed object arrives in `structured_output`
                               and `result` is an EMPTY STRING
    -p with no prompt arg  ->  the prompt is read from stdin

The second detail is why this file reads `structured_output` first. Reading
`result` and parsing it -- the obvious guess -- yields '' and fails every time.

The third is not a stylistic choice. npm installs the CLI as `claude.CMD`, so on
Windows the process is launched through cmd.exe, whose command line is capped at
about 8191 characters. A 6 KB payload plus the system prompt and the schema
exceeded it and the CLI exited 1 with "the command line is too long" -- observed,
not predicted. Since payload size grows with the size of the run, argv was never
a viable channel for it. The prompt goes over stdin, which has no such limit.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .... import config

log = logging.getLogger(__name__)

# Long enough for a synthesis of a large run, short enough that a wedged CLI
# does not hold a worker thread forever.
#
# Read from config rather than fixed here: the first real full-run validation
# took 160.7s and the previous hard-coded 120 killed it. See
# config.SYNTHESIS_TIMEOUT_SECONDS for why the number is what it is.
DEFAULT_TIMEOUT_SECONDS = config.SYNTHESIS_TIMEOUT_SECONDS

# Environment names that would route the CLI to a metered API path. Presence is
# checked; values are never read, logged, or included in an error.
_METERED_AUTH_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# Auth methods that bill a subscription rather than API credit. From
# `claude auth status` on the installed CLI, which reports authMethod
# "claude.ai" for a subscription login.
_SUBSCRIPTION_AUTH_METHODS = ("claude.ai", "console-oauth")


class ProviderError(Exception):
    """The provider could not produce a response.

    Carries a stable `category` so the API can report *why* without ever
    exposing CLI stdout or stderr, which may contain paths and prompt text.
    """

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True)
class ProviderResult:
    """One provider response, already unwrapped from the CLI envelope."""

    # The object the model produced, validated against the JSON schema by the
    # CLI. Still untrusted here -- Pydantic upstream is the real gate.
    payload: dict[str, Any]
    # Provenance. Safe to surface: no auth material, no prompt, no paths.
    models: list[str] = field(default_factory=list)
    durationMs: int | None = None
    numTurns: int | None = None


def _child_environment() -> dict[str, str]:
    """A clean environment for the child process.

    Two problems are being avoided.

    The metered-auth names are stripped as defence in depth: the preflight has
    already refused if one is set, so this only matters if the check is ever
    bypassed or the variable appears between check and spawn.

    The CLAUDE_CODE_* names matter for a different reason -- when the backend
    itself is started from inside a Claude Code session, the child inherits
    session identifiers and a messaging socket, and would try to attach to its
    parent's session rather than run standalone. That is a real condition in
    this repository's development setup, not a hypothetical.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _METERED_AUTH_ENV and not key.startswith("CLAUDE_CODE_")
    }
    env.pop("CLAUDECODE", None)
    return env


def _preflight(executable: str) -> str:
    """Refuse before spending anything. Returns the resolved executable path.

    The path is resolved here and reused for the real call, because on Windows
    the bare name does not work: npm installs the CLI as `claude.CMD`, and
    CreateProcess cannot launch a batch file from a bare name --
    `subprocess.run(["claude", ...])` raises FileNotFoundError even though the
    command works in a shell. Handing subprocess the full resolved path works on
    both platforms and avoids `shell=True`, which would mean quoting a JSON
    prompt through a command line.
    """
    for name in _METERED_AUTH_ENV:
        if os.environ.get(name):
            raise ProviderError(
                "meteredAuthPresent",
                f"{name} is set in the backend environment. Claude Code would "
                "authenticate with it and bill API credit, so synthesis is "
                "refused. Unset it to use the subscription login.",
            )

    resolved = shutil.which(executable)
    if resolved is None:
        raise ProviderError(
            "providerUnavailable",
            f"{executable} was not found on PATH.",
        )

    try:
        completed = subprocess.run(
            [resolved, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=_child_environment(),
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ProviderError(
            "providerUnavailable", f"could not check authentication: {exc}"
        ) from exc

    try:
        status = json.loads(completed.stdout)
    except ValueError as exc:
        raise ProviderError(
            "providerUnavailable",
            "authentication status was not readable.",
        ) from exc

    if not status.get("loggedIn"):
        raise ProviderError(
            "notAuthenticated",
            "Claude Code is not logged in. Run `claude auth login`.",
        )

    method = str(status.get("authMethod") or "")
    if method not in _SUBSCRIPTION_AUTH_METHODS:
        # Fail closed on anything unrecognised. A new auth method might be
        # metered, and guessing in the permissive direction spends the user's
        # money; guessing in the restrictive direction only shows an error.
        raise ProviderError(
            "meteredAuthPresent",
            f"Claude Code reports authMethod {method!r}, which is not a known "
            "subscription login. Synthesis is refused rather than risk API "
            "billing.",
        )
    # The method is checked and discarded; only the resolved path is returned.
    # email, orgId and subscriptionType are also in that response and are
    # account identifiers -- they are not carried further.
    return resolved


def run_structured(
    *,
    user_prompt: str,
    json_schema: dict[str, Any],
    model: str | None = None,
    executable: str = "claude",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ProviderResult:
    """One non-interactive, tool-less, single-turn call.

    The payload travels over stdin, not argv -- see the module docstring.

    Every flag here is load-bearing:

        -p                        non-interactive; exit after one response
                                  (with no prompt argument it reads stdin)
        (no --system-prompt)      a custom system prompt suppresses
                                  structured_output on this CLI version, so the
                                  constraints ride in the user turn instead
                                  (see prompt.py)
        (no --system-prompt)      a custom system prompt suppresses
                                  structured_output on this CLI version; the
                                  constraints ride in the user turn instead
                                  (see prompt.py)
        --output-format json      machine-readable envelope
        --json-schema             the model's output is shaped and parsed by
                                  the CLI, so no fence-stripping heuristics
        --tools ""                NO tools. This call must not read the repo,
                                  run Bash, or fetch anything -- its only input
                                  is the payload we hand it
        --disable-slash-commands  a runtime string cannot invoke a skill
        --strict-mcp-config       ignore any MCP servers configured on the box
        --setting-sources ""      ignore user/project/local settings, so the
                                  result does not depend on the developer's
                                  machine
        --no-session-persistence  nothing about a user's run is written to the
                                  CLI's session store

    Not agentic: one turn in, one object out.
    """
    resolved = _preflight(executable)

    argv = [
        resolved,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(json_schema),
        "--tools",
        "",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
    ]
    if model:
        argv += ["--model", model]

    try:
        completed = subprocess.run(
            argv,
            input=user_prompt,
            capture_output=True,
            text=True,
            # The CLI writes UTF-8 and the payload is Korean; without this the
            # child is decoded with the Windows ANSI codepage and the JSON
            # envelope comes back mangled.
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=_child_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(
            "timeout", f"the provider did not respond within {timeout_seconds}s."
        ) from exc
    except OSError as exc:
        raise ProviderError("providerUnavailable", f"could not start: {exc}") from exc

    if completed.returncode != 0:
        # stderr is logged for the operator and withheld from the response: it
        # can contain the prompt, absolute paths and account hints.
        log.error(
            "claude exited %s: %s",
            completed.returncode,
            (completed.stderr or "").strip()[:500],
        )
        raise ProviderError(
            "providerFailed",
            f"the provider exited with status {completed.returncode}.",
        )

    try:
        envelope = json.loads(completed.stdout)
    except ValueError as exc:
        raise ProviderError(
            "malformedProviderResponse",
            "the provider response was not valid JSON.",
        ) from exc

    if not isinstance(envelope, dict):
        raise ProviderError(
            "malformedProviderResponse", "the provider response was not an object."
        )

    if envelope.get("is_error") or envelope.get("subtype") != "success":
        subtype = str(envelope.get("subtype") or "unknown")
        # The CLI reports a reached usage limit through this path. It is called
        # out by name because it is the one failure the user can act on, and
        # because it must never be retried automatically.
        category = "usageLimit" if "limit" in subtype.lower() else "providerFailed"
        log.warning("claude reported %s", subtype)
        raise ProviderError(category, f"the provider reported {subtype!r}.")

    payload = envelope.get("structured_output")
    if not isinstance(payload, dict):
        # With --json-schema the object arrives here and `result` is ''. If this
        # is missing the CLI contract has changed; do not silently fall back to
        # parsing `result`, which would quietly accept unshaped output.
        raise ProviderError(
            "malformedProviderResponse",
            "the provider returned no structured output.",
        )

    usage = envelope.get("modelUsage")
    models = sorted(usage) if isinstance(usage, dict) else []

    return ProviderResult(
        payload=payload,
        models=models,
        durationMs=envelope.get("duration_ms"),
        numTurns=envelope.get("num_turns"),
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ProviderError",
    "ProviderResult",
    "run_structured",
]
