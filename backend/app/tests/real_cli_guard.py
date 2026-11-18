"""Make it impossible for a test to start the real Claude CLI or reach the network.

Why this exists (development log, chapter 25): a fake CLI was put on PATH for
an end-to-end check, the PATH entry was written in a form Git Bash splits at
the drive colon, the fake silently dropped out, and `shutil.which("claude")`
found the real CLI. One real `claude auth status` and one real `claude -p`
started. The trap CLI used for the test suite was added the same way, so it
had been silently absent too. Anything that depends on PATH order fails open.

This guard does not depend on PATH. It is a CPython audit hook
(`sys.addaudithook`): `subprocess.Popen` raises the "subprocess.Popen" audit
event before it creates the process, and an exception raised by the hook
aborts the call. Hooks cannot be removed once added, so a test cannot switch
it off by accident.

On Windows the event carries the command line as ONE STRING (CPython calls
`list2cmdline` before auditing), so `["powershell", "-Command", "claude -p"]`
arrives as `powershell -Command "claude -p"`. The first version of this guard
split that string into shell tokens, saw the quoted `"claude -p"` as one word,
and let it through -- found by its own negative test, which had used a real
shell and therefore really started it (chapter 25). Since then, (1) words are
also split inside quotes, and (2) the guard's tests check spellings by calling
`decide()` directly; only harmless dummy scripts are ever started.

Two modes:

    deny  (pytest, via backend/conftest.py)
          a process whose program is `claude` (any extension, any case) is
          refused, and so is a shell/launcher (cmd, powershell, sh, node, ...)
          whose command line contains the word `claude` anywhere, and anything
          that names the npm package path `claude-code`.
    allow (the fake-CLI end-to-end launcher)
          only the exact executables listed are allowed; everything else is
          refused, whatever its name.

Both modes also refuse socket connections to non-loopback addresses, so a
test that tries to reach a server outside this machine fails instead of
sending anything.

Known limit of deny mode: a launcher command line that builds the name at run
time (`%X%`, `$X`, string concatenation inside a script) is not recognised.
Allow mode has no such gap, which is why the end-to-end launcher uses it.

Each refusal is appended to the file named by WES_GUARD_LOG, when set, so a
run can prove afterwards what was attempted. The refusal itself is the
protection; the log is the evidence.

This module is test infrastructure. Nothing under app/ outside app/tests
imports it, and the production provider does not change.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import sys
import time
from collections.abc import Iterable

_PROCESS_EVENTS = {
    "subprocess.Popen",
    "os.system",
    "os.startfile",
    "os.spawn",
    "os.exec",
    "os.posix_spawn",
}

# Programs that run whatever their arguments name. For these every word is a
# potential program; for anything else (python -c "...", git, taskkill) only
# the program itself is, or a test passing a path as data would be refused.
_LAUNCHERS = {
    "cmd", "sh", "bash", "zsh", "dash", "powershell", "pwsh", "env", "wsl",
    "start", "node", "npx", "npm", "bun", "deno",
}

_WORD_SPLIT = re.compile(r"[\s&|;<>(),=]+")
_DROP = str.maketrans("", "", "\"'^`")

_installed: dict[str, object] = {}


class RealCliBlocked(RuntimeError):
    """Raised instead of starting a refused process or connection.

    Deliberately not an OSError: the provider turns OSError into a polite
    `providerUnavailable` and carries on. A blocked start must stay loud.
    """


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _stem(token: str) -> str:
    base = os.path.basename(token.translate(_DROP).strip().replace("\\", "/").rstrip("/"))
    return base.split(".", 1)[0].lower()


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, os.PathLike)):
        return os.fsdecode(value)
    return value if isinstance(value, str) else None


def _shell_tokens(text: str) -> list[str]:
    try:
        toks = shlex.split(text, posix=False)
    except ValueError:
        toks = text.split()
    return [t.translate(_DROP) for t in toks if t.translate(_DROP)]


def _words(value: object) -> list[str]:
    """Every token AND every word inside every token, quotes ignored."""
    s = _as_str(value)
    if s is not None:
        toks = _shell_tokens(s)
        inner = [w for w in _WORD_SPLIT.split(s.translate(_DROP)) if w]
        return toks + inner
    if isinstance(value, Iterable):
        out: list[str] = []
        for item in value:
            out.extend(_words(item))
        return out
    return [] if value is None else [str(value)]


def _program(executable: object, args: object) -> str | None:
    exe = _as_str(executable)
    if exe is not None:
        return exe
    s = _as_str(args)
    if s is not None:
        toks = _shell_tokens(s)
        return toks[0] if toks else None
    if isinstance(args, Iterable):
        for item in args:
            first = _as_str(item)
            return first if first is not None else str(item)
    return None


def _names_claude(program: str | None, words: list[str]) -> bool:
    if program is not None and _stem(program) == "claude":
        return True
    if any("claude-code" in w.replace("\\", "/").lower() for w in words):
        return True
    if program is None or _stem(program) in _LAUNCHERS:
        return any(_stem(w) == "claude" for w in words)
    return False


def _is_loopback(host: object) -> bool:
    if isinstance(host, str) and host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def decide(mode: str, allowed: frozenset[str], event: str, args: tuple) -> tuple[str, str] | None:
    """Pure decision: (kind, reason) to refuse, or None to allow. Starts nothing."""
    if event == "socket.connect":
        address = args[1] if len(args) > 1 else None
        if isinstance(address, tuple) and address and not _is_loopback(address[0]):
            return ("network", f"connect to non-loopback {address[0]!r}")
        return None
    if event not in _PROCESS_EVENTS:
        return None

    if event == "subprocess.Popen":
        executable, argv = args[0], args[1]
        program = _program(executable, argv)
        words = _words(argv) + ([_as_str(executable)] if _as_str(executable) else [])
    elif event == "os.system":
        program = None
        words = _words(args[0])
    else:
        program = _as_str(args[0]) if args else None
        words = _words(args[1] if len(args) > 1 else None) + ([program] if program else [])

    if mode == "allow":
        if program is None or _norm(program) not in allowed:
            return ("process", f"{event} {os.path.basename(program or '?')} is not on the allowlist")
        others = [w for w in words if _norm(w) not in allowed]
        if _names_claude(None, others):
            return ("process", f"{event} command line names claude")
        return None

    if _names_claude(program, words):
        return ("process", f"{event} would start claude")
    return None


def _record(entry: dict) -> None:
    path = os.environ.get("WES_GUARD_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **entry}, ensure_ascii=False) + "\n")


def _hook_factory(mode: str, allowed: frozenset[str]):
    def hook(event: str, args: tuple) -> None:
        if event != "socket.connect" and event not in _PROCESS_EVENTS:
            return
        verdict = decide(mode, allowed, event, args)
        if verdict is not None:
            kind, reason = verdict
            _record({"refused": kind, "detail": reason})
            raise RealCliBlocked(f"real_cli_guard refused {kind}: {reason}")

    return hook


def install(mode: str = "deny", allowed: Iterable[str] = ()) -> None:
    """Install once per process. A second call must ask for the same thing."""
    if mode not in ("deny", "allow"):
        raise ValueError(mode)
    allowed = list(allowed)
    if mode == "allow":
        for p in allowed:
            if not os.path.isabs(p) or not os.path.isfile(p):
                raise ValueError("allowlist entries must be existing absolute files")
    allow = frozenset(_norm(p) for p in allowed)
    if _installed:
        if _installed != {"mode": mode, "allowed": allow}:
            raise RuntimeError("real_cli_guard already installed with a different policy")
        return
    sys.addaudithook(_hook_factory(mode, allow))
    _installed.update({"mode": mode, "allowed": allow})


def active_policy() -> dict[str, object]:
    return dict(_installed)
