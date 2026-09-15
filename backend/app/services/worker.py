"""Single background worker.

WES runs for hours, so nothing about starting one may happen inside an HTTP
request handler. POST /api/jobs writes the config, records the job and returns;
this thread picks the job up and blocks on the subprocess.

One worker on purpose: one machine runs one WES pipeline at a time, and main.sh
already refuses concurrent orchestrators of the same run through its run lock.
There is no Celery/Redis here because there is nothing for them to do yet.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from .. import config, db
from . import pipeline_executor

_queue: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None
_stop = threading.Event()

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


def _run_job(job_id: str) -> None:
    row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        return
    if row["status"] in (CANCELLED, CANCELLING):
        return

    config_path = Path(row["config_path"])
    log_path = config.JOBS_ROOT / job_id / "executor.log"

    try:
        launched = pipeline_executor.launch(config_path, row["run_mode"], log_path)
    except Exception as exc:  # noqa: BLE001 - any launch failure must reach the user
        db.update_job(
            job_id,
            status=EXEC_FAILED,
            error=f"could not start the pipeline: {exc}",
            finished_at=db.now_iso(),
        )
        return

    db.update_job(
        job_id,
        status=RUNNING,
        pid=launched.pid,
        pgid=launched.pgid,
        command=" ".join(launched.command),
        started_at=db.now_iso(),
    )

    exit_code = launched.process.wait()

    current = db.query_one("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
    was_cancelling = current is not None and current["status"] in (CANCELLING, CANCELLED)

    error = None
    if was_cancelling:
        status = CANCELLED
    elif exit_code == 0:
        status = DONE
    else:
        # A non-zero exit is not automatically a backend failure: main.sh exits 1
        # when a core step fails, and in that case it has already written a
        # proper run_status.json. Only treat it as an executor failure when the
        # pipeline never got far enough to leave one.
        run_status = Path(row["run_dir"]) / "status" / "run_status.json"
        if run_status.is_file():
            status = DONE
        else:
            status = EXEC_FAILED
            tail = _executor_log_tail(log_path)
            error = (
                f"main.sh exited with code {exit_code} before creating a run directory. "
                "This is a configuration or environment failure, not a pipeline result."
                + (f"\n{tail}" if tail else "")
            )

    db.update_job(
        job_id,
        status=status,
        exit_code=exit_code,
        error=error,
        finished_at=db.now_iso(),
    )


def _loop() -> None:
    while not _stop.is_set():
        try:
            job_id = _queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _run_job(job_id)
        except Exception as exc:  # noqa: BLE001 - the worker must never die
            db.update_job(
                job_id,
                status=EXEC_FAILED,
                error=f"worker error: {exc}",
                finished_at=db.now_iso(),
            )
        finally:
            _queue.task_done()


def recover_orphans() -> None:
    """Reconcile jobs left mid-flight by a backend restart.

    The pipeline is started with setsid on POSIX, so it survives a backend
    restart; the DB row just needs to be re-attached. On a platform where the
    child died with the parent, or where the process is simply gone, the job is
    closed out as DONE if the pipeline left a run_status.json (its own status is
    then authoritative) and as EXEC_FAILED otherwise.
    """
    for row in db.query_all("SELECT * FROM jobs WHERE status IN (?, ?)", (RUNNING, CANCELLING)):
        pid = row["pid"] or 0
        if pid and pipeline_executor.is_alive(pid):
            continue
        run_status = Path(row["run_dir"]) / "status" / "run_status.json"
        if run_status.is_file():
            db.update_job(row["job_id"], status=DONE, finished_at=db.now_iso())
        else:
            db.update_job(
                row["job_id"],
                status=EXEC_FAILED,
                error="the pipeline process disappeared and left no run status document",
                finished_at=db.now_iso(),
            )

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
