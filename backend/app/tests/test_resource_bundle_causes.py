"""P0-1: the internal analysis of a failed resource_bundle check.

Spec: docs/specs/P0-1_resource_bundle_causes.md (v4)
ADR:  docs/adr/ADR-001-resource-cause-boundary.md

This file tests the INTERNAL half only -- raw sentences, before any redaction.
What may leave the backend is tested in test_resource_bundle_diagnosis.py.

Three kinds of evidence, kept apart on purpose:

  synthetic   strings written here, modelled on the real record's line shapes
              but with invented paths and sample names. Always run.
  heredoc     the real PYBUNDLE block extracted from script/main.sh and run,
              so the rule table is checked against the sentences main.sh
              actually prints (NFR-9). Always run.
  real run    the untracked evidence archive at the repository root
              (wes_failure_evidence_20261112.tar.gz), extracted read-only into
              tmp_path. Skipped, and reported as skipped, when it is absent.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from .. import config
from ..services import resource_bundle_causes as rbc
from ..services import step_reader

STEP = "00_input_validation"
REPORT = Path("00_input_validation") / "resource_validation.txt"
LOG = Path("logs") / "pipeline.log"

FAIL = [
    {"name": "required_tools", "status": "PASS", "detail": "all present"},
    {
        "name": "resource_bundle",
        "status": "FAIL",
        "detail": "validation failed; see 00_input_validation/resource_validation.txt",
    },
]
PASS = [{"name": "resource_bundle", "status": "PASS", "detail": "ok"}]

HEADER = "[ERROR] Resource bundle validation failed:"
START = "[2026-09-04 19:47:04] START 00_input_validation"

# Synthetic reproduction of 3a22c5's block. Paths and sample are invented.
BED_MISSING = [
    "  - target_bed missing or empty: /srv/wes/ref/beds/kit_v2/targets.bed",
    "  - coverage_bed missing or empty: /srv/wes/ref/beds/kit_v2/coverage.bed",
]
# Synthetic reproduction of b94559's block.
BCFTOOLS_ABSENT = [
    "  - bcftools unavailable for /srv/wes/ref/known_indels.vcf.gz: "
    "[Errno 2] No such file or directory: 'bcftools'",
    "  - bcftools unavailable for /srv/wes/ref/mills_indels.vcf.gz: "
    "[Errno 2] No such file or directory: 'bcftools'",
]


def log_with(*segments: list[str], preamble: tuple[str, ...] = ()) -> str:
    """A pipeline.log: an optional preamble, then one START segment per list."""
    lines = [
        "[2026-09-04 19:46:50] ============================================================",
        "[2026-09-04 19:46:50] variant-pipeline-lab-wes 1.2.0",
        *preamble,
    ]
    for body in segments:
        lines.append(START)
        lines.append("[OK] Validated 1 lane row(s) for sample 'DEMO01'.")
        lines.extend(body)
        lines.append(
            "[2026-09-04 19:47:13] [WARN] [00_input_validation] FAIL resource_bundle: "
            "validation failed; see 00_input_validation/resource_validation.txt"
        )
        lines.append("[2026-09-04 19:47:13] DONE  00_input_validation status=failed exit=1 (9s)")
    return "\n".join(lines) + "\n"


def block(items: list[str]) -> list[str]:
    return ["[NOTE] reference contigs: 3366", HEADER, *items]


def write(run_dir: Path, rel: Path, text: str | bytes) -> Path:
    path = run_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="\n")
    return path


@pytest.fixture
def run_dir(tmp_path) -> Path:
    path = tmp_path / "wes-20260904-194645-aaaaaa"
    path.mkdir()
    return path


@pytest.fixture
def reads(monkeypatch):
    """Every path the analysis asks to read, in order."""
    seen: list[Path] = []
    original = rbc._read_tail

    def spy(path: Path):
        seen.append(Path(path))
        return original(path)

    monkeypatch.setattr(rbc, "_read_tail", spy)
    return seen


def kinds(result) -> list[tuple[str, str, str | None, str | None]]:
    return [(c.kind, c.resource_role, c.tool, c.rule_id) for c in result.causes]


# --- applicability (FR-1, FR-2) ----------------------------------------------


def test_other_steps_have_no_analysis_and_read_nothing(run_dir, reads):
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    assert rbc.analyze(run_dir, "03_alignment", FAIL) is None
    assert reads == []


@pytest.mark.parametrize(
    "checks",
    [
        PASS,
        [{"name": "resource_bundle", "status": "WARN", "detail": "x"}],
        [{"name": "required_tools", "status": "FAIL", "detail": "x"}],
        [],
    ],
    ids=["pass", "warn", "no-row", "pending-or-running"],
)
def test_not_failed_is_not_applicable_and_reads_nothing(run_dir, reads, checks):
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, checks)
    assert result is not None
    assert result.state == "not_applicable"
    assert result.causes == ()
    assert result.source is None
    assert reads == []


# --- the two real shapes, synthetic (FR-4, FR-5, FR-14) ----------------------


def test_bed_pair_missing_is_two_causes(run_dir):
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "parsed"
    assert result.source == "pipeline_log"
    assert kinds(result) == [
        ("resource_missing_or_empty", "target_bed", None, "R-MISSING"),
        ("resource_missing_or_empty", "coverage_bed", None, "R-MISSING"),
    ]
    assert result.truncated is False


def test_beds_plus_bcftools_is_four_causes_with_unknown_role(run_dir):
    write(run_dir, LOG, log_with(block(BED_MISSING + BCFTOOLS_ABSENT)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "parsed"
    assert kinds(result) == [
        ("resource_missing_or_empty", "target_bed", None, "R-MISSING"),
        ("resource_missing_or_empty", "coverage_bed", None, "R-MISSING"),
        # Q2: the sentence has no label, so the role is not guessed from the
        # file name in it.
        ("vcf_tool_unavailable", "unknown", "bcftools", "R-VCF-TOOL-B"),
        ("vcf_tool_unavailable", "unknown", "bcftools", "R-VCF-TOOL-B"),
    ]


def test_raw_text_is_kept_internally_verbatim(run_dir):
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.causes[0].raw_text == BED_MISSING[0][len("  - "):]


# --- unknown is preserved, never guessed (FR-6) -------------------------------


def test_unclassified_sentence_is_unknown(run_dir):
    write(run_dir, LOG, log_with(block(["  - something new happened to the bundle"])))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "parsed"
    assert kinds(result) == [("unknown", "unknown", None, None)]
    assert result.causes[0].raw_text == "something new happened to the bundle"


def test_known_and_unknown_keep_their_order(run_dir):
    items = ["  - mystery", BED_MISSING[0], "  - another mystery"]
    write(run_dir, LOG, log_with(block(items)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert [c.kind for c in result.causes] == [
        "unknown",
        "resource_missing_or_empty",
        "unknown",
    ]


# --- rule table against every PYBUNDLE template (FR-5, §7.3) -----------------


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("reference_fasta is not set in the resource bundle",
         ("resource_not_declared", "reference_fasta", None, "R-NOTSET")),
        ("dbsnp_vcf missing or empty: /x/y/dbsnp.vcf.gz",
         ("resource_missing_or_empty", "dbsnp_vcf", None, "R-MISSING")),
        ("reference FASTA index (.fai) missing or empty: /x/y/ref.fa.fai",
         ("resource_missing_or_empty", "reference_fai", None, "R-MISSING")),
        ("reference sequence dictionary (.dict) missing or empty: /x/ref.dict",
         ("resource_missing_or_empty", "reference_dict", None, "R-MISSING")),
        ("known_sites entry missing or empty: /x/y/mills.vcf.gz",
         ("resource_missing_or_empty", "known_sites", None, "R-MISSING")),
        ("mystery_label missing or empty: /x/y/z",
         ("resource_missing_or_empty", "unknown", None, "R-MISSING")),
        ("BWA index at '/x/ref.fa.64.*' is incomplete: missing or empty .sa. bwa ...",
         ("bwa_index_incomplete", "bwa_index", None, "R-BWA-INCOMPLETE")),
        ("BWA index not found: neither '/x/ref.fa.64.bwt' nor '/x/ref.fa.bwt' exists.",
         ("bwa_index_not_found", "bwa_index", None, "R-BWA-NONE")),
        ("reference .fai and .dict disagree on contig order or lengths",
         ("reference_index_mismatch", "reference_fasta", None, "R-FAI-DICT")),
        ("contig_style='plain' declares no 'chr' prefix but the reference uses 'chr'",
         ("contig_style_mismatch", "reference_fasta", None, "R-STYLE")),
        ("contig_style='chr' declares a 'chr' prefix but the reference does not use it",
         ("contig_style_mismatch", "reference_fasta", None, "R-STYLE")),
        ("contig_style='GRCh38' is not a recognised chromosome naming convention; expected",
         ("contig_style_unrecognised", "reference_fasta", None, "R-STYLE")),
        ("target BED SHA-256 mismatch: metadata=" + "a" * 64 + " actual=" + "b" * 64,
         ("checksum_mismatch", "target_bed", None, "R-SHA")),
        ("coverage BED line 7: fewer than 3 columns",
         ("bed_content_invalid", "coverage_bed", None, "R-BED-CONTENT")),
        ("target BED line 3: start/end are not integers",
         ("bed_content_invalid", "target_bed", None, "R-BED-CONTENT")),
        ("target BED line 9: contig absent from reference: chrZ",
         ("bed_content_invalid", "target_bed", None, "R-BED-CONTENT")),
        ("target BED line 9: interval out of range chr1:0-99999999999",
         ("bed_content_invalid", "target_bed", None, "R-BED-CONTENT")),
        ("coverage BED contains no usable intervals",
         ("bed_content_invalid", "coverage_bed", None, "R-BED-CONTENT")),
        ("known_sites entry index missing (.tbi or .csi): /x/mills.vcf.gz",
         ("vcf_index_missing", "known_sites", None, "R-VCF-INDEX")),
        ("cannot parse VCF header: /x/mills.vcf.gz",
         ("vcf_header_unparseable", "unknown", "bcftools", "R-VCF-HEADER")),
        ("bcftools unavailable for /x/mills.vcf.gz: [Errno 2] No such file",
         ("vcf_tool_unavailable", "unknown", "bcftools", "R-VCF-TOOL-B")),
        ("tabix unavailable for /x/mills.vcf.gz: [Errno 2] No such file",
         ("vcf_tool_unavailable", "unknown", "tabix", "R-VCF-TOOL-T")),
        ("cannot read tabix contig list: /x/mills.vcf.gz",
         ("vcf_contig_list_unreadable", "unknown", "tabix", "R-TABIX-LIST")),
        ("dbsnp_vcf declares contig lengths that differ from the reference: /x: ['chr1']",
         ("vcf_contig_length_mismatch", "dbsnp_vcf", None, "R-VCF-LEN")),
        ("known_sites entry contigs absent from the reference: /x: ['chrUn']",
         ("vcf_contigs_absent", "known_sites", None, "R-VCF-ABSENT")),
        ("known_sites is empty; BQSR is a core step and requires known sites",
         ("known_sites_empty", "known_sites", None, "R-KS-EMPTY")),
    ],
)
def test_rule_table(run_dir, sentence, expected):
    write(run_dir, REPORT, f"{HEADER}\n  - {sentence}\n")
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert kinds(result) == [expected]


# --- sources (FR-3) -----------------------------------------------------------


def test_report_wins_over_log(run_dir):
    write(run_dir, REPORT, f"{HEADER}\n{BED_MISSING[0]}\n")
    write(run_dir, LOG, log_with(block(BED_MISSING + BCFTOOLS_ABSENT)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.source == "report"
    assert len(result.causes) == 1


def test_report_without_block_does_not_fall_back_to_the_log(run_dir):
    """The log may hold an older attempt's block; the report is the latest."""
    write(run_dir, REPORT, "Traceback (most recent call last):\n  boom\nKeyError: 'x'\n")
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "no_error_block"
    assert result.source == "report"
    assert result.causes == ()
    assert "KeyError" in result.excerpt


