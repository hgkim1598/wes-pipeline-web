"""Redactor: paths whose segment names hold punctuation (2026-11-15).

Before this fix the rooted-path rule only accepted [\\w.-] in a segment, so a
punctuation character ended the match and left the first folder name in front
of the placeholder ("/lab+private/run/x.bed" -> "/lab+private<path>"). These
strings reach the model through step_evidence (check detail, message, ...),
which has no residual check of its own.

All inputs are synthetic.
"""

from __future__ import annotations

import pytest

from app.services.agent.privacy import Redactor


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/lab+private/run/x.bed", "<path>"),
        ("/srv/a@b/c/d", "<path>"),
        ("/data/~user/x", "<path>"),
        ("/data/(lab)/x", "<path>"),
        ("/data/a,b/x", "<path>"),
        ("/srv/a=b/c", "<path>"),
        # URL-encoded space: one token, so masked whole.
        ("/home/lab%20x/run/y", "<path>"),
        # relative path whose first segment holds punctuation
        ("lab+private/run/x.bed", "<path>"),
        ("a@b/run/x.bed", "<path>"),
        # trailing punctuation and a line number stay outside the placeholder
        ("(see /a+b/c/d.bed)", "(see <path>)"),
        ("missing /a+b/c.bed, /d/e/f.bed.", "missing <path>, <path>."),
        ("/a+b/c/x.bed:12: bad line", "<path>:12: bad line"),
        ("**/a+b/c**", "**<path>**"),
        # ":" ends a path (Codex review r3): what the tool said after it stays.
        ("failed /a+b/c:ENOENT", "failed <path>:ENOENT"),
        ("/a+b/c/x.bam:12:34", "<path>:12:34"),
    ],
)
def test_a_path_with_punctuation_is_masked_whole(raw, expected):
    assert Redactor().text(raw) == expected


@pytest.mark.parametrize(
    "fragment_source",
    ["/lab+private/run/x.bed", "/srv/a@b/c/d", "/home/lab%20x/run/y"],
)
def test_no_fragment_of_the_path_survives(fragment_source):
    # Exact comparison: a per-segment "not in" check is too weak (a one-letter
    # segment such as "d" also occurs in "failed", "lab%20x" vs "%20x").
    assert Redactor().text(f"open failed: {fragment_source}") == "open failed: <path>"


@pytest.mark.parametrize(
    "text",
    [
        "PASS/WARN",
        "chr1:12345-67890",
        "mg/dL",
        "mapped_pct 99.1",
        "bcftools: command not found",
        "'bcftools' not found in PATH",
        "GRCh38 / hg38",
        "04_processing",
        "+/- 5%",
        "reads/sec=1.5",
        "A/B test",
        "missing or empty: <path>",
        "ratio 0.98 (target >= 0.95)",
        "필수 도구 bcftools를 찾을 수 없습니다",
    ],
)
def test_ordinary_analysis_text_is_kept(text):
    assert Redactor().text(text) == text


def test_known_limit_a_space_inside_a_path_splits_it():
    """Documented limit, pinned so it is not mistaken for coverage."""
    assert Redactor().text("/data/my lab/x.bed") == "<path> <path>"
    assert Redactor().text("/data/my lab/run/x") == "<path> <path>"
    # A tail word that holds a separator is now taken as the rest of the path
    # (_CONTINUATION). What is still visible: a last folder name after a space
    # with no separator after it, which cannot be told apart from prose.
    assert Redactor().text("/data/my lab/x") == "<path>"
    assert Redactor().text("/data/my lab") == "<path> lab"


@pytest.mark.parametrize(
    "shape",
    [
        "ab+" * 20000,  # quadratic before the token-start lookbehind
        "a" * 60000,  # long plain word (_DATA_FILENAME retries it)
        "a" + chr(92) + ("a" + chr(92)) * 30000 + "z",  # backslash-separated, no extension
        "/a/" + ":1" * 30000 + "X",  # colon-number run (Codex review r3)
        "/a/" + ")" * 3996 + "X",  # trailer run just under MAX_SCAN (Codex review r4)
    ],
    ids=["ab-plus", "plain-word", "backslashes", "colon-numbers", "paren-run"],
)
def test_a_long_adversarial_string_is_bounded(shape):
    """Every shape here took seconds to tens of seconds at this length before
    MAX_SCAN (Codex review r3). The bound is loose on purpose."""
    import time

    started = time.perf_counter()
    out = Redactor().text(shape)
    assert time.perf_counter() - started < 1.0
    assert out.endswith(" ...(truncated)") or out == "<path>"


def test_a_string_over_the_scan_limit_is_cut_at_whitespace_not_inside_a_name():
    """The literal sits across MAX_SCAN. Paths shrink to "<path>", so the area
    around the cut reaches the output; a hard cut would leave "SYNTHSAM..." that
    the literal rule can no longer match."""
    from app.services.agent.privacy import MAX_SCAN

    unit = "/" + "a" * 30 + "/" + "b" * 30 + " "
    head = unit * ((MAX_SCAN - 9) // len(unit))
    head += "x" * (MAX_SCAN - 9 - len(head))
    text = head + " SYNTHSAMPLE01 tail"
    assert text.index("SYNTHSAMPLE01") < MAX_SCAN < text.index("SYNTHSAMPLE01") + 13
    out = Redactor(literals=(("SYNTHSAMPLE01", "<sample>"),)).text(text)
    assert "SYN" not in out  # a hard cut leaves "SYNTHSAM"
    assert out.endswith(" ...(truncated)") and len(out) < 1000


def test_a_short_string_is_not_marked_truncated():
    assert Redactor().text("PASS/WARN") == "PASS/WARN"


def test_known_limit_text_glued_after_a_closing_paren_is_taken_with_the_path():
    """Documented cost of keeping ")" inside names (privacy first)."""
    assert Redactor().text("(see /a/b)retry") == "(see <path>"


# --- Codex review r4: the scan cut must never split a known literal ---------------

_SHRINKING_HEAD = ("/" + "a" * 30 + "/" + "b" * 30 + "|") * 63 + "x" * 22  # 3991 chars, no space


# Known literals are marked (QZLIT<n>QZ, 8 characters) before the cut, so the
# cut works on marks: either the whole mark is kept and becomes the placeholder,
# or the cut moves to its start. Never a part of the name.
def test_a_hard_cut_does_not_leave_part_of_a_literal():
    out = Redactor(literals=(("SYNTHSAMPLE01", "<sample>"),)).text(_SHRINKING_HEAD + "SYNTHSAMPLE01 tail")
    assert out == "<path>|" * 63 + "x" * 22 + "<sample> ...(truncated)"


def test_a_hard_cut_across_a_mark_moves_to_its_start():
    # 3995 characters, then the mark: it spans MAX_SCAN and there is no space.
    out = Redactor(literals=(("SYNTHSAMPLE01", "<sample>"),)).text(_SHRINKING_HEAD + "xxxx" + "SYNTHSAMPLE01tail")
    assert out == "<path>|" * 63 + "x" * 26 + " ...(truncated)"


def test_a_cut_at_a_space_inside_a_literal_does_not_leave_part_of_it():
    out = Redactor(literals=(("SYNTH PRIVATE01", "<sample>"),)).text(_SHRINKING_HEAD + "SYNTH PRIVATE01 tail")
    assert out == "<path>|" * 63 + "x" * 22 + "<sample> ...(truncated)"
