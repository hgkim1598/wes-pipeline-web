"""Read the step-start events main.sh appends to logs/stage_status.tsv.

Why this file and not the step documents: main.sh writes
status/steps/<step>.json only when a step *finishes* (finish_step), so while a
step is running there is nothing on disk that says when it began. start_step()
does append a row here first:

    append_status_tsv "$CURRENT_STEP" "STARTED" "0"      script/main.sh:644

so this is the pipeline's own record of the start, not an inference. The layout
is fixed by append_status_tsv (script/main.sh:541-546):

    timestamp<TAB>step<TAB>status<TAB>exit_code
    2026-08-13T17:01:08+09:00<TAB>00_input_validation<TAB>STARTED<TAB>0

Timestamps come from iso_now(), which is `date -Is` with a
'+%Y-%m-%dT%H:%M:%S%z' fallback, so both "+09:00" and "+0900" are legitimate.

Everything here is best-effort by design. A missing, truncated or malformed
file means "the elapsed time is not known", which is a display detail. It must
never change a step's status or fail a request: the authority on what happened
is still the JSON document set.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

STAGE_STATUS_TSV = ("logs", "stage_status.tsv")
STARTED = "STARTED"

# A trailing "+0900" that datetime.fromisoformat rejects on older interpreters.
_COMPACT_OFFSET_RE = re.compile(r"([+-])(\d{2})(\d{2})$")


def _parse_timestamp(raw: str) -> datetime | None:
    """Parse one iso_now() timestamp, or give up quietly."""
    value = raw.strip()
    if not value:
        return None
    candidates = [value]
    compact = _COMPACT_OFFSET_RE.sub(r"\1\2:\3", value)
    if compact != value:
        candidates.append(compact)
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        # A row without an offset is read as this machine's local time, which
        # is what `date` would have produced on the box that wrote it.
        return parsed if parsed.tzinfo is not None else parsed.astimezone()
    return None


def step_started_at(run_dir: Path | str, step_id: str) -> datetime | None:
    """When the pipeline last reported starting this step.

    The *last* valid STARTED row wins. A step legitimately starts more than
    once across --resume, and a retried run must report the current attempt,
    not the first one.
    """
    path = Path(run_dir).joinpath(*STAGE_STATUS_TSV)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    latest: datetime | None = None
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            # Blank line, or a row truncated by a crash mid-write. The header
            # has four fields and is skipped by the STARTED test below.
            continue
        timestamp, step, status = (field.strip() for field in fields[:3])
        if step != step_id or status.upper() != STARTED:
            continue
        parsed = _parse_timestamp(timestamp)
        if parsed is not None:
            latest = parsed
    return latest


def running_elapsed_seconds(
    run_dir: Path | str, step_id: str, *, now: datetime | None = None
) -> int:
    """Seconds since this step last started, or 0 when that is unknowable.

    0 is the same value the caller used before this module existed, so an
    unreadable stage status degrades to the previous behaviour instead of
    producing a wrong number. A negative result (clock skew between the writer
    and this process) is clamped for the same reason.
    """
    started = step_started_at(run_dir, step_id)
    if started is None:
        return 0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.astimezone()
    elapsed = (current - started).total_seconds()
    return int(elapsed) if elapsed > 0 else 0
