"""Which run an agent tool may read -- decided by the server, never by a model.

Every WES reader in this backend is addressed by (run_dir, planned, run_mode).
An agent tool that accepted those, or a jobId that resolves to them, would let
the model choose the run: one fabricated id in a tool call and it is reading
somebody else's analysis. So the tools take no run identifier at all. The
server binds one scope when it is built, and a tool can only ever read inside
it.

    build the server for job X   ->   RunScope(X)   ->   every tool call
                                                         reads run X

The scope also carries the redactor, because the same decision produces both:
the identifiers that name this run are exactly the identifiers that must not
come back out of it.

What the scope freezes, and what it does not
--------------------------------------------

run_dir, the planned step list and the run mode are fixed at construction.
None of them changes after the job row is written, and freezing them means a
long-lived server cannot be walked onto another run. The *contents* of the run
directory are deliberately NOT cached: a step that finishes after the server
started must be visible to the next call, so every call re-reads through
step_reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ... import db
from .privacy import Redactor


class RunNotFound(Exception):
    """No job row with this id, so there is no run to scope a server to."""


@dataclass(frozen=True)
class RunScope:
    """The one run a set of agent tools is allowed to read."""

    run_dir: Path
    planned_steps: tuple[str, ...]
    run_mode: str
    redactor: Redactor


def for_job(job_id: str) -> RunScope:
    """Resolve a job id to a scope. Server-side only; never from tool input.

    Raises RunNotFound for an unknown id.
    """
    row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        raise RunNotFound(job_id)

    # Longest first: job_id and run_id are the same string in the current
    # schema, and a shorter identifier must never consume part of a longer one
    # before that one has had its turn.
    candidates = [
        (row["sample_id"], "<sample>"),
        (row["run_id"], "<run>"),
        (row["job_id"], "<job>"),
    ]
    literals = tuple(
        sorted(
            ((str(value), placeholder) for value, placeholder in candidates if value),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
    )

    return RunScope(
        run_dir=Path(row["run_dir"]),
        planned_steps=tuple(db.loads(row["planned_steps"], [])),
        run_mode=row["run_mode"],
        redactor=Redactor(literals=literals),
    )


__all__ = ["RunNotFound", "RunScope", "for_job"]