def test_empty_report_counts_as_present(run_dir):
    write(run_dir, REPORT, "")
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.source, result.causes) == ("no_error_block", "report", ())


def test_unreadable_report_falls_back_to_the_log(run_dir):
    (run_dir / REPORT).mkdir(parents=True)  # opening a directory is an OS error
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.source) == ("parsed", "pipeline_log")


def test_both_missing_is_source_unavailable(run_dir):
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.source, result.causes) == ("source_unavailable", None, ())
    assert result.excerpt is None


def test_both_unreadable_is_source_unreadable(run_dir):
    (run_dir / REPORT).mkdir(parents=True)
    (run_dir / LOG).mkdir(parents=True)
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.source, result.causes) == ("source_unreadable", None, ())


def test_os_error_while_reading_is_unreadable_not_partial(run_dir, monkeypatch):
    write(run_dir, REPORT, f"{HEADER}\n{BED_MISSING[0]}\n")
    write(run_dir, LOG, log_with(block(BED_MISSING)))

    def broken(path):
        raise PermissionError("denied")

    monkeypatch.setattr(rbc, "_read_tail", broken)
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.causes) == ("source_unreadable", ())


# --- block parsing details (FR-4, NFR-5) -------------------------------------


def test_header_without_items_is_no_error_block(run_dir):
    write(run_dir, REPORT, f"[NOTE] x\n{HEADER}\n[OK] nothing\n")
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.causes) == ("no_error_block", ())


