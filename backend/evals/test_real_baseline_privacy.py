"""A real capture's baseline is leak-checked before it is written.

Reported as a remaining gap (development log 16.12) and reproduced in
Cycle 2 (log 17): an archive record went through `archive_record_leaks`
before `write_baseline`, a capture record went straight to the file. baselines/
is tracked by git, so a sample name or a path in `output` or `rejectedOutput`
would have been one `git add` away from the repository.

All data here is synthetic; the capture is never read.
"""

from __future__ import annotations

import json

import pytest

from . import real_runs, run_eval

SAMPLE = "SAMPLE_LITERAL_QZX"
# The registered run's own source values: the exemption is for exactly these.
CAPTURE_DIR_NAME = real_runs.REAL_RUNS["real_cba73e"].capture_dir.name
RUN_ID = real_runs.REAL_RUNS["real_cba73e"].run_id


def _record(summary: str, rejected: str | None = None) -> dict:
    return {
        "case": "real_cba73e",
        "runId": real_runs.REAL_RUNS["real_cba73e"].run_id,
        "captureDir": real_runs.REAL_RUNS["real_cba73e"].capture_dir.name,
        "evaluation": {"results": [], "deterministicPassed": True},
        "humanReview": {"items": []},
        "output": {"summary": summary},
        "rejectedOutput": None
        if rejected is None
        else {"attempt": 1, "category": "c", "findings": [], "answer": {"summary": rejected}},
    }


@pytest.fixture
def runner(monkeypatch, tmp_path):
    """main() on the real case with preflight, capture and model replaced."""
    literals = [SAMPLE, RUN_ID, CAPTURE_DIR_NAME]
    monkeypatch.setattr(real_runs, "capture_available", lambda _run: True)
    monkeypatch.setattr(run_eval, "preflight_real", lambda _n: {
        "payloadHash": "0" * 16, "restorationsMatch": True, "variantRunDataMatch": True,
        "privacy": "pass", "privacyDetail": "", "captureManifest": "0" * 16,
        "captureUnchanged": True,
    })
    monkeypatch.setattr(run_eval, "preflight_ok", lambda _c: True)
    monkeypatch.setattr(real_runs, "forbidden_literals", lambda _run: list(literals))
    monkeypatch.setattr(run_eval, "BASELINES", tmp_path)

    def run(record: dict) -> int:
        monkeypatch.setattr(run_eval, "evaluate_real", lambda _n, variant: record)
        monkeypatch.setattr(
            "sys.argv", ["run_eval", "--case", "realcba73e", "--yes", "--record-baseline"]
        )
        return run_eval.main()

    return run, tmp_path


def test_a_sample_name_in_the_output_is_not_written(runner, capsys):
    run, folder = runner
    assert run(_record(f"검체 {SAMPLE}의 결과")) == 2
    assert list(folder.iterdir()) == []
    out = capsys.readouterr().out
    assert "저장하지 않고 중단" in out
    assert SAMPLE not in out


def test_a_path_in_the_discarded_answer_is_not_written(runner):
    run, folder = runner
    assert run(_record("문제 없는 요약", rejected="파일 /data/runs/x/config.yaml 확인")) == 2
    assert list(folder.iterdir()) == []


def test_a_clean_record_is_written_with_its_source_fields(runner):
    # runId and captureDir name the source on purpose; they are not leaks.
    run, folder = runner
    assert run(_record("문제 없는 요약")) == 0
    written = list(folder.iterdir())
    assert len(written) == 1
    saved = json.loads(written[0].read_text(encoding="utf-8"))
    assert (saved["captureDir"], saved["runId"]) == (CAPTURE_DIR_NAME, RUN_ID)


def test_the_count_excludes_only_the_source_fields(monkeypatch):
    run = real_runs.REAL_RUNS["real_cba73e"]
    monkeypatch.setattr(real_runs, "forbidden_literals", lambda _run: [SAMPLE, CAPTURE_DIR_NAME])
    record = _record("요약")
    assert run_eval.real_record_leaks(run, record) == 0
    leaky = {**record, "humanReview": {"notes": CAPTURE_DIR_NAME}}
    assert run_eval.real_record_leaks(run, leaky) == 1


# --- Codex review (log 17.3): HIGH 1 -------------------------------------------


def test_a_source_field_holding_something_else_is_checked(monkeypatch):
    run = real_runs.REAL_RUNS["real_cba73e"]
    monkeypatch.setattr(real_runs, "forbidden_literals", lambda _run: [SAMPLE, CAPTURE_DIR_NAME])
    assert run_eval.real_record_leaks(run, {**_record("요약"), "runId": SAMPLE}) == 1
    assert run_eval.real_record_leaks(
        run, {**_record("요약"), "captureDir": "/private/captures/run/x"}
    ) >= 1


def test_a_nested_key_named_like_a_source_field_is_checked(monkeypatch):
    run = real_runs.REAL_RUNS["real_cba73e"]
    monkeypatch.setattr(real_runs, "forbidden_literals", lambda _run: [SAMPLE])
    nested = {**_record("요약"), "humanReview": {"runId": SAMPLE}}
    assert run_eval.real_record_leaks(run, nested) == 1


def test_the_known_limit_of_path_detection_is_stated():
    # Not a guarantee: a one-segment rooted path is not counted by the shared
    # detector (real_runs.count_paths). Recorded as a limit, not hidden.
    assert real_runs.count_paths("파일 /etc 확인") == 0


# --- Codex round 2 (log 17.3): an ancestor of a real path -----------------------
# Fixed after the second (last) review round: not reviewed by Codex.


def test_an_ancestor_of_a_forbidden_path_is_not_written(runner, monkeypatch):
    run, folder = runner
    monkeypatch.setattr(
        real_runs, "forbidden_literals",
        lambda _run: [SAMPLE, RUN_ID, CAPTURE_DIR_NAME, "/ClinicSecret/runs/job42"],
    )
    assert run(_record("문제 없는 요약", rejected="Failure opening /ClinicSecret")) == 2
    assert list(folder.iterdir()) == []


def test_ancestors_exclude_the_root_and_cover_both_path_styles():
    assert run_eval.path_ancestors("/a/b/c") == ["/a/b", "/a"]
    assert run_eval.path_ancestors("C:\\Users\\x\\proj") == ["C:\\Users\\x", "C:\\Users"]
    assert run_eval.path_ancestors(".capture_name") == []
    assert run_eval.path_ancestors("/one") == []
