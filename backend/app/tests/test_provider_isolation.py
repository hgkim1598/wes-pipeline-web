"""Where and how the CLI child runs: working directory, environment, timeout.

P2 -- context isolation. The child used to inherit the backend's working
directory (the repository's backend/), so the CLI could pick up CLAUDE.md files
from the repository and its parents and a git status snapshot of the working
tree. It now runs in an empty per-call temporary directory, with the documented
switches that turn off CLAUDE.md, auto memory, git instructions and claude.ai
connectors. What the real CLI then puts in its context is NOT verified here --
that needs a real call. These tests pin what this code hands it.

P3 -- timeout. `subprocess.run(timeout=)` killed only the direct child. On
Windows that is cmd.exe (npm installs the CLI as claude.CMD); a grandchild kept
the pipes open and the request waited for it, far past the timeout. The test
below builds that exact shape with a short-sleeping Python grandchild and checks
the call returns promptly and the grandchild is gone.

The fake processes here are plain Python; no Claude CLI is started.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from .. import config
from ..services.explanation.llm import provider

ISOLATION = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1",
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
}


# --- P2: environment ---------------------------------------------------------


def test_child_environment_sets_the_documented_isolation_switches(monkeypatch):
    # A parent value must not win: the switches are set after the strip.
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_CLAUDE_MDS", "0")
    monkeypatch.setenv("ENABLE_CLAUDEAI_MCP_SERVERS", "true")
    env = provider._child_environment()
    for name, value in ISOLATION.items():
        assert env.get(name) == value, name


def test_isolation_does_not_reintroduce_parent_session_state(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "1234")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    env = provider._child_environment()
    leftover = sorted(k for k in env if k.startswith("CLAUDE_CODE_") and k not in ISOLATION)
    assert leftover == []
    assert "CLAUDECODE" not in env and "ANTHROPIC_API_KEY" not in env


def test_login_relevant_environment_is_kept(monkeypatch):
    """The subscription login is found through HOME / USERPROFILE / APPDATA.

    The isolation must not strip them, or the CLI would report "not logged in".
    """
    for name in ("HOME", "USERPROFILE", "APPDATA", "PATH"):
        monkeypatch.setenv(name, f"value-{name}")
    env = provider._child_environment()
    for name in ("HOME", "USERPROFILE", "APPDATA", "PATH"):
        assert env[name] == f"value-{name}"


# --- P2: working directory ---------------------------------------------------


class _RecordingPopen:
    """Stands in for subprocess.Popen; records cwd/env, returns a CLI envelope."""

    calls: list[dict] = []

    def __init__(self, argv, **kwargs):
        cwd = kwargs.get("cwd")
        type(self).calls.append(
            {
                "argv": argv,
                "cwd": cwd,
                "cwd_existed": bool(cwd) and Path(cwd).is_dir(),
                "cwd_entries": sorted(os.listdir(cwd)) if cwd and Path(cwd).is_dir() else None,
                "env": kwargs.get("env"),
                "kwargs": kwargs,
            }
        )
        self.pid = 999999
        self.returncode = 0

    def communicate(self, input=None, timeout=None):
        if "auth" in self_argv(self):
            return '{"loggedIn": true, "authMethod": "claude.ai"}', ""
        return (
            '{"type":"result","subtype":"success","is_error":false,'
            '"structured_output":{"ok":true},"modelUsage":{"m":{}}}',
            "",
        )

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


def self_argv(proc) -> list[str]:
    return _RecordingPopen.calls[-1]["argv"]


@pytest.fixture
def recorded(monkeypatch):
    _RecordingPopen.calls = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(provider.shutil, "which", lambda name: "/fake/bin/claude")
    monkeypatch.setattr(provider.subprocess, "Popen", _RecordingPopen)

    def no_run(*_a, **_k):
        raise AssertionError("subprocess.run must not be used for the CLI")

    monkeypatch.setattr(provider.subprocess, "run", no_run)
    return _RecordingPopen.calls


def test_every_cli_call_runs_in_an_empty_directory_outside_the_repository(recorded):
    result = provider.run_structured(user_prompt="u", json_schema={"type": "object"})
    assert result.payload == {"ok": True}
    assert len(recorded) == 2  # auth status, then the call
    repo = config.ROOT.resolve()
    for call in recorded:
        cwd = Path(call["cwd"]).resolve()
        assert call["cwd_existed"] and call["cwd_entries"] == []
        assert repo != cwd and repo not in cwd.parents
        assert cwd != Path.cwd().resolve()
        for name, value in ISOLATION.items():
            assert call["env"][name] == value
    # Removed afterwards.
    for call in recorded:
        assert not Path(call["cwd"]).exists()


def test_the_directory_is_removed_when_the_call_fails(recorded, monkeypatch):
    def failing(self, input=None, timeout=None):
        if "auth" in self_argv(self):
            return '{"loggedIn": true, "authMethod": "claude.ai"}', ""
        self.returncode = 1
        return "", "boom"

    monkeypatch.setattr(_RecordingPopen, "communicate", failing)
    with pytest.raises(provider.ProviderError) as caught:
        provider.run_structured(user_prompt="u", json_schema={"type": "object"})
    assert caught.value.category == "providerFailed"
    assert all(not Path(call["cwd"]).exists() for call in recorded)


def test_the_mcp_server_config_survives_a_different_working_directory(tmp_path, monkeypatch):
    """The CLI starts the MCP server in ITS working directory -- now a temp dir.

    Every path the server needs must therefore be absolute, including a data
    path an operator gave as a relative WES_DB_PATH.
    """
    from ..agent_mcp import launch

    monkeypatch.setattr(config, "DB_PATH", Path("data/app.db"))
    monkeypatch.setattr(config, "RUNS_ROOT", Path("../runs"))

    class Sink:
        path = tmp_path / "sink.jsonl"

    server = launch.build_mcp_config(job_id="j", sink=Sink(), max_distinct_steps=2)
    spec = next(iter(server["mcpServers"].values()))
    assert Path(spec["command"]).is_absolute()
    for name in ("PYTHONPATH", "WES_DB_PATH", "WES_RUNS_ROOT", "WES_DOC_PASSAGES_FILE"):
        assert Path(spec["env"][name]).is_absolute(), name
    assert spec["env"]["WES_DB_PATH"] == str(Path("data/app.db").resolve())


# --- P3: timeout kills the whole tree ----------------------------------------


_CHILD = textwrap.dedent(
    """
    import subprocess, sys, time
    # A grandchild that inherits stdout and outlives the child, like the
    # node process under cmd.exe.
    grand = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    open(sys.argv[1], "w").write(str(grand.pid))
    sys.stdout.write("started\\n"); sys.stdout.flush()
    time.sleep(30)
    """
)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie is dead for this purpose; it is reaped by its parent or init.
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return handle.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def _force_kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _launchers(tmp_path: Path) -> list[list[str]]:
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    pidfile = tmp_path / "grand.pid"
    out = [[sys.executable, str(script), str(pidfile)]]
    if os.name == "nt":
        # The production shape on Windows: a .cmd wrapper, so cmd.exe is the
        # direct child and Python is a grandchild with its own grandchild.
        # Not named claude.cmd: the suite-wide guard refuses any program of
        # that name (app/tests/real_cli_guard.py), and only the shape matters.
        cmd = tmp_path / "fake_cli.cmd"
        cmd.write_text(f'@"{sys.executable}" "{script}" "{pidfile}"\r\n', encoding="utf-8")
        out.append([str(cmd)])
    return out


@pytest.mark.parametrize("which", [0, 1])
def test_a_timeout_returns_promptly_and_leaves_no_grandchild(tmp_path, which):
    launchers = _launchers(tmp_path)
    if which >= len(launchers):
        pytest.skip("the .cmd shape exists only on Windows")
    argv = launchers[which]
    pidfile = tmp_path / "grand.pid"
    grand_pid = None
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            provider._run_child(argv, input_text=None, timeout=3, env=dict(os.environ))
        elapsed = time.monotonic() - started
        assert pidfile.exists(), "the fake child never started its grandchild"
        grand_pid = int(pidfile.read_text())
        # 3s timeout + kill grace; well under the 30s the processes would sleep.
        assert elapsed < 15, f"returned after {elapsed:.1f}s"
        deadline = time.monotonic() + 5
        while _alive(grand_pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _alive(grand_pid), "the grandchild outlived the timeout"
    finally:
        if grand_pid is not None and _alive(grand_pid):
            _force_kill(grand_pid)


def test_a_normal_exit_is_returned_unchanged(tmp_path):
    completed = provider._run_child(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper()); sys.exit(3)"],
        input_text="한국어 ok",
        timeout=20,
        env=dict(os.environ),
    )
    assert completed.returncode == 3
    assert completed.stdout.strip() == "한국어 OK"


def test_the_timeout_value_is_unchanged():
    """P3 changes how a timeout ends, not when. 300s stays the default."""
    assert provider.DEFAULT_TIMEOUT_SECONDS == config.SYNTHESIS_TIMEOUT_SECONDS
    if not os.environ.get("WES_SYNTHESIS_TIMEOUT_SECONDS"):
        assert config.SYNTHESIS_TIMEOUT_SECONDS == 300
