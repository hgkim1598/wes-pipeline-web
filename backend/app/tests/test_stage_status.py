"""logs/stage_status.tsv parsing.

This is the only place the backend learns when a still-running step began, so
it has to be forgiving: the file is appended to by a shell script that may be
killed mid-write, and it survives --resume. Every failure mode here degrades to
"elapsed time unknown" (0), never to an exception or a changed step status.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import stage_status_reader

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds_before: int, *, offset: str = "+00:00") -> str:
    moment = NOW - timedelta(seconds=seconds_before)
    return moment.replace(tzinfo=None).isoformat() + offset


def elapsed(builder, step_id: str) -> int:
    return stage_status_reader.running_elapsed_seconds(
        builder.run_dir, step_id, now=NOW
    )


def test_missing_file_is_zero(run):
    builder = run()
    assert stage_status_reader.step_started_at(builder.run_dir, "03_alignment") is None
    assert elapsed(builder, "03_alignment") == 0


def test_empty_file_is_zero(run):
    builder = run()
    builder.raw("logs/stage_status.tsv", "")
    assert elapsed(builder, "03_alignment") == 0


def test_header_only_is_zero(run):
    builder = run()
    builder.stage_status([])
    assert elapsed(builder, "03_alignment") == 0


def test_started_row_gives_elapsed(run):
    builder = run()
    builder.stage_status([(at(600), "03_alignment", "STARTED")])
    assert elapsed(builder, "03_alignment") == 600


def test_compact_utc_offset_is_understood(run):
    """iso_now() falls back to '+%Y-%m-%dT%H:%M:%S%z', which has no colon."""
    builder = run()
    builder.stage_status([(at(300, offset="+0000"), "03_alignment", "STARTED")])
    assert elapsed(builder, "03_alignment") == 300


def test_other_steps_are_ignored(run):
    builder = run()
    builder.stage_status(
        [
            (at(900), "02_preprocessing", "STARTED"),
            (at(870), "02_preprocessing", "COMPLETED"),
            (at(600), "03_alignment", "STARTED"),
        ]
    )
    assert elapsed(builder, "03_alignment") == 600
    assert elapsed(builder, "02_preprocessing") == 900


def test_non_started_rows_are_ignored(run):
    builder = run()
    builder.stage_status(
        [
            (at(900), "03_alignment", "STARTED"),
            (at(100), "03_alignment", "FAILED"),
        ]
    )
    assert elapsed(builder, "03_alignment") == 900


def test_latest_started_wins_on_retry(run):
    """A --resume run starts the same step again; report the current attempt."""
    builder = run()
    builder.stage_status(
        [
            (at(9000), "03_alignment", "STARTED"),
            (at(8000), "03_alignment", "FAILED"),
            (at(120), "03_alignment", "STARTED"),
        ]
    )
    assert elapsed(builder, "03_alignment") == 120


def test_malformed_rows_do_not_hide_a_good_one(run):
    builder = run()
    builder.raw(
        "logs/stage_status.tsv",
        "timestamp\tstep\tstatus\texit_code\n"
        "not a tsv row at all\n"
        "\n"
        "\t\t\n"
        f"garbage-timestamp\t03_alignment\tSTARTED\t0\n"
        f"{at(450)}\t03_alignment\tSTARTED\t0\n"
        "truncated\trow\n",
    )
    assert elapsed(builder, "03_alignment") == 450


def test_only_malformed_rows_is_zero(run):
    builder = run()
    builder.raw(
        "logs/stage_status.tsv",
        "timestamp\tstep\tstatus\texit_code\n"
        "definitely-not-a-time\t03_alignment\tSTARTED\t0\n",
    )
    assert elapsed(builder, "03_alignment") == 0


def test_future_timestamp_clamps_to_zero(run):
    """Clock skew between the pipeline host and this process."""
    builder = run()
    builder.stage_status([(at(-300), "03_alignment", "STARTED")])
    assert elapsed(builder, "03_alignment") == 0


def test_naive_timestamp_is_read_as_local_time(run):
    builder = run()
    builder.raw(
        "logs/stage_status.tsv",
        "timestamp\tstep\tstatus\texit_code\n"
        "2026-08-22T12:00:00\t03_alignment\tSTARTED\t0\n",
    )
    started = stage_status_reader.step_started_at(builder.run_dir, "03_alignment")
    assert started is not None and started.tzinfo is not None
