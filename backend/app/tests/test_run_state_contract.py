"""The job status contract across the worker, the API and the explanation.

worker.py (who writes a job row's state) and job_state.py (how a state is
reported) state the contract; these tests hold every path to it, including the
ones a happy-path run never takes: a backend restart with a pipeline still
running, a process killed before main.sh's traps run, a recycled pid, and a
cancel racing the worker.

No real process is started. pipeline_executor.launch / terminate / is_alive are
replaced by fakes that only record what they were asked; the database and the
run directory are the temporary ones from `env`.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from .. import db
from ..api import jobs as jobs_api
from ..api import results as results_api
from ..services import pipeline_executor, run_status_reader, step_reader, worker
from ..services.agent import run_scope
from ..services.explanation import run_context

FULL_PLAN_DONE = ["00_input_validation", "01_raw_qc", "02_preprocessing"]
COMMAND = "bash /srv/wes/script/main.sh --config /srv/wes/runs/_jobs/x/run_config.json"


class FakeProcess:
    def __init__(self, exit_code: int, on_wait=None) -> None:
        self.exit_code = exit_code
        self.on_wait = on_wait

    def wait(self) -> int:
        if self.on_wait is not None:
            self.on_wait()
        return self.exit_code


class Executor:
    """Stands in for pipeline_executor; records instead of acting."""

    def __init__(self, monkeypatch) -> None:
        self.launched: list[str] = []
        self.terminated: list[int] = []
        self.alive: dict[int, bool] = {}
        self.alive_calls: list[tuple[int, str | None]] = []
        self.exit_code = 0
        self.before_launch = None  # callable(job_id) run inside launch()
        self.on_wait = None
        self.raise_on_launch: Exception | None = None
        monkeypatch.setattr(pipeline_executor, "launch", self.launch)
        monkeypatch.setattr(pipeline_executor, "terminate", self.terminate)
        monkeypatch.setattr(pipeline_executor, "is_alive", self.is_alive)

    def launch(self, config_path: Path, run_mode: str, log_path: Path):
        job_id = config_path.parent.name
        if self.before_launch is not None:
            self.before_launch(job_id)
        if self.raise_on_launch is not None:
            raise self.raise_on_launch
        self.launched.append(job_id)
        return pipeline_executor.LaunchedProcess(
            process=FakeProcess(self.exit_code, self.on_wait),
            command=COMMAND.split(" "),
            pid=4242,
            pgid=4242,
            stderr_log=log_path,
        )

    def terminate(self, pid: int, pgid: int | None):
        self.terminated.append(pid)
        return True, "fake terminate"

    def is_alive(self, pid: int, command: str | None = None) -> bool:
        self.alive_calls.append((pid, command))
        return self.alive.get(pid, False)


@pytest.fixture
def executor(env, monkeypatch):
    return Executor(monkeypatch)


def _row(job_id: str):
    return db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))


def _interrupted_run(make_job, run, *, status: str, job_id: str = "wes-20260821-142659-c66d6e"):
    """main.sh wrote `running` at 03_alignment and never wrote again."""
    make_job(job_id, run_mode="full", status=status)
    builder = run(job_id)
    for step_id in FULL_PLAN_DONE:
        builder.step(step_id)
    builder.run_status(
        "running",
        current_step="03_alignment",
        steps=[{"step_id": s, "status": "completed"} for s in FULL_PLAN_DONE],
    )
    return job_id


# --- reporting: a `running` document whose process is gone -------------------


@pytest.mark.parametrize("row_status", [worker.DONE, worker.EXEC_FAILED])
def test_a_running_document_with_no_process_reads_failed_on_every_path(
    client, make_job, run, row_status
):
    job_id = _interrupted_run(make_job, run, status=row_status)

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "failed"
    assert detail["error"] == run_status_reader.INTERRUPTED_ERROR
    assert detail["currentStep"] is None
    assert "running" not in {s["status"] for s in detail["steps"]}

    listed = client.get("/api/jobs").json()["jobs"][0]
    assert listed["status"] == "failed"

    step = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()
    assert step["status"] != "running"

    assert results_api._reconciled_status(_row(job_id)) == "failed"

    context = run_context.build_run_diagnostic_context(job_id)
    assert context.outcome.status == "failed"
    assert context.contextKind == "failed"
    # The step in flight is not claimed as failed or as never run.
    assert context.outcome.recordedCurrentStep == "03_alignment"


def test_the_agent_tool_is_told_the_same(make_job, run):
    job_id = _interrupted_run(make_job, run, status=worker.DONE)
    scope = run_scope.for_job(job_id)
    assert scope.process_ended is True
    detail = step_reader.read(
        scope.run_dir, list(scope.planned_steps), scope.run_mode, "03_alignment",
        process_ended=scope.process_ended,
    )
    assert detail["status"] != "running"


@pytest.mark.parametrize("row_status", [worker.RUNNING, worker.CANCELLING])
def test_a_running_document_with_a_live_process_still_reads_running(
    client, make_job, run, row_status
):
    job_id = _interrupted_run(make_job, run, status=row_status)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "running"
    assert detail["currentStep"] == "03_alignment"
    assert client.get("/api/jobs").json()["jobs"][0]["status"] == "running"


def test_a_backend_cancel_still_reads_cancelled_without_the_interrupted_error(
    client, make_job, run
):
    job_id = _interrupted_run(make_job, run, status=worker.CANCELLED)
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["status"] == "cancelled"
    assert detail["error"] != run_status_reader.INTERRUPTED_ERROR
    assert client.get("/api/jobs").json()["jobs"][0]["status"] == "cancelled"


def test_a_terminal_document_is_still_the_verdict(client, make_job, run):
    job_id = make_job(run_mode="full", status=worker.DONE)
    run(job_id).as_completed_full()
    assert client.get(f"/api/jobs/{job_id}").json()["status"] in (
        "completed", "completed_with_warnings"
    )


# --- closing a job out: worker child and orphan, one rule ---------------------


def test_a_non_zero_exit_that_left_running_is_not_reported_as_running(
    client, make_job, run, executor
):
    job_id = make_job(run_mode="full", status=worker.QUEUED)
    executor.exit_code = 137  # SIGKILL: main.sh's traps never ran
    executor.on_wait = lambda: _interrupted_run_documents(run, job_id)

    worker._run_job(job_id)

    row = _row(job_id)
    assert row["status"] == worker.DONE and row["exit_code"] == 137
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"


def _interrupted_run_documents(run, job_id: str) -> None:
    builder = run(job_id)
    builder.run_status("running", current_step="01_raw_qc")


def test_a_non_zero_exit_without_a_document_is_an_executor_failure(make_job, executor):
    job_id = make_job(run_mode="full", status=worker.QUEUED)
    executor.exit_code = 2
    worker._run_job(job_id)
    row = _row(job_id)
    assert row["status"] == worker.EXEC_FAILED
    assert row["error"].startswith("main.sh exited with code 2")


def test_a_cancelling_job_whose_process_is_gone_is_recovered_as_cancelled(make_job, executor):
    job_id = make_job(run_mode="full", status=worker.CANCELLING)
    db.update_job(job_id, pid=4242, pgid=4242, command=COMMAND)
    executor.alive[4242] = False

    worker.recover_orphans()

    assert _row(job_id)["status"] == worker.CANCELLED


def test_a_dead_orphan_is_closed_out_and_reported_by_its_document(client, make_job, run, executor):
    job_id = _interrupted_run(make_job, run, status=worker.RUNNING)
    db.update_job(job_id, pid=4242, pgid=4242, command=COMMAND)

    worker.recover_orphans()

    row = _row(job_id)
    assert row["status"] == worker.DONE and row["finished_at"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"


def test_recovery_identifies_the_process_by_its_recorded_command(make_job, executor):
    job_id = make_job(run_mode="full", status=worker.RUNNING)
    db.update_job(job_id, pid=4242, pgid=4242, command=COMMAND)
    worker.recover_orphans()
    assert executor.alive_calls == [(4242, COMMAND)]


# --- one pipeline at a time, across a restart ---------------------------------


def test_the_queue_waits_for_a_pipeline_left_running_by_a_previous_backend(
    make_job, executor, monkeypatch
):
    orphan = make_job("wes-20260821-100000-aaaaaa", run_mode="full", status=worker.RUNNING)
    db.update_job(orphan, pid=4242, pgid=4242, command=COMMAND)
    queued = make_job("wes-20260821-110000-bbbbbb", run_mode="full", status=worker.QUEUED)

    executor.alive[4242] = True
    checks = {"n": 0}
    real_is_alive = executor.is_alive

    def is_alive(pid, command=None):
        checks["n"] += 1
        if checks["n"] >= 4:
            executor.alive[4242] = False  # the orphan finishes after a few checks
        return real_is_alive(pid, command)

    monkeypatch.setattr(pipeline_executor, "is_alive", is_alive)
    monkeypatch.setattr(worker, "ORPHAN_POLL_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(worker, "_queue", __import__("queue").Queue())

    orphan_state_at_launch: list[str] = []
    executor.before_launch = lambda job_id: orphan_state_at_launch.append(_row(orphan)["status"])

    worker._stop.clear()
    worker.recover_orphans()
    thread = threading.Thread(target=worker._loop, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not executor.launched and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        worker._stop.set()
        thread.join(timeout=5)
        worker._stop.clear()

    assert executor.launched == [queued]
    # The queued job started only after the orphan was seen to exit and closed.
    assert checks["n"] >= 4
    # (It left no run_status.json in this fixture, so it closes as EXEC_FAILED.)
    assert orphan_state_at_launch == [worker.EXEC_FAILED]


# --- pid identity --------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, expected",
    [
        (COMMAND.split(" "), True),          # our pipeline
        (["/usr/sbin/sshd", "-D"], False),   # a recycled pid after a reboot
        ([], False),                         # exited (zombie) between the checks
        (None, True),                        # argv unknowable: pid check decides
    ],
)
def test_a_pid_is_the_pipeline_only_if_its_argv_matches(monkeypatch, argv, expected):
    monkeypatch.setattr(pipeline_executor, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(pipeline_executor, "_read_cmdline", lambda pid: argv)
    assert pipeline_executor.is_alive(4242, COMMAND) is expected


def test_a_missing_pid_is_never_alive(monkeypatch):
    monkeypatch.setattr(pipeline_executor, "_pid_exists", lambda pid: False)
    assert pipeline_executor.is_alive(4242, COMMAND) is False
    assert pipeline_executor.is_alive(0) is False


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") and Path("/proc/self/cmdline").is_file()),
    reason="the /proc identity check exists only on Linux (the others fall back to the pid)",
)
def test_the_identity_check_and_the_group_signal_on_a_real_linux_process():
    # The tests above fake /proc. This one reads it: a harmless `sleep`, started
    # the way launch() starts main.sh (own session, argv list), recorded the way
    # the worker records it (" ".join(argv)). Only this test's own child is
    # signalled.
    argv = [shutil.which("sleep") or "/bin/sleep", "300"]
    process = subprocess.Popen(argv, start_new_session=True)
    try:
        # Hypothesis, not reproduced on Linux: Popen returns once the child's
        # close-on-exec error pipe closes (begin_new_exec), before the kernel
        # sets the new argv (load_elf_binary), so /proc/<pid>/cmdline can read
        # empty -- CI run 45114421318 failed on this line. A pipeline is never
        # cancelled within microseconds of its exec, so wait for the argv, reading
        # /proc directly (not through is_alive, which is what is under test).
        cmdline = Path(f"/proc/{process.pid}/cmdline")
        deadline = time.monotonic() + 10
        while not cmdline.read_bytes():
            assert process.poll() is None, "sleep exited before its argv was published"
            assert time.monotonic() < deadline, "argv never appeared in /proc"
            time.sleep(0.01)

        recorded = " ".join(argv)
        assert pipeline_executor.is_alive(process.pid, recorded) is True
        assert pipeline_executor.is_alive(process.pid, recorded + "1") is False  # same pid, other program
        assert pipeline_executor.is_alive(process.pid) is True

        pgid = os.getpgid(process.pid)
        assert pgid == process.pid  # its own group: killpg reaches only what it started
        ok, _ = pipeline_executor.terminate(process.pid, pgid)
        assert ok
        assert process.wait(timeout=10) == -signal.SIGTERM
        assert pipeline_executor.is_alive(process.pid, recorded) is False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


# --- races between a cancel and the worker ------------------------------------


def test_a_cancel_between_the_claim_and_the_start_stops_the_process(client, make_job, executor):
    job_id = make_job(run_mode="full", status=worker.QUEUED)
    executor.before_launch = lambda jid: client.post(f"/api/jobs/{jid}/cancel")

    worker._run_job(job_id)

    assert executor.terminated == [4242]
    assert _row(job_id)["status"] == worker.CANCELLED


def test_a_launch_failure_after_a_cancel_stays_cancelled(client, make_job, executor):
    job_id = make_job(run_mode="full", status=worker.QUEUED)
    executor.before_launch = lambda jid: client.post(f"/api/jobs/{jid}/cancel")
    executor.raise_on_launch = FileNotFoundError("pipeline script not found")

    worker._run_job(job_id)

    assert _row(job_id)["status"] == worker.CANCELLED


def test_a_cancel_that_read_a_job_before_it_closed_does_not_reopen_it(
    client, make_job, executor, monkeypatch
):
    job_id = make_job(run_mode="full", status=worker.RUNNING)
    db.update_job(job_id, pid=4242, pgid=4242, command=COMMAND)
    stale = _row(job_id)
    db.update_job(job_id, status=worker.DONE, exit_code=0)  # the worker closed it

    real_load = jobs_api._load_job
    calls = {"n": 0}

    def load(jid):
        calls["n"] += 1
        return stale if calls["n"] == 1 else real_load(jid)

    monkeypatch.setattr(jobs_api, "_load_job", load)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204

    assert _row(job_id)["status"] == worker.DONE
    assert executor.terminated == []


def test_a_cancel_of_a_running_job_signals_its_process(client, make_job, executor):
    job_id = make_job(run_mode="full", status=worker.RUNNING)
    db.update_job(job_id, pid=4242, pgid=4242, command=COMMAND)
    executor.alive[4242] = True

    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204

    assert _row(job_id)["status"] == worker.CANCELLING
    assert executor.terminated == [4242]
    assert executor.alive_calls == [(4242, COMMAND)]


def test_a_cancel_never_signals_a_pid_that_is_no_longer_the_pipeline(client, make_job, executor):
    # A pipeline left by a previous backend is not this process's child: when it
    # exits, init reaps it and the number is free for reuse before the orphan
    # supervisor notices (up to ORPHAN_POLL_SECONDS). SIGTERM to that number --
    # or to its process group -- would stop an unrelated process. is_alive
    # checks the recorded argv, so a recycled pid reads as gone.
    job_id = make_job(run_mode="full", status=worker.RUNNING)
    db.update_job(job_id, pid=4242, pgid=4242, command=COMMAND)
    executor.alive[4242] = False

    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204

    assert executor.terminated == []
    # Left CANCELLING: the worker or the orphan supervisor closes it as CANCELLED
    # once it sees the process gone (see the recovery test above).
    assert _row(job_id)["status"] == worker.CANCELLING


def test_a_job_queued_twice_is_started_once(make_job, executor):
    job_id = make_job(run_mode="full", status=worker.QUEUED)
    worker._run_job(job_id)
    worker._run_job(job_id)
    assert executor.launched == [job_id]
