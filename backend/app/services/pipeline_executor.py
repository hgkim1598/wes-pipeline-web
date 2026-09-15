"""Run script/main.sh as a real subprocess.

This module is the only place that starts the pipeline. It does not reimplement
any analysis step, does not parse pipeline.log, and does not synthesise status:
it starts bash, waits, and reports the exit code.

Design notes:

* argv list, never shell=True.
* stdout/stderr go to a file, never to an unread PIPE. main.sh already tees its
  own logs/pipeline.log; this capture exists for the window *before* the run
  directory exists, where a fail-closed `die` in normalize_config would
  otherwise be lost entirely.
* On POSIX the child gets its own session so the whole process group can be
  signalled on cancel. Windows has no equivalent that also lets main.sh run its
  trap, so cancellation there is partial and is reported as such.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import config

IS_POSIX = os.name == "posix"


@dataclass
class LaunchedProcess:
    process: subprocess.Popen
    command: list[str]
    pid: int
    pgid: int | None
    stderr_log: Path


def build_command(config_path: Path, run_mode: str) -> list[str]:
    """The exact argv handed to the OS.

    main.sh's CLI (parse_args) accepts --config, --check-only, --resume,
    --from-step, --to-step, --help. Only the first two are used here; --resume is
    deliberately never passed, because every submission gets a fresh run_id and
    resuming someone else's directory is exactly what run lock exists to prevent.
    """
    cmd = [config.BASH_BIN, str(config.PIPELINE_SH), "--config", str(config_path)]
    if run_mode == "check_only":
        cmd.append("--check-only")
    return cmd


def launch(config_path: Path, run_mode: str, log_path: Path) -> LaunchedProcess:
    if not config.PIPELINE_SH.is_file():
        raise FileNotFoundError(f"pipeline script not found: {config.PIPELINE_SH}")

    command = build_command(config_path, run_mode)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("wb")

    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "cwd": str(config.ROOT),
        "close_fds": True,
    }
    if IS_POSIX:
        # setsid: survives a backend restart and gives us a process group to
        # signal, so cancel reaches the tools main.sh spawned.
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(command, **kwargs)
    finally:
        # The child holds its own duplicate of the fd.
        handle.close()

    pgid: int | None = None
    if IS_POSIX:
        try:
            pgid = os.getpgid(process.pid)
        except (ProcessLookupError, OSError):
            pgid = None

    return LaunchedProcess(
        process=process,
        command=command,
        pid=process.pid,
        pgid=pgid,
        stderr_log=log_path,
    )


def terminate(pid: int, pgid: int | None) -> tuple[bool, str]:
    """Ask a running pipeline to stop.

    POSIX: SIGTERM to the process group. main.sh traps it (on_signal), marks the
    current step `cancelled`, writes run_status `cancelled`, drops a
    RUN_CANCELLED marker and releases the run lock. That is a clean cancel.

    Windows: there is no way to deliver a POSIX signal that bash would trap, so
    the child is terminated outright. main.sh cannot run its trap in that case,
    which means no `cancelled` status document and a leftover .run.lock
    directory. This is reported rather than papered over.
    """
    if IS_POSIX and pgid:
        try:
            os.killpg(pgid, signal.SIGTERM)
            return True, "SIGTERM sent to process group; main.sh will record the cancellation"
        except ProcessLookupError:
            return False, "process group no longer exists"
        except OSError as exc:
            return False, f"could not signal process group: {exc}"

    try:
        os.kill(pid, signal.SIGTERM)
        return True, "SIGTERM sent to the pipeline process"
    except ProcessLookupError:
        return False, "process no longer exists"
    except OSError as exc:
        if not IS_POSIX:
            return (
                False,
                "cancellation is not fully supported on Windows: main.sh cannot trap a "
                "signal here, so the run lock and step status may be left behind "
                f"({exc})",
            )
        return False, f"could not signal process: {exc}"


def is_alive(pid: int) -> bool:
    """Best-effort liveness check used when recovering after a backend restart."""
    if pid <= 0:
        return False
    if IS_POSIX:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return str(pid) in out.stdout
