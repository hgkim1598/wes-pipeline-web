"""Coverage metrics must say which of two different things they measure.

mosdepth is invoked once and produces two outputs that answer different
questions:

    regions.bed.gz     one MEAN DEPTH per target interval
    thresholds.bed.gz  per interval, the COUNT OF BASES at or above each depth

The numbers derived from the first are interval level; the ones derived from
the second are base level. They are not interchangeable, and the gap between
them is not rounding: an interval that is half covered has a mean above 0, so
it is not a "fully uncovered interval", yet every uncovered base inside it is
still a zero-coverage base.

Before this change the interval-level numbers were named `uncovered_bases*` and
`low_coverage_bases*`, and the UNCOVERED_TARGETS warning reported one of them
while its message described target *bases*. The rename exists to remove that
confusion, and these tests pin the distinction with a fixture built so the two
measures deliberately disagree.

The Python block is extracted from script/main.sh rather than reproduced here.
A copy would keep passing after main.sh changed, which is the one thing a
regression test must not do.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import re
import subprocess
import sys

import pytest

from .. import config


def extract_heredoc(name: str) -> str:
    """Lift one quoted heredoc body out of main.sh as it is on disk."""
    text = config.PIPELINE_SH.read_text(encoding="utf-8")
    match = re.search(
        rf"<<'{name}'\n(.*?)\n{name}\n", text, re.DOTALL
    )
    assert match is not None, f"could not find the {name} heredoc in main.sh"
    return match.group(1)


# Three intervals, chosen so the two measures cannot coincide.
#
#   A  0-100    fully covered at 10x   mean 10   bases >=1x: 100
#   B  100-200  HALF covered           mean  5   bases >=1x:  50   <- the point
#   C  200-300  never covered          mean  0   bases >=1x:   0
#
# base level      150 of 300 bases never reached 1x        -> 50.0000 %
# interval level  only C is fully uncovered, 100 of 300    -> 33.3333 %
REGIONS = [
    ("chr1", 0, 100, "A", "10.00"),
    ("chr1", 100, 200, "B", "5.00"),
    ("chr1", 200, 300, "C", "0.00"),
]
THRESHOLDS_HEADER = "#chrom\tstart\tend\tregion\t1X\t10X\t20X\n"
THRESHOLDS = [
    ("chr1", 0, 100, "A", 100, 100, 0),
    ("chr1", 100, 200, "B", 50, 0, 0),
    ("chr1", 200, 300, "C", 0, 0, 0),
]


@pytest.fixture
def metrics(tmp_path: pathlib.Path) -> dict:
    """Run main.sh's own coverage block over the fixture above."""
    regions = tmp_path / "regions.bed.gz"
    thresholds = tmp_path / "thresholds.bed.gz"
    out_json = tmp_path / "coverage_metrics.json"
    low_bed = tmp_path / "low_mean_depth_intervals.bed"

    with gzip.open(regions, "wt", encoding="utf-8") as handle:
        for chrom, start, end, name, depth in REGIONS:
            handle.write(f"{chrom}\t{start}\t{end}\t{name}\t{depth}\n")

    with gzip.open(thresholds, "wt", encoding="utf-8") as handle:
        handle.write(THRESHOLDS_HEADER)
        for chrom, start, end, name, ge1, ge10, ge20 in THRESHOLDS:
            handle.write(f"{chrom}\t{start}\t{end}\t{name}\t{ge1}\t{ge10}\t{ge20}\n")

    script = tmp_path / "cov.py"
    script.write_text(extract_heredoc("PYCOV"), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(regions),
            str(thresholds),
            str(out_json),
            str(low_bed),
            "20",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(out_json.read_text(encoding="utf-8"))


# --- base level -------------------------------------------------------------


def test_zero_coverage_is_the_complement_of_1x_breadth(metrics):
    """The identity that defines the base-level measure.

    Both sides come from the same thresholds counts and the same denominator,
    so any drift means one of them is being computed differently.
    """
    assert metrics["target_bases_ge_1X_pct"] == 50.0
    assert metrics["zero_coverage_bases_pct"] == pytest.approx(
        100.0 - metrics["target_bases_ge_1X_pct"], abs=1e-9
    )


def test_zero_coverage_count_comes_from_the_1x_count(metrics):
    """150 = 300 total - 150 bases at or above 1x.

    Counted, not derived from a rounded percentage: 0 uncovered in A,
    50 in B, 100 in C.
    """
    assert metrics["zero_coverage_bases"] == 150
    assert metrics["target_nonoverlap_bases"] == 300
    assert 100.0 * metrics["zero_coverage_bases"] / 300 == pytest.approx(
        metrics["zero_coverage_bases_pct"], abs=1e-9
    )


# --- interval level ---------------------------------------------------------


def test_a_partially_covered_interval_is_not_fully_uncovered(metrics):
    """B is half covered, so its mean is 5 and it is not counted here.

    Only C qualifies. This is what makes the interval measure different from
    the base measure rather than a rounding of it.
    """
    assert metrics["fully_uncovered_intervals"] == 1
    assert metrics["bases_in_fully_uncovered_intervals"] == 100
    assert metrics["bases_in_fully_uncovered_intervals_pct"] == pytest.approx(
        33.3333, abs=1e-4
    )


def test_low_mean_depth_uses_the_configured_threshold(metrics):
    """All three means (10, 5, 0) are below the 20x passed in."""
    assert metrics["low_mean_depth_threshold_x"] == 20.0
    assert metrics["low_mean_depth_intervals"] == 3
    assert metrics["bases_in_low_mean_depth_intervals"] == 300
    assert metrics["bases_in_low_mean_depth_intervals_pct"] == 100.0


# --- the distinction itself -------------------------------------------------


def test_interval_measure_understates_zero_coverage(metrics):
    """33.3333 % vs 50.0 % for the same run.

    The 50 uncovered bases inside the partially covered interval are invisible
    to the interval measure. Reporting the interval number as though it were
    the share of uncovered target bases understates it -- which is exactly what
    the old UNCOVERED_TARGETS message did.
    """
    assert metrics["bases_in_fully_uncovered_intervals_pct"] == pytest.approx(33.3333, abs=1e-4)
    assert metrics["zero_coverage_bases_pct"] == 50.0
    assert (
        metrics["bases_in_fully_uncovered_intervals_pct"]
        < metrics["zero_coverage_bases_pct"]
    )


def test_legacy_metric_names_are_no_longer_written(metrics):
    """New runs must not emit the ambiguous names.

    Old runs keep them on disk and the backend reader maps them
    (result_reader._coverage); nothing here rewrites history. But a new run
    emitting both would leave two names for one number.
    """
    for legacy in (
        "uncovered_bases",
        "uncovered_bases_pct",
        "uncovered_intervals",
        "low_coverage_bases",
        "low_coverage_bases_pct",
        "low_coverage_intervals",
        "low_coverage_threshold_x",
    ):
        assert legacy not in metrics, legacy


def test_median_stays_null(metrics):
    """mosdepth runs with --no-per-base, so there is no per-base median."""
    assert metrics["median_target_depth"] is None
    assert "no-per-base" in metrics["median_note"]


# --- guards -----------------------------------------------------------------


def test_zero_coverage_absent_when_1x_was_not_requested(tmp_path):
    """No 1X column, no honest zero-coverage figure. Omitted, not guessed."""
    regions = tmp_path / "regions.bed.gz"
    thresholds = tmp_path / "thresholds.bed.gz"
    out_json = tmp_path / "coverage_metrics.json"
    low_bed = tmp_path / "low.bed"

    with gzip.open(regions, "wt", encoding="utf-8") as handle:
        handle.write("chr1\t0\t100\tA\t10.00\n")

    with gzip.open(thresholds, "wt", encoding="utf-8") as handle:
        handle.write("#chrom\tstart\tend\tregion\t10X\t20X\n")
        handle.write("chr1\t0\t100\tA\t100\t0\n")

    script = tmp_path / "cov.py"
    script.write_text(extract_heredoc("PYCOV"), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(regions),
            str(thresholds),
            str(out_json),
            str(low_bed),
            "20",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["target_bases_ge_10X_pct"] == 100.0
    assert "zero_coverage_bases" not in doc
    assert "zero_coverage_bases_pct" not in doc


def test_low_mean_depth_bed_lists_the_intervals_below_threshold(tmp_path, metrics):
    """The artifact is a list of low-MEAN intervals, not of 0x positions.

    Regenerated here rather than reused from the fixture so the file contents
    are asserted directly.
    """
    regions = tmp_path / "r.bed.gz"
    thresholds = tmp_path / "t.bed.gz"
    out_json = tmp_path / "c.json"
    low_bed = tmp_path / "low_mean_depth_intervals.bed"

    with gzip.open(regions, "wt", encoding="utf-8") as handle:
        for chrom, start, end, name, depth in REGIONS:
            handle.write(f"{chrom}\t{start}\t{end}\t{name}\t{depth}\n")
    with gzip.open(thresholds, "wt", encoding="utf-8") as handle:
        handle.write(THRESHOLDS_HEADER)
        for chrom, start, end, name, ge1, ge10, ge20 in THRESHOLDS:
            handle.write(f"{chrom}\t{start}\t{end}\t{name}\t{ge1}\t{ge10}\t{ge20}\n")

    script = tmp_path / "cov.py"
    script.write_text(extract_heredoc("PYCOV"), encoding="utf-8")
    subprocess.run(
        [
            sys.executable, str(script), str(regions), str(thresholds),
            str(out_json), str(low_bed), "8",
        ],
        capture_output=True, text=True, check=True,
    )

    rows = [r.split("\t") for r in low_bed.read_text().splitlines() if r.strip()]
    # Only B (mean 5) and C (mean 0) are below 8x; A (mean 10) is not.
    assert [r[1] for r in rows] == ["100", "200"]
    # The fourth column is the interval MEAN, which is what makes this file an
    # interval-level artifact.
    assert rows[0][3] == "5.0"
    assert rows[1][3] == "0.0"