def test_timestamped_error_line_is_not_the_header(run_dir):
    body = [f"[2026-09-04 19:47:10] {HEADER}", "  - target_bed missing or empty: /a/b/c.bed"]
    write(run_dir, LOG, log_with(body))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "no_error_block"


def test_undecodable_bytes_are_replaced_not_fatal(run_dir):
    raw = (HEADER + "\n  - target_bed missing or empty: /a/b/\xff\xfe.bed\n").encode(
        "latin-1"
    )
    write(run_dir, REPORT, raw)
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "parsed"
    assert "�" in result.causes[0].raw_text


def test_cut_last_line_still_counts(run_dir):
    write(run_dir, REPORT, f"{HEADER}\n{BED_MISSING[0]}\n  - coverage_bed missing or")
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert [c.rule_id for c in result.causes] == ["R-MISSING", None]


# --- log segment (FR-16, Q4) ---------------------------------------------------


def test_only_the_last_attempt_counts(run_dir):
    write(run_dir, LOG, log_with(block(BCFTOOLS_ABSENT), block(BED_MISSING)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert [c.resource_role for c in result.causes] == ["target_bed", "coverage_bed"]


def test_old_block_is_not_reused_when_the_last_attempt_has_none(run_dir):
    traceback = ["Traceback (most recent call last):", "ZeroDivisionError: boom"]
    write(run_dir, LOG, log_with(block(BED_MISSING), traceback))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.causes) == ("no_error_block", ())
    assert "ZeroDivisionError" in result.excerpt
    assert "target_bed" not in result.excerpt


def test_no_start_marker_is_unresolved(run_dir):
    text = "\n".join(["[2026-09-04 19:46:50] header", HEADER, *BED_MISSING]) + "\n"
    write(run_dir, LOG, text)
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "segment_unresolved"
    assert result.causes == ()
    assert result.excerpt is None
    assert result.truncated is False


def test_two_blocks_in_one_segment_is_unresolved(run_dir):
    write(run_dir, LOG, log_with(block(BED_MISSING) + block(BCFTOOLS_ABSENT)))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.causes) == ("segment_unresolved", ())


