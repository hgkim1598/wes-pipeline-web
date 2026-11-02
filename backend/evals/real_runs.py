"""Preserved real WES runs, restored into a throwaway environment.

Why a real run as well as the synthetic cases
---------------------------------------------

The cases in agent_cases.py are scripts that write what main.sh *would* have
written. That is what makes failures, injections and budget refusals possible
to stage -- and it is also how a value can drift from the pipeline unnoticed:
the synthetic `percent_duplication` was written on the wrong scale. A preserved
run carries values, warnings and messages the pipeline actually produced.

The run here is a **dev** run. It was looked at while the prompt and the
knowledge were written, so a good result on it does not show that the agent
generalises. It is not a held-out test set.

Copied, never connected
-----------------------

A capture is a directory holding the backend's `app.db` and the run's documents
(no FASTQ, BAM or VCF). Its `jobs.run_dir` points at the capture itself, so
pointing the backend at that database would let a synthesis write a trace into
it -- which is how a second capture of the same run ended up differing from the
first. So the capture is only ever a source:

    run documents   copied into the temporary runs root
    database        opened read-only (`mode=ro`); one `jobs` row is read
    jobs row        inserted into the temporary database, paths rewritten
    uploads         not copied -- original file names and server paths
    traces          not copied -- earlier observations, not run evidence

`sample_id` is kept on purpose: it is what the privacy projection redacts
against, so dropping it would let the sample name through rather than hide it.
`command` is dropped: it is the argv of the original process, carries absolute
paths, and nothing that explains a run reads it.

`capture_manifest()` hashes every file in the capture, so a caller can record
which capture it used and a test can show the capture was left as it was.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from shutil import copytree

from app import config, db
from app.services.explanation import deterministic, run_context
from app.services.explanation.deterministic import RunExplanation

from .agent_cases import isolated_environment

# The original process's argv. Not evidence, and it carries absolute paths.
_DROPPED_JOB_COLUMNS = frozenset({"command"})


@dataclass(frozen=True)
class RealRun:
    """One preserved run and where its capture lives."""

    name: str
    intent: str
    capture_dir: Path
    run_id: str
    # "dev": seen while the agent was developed. Not a held-out test run.
    split: str


REAL_RUNS: dict[str, RealRun] = {
    "real_cba73e": RealRun(
        name="real_cba73e",
        intent="실제 완주 Run -- completed_with_warnings, 경고 3종이 04/05/06에 하나씩",
        capture_dir=config.ROOT / ".capture_success_cba73e",
        run_id="wes-20260918-222933-cba73e",
        split="dev",
    ),
}


class CaptureMissing(RuntimeError):
    """The capture is not on this machine. Captures are not in git."""


def capture_available(run: RealRun) -> bool:
    return (run.capture_dir / "app.db").is_file() and (
        run.capture_dir / "runs" / run.run_id
    ).is_dir()


def capture_manifest(capture_dir: Path) -> str:
    """SHA-256 over every file in the capture: relative path and content.

    Paths are relative and '/'-separated, so the hash names the capture's
    content and not where it happens to sit on this machine.
    """
    digest = hashlib.sha256()
    files = sorted(p for p in capture_dir.rglob("*") if p.is_file())
    for path in files:
        digest.update(path.relative_to(capture_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def payload_hash(payload: object) -> str:
    """SHA-256 of a payload, key order normalised. Equal hash, equal payload."""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# A Windows drive path, or a POSIX path under a typical server root. In JSON
# text a backslash is escaped, hence both separators.
_ABSOLUTE_PATH = re.compile(
    r"[A-Za-z]:(?:\\\\|\\|/)|(?<![\w.])/(?:home|root|mnt|data|tmp|Users|var|opt|srv)/"
)


def forbidden_literals(run: RealRun) -> list[str]:
    """What must never reach a model: the sample name and where things live."""
    row = _read_job_row(run)
    literals = [
        row.get("sample_id"),
        row.get("run_dir"),
        row.get("config_path"),
        row.get("samplesheet_path"),
        str(run.capture_dir),
        run.capture_dir.name,
    ]
    return [str(value) for value in literals if value]


def count_leaks(text: str, run: RealRun, extra: Iterable[str] = ()) -> int:
    """How many forbidden things `text` contains.

    A count, never the matches: a caller that prints or asserts on it cannot
    put the sample name or a path into a log.
    """
    literals = [*forbidden_literals(run), *(str(value) for value in extra)]
    hits = sum(1 for literal in literals if literal and literal in text)
    return hits + len(_ABSOLUTE_PATH.findall(text))


def _read_job_row(run: RealRun) -> dict[str, object]:
    """The run's `jobs` row, read without any chance of writing the capture."""
    uri = (run.capture_dir / "app.db").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (run.run_id,)
        ).fetchone()
    if row is None:
        raise CaptureMissing(f"{run.name}: the capture has no jobs row for its run")
    return dict(row)


def _insert_job(row: dict[str, object], run_dir: Path, jobs_dir: Path) -> None:
    """Copy the row into the temporary database, pointing at the copies."""
    restored = dict(row)
    restored["run_dir"] = str(run_dir)
    restored["config_path"] = str(jobs_dir / "run_config.json")
    restored["samplesheet_path"] = str(jobs_dir / "samplesheet.csv")

    # Only the columns this backend's schema has, minus the ones not carried.
    known = {r["name"] for r in db.query_all("PRAGMA table_info(jobs)")}
    columns = [c for c in restored if c in known and c not in _DROPPED_JOB_COLUMNS]
    placeholders = ",".join("?" for _ in columns)
    db.execute(
        f"INSERT INTO jobs ({','.join(columns)}) VALUES ({placeholders})",
        tuple(restored[c] for c in columns),
    )


@contextmanager
def materialise(run: RealRun) -> Iterator[RunExplanation]:
    """Restore the run into a throwaway environment and explain it.

    Same isolation as the synthetic cases, so the agent's MCP server resolves
    the restored copy -- never the capture. Outside the block nothing remains.
    """
    if not capture_available(run):
        raise CaptureMissing(f"{run.name}: capture not found on this machine")

    row = _read_job_row(run)
    with isolated_environment():
        run_dir = config.RUNS_ROOT / run.run_id
        jobs_dir = config.JOBS_ROOT / run.run_id
        copytree(run.capture_dir / "runs" / run.run_id, run_dir)
        source_jobs = run.capture_dir / "runs" / "_jobs" / run.run_id
        if source_jobs.is_dir():
            copytree(source_jobs, jobs_dir)
        _insert_job(row, run_dir, jobs_dir)

        context = run_context.build_run_diagnostic_context(run.run_id)
        yield deterministic.build_run_explanation(context)


__all__ = [
    "REAL_RUNS",
    "CaptureMissing",
    "RealRun",
    "capture_available",
    "capture_manifest",
    "count_leaks",
    "forbidden_literals",
    "materialise",
    "payload_hash",
]
