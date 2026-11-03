"""compare_versions: one common basis, no overwrites, no model call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import compare_versions as cv

DAY2 = "2026-11-02_real_cba73e_v3_sonnet_d505c173885f6c9b.json"
DAY3 = "2026-11-02_real_cba73e_v3_sonnet_08c1f9035445420a.json"


def test_every_answer_is_scored_with_both_rule_versions():
    """Each side is judged by v1 and v2 alike, not by the checker it was written against."""
    row = cv.score_record(cv._resolve(DAY3), {})
    assert set(row["quality"]) == {"v1", "v2"}
    assert row["usage"] == "not recorded"
    assert row["deterministic"]["passed"] is True
    assert row["length"]["statementTotal"] == sum(row["length"]["statements"].values())


def test_a_side_mixing_prompt_versions_is_flagged():
    rows = [cv.score_record(cv._resolve(n), {}) for n in (DAY2, DAY3)]
    assert cv._side_summary(rows)["mixedVersions"] is True
    assert cv._side_summary(rows[:1])["mixedVersions"] is False


def test_output_files_are_never_overwritten(tmp_path: Path):
    existing = tmp_path / "report.json"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(SystemExit):
        cv.main(["--a", DAY2, "--b", DAY3, "--out", str(existing)])
    assert existing.read_text(encoding="utf-8") == "keep"


def test_the_blind_sheet_hides_which_side_wrote_each_answer(tmp_path: Path):
    sheet, key = tmp_path / "sheet.md", tmp_path / "key.json"
    cv.main(["--a", DAY2, "--b", DAY3, "--blind", str(sheet), "--blind-key", str(key)])
    text = sheet.read_text(encoding="utf-8")
    mapping = json.loads(key.read_text(encoding="utf-8"))
    assert set(mapping) == {"X01", "X02"}
    for name in (DAY2, DAY3, "d505c173885f6c9b", "08c1f9035445420a"):
        assert name not in text
