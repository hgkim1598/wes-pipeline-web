"""main.sh's BWA index check, exercised as the real code.

The validator is a Python heredoc inside script/main.sh (`PYBUNDLE`). Running
main.sh itself would need a run directory, a samplesheet and the analysis tools,
so the block is extracted and run directly. Extracting rather than copying is the
point: a copy would keep passing after main.sh changed.

Only the BWA-index lines are asserted on. With no BED and no known-sites the
validator reports those as errors too and exits non-zero; that is expected and
irrelevant here, and it keeps the fixture from needing bcftools/tabix.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from .. import config

HEREDOC_OPEN = "<<'PYBUNDLE'\n"
HEREDOC_CLOSE = "\nPYBUNDLE\n"

# argv the block expects, minus the reference:
#   ref, bed, coverage_bed, contig_style, dbsnp, bed_sha256, coverage_sha256, *known_sites
REST_OF_ARGV = ["", "", "chr", "", "", ""]

BWA_EXTS = ("amb", "ann", "bwt", "pac", "sa")


@pytest.fixture(scope="module")
def validator(tmp_path_factory):
    """The PYBUNDLE block, lifted out of main.sh as it is on disk."""
    text = config.PIPELINE_SH.read_text(encoding="utf-8")
    start = text.index(HEREDOC_OPEN) + len(HEREDOC_OPEN)
    end = text.index(HEREDOC_CLOSE, start)
    path = tmp_path_factory.mktemp("validator") / "resource_validation.py"
    path.write_text(text[start:end], encoding="utf-8")
    return path


def bwa_lines(validator, ref) -> list[str]:
    """Every reported line that talks about the BWA index."""
    proc = subprocess.run(
        [sys.executable, str(validator), str(ref), *REST_OF_ARGV],
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr
    return [line.strip() for line in output.splitlines() if "BWA index" in line]


def make_reference(tmp_path, index_suffixes, empty=()):
    """A reference FASTA plus exactly the index files named."""
    ref = tmp_path / "Homo_sapiens_assembly38.fasta"
    ref.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in index_suffixes:
        target = tmp_path / (ref.name + suffix)
        target.write_bytes(b"" if suffix in empty else b"index")
    return ref


def standard_set():
    return [f".{ext}" for ext in BWA_EXTS]


def sixty_four_set():
    return [f".64.{ext}" for ext in BWA_EXTS]


# --- the two normal shapes ---------------------------------------------------


def test_standard_index_passes(validator, tmp_path):
    """The pre-existing layout must keep working: this is the regression guard."""
    lines = bwa_lines(validator, make_reference(tmp_path, standard_set()))

    assert not [line for line in lines if line.startswith("-")], lines
    assert any("standard naming" in line for line in lines), lines


def test_64_bit_index_passes(validator, tmp_path):
    """The Broad GRCh38 bundle ships .64 names. It used to fail this check."""
    lines = bwa_lines(validator, make_reference(tmp_path, sixty_four_set()))

    assert not [line for line in lines if line.startswith("-")], lines
    assert any("64-bit .64 naming" in line for line in lines), lines


def test_both_layouts_present_reports_the_one_bwa_would_use(validator, tmp_path):
    lines = bwa_lines(
        validator, make_reference(tmp_path, standard_set() + sixty_four_set())
    )

    assert not [line for line in lines if line.startswith("-")], lines
    # bwa probes .64.bwt first, so that is the prefix it resolves to.
    assert any("64-bit .64 naming" in line for line in lines), lines


# --- incomplete sets ---------------------------------------------------------


def test_incomplete_64_set_fails_and_names_what_is_missing(validator, tmp_path):
    ref = make_reference(tmp_path, [".64.amb", ".64.ann", ".64.bwt"])

    lines = bwa_lines(validator, ref)

    assert any("is incomplete" in line for line in lines), lines
    problem = next(line for line in lines if "is incomplete" in line)
    assert ".pac" in problem and ".sa" in problem, problem
    assert ".64" in problem, problem


def test_stray_64_bwt_beside_a_complete_standard_set_fails(validator, tmp_path):
    """The case where "any complete set will do" would have been wrong.

    bwa_idx_infer_prefix() returns the .64 prefix as soon as .64.bwt opens and
    never falls back, so the complete standard set next to it is unreachable.
    Passing this would move the failure to 03_alignment, hours in.
    """
    ref = make_reference(tmp_path, standard_set() + [".64.bwt"])

    lines = bwa_lines(validator, ref)

    problem = next(line for line in lines if "is incomplete" in line)
    assert ".64" in problem, problem
    assert all(f".{ext}" in problem for ext in ("amb", "ann", "pac", "sa")), problem


def test_empty_bwt_is_not_a_usable_index(validator, tmp_path):
    """A zero-byte .bwt still selects the prefix, exactly as fopen() would."""
    ref = make_reference(tmp_path, standard_set(), empty={".bwt"})

    lines = bwa_lines(validator, ref)

    assert any("is incomplete" in line and ".bwt" in line for line in lines), lines


def test_no_index_at_all_fails(validator, tmp_path):
    lines = bwa_lines(validator, make_reference(tmp_path, []))

    assert any("BWA index not found" in line for line in lines), lines
    problem = next(line for line in lines if "BWA index not found" in line)
    assert ".64.bwt" in problem and "bwa index" in problem, problem


def test_missing_reference_reports_nothing_about_the_index(validator, tmp_path):
    """No reference means no prefix to resolve; the FASTA error stands alone."""
    assert bwa_lines(validator, tmp_path / "absent.fasta") == []
