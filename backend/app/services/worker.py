"""Single background worker.

WES runs for hours, so nothing about starting one may happen inside an HTTP
request handler. POST /api/jobs writes the config, records the job and returns;
this thread picks the job up and blocks on the subprocess.

One worker on purpose: one machine runs one WES pipeline at a time, and main.sh
already refuses concurrent orchestrators of the same run through its run lock.
There is no Celery/Redis here because there is nothing for them to do yet.

Status contract of the job row (services/job_state.py says how it is reported):

  QUEUED -> RUNNING          only by the worker, claimed with a compare-and-set
                             before the process starts; a cancel can no longer be
                             overwritten by the start
  RUNNING -> CANCELLING      only by POST /cancel, compare-and-set
  RUNNING|CANCELLING -> DONE | EXEC_FAILED | CANCELLED
                             only once the process is known to have exited, by
                             _close(), for the worker's own child and for a
                             pipeline left running by a previous backend process
                             alike
  QUEUED -> CANCELLED        only by POST /cancel, compare-and-set

"One pipeline at a time" covers a pipeline this process did not start: after a
restart, a pipeline still alive from before is supervised (_supervise_orphans)
and the queue waits until it has exited.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from .. import config, db
from . import pipeline_executor

log = logging.getLogger(__name__)

_queue: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None
_stop = threading.Event()

# Pipelines a previous backend process started that were still alive when this
# one came up (recover_orphans). The worker thread waits for each before it
# takes queued work. Seconds between liveness checks of such a pipeline:
_orphans: list[str] = []
ORPHAN_POLL_SECONDS = 15.0

# Job orchestration states. These are the backend's own vocabulary and are
# deliberately kept separate from the pipeline's run states.
QUEUED = "QUEUED"
RUNNING = "RUNNING"
DONE = "DONE"            # subprocess exited; the verdict lives in the run JSON
EXEC_FAILED = "EXEC_FAILED"  # never reached main.sh, or main.sh died pre-run-dir
CANCELLING = "CANCELLING"
CANCELLED = "CANCELLED"


def submit(job_id: str) -> None:
    _queue.put(job_id)


def _executor_log_tail(path: Path, limit: int = 40) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


# The two ways a closed-out row can say "no process left a verdict". Kept as
# constants because tests and the job list tell them apart.
EXITED_WITHOUT_STATUS = (
    "main.sh exited with code {code} without writing a run status document. "
    "This is a configuration or environment failure, not a pipeline result."
)
LOST_WITHOUT_STATUS = "the pipeline process disappeared and left no run status document"
CANCELLED_BEFORE_START = "cancelled before the pipeline started"


def _closing_state(current: str, exit_code: int | None, has_status_document: bool) -> str:
    """The row's final state once its process has exited.

    One rule for the worker's own child (exit code known) and for a pipeline a
    previous backend process started (exit code unknown, exit_code=None):

    * a cancel was requested               -> CANCELLED
    * exit 0                               -> DONE
    * main.sh wrote run_status.json        -> DONE; the verdict is that document.
      If it still says `running`, job_state reports the run as failed: DONE is
      "the process exited", never "the run succeeded".
    * nothing was written                  -> EXEC_FAILED
    """
    if current in (CANCELLING, CANCELLED):
        return CANCELLED
    if exit_code == 0 or has_status_document:
        return DONE
    return EXEC_FAILED


def _close(job_id: str, exit_code: int | None, log_path: Path | None = None) -> None:
    """Record that the job's process has exited.

    The only writer of a final state for a job that had a process. Read and
    write happen in one transaction, so a cancel cannot slip in between.
    """
    tail = _executor_log_tail(log_path) if log_path is not None else ""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, run_dir, error FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None or row["status"] not in (RUNNING, CANCELLING, CANCELLED):
            return
        has_document = (Path(row["run_dir"]) / "status" / "run_status.json").is_file()
        status = _closing_state(row["status"], exit_code, has_document)
        error = row["error"]
        if status == EXEC_FAILED:
            if exit_code is None:
                error = LOST_WITHOUT_STATUS
            else:
                error = EXITED_WITHOUT_STATUS.format(code=exit_code) + (f"\n{tail}" if tail else "")
        now = db.now_iso()
        conn.execute(
            "UPDATE jobs SET status = ?, exit_code = ?, error = ?, finished_at = ?, updated_at = ?"
            " WHERE job_id = ?",
            (status, exit_code, error, now, now, job_id),
        )


def _close_unlaunched(job_id: str, error: str) -> None:
    """The claimed job never got a process: a launch failure, or a cancel first."""
    with db.transaction() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None or row["status"] not in (RUNNING, CANCELLING):
            return
        if row["status"] == CANCELLING:
            status, error = CANCELLED, CANCELLED_BEFORE_START
        else:
            status = EXEC_FAILED
        now = db.now_iso()
        conn.execute(
            "UPDATE jobs SET status = ?, error = ?, finished_at = ?, updated_at = ? WHERE job_id = ?",
            (status, error, now, now, job_id),
        )


def _run_job(job_id: str) -> None:
    row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        return
    # Claim before starting anything. A cancel that got in first leaves the row
    # CANCELLED and the claim fails; one that comes later finds RUNNING and goes
    # through the CANCELLING path, which this function honours below. A job id
    # queued twice is claimed once.
    if not db.update_job_if(job_id, (QUEUED,), status=RUNNING, started_at=db.now_iso()):
        return

    config_path = Path(row["config_path"])
    log_path = config.JOBS_ROOT / job_id / "executor.log"

    try:
        launched = pipeline_executor.launch(config_path, row["run_mode"], log_path)
    except Exception as exc:  # noqa: BLE001 - any launch failure must reach the user
        _close_unlaunched(job_id, f"could not start the pipeline: {exc}")
        return

    command = " ".join(launched.command)
    try:
        recorded = db.update_job_if(
            job_id, (RUNNING,), pid=launched.pid, pgid=launched.pgid, command=command
        )
        if not recorded:
            # A cancel arrived between the claim and now. POST /cancel found no
            # process to signal, so stopping this one is the worker's job.
            db.update_job(job_id, pid=launched.pid, pgid=launched.pgid, command=command)
            ok, detail = pipeline_executor.terminate(launched.pid, launched.pgid)
            if not ok:
                log.warning("job %s: cancel during start could not stop the process: %s", job_id, detail)
    finally:
        # Whatever happened above, the process is ours until it exits: the
        # worker must not take the next job while it runs.
        exit_code = launched.process.wait()
        _close(job_id, exit_code, log_path)


def _supervise_orphans() -> None:
    """Wait for each pipeline a previous backend process left running.

    Runs on the worker thread before any queued job, so a restart cannot start a
    second WES pipeline beside one that is still working. Not this process's
    child, so its exit code cannot be collected; _close() records None.
    """
    while _orphans and not _stop.is_set():
        job_id = _orphans[0]
        row = db.query_one("SELECT status, pid, command FROM jobs WHERE job_id = ?", (job_id,))
        if row is None or row["status"] not in (RUNNING, CANCELLING):
            _orphans.pop(0)
            continue
        if pipeline_executor.is_alive(row["pid"] or 0, row["command"]):
            _stop.wait(ORPHAN_POLL_SECONDS)
            continue
        _close(job_id, None)
        _orphans.pop(0)


def _loop() -> None:
    _supervise_orphans()
    while not _stop.is_set():
        try:
            job_id = _queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _run_job(job_id)
        except Exception as exc:  # noqa: BLE001 - the worker must never die
            # Only a job that never got a process ends up here: _run_job closes
            # one that did before the exception leaves it. The compare-and-set
            # keeps a final state _close() already wrote.
            db.update_job_if(
                job_id,
                (QUEUED, RUNNING, CANCELLING),
                status=EXEC_FAILED,
                error=f"worker error: {exc}",
                finished_at=db.now_iso(),
            )
        finally:
            _queue.task_done()


def recover_orphans() -> None:
    """Reconcile jobs left mid-flight by a previous backend process.

    The pipeline is started with setsid on POSIX, so it survives a backend
    restart. One still alive -- the same process, not a recycled pid; see
    pipeline_executor.is_alive -- is handed to the worker thread, which waits for
    it to exit before taking queued work and then closes it out. One that is gone
    is closed out now, by the same rule as a child the worker saw exit.
    """
    _orphans.clear()
    for row in db.query_all("SELECT * FROM jobs WHERE status IN (?, ?)", (RUNNING, CANCELLING)):
        pid = row["pid"] or 0
        if pid and pipeline_executor.is_alive(pid, row["command"]):
            _orphans.append(row["job_id"])
            continue
        _close(row["job_id"], None)

    # Anything still queued when the process died never started; re-enqueue it.
    for row in db.query_all("SELECT job_id FROM jobs WHERE status = ?", (QUEUED,)):
        submit(row["job_id"])


def start() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="pipeline-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
