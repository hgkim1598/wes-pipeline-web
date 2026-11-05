"""What happened during one synthesis, and nothing about how it was thought.

The question this answers, days later, is narrow:

    which model ran, for how long, over how many turns,
    which pipeline steps did the agent actually open,
    and did the answer reach the user or die at a guardrail?

That is an execution record. It is **not** a transcript. The model's reasoning,
the prompt, the tool results, the generated text and the evidence sink are all
absent by construction -- not filtered out afterwards, but never assembled into
the record in the first place. `SynthesisTrace` has nine fields and no room for
anything else, so "we could also store..." is a schema change someone has to
make on purpose.

Why the fields are the ones they are
------------------------------------

    models           which model answered -- a comparison is impossible without it
    durationMs       the cost the user actually felt
    numTurns         the CLI's own turn count, already measured and, until
                     now, thrown away. It is NOT a tool-call count: a recorded
                     run that opened no step reported 2, because structured
                     output takes a turn of its own (see prompt.py). How it
                     grows with tool calls has not been measured, so do not
                     read one from the other -- the eval's tool observation
                     carries the call count
    openedStepIds    where it went. From the MCP server's own record of what it
                     answered (tools.observe), never from the model's account
    available        was the user shown anything
    errorCategory    if not, which gate stopped it -- for a repaired request,
                     the verdict on the rewrite
    repairEnabled    whether WES_SYNTHESIS_REPAIR was on for this request
    attempts         provider calls actually made: 1, or 2 when a rewrite was
                     asked for. A call that failed still counts
    firstRejection   the gate that rejected the FIRST answer, or None when it
                     passed or never arrived. Kept whether or not repair was
                     on, so "how often does the first answer fail" stays
                     answerable after the feature is enabled

With a rewrite, `models` is both calls' models in order of first appearance,
and `durationMs` and `numTurns` are the two calls added together -- what one
request cost. The first answer's text is not kept, like any other answer.

A row written before the repair columns existed reads back with all three as
None: those requests were single-generation, recorded by an older backend.

`openedStepIds` holds pipeline step ids -- `04_processing`, `01_raw_qc`. They
are the pipeline's vocabulary and say nothing about the sample, which is why
this is the one part of the tool interaction that may be kept.

Failing to record must not fail the request
-------------------------------------------

A trace is observability. If the insert fails, the user's explanation is still
correct and still theirs; losing the record is the smaller loss by a wide
margin. `record()` therefore logs and returns instead of raising. This is the
one place in this backend that swallows a database error, and it does so
because nothing downstream reads what it writes.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any

from .... import db

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SynthesisTrace:
    """One synthesis attempt, as an execution record.

    Built by `synthesis.build_run_synthesis` on every exit path -- success,
    guardrail rejection, and provider failure alike. A run that died before the
    provider answered still has `openedStepIds`, because the tool may already
    have run by then.
    """

    models: tuple[str, ...] = ()
    durationMs: int | None = None
    numTurns: int | None = None
    openedStepIds: tuple[str, ...] = ()
    available: bool = False
    errorCategory: str | None = None
    repairEnabled: bool = False
    attempts: int = 1
    firstRejection: str | None = None

    @property
    def toolUsed(self) -> bool:
        """Derived, never stored: an empty step list already says this."""
        return bool(self.openedStepIds)

    @property
    def repairAttempted(self) -> bool:
        """Derived, never stored: a second call is a rewrite and nothing else."""
        return self.attempts > 1


def record(job_id: str, trace: SynthesisTrace) -> str | None:
    """Store one trace. Returns its id, or None when it could not be stored."""
    trace_id = "tr_" + secrets.token_hex(12)
    try:
        db.execute(
            """INSERT INTO synthesis_traces
               (trace_id, job_id, created_at, models, duration_ms, num_turns,
                opened_step_ids, available, error_category,
                repair_enabled, attempts, first_rejection)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trace_id,
                job_id,
                db.now_iso(),
                json.dumps(list(trace.models)),
                trace.durationMs,
                trace.numTurns,
                json.dumps(list(trace.openedStepIds)),
                1 if trace.available else 0,
                trace.errorCategory,
                1 if trace.repairEnabled else 0,
                trace.attempts,
                trace.firstRejection,
            ),
        )
    except sqlite3.Error as exc:
        # Deliberate: see the module docstring. The synthesis the user asked for
        # is unaffected, and an operator sees this in the log.
        log.warning("could not record synthesis trace for %s: %s", job_id, exc)
        return None
    return trace_id


def recorder(job_id: str):
    """The callback `build_run_synthesis` takes, bound to one job."""

    def _record(trace: SynthesisTrace) -> None:
        record(job_id, trace)

    return _record


def recent(job_id: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    """Stored traces, newest first. For an operator and for tests.

    There is no endpoint for this on purpose: this is developer-facing data,
    and deciding what a user may see about a model call is a separate question
    from deciding what we keep.
    """
    if job_id is None:
        rows = db.query_all(
            "SELECT * FROM synthesis_traces ORDER BY created_at DESC, rowid DESC"
            " LIMIT ?",
            (limit,),
        )
    else:
        rows = db.query_all(
            "SELECT * FROM synthesis_traces WHERE job_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (job_id, limit),
        )
    return [
        {
            "traceId": row["trace_id"],
            "jobId": row["job_id"],
            "createdAt": row["created_at"],
            "models": db.loads(row["models"], []),
            "durationMs": row["duration_ms"],
            "numTurns": row["num_turns"],
            "openedStepIds": db.loads(row["opened_step_ids"], []),
            "available": bool(row["available"]),
            "errorCategory": row["error_category"],
            # NULL on rows from before these columns: not False, not 1 --
            # unknown, because that backend did not record them.
            "repairEnabled": (
                None if row["repair_enabled"] is None else bool(row["repair_enabled"])
            ),
            "attempts": row["attempts"],
            "firstRejection": row["first_rejection"],
        }
        for row in rows
    ]


__all__ = ["SynthesisTrace", "record", "recent", "recorder"]
