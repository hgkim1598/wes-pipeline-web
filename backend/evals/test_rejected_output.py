"""The discarded answer an eval record keeps (`rejectedOutput`).

It is kept so a gate rejection can be read and reproduced (development log
16.8). It is never served and never scored, and it is held to the same leak
rules as the rest of an archive record before anything is written.
"""

from __future__ import annotations

from . import archive_runs, run_eval
from .test_archive_runs import needs_archive

ANSWER = {
    "summary": "요약 문장",
    "importantFindings": [
        {"statement": "첫째", "evidenceRefs": []},
        {"statement": "둘째", "evidenceRefs": []},
    ],
}


def test_the_flagged_sentence_is_found_by_its_gate_location():
    assert run_eval.rejected_statement(ANSWER, "importantFindings.1") == "둘째"
    assert run_eval.rejected_statement(ANSWER, "summary") == "요약 문장"


def test_a_location_that_does_not_resolve_gives_none():
    assert run_eval.rejected_statement(ANSWER, "importantFindings.9") is None
    assert run_eval.rejected_statement(ANSWER, "nextChecks.0") is None
    assert run_eval.rejected_statement(None, "summary") is None


def test_the_report_prints_the_sentence_and_the_problem(capsys):
    run_eval.print_rejected(
        {
            "attempt": 1,
            "category": "runFactMismatch",
            "findings": [
                {"locations": ["importantFindings.1"], "values": ["warning steps: X"]}
            ],
            "answer": ANSWER,
        }
    )
    out = capsys.readouterr().out
    assert "importantFindings.1: 둘째" in out
    assert "warning steps: X" in out
    assert "사용자에게 제공되지 않음" in out


@needs_archive
def test_a_sample_name_inside_the_discarded_answer_is_a_leak():
    run = archive_runs.ARCHIVE_RUNS["real_3a22c5"]
    clean = {"runId": run.run_id, "output": None, "rejectedOutput": {"answer": ANSWER}}
    leaky = {
        **clean,
        "rejectedOutput": {"answer": {"summary": archive_runs.read_sample(run)}},
    }
    assert run_eval.archive_record_leaks(run, clean) == 0
    assert run_eval.archive_record_leaks(run, leaky) > 0


@needs_archive
def test_masking_reaches_the_discarded_answer():
    run = archive_runs.ARCHIVE_RUNS["real_3a22c5"]
    sample = archive_runs.read_sample(run)
    record = {"rejectedOutput": {"answer": {"summary": f"검체 {sample}"}}}
    masked = run_eval.mask_record(record, [sample])
    assert sample not in str(masked)


# --- Codex review of this unit (2026-11-16) -----------------------------------
# HIGH (confirmed by reading main()): a real capture's report was printed
# unmasked, and rejectedOutput made it print answer text. L: odd locations.


def _rejected_record(text: str) -> dict:
    return {
        "case": "real_cba73e",
        "evaluation": {"results": [], "deterministicPassed": False},
        "humanReview": {"items": []},
        "rejectedOutput": {
            "attempt": 1,
            "category": "runFactMismatch",
            "findings": [{"locations": ["summary"], "values": ["x"]}],
            "answer": {"summary": text},
        },
    }


def test_a_real_capture_report_is_masked_before_printing(monkeypatch, capsys, tmp_path):
    from . import real_runs

    secret = "SAMPLE_LITERAL_QZX"
    monkeypatch.setattr(real_runs, "capture_available", lambda _run: True)
    monkeypatch.setattr(run_eval, "preflight_real", lambda _n: {
        "payloadHash": "0" * 16, "restorationsMatch": True, "variantRunDataMatch": True,
        "privacy": "pass", "privacyDetail": "", "captureManifest": "0" * 16,
        "captureUnchanged": True,
    })
    monkeypatch.setattr(run_eval, "preflight_ok", lambda _c: True)
    monkeypatch.setattr(real_runs, "forbidden_literals", lambda _run: [secret])
    monkeypatch.setattr(
        run_eval, "evaluate_real",
        lambda _n, variant: _rejected_record(f"검체 {secret} 경로 /data/runs/x 문장"),
    )
    monkeypatch.setattr("sys.argv", ["run_eval", "--case", "realcba73e", "--yes"])

    run_eval.main()
    out = capsys.readouterr().out
    assert "폐기된 답" in out
    assert secret not in out
    assert "/data/runs/x" not in out


def test_the_rejected_sentence_lookup_refuses_malformed_locations():
    weird = {**ANSWER, "limitations": [{"statement": {"not": "a sentence"}}]}
    for location in ["summary.", "summary.0", "importantFindings", "importantFindings.²",
                     "importantFindings.9999999", "importantFindings.-1", 5, None,
                     " importantFindings.0", "limitations.0"]:
        assert run_eval.rejected_statement(weird, location) is None, location


def test_printing_tolerates_odd_findings(capsys):
    run_eval.print_rejected({
        "attempt": 1, "category": "c", "answer": ANSWER,
        "findings": ["not a dict", {"locations": "summary", "values": "abc"},
                     {"locations": [7, "summary"], "values": [{"k": 1}]}],
    })
    out = capsys.readouterr().out
    assert "summary: 요약 문장" in out
    # A bare string is not iterated character by character.
    assert "\n      - a\n" not in out


def test_an_index_above_999_resolves():
    # Codex round 2 (LOW): the schema does not cap a group's length.
    many = {"nextChecks": [{"statement": f"s{i}", "evidenceRefs": []} for i in range(1001)]}
    assert run_eval.rejected_statement(many, "nextChecks.1000") == "s1000"
