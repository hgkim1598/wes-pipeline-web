"""The guard that keeps the real Claude CLI out of every test (chapter 25).

Two kinds of test, kept strictly apart:

    decision tests  call `real_cli_guard.decide()` directly. They start no
                    process at all, so a spelling the guard fails to catch
                    costs a failed assertion, not a real CLI start. Every
                    real-looking name (bare `claude`, shells, node + the npm
                    path) is tested ONLY this way.
    spawn tests     really call subprocess / os.system, and only ever on a
                    dummy script written into tmp_path whose sole effect, if
                    it ran, would be to create a marker file. The assertion is
                    the pair: refused, and no marker.

The first version mixed the two: one spelling test handed a real shell
`claude -p`, the guard missed the Windows string form, and the shell started
(chapter 25, second incident). That is why the split above is a rule.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.services.explanation.llm import provider
from app.tests import real_cli_guard as guard

DENY = ("deny", frozenset())


def _dummy(dir_: Path, name: str, marker: Path) -> Path:
    """A script that only creates `marker`. Never a real CLI."""
    dir_.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = dir_ / f"{name}.cmd"
        path.write_text(f'@echo off\r\necho ran> "{marker}"\r\necho {{}}\r\n', encoding="ascii")
    else:
        path = dir_ / name
        path.write_text(f'#!/bin/sh\necho ran > "{marker}"\necho {{}}\n', encoding="ascii")
        path.chmod(0o755)
    return path


def _popen_event(argv, executable=None):
    """Both shapes the audit event can have: the list (POSIX) and the one
    command-line string CPython builds on Windows before auditing."""
    shapes = [(executable, argv, None, None)]
    if not isinstance(argv, str):
        shapes.append((executable, subprocess.list2cmdline(argv), None, None))
    return shapes


# --- decision tests: no process is started ----------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["claude", "--version"],
        ["claude.exe", "-p"],
        ["CLAUDE.CMD", "auth", "status"],
        ["C:/Users/x/AppData/Roaming/npm/claude.CMD", "-p"],
        ["C:/Program Files/x/claude.exe", "-p"],
        ["/usr/local/bin/claude", "-p"],
        ["/home/x/.local/bin/claude", "-p"],
        ["cmd.exe", "/c", "claude", "-p"],
        ["cmd.exe", "/d", "/s", "/c", "claude -p"],
        ["powershell", "-Command", "claude -p"],          # the one that got through
        ["powershell.exe", "-NoProfile", "-Command", "& claude auth status"],
        ["pwsh", "-c", "claude;"],
        ["cmd", "/c", "cl^aude -p"],                      # cmd caret escape
        ["sh", "-c", "claude -p < /dev/null"],
        ["bash", "-lc", "'claude' -p"],
        ["/usr/bin/env", "claude", "-p"],
        ["node", "C:/npm/node_modules/@anthropic-ai/claude-code/cli.js", "-p"],
        ["npx", "@anthropic-ai/claude-code", "-p"],
        "cmd /c claude auth status",
    ],
)
def test_every_spelling_is_refused_in_both_event_shapes(argv):
    for args in _popen_event(argv):
        verdict = guard.decide(*DENY, "subprocess.Popen", args)
        assert verdict is not None and verdict[0] == "process", args


def test_the_executable_argument_is_checked_not_only_argv():
    args = ("C:/npm/claude.cmd", ["harmless-looking-name", "-p"], None, None)
    assert guard.decide(*DENY, "subprocess.Popen", args) is not None


@pytest.mark.parametrize("cmd", ["claude --version", "cmd /c claude -p", '"claude" -p'])
def test_os_system_spellings_are_refused(cmd):
    assert guard.decide(*DENY, "os.system", (cmd,)) is not None


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "-c", "print(1)"],
        [sys.executable, "-c", "import sys; print(sys.argv[1])", "C:/x/claude.cmd"],  # data, not a program
        ["C:/Windows/System32/taskkill.exe", "/T", "/F", "/PID", "123"],
        ["git", "status"],
        ["C:/Users/x/AppData/Local/Temp/claude/abc/run.cmd"],   # a DIRECTORY named claude
    ],
)
def test_ordinary_programs_are_allowed(argv):
    for args in _popen_event(argv):
        assert guard.decide(*DENY, "subprocess.Popen", args) is None, args


def test_allow_mode_is_an_allowlist_not_a_name_filter(tmp_path):
    fake = _dummy(tmp_path / "fakebin", "claude", tmp_path / "m")
    other = _dummy(tmp_path / "x", "harmless", tmp_path / "n")
    allowed = frozenset({guard._norm(str(fake))})
    for args in _popen_event([str(fake), "-p", "--tools", ""]):
        assert guard.decide("allow", allowed, "subprocess.Popen", args) is None
    for argv in ([str(other)], [sys.executable, "-c", "1"], ["claude", "-p"]):
        for args in _popen_event(argv):
            assert guard.decide("allow", allowed, "subprocess.Popen", args) is not None
    # An allowed program still may not be handed a claude command line.
    for args in _popen_event([str(fake), "&", "claude", "-p"]):
        assert guard.decide("allow", allowed, "subprocess.Popen", args) is not None


def test_network_decisions():
    assert guard.decide(*DENY, "socket.connect", (None, ("192.0.2.1", 443))) is not None
    assert guard.decide(*DENY, "socket.connect", (None, ("api.anthropic.com", 443))) is not None
    for host in ("127.0.0.1", "::1", "localhost"):
        assert guard.decide(*DENY, "socket.connect", (None, (host, 8000))) is None


# --- spawn tests: only harmless dummies ever start ---------------------------


def test_the_guard_is_installed_for_every_test():
    assert guard.active_policy()["mode"] == "deny"


@pytest.mark.parametrize("name", ["claude", "CLAUDE", "Claude"])
def test_a_dummy_named_claude_is_refused_before_it_starts(tmp_path, name):
    marker = tmp_path / "ran.txt"
    exe = _dummy(tmp_path / "bin", name, marker)
    with pytest.raises(guard.RealCliBlocked):
        subprocess.Popen([str(exe), "auth", "status"])
    with pytest.raises(guard.RealCliBlocked):
        subprocess.run([str(exe), "-p"], capture_output=True, check=False)
    with pytest.raises(guard.RealCliBlocked):
        os.system(f'"{exe}"')
    assert not marker.exists()


def test_ordinary_children_still_run():
    out = subprocess.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1][-10:])", "C:/x/claude.cmd"],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "claude.cmd"


def test_a_non_loopback_connection_is_refused_before_it_is_made():
    # 192.0.2.1 is TEST-NET-1 (RFC 5737): unroutable even if the guard failed.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(guard.RealCliBlocked):
            s.connect(("192.0.2.1", 9))
    finally:
        s.close()


def test_loopback_connections_still_work():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        socket.create_connection(srv.getsockname(), timeout=5).close()
    finally:
        srv.close()


def test_the_provider_cannot_reach_a_claude_even_when_which_points_at_one(tmp_path, monkeypatch):
    """The incident's exact shape, with a dummy: lookup resolved to an
    unintended `claude`. Not swallowed into ProviderError: RealCliBlocked is
    not an OSError, so the refusal is loud."""
    marker = tmp_path / "ran.txt"
    exe = _dummy(tmp_path / "npm", "claude", marker)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(provider.shutil, "which", lambda name: str(exe))
    with pytest.raises(guard.RealCliBlocked):
        provider.run_structured(user_prompt="u", json_schema={"type": "object"})
    assert not marker.exists()


def test_the_policy_cannot_be_swapped_after_install(tmp_path):
    other = _dummy(tmp_path, "anything", tmp_path / "m")
    with pytest.raises(RuntimeError):
        guard.install("allow", [str(other)])
    assert guard.active_policy()["mode"] == "deny"


def test_allow_mode_in_a_fresh_interpreter(tmp_path):
    """The end-to-end launcher's mode (hooks are permanent, so a new process).

    Only dummies: the allowed fake runs; a second dummy NOT named claude is
    refused anyway; so is the provider when its lookup is pointed at it.
    """
    fake_marker, other_marker = tmp_path / "fake_ran.txt", tmp_path / "other_ran.txt"
    fake = _dummy(tmp_path / "fakebin", "claude", fake_marker)
    other = _dummy(tmp_path / "elsewhere", "harmless", other_marker)
    backend = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        f"""
        import os, subprocess, sys
        sys.path.insert(0, {str(backend)!r})
        from app.tests import real_cli_guard as g
        g.install("allow", [{str(fake)!r}])
        subprocess.run([{str(fake)!r}], capture_output=True, check=True)
        try:
            subprocess.run([{str(other)!r}], capture_output=True)
            print("OTHER_STARTED")
        except g.RealCliBlocked:
            print("OTHER_REFUSED")
        from app.services.explanation.llm import provider
        os.environ.pop("ANTHROPIC_API_KEY", None); os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        provider.shutil.which = lambda name: {str(other)!r}
        try:
            provider.run_structured(user_prompt="u", json_schema={{"type": "object"}})
            print("PROVIDER_STARTED")
        except g.RealCliBlocked:
            print("PROVIDER_REFUSED")
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "WES_GUARD_LOG"}
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
        env=env, cwd=str(backend),
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split() == ["OTHER_REFUSED", "PROVIDER_REFUSED"]
    assert fake_marker.exists()
    assert not other_marker.exists()