def test_two_blocks_in_one_report_is_unresolved(run_dir):
    write(run_dir, REPORT, "\n".join(block(BED_MISSING) + block(BCFTOOLS_ABSENT)) + "\n")
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.causes) == ("segment_unresolved", ())


# --- size limits (NFR-6, Q5) -------------------------------------------------

FILLER = "[2026-09-04 19:40:00] " + "x" * 200


def filler(n_bytes: int) -> list[str]:
    return [FILLER] * (n_bytes // (len(FILLER) + 1) + 1)


def test_large_log_with_start_outside_the_window_is_unresolved_and_truncated(run_dir):
    body = block(BED_MISSING) + filler(rbc.READ_LIMIT_BYTES + 10_000)
    write(run_dir, LOG, log_with(body))
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "segment_unresolved"
    assert result.truncated is True
    assert result.causes == ()


def test_large_log_with_segment_inside_the_window_is_complete(run_dir, monkeypatch):
    read_sizes: list[int] = []
    original = rbc._read_tail

    def spy(path):
        text, cut, nbytes = original(path)
        read_sizes.append(nbytes)
        return text, cut, nbytes

    monkeypatch.setattr(rbc, "_read_tail", spy)
    write(run_dir, LOG, log_with(block(BED_MISSING), preamble=tuple(filler(400_000))))
    assert (run_dir / LOG).stat().st_size > rbc.READ_LIMIT_BYTES
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "parsed"
    assert result.truncated is False
    assert len(result.causes) == 2
    assert read_sizes and max(read_sizes) <= rbc.READ_LIMIT_BYTES == 262_144


def test_large_report_without_header_in_window_is_unresolved(run_dir):
    text = "\n".join([HEADER, *BED_MISSING, *filler(rbc.READ_LIMIT_BYTES + 5_000)]) + "\n"
    write(run_dir, REPORT, text)
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert (result.state, result.truncated) == ("segment_unresolved", True)


def test_more_than_fifty_causes_is_truncated(run_dir):
    items = [f"  - mystery number {i}" for i in range(60)]
    write(run_dir, REPORT, "\n".join([HEADER, *items]) + "\n")
    result = rbc.analyze(run_dir, STEP, FAIL)
    assert result.state == "parsed"
    assert len(result.causes) == rbc.MAX_CAUSES == 50
    assert result.causes[0].raw_text == "mystery number 0"
    assert result.causes[-1].raw_text == "mystery number 49"
    assert result.truncated is True


# --- determinism, read-only, no raw text in server logs (NFR-1, FR-13, NFR-2) --


def test_same_input_same_output(run_dir):
    write(run_dir, LOG, log_with(block(BED_MISSING + BCFTOOLS_ABSENT)))
    assert rbc.analyze(run_dir, STEP, FAIL) == rbc.analyze(run_dir, STEP, FAIL)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sources_are_not_modified(run_dir):
    report = write(run_dir, REPORT, f"{HEADER}\n{BED_MISSING[0]}\n")
    log = write(run_dir, LOG, log_with(block(BED_MISSING)))
    before = (digest(report), digest(log), report.stat().st_mtime_ns, log.stat().st_mtime_ns)
    rbc.analyze(run_dir, STEP, FAIL)
    after = (digest(report), digest(log), report.stat().st_mtime_ns, log.stat().st_mtime_ns)
    assert before == after


def test_raw_sentences_never_reach_the_server_log(run_dir, caplog):
    caplog.set_level("DEBUG")
    write(run_dir, LOG, log_with(block(BED_MISSING)))
    (run_dir / REPORT).mkdir(parents=True)
    rbc.analyze(run_dir, STEP, FAIL)
    assert "/srv/wes" not in caplog.text
    assert "targets.bed" not in caplog.text


# --- heredoc contract: the real PYBUNDLE output (NFR-9, T-09) ---------------

HEREDOC_OPEN = "<<'PYBUNDLE'\n"
HEREDOC_CLOSE = "\nPYBUNDLE\n"


@pytest.fixture(scope="module")
def pybundle(tmp_path_factory) -> Path:
    text = config.PIPELINE_SH.read_text(encoding="utf-8")
    start = text.index(HEREDOC_OPEN) + len(HEREDOC_OPEN)
    end = text.index(HEREDOC_CLOSE, start)
    path = tmp_path_factory.mktemp("pybundle") / "resource_validation.py"
    path.write_text(text[start:end], encoding="utf-8")
    return path


def reference(tmp: Path) -> Path:
    """A one-contig reference whose .fai, .dict and BWA index all agree."""
    ref = tmp / "ref.fasta"
    ref.write_text(">chr1\nACGTACGTAC\n", encoding="utf-8")
    (tmp / "ref.fasta.fai").write_text("chr1\t10\t6\t10\t11\n", encoding="utf-8")
    (tmp / "ref.dict").write_text("@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:10\n", encoding="utf-8")
    for ext in ("amb", "ann", "bwt", "pac", "sa"):
        (tmp / f"ref.fasta.{ext}").write_bytes(b"index")
    return ref


def run_pybundle(pybundle: Path, tmp: Path, argv: list[str]) -> str:
    """Run the block with an empty PATH, so bcftools/tabix are never found."""
    empty = tmp / "empty_path"
    empty.mkdir(exist_ok=True)
    env = dict(os.environ, PATH=str(empty))
    proc = subprocess.run(
        [sys.executable, str(pybundle), *argv],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    return proc.stdout


def analyze_report(tmp: Path, text: str):
    run = tmp / "run"
    write(run, REPORT, text)
    return rbc.analyze(run, STEP, FAIL)


def test_heredoc_missing_beds_and_empty_known_sites(pybundle, tmp_path):
    ref = reference(tmp_path)
    out = run_pybundle(
        pybundle,
        tmp_path,
        [str(ref), str(tmp_path / "no.bed"), str(tmp_path / "no_cov.bed"), "chr", "", "", ""],
    )
    result = analyze_report(tmp_path, out)
    assert result.state == "parsed"
    assert [(c.rule_id, c.resource_role) for c in result.causes] == [
        ("R-MISSING", "target_bed"),
        ("R-MISSING", "coverage_bed"),
        ("R-KS-EMPTY", "known_sites"),
    ]


def test_heredoc_checksum_bed_content_and_bcftools_absent(pybundle, tmp_path):
    ref = reference(tmp_path)
    bed = tmp_path / "targets.bed"
    bed.write_text("chr1\t0\t5\n", encoding="utf-8")
    cov = tmp_path / "coverage.bed"
    cov.write_text("chrZ\t0\t5\n", encoding="utf-8")
    vcf = tmp_path / "mills.vcf.gz"
    vcf.write_bytes(b"not really a vcf")
    (tmp_path / "mills.vcf.gz.tbi").write_bytes(b"index")
    no_index = tmp_path / "known.vcf.gz"
    no_index.write_bytes(b"vcf")
    out = run_pybundle(
        pybundle,
        tmp_path,
        [str(ref), str(bed), str(cov), "chr", "", "a" * 64, "b" * 64, str(vcf), str(no_index)],
    )
    result = analyze_report(tmp_path, out)
    assert result.state == "parsed"
    rules = [(c.rule_id, c.resource_role, c.tool) for c in result.causes]
    assert ("R-SHA", "target_bed", None) in rules
    assert ("R-SHA", "coverage_bed", None) in rules
    assert ("R-BED-CONTENT", "coverage_bed", None) in rules
    assert ("R-VCF-TOOL-B", "unknown", "bcftools") in rules
    assert ("R-VCF-INDEX", "known_sites", None) in rules


def test_heredoc_reference_level_failures(pybundle, tmp_path):
    ref = reference(tmp_path)
    (tmp_path / "ref.dict").write_text("@SQ\tSN:chr1\tLN:11\n", encoding="utf-8")
    for ext in ("amb", "ann", "bwt", "pac", "sa"):
        (tmp_path / f"ref.fasta.{ext}").unlink()
    out = run_pybundle(pybundle, tmp_path, [str(ref), "", "", "GRCh38", "", "", ""])
    result = analyze_report(tmp_path, out)
    rules = {c.rule_id for c in result.causes}
    assert {"R-NOTSET", "R-BWA-NONE", "R-FAI-DICT", "R-STYLE", "R-KS-EMPTY"} <= rules


def test_heredoc_output_has_no_unclassified_sentence(pybundle, tmp_path):
    """Every sentence the real block prints in these scenarios has a rule."""
    ref = reference(tmp_path)
    out = run_pybundle(
        pybundle,
        tmp_path,
        [str(ref), str(tmp_path / "x.bed"), "", "nochr", "", "", ""],
    )
    result = analyze_report(tmp_path, out)
    assert result.causes
    assert all(c.rule_id is not None for c in result.causes), result.causes


# --- real runs from the evidence archive (FR-14) ----------------------------

ARCHIVE = config.ROOT / "wes_failure_evidence_20261112.tar.gz"
RUN_3A22C5 = "wes-20260904-194645-3a22c5"
RUN_B94559 = "wes-20260917-223800-b94559"
RUN_68AA20 = "wes-20260904-172826-68aa20"

real = pytest.mark.skipif(
    not ARCHIVE.is_file(),
    reason="real-run archive wes_failure_evidence_20261112.tar.gz is not present",
)


@pytest.fixture(scope="module")
def evidence(tmp_path_factory) -> Path:
    """The archive, extracted read-only into a temporary directory."""
    target = tmp_path_factory.mktemp("evidence")
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        tar.extractall(target, filter="data")
    return target


def real_checks(run_dir: Path) -> list[dict]:
    """The step document's own check rows, through the existing reader."""
    planned = [STEP]
    return step_reader.read(run_dir, planned, "full", STEP)["validation"]["results"]


@real
def test_real_3a22c5_two_bed_causes(evidence):
    run_dir = evidence / RUN_3A22C5
    checks = real_checks(run_dir)
    assert {"name": "resource_bundle", "status": "FAIL"}.items() <= next(
        c for c in checks if c["name"] == "resource_bundle"
    ).items()
    result = rbc.analyze(run_dir, STEP, checks)
    assert (result.state, result.source, result.truncated) == ("parsed", "pipeline_log", False)
    assert kinds(result) == [
        ("resource_missing_or_empty", "target_bed", None, "R-MISSING"),
        ("resource_missing_or_empty", "coverage_bed", None, "R-MISSING"),
    ]


@real
def test_real_b94559_four_causes(evidence):
    run_dir = evidence / RUN_B94559
    checks = real_checks(run_dir)
    statuses = {c["name"]: c["status"] for c in checks}
    assert statuses["required_tools"] == "FAIL"
    assert statuses["resource_bundle"] == "FAIL"
    result = rbc.analyze(run_dir, STEP, checks)
    assert result.state == "parsed"
    assert kinds(result) == [
        ("resource_missing_or_empty", "target_bed", None, "R-MISSING"),
        ("resource_missing_or_empty", "coverage_bed", None, "R-MISSING"),
        ("vcf_tool_unavailable", "unknown", "bcftools", "R-VCF-TOOL-B"),
        ("vcf_tool_unavailable", "unknown", "bcftools", "R-VCF-TOOL-B"),
    ]


@real
def test_real_68aa20_passed_is_not_applicable_without_reading(evidence, reads):
    run_dir = evidence / RUN_68AA20
    checks = real_checks(run_dir)
    result = rbc.analyze(run_dir, STEP, checks)
    assert (result.state, result.causes, result.source) == ("not_applicable", (), None)
    assert reads == []


@real
def test_real_sources_are_not_modified(evidence):
    files = sorted((evidence / RUN_B94559).rglob("*"))
    before = {p: digest(p) for p in files if p.is_file()}
    rbc.analyze(evidence / RUN_B94559, STEP, real_checks(evidence / RUN_B94559))
    assert before == {p: digest(p) for p in files if p.is_file()}
