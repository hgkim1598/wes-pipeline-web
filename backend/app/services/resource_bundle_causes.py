"""Why resource_bundle failed: the INTERNAL analysis (P0-1, ADR-001 D1).

When 00_input_validation's resource_bundle check fails, the step document says
only "validation failed; see 00_input_validation/resource_validation.txt". The
actual sentences are in that report and, copied by `cat "$report"`, in
logs/pipeline.log (script/main.sh validate_reference_bundle). This module reads
them back and classifies each one with a fixed rule table. No model, no guess.

What this module is NOT
-----------------------

It is not an API shape and it does not redact. Its result keeps the raw
sentences, which contain server paths and sometimes the sample name, so it is a
frozen dataclass rather than a Pydantic model: nothing here can be handed to a
response by accident. The one way out is services/resource_bundle_diagnosis.py.
For the same reason this module never logs a sentence it read.

It does not decide how causes relate (which one is the root cause). It does
not read anything but the two fixed files below, and it never follows a path
written inside a sentence.

Sources, in order (spec FR-3)
-----------------------------

  1. <run_dir>/00_input_validation/resource_validation.txt
     main.sh writes it with `>`, so it always holds the latest attempt.
  2. <run_dir>/logs/pipeline.log, only when (1) is missing or unreadable.
     main.sh appends to it (`tee -a`), so it can hold older attempts too; only
     the part after the last `START 00_input_validation` line is used (FR-16).

A report that was read but holds no block does NOT fall back to the log: the
log's block could belong to an earlier attempt.

Size (spec NFR-6, initial policy): each file is read from its END, at most
READ_LIMIT_BYTES. At most MAX_CAUSES sentences are kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

STEP_ID = "00_input_validation"
CHECK_NAME = "resource_bundle"

REPORT_PATH = Path("00_input_validation") / "resource_validation.txt"
LOG_PATH = Path("logs") / "pipeline.log"

READ_LIMIT_BYTES = 256 * 1024
MAX_CAUSES = 50
# The excerpt is cut again after redaction; this only bounds what is carried.
EXCERPT_CHARS = 1000

# Printed by PYBUNDLE at column 0. A timestamped "[...] [ERROR] ..." line is
# die()'s, not this block's.
HEADER = "[ERROR] Resource bundle validation failed:"
ITEM_PREFIX = "  - "
# log() writes "[<timestamp>] START <step>".
_START_RE = re.compile(r"^\[[^\]]+\] START " + re.escape(STEP_ID) + r"\s*$")

State = Literal[
    "not_applicable",
    "source_unavailable",
    "source_unreadable",
    "segment_unresolved",
    "no_error_block",
    "parsed",
]
Source = Literal["report", "pipeline_log"]


@dataclass(frozen=True)
class RawCause:
    """One sentence and its classification. `raw_text` is NOT redacted."""

    kind: str
    resource_role: str
    tool: str | None
    rule_id: str | None
    raw_text: str


@dataclass(frozen=True)
class ResourceBundleAnalysis:
    state: State
    source: Source | None
    causes: tuple[RawCause, ...]
    # Raw tail of the segment, only for no_error_block. NOT redacted.
    excerpt: str | None
    truncated: bool


# --- rule table (spec §7.3) ---------------------------------------------------
#
# Every template is copied from PYBUNDLE in script/main.sh. A heredoc contract
# test runs that block and fails if a sentence it prints stops matching here.
# Order matters: the first rule that matches wins.

_LABEL_ROLES = {
    "reference_fasta": "reference_fasta",
    "reference FASTA index (.fai)": "reference_fai",
    "reference sequence dictionary (.dict)": "reference_dict",
    "target_bed": "target_bed",
    "target BED": "target_bed",
    "coverage_bed": "coverage_bed",
    "coverage BED": "coverage_bed",
    "known_sites entry": "known_sites",
    "dbsnp_vcf": "dbsnp_vcf",
}

UNKNOWN = "unknown"


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    pattern: re.Pattern[str]
    kind: str
    # A fixed role, or None to take it from the sentence's `label` group.
    role: str | None = None
    tool: str | None = None


def _rule(rule_id, pattern, kind, role=None, tool=None) -> _Rule:
    return _Rule(rule_id, re.compile(pattern), kind, role, tool)


_RULES: tuple[_Rule, ...] = (
    _rule("R-BWA-INCOMPLETE", r"^BWA index at '.*' is incomplete:", "bwa_index_incomplete",
          role="bwa_index"),
    _rule("R-BWA-NONE", r"^BWA index not found:", "bwa_index_not_found", role="bwa_index"),
    _rule("R-FAI-DICT", r"^reference \.fai and \.dict disagree on contig order or lengths$",
          "reference_index_mismatch", role="reference_fasta"),
    _rule("R-STYLE",
          r"^contig_style='.*' declares (?:no 'chr' prefix but the reference uses 'chr'"
          r"|a 'chr' prefix but the reference does not use it)$",
          "contig_style_mismatch", role="reference_fasta"),
    _rule("R-STYLE", r"^contig_style='.*' is not a recognised chromosome naming convention;",
          "contig_style_unrecognised", role="reference_fasta"),
    _rule("R-KS-EMPTY", r"^known_sites is empty; BQSR is a core step and requires known sites$",
          "known_sites_empty", role="known_sites"),
    _rule("R-VCF-HEADER", r"^cannot parse VCF header: ", "vcf_header_unparseable",
          role=UNKNOWN, tool="bcftools"),
    # Q2: these two carry no label, so the role is never inferred from the
    # file name in the sentence.
    _rule("R-VCF-TOOL-B", r"^bcftools unavailable for ", "vcf_tool_unavailable",
          role=UNKNOWN, tool="bcftools"),
    _rule("R-VCF-TOOL-T", r"^tabix unavailable for ", "vcf_tool_unavailable",
          role=UNKNOWN, tool="tabix"),
    _rule("R-TABIX-LIST", r"^cannot read tabix contig list: ", "vcf_contig_list_unreadable",
          role=UNKNOWN, tool="tabix"),
    _rule("R-NOTSET", r"^(?P<label>.+?) is not set in the resource bundle$",
          "resource_not_declared"),
    _rule("R-SHA", r"^(?P<label>.+?) SHA-256 mismatch: ", "checksum_mismatch"),
    _rule("R-BED-CONTENT",
          r"^(?P<label>.+?) (?:line \d+: (?:fewer than 3 columns$|start/end are not integers$"
          r"|contig absent from reference: |interval out of range )"
          r"|contains no usable intervals$)",
          "bed_content_invalid"),
    _rule("R-VCF-INDEX", r"^(?P<label>.+?) index missing \(\.tbi or \.csi\): ",
          "vcf_index_missing"),
    _rule("R-VCF-LEN", r"^(?P<label>.+?) declares contig lengths that differ from the reference: ",
          "vcf_contig_length_mismatch"),
    _rule("R-VCF-ABSENT", r"^(?P<label>.+?) contigs absent from the reference: ",
          "vcf_contigs_absent"),
    _rule("R-MISSING", r"^(?P<label>.+?) missing or empty: ", "resource_missing_or_empty"),
)


def classify(sentence: str) -> RawCause:
    """One sentence -> its rule, or `unknown` (spec FR-5, FR-6)."""
    for rule in _RULES:
        match = rule.pattern.match(sentence)
        if match is None:
            continue
        role = rule.role
        if role is None:
            role = _LABEL_ROLES.get(match.group("label"), UNKNOWN)
        return RawCause(rule.kind, role, rule.tool, rule.rule_id, sentence)
    return RawCause(UNKNOWN, UNKNOWN, None, None, sentence)


# --- reading ------------------------------------------------------------------


def _read_tail(path: Path) -> tuple[str, bool, int]:
    """(text, cut, bytes read) of at most READ_LIMIT_BYTES from the file's end.

    `cut` is True when the beginning of the file was skipped; the first line
    then started mid-way and is dropped. Undecodable bytes are replaced, the
    way run_status_reader.read_log_tail does, so damage alone is never an OS
    error. FileNotFoundError and other OSErrors propagate to the caller.
    """
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        cut = size > READ_LIMIT_BYTES
        handle.seek(size - READ_LIMIT_BYTES if cut else 0)
        data = handle.read(READ_LIMIT_BYTES)
    text = data.decode("utf-8", errors="replace")
    if cut:
        newline = text.find("\n")
        text = text[newline + 1 :] if newline >= 0 else ""
    return text, cut, len(data)


class _Missing:
    pass


class _Unreadable:
    pass


def _try_read(path: Path) -> tuple[str, bool] | _Missing | _Unreadable:
    try:
        text, cut, _ = _read_tail(path)
    except FileNotFoundError:
        return _Missing()
    except OSError:
        return _Unreadable()
    return text, cut


# --- block and segment --------------------------------------------------------


def _headers(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line.rstrip() == HEADER]


def _items_after(lines: list[str], header: int) -> list[str]:
    items: list[str] = []
    for line in lines[header + 1 :]:
        if not line.startswith(ITEM_PREFIX):
            break
        items.append(line[len(ITEM_PREFIX) :].rstrip("\r"))
    return items


def _excerpt(lines: list[str]) -> str | None:
    text = "\n".join(lines).strip()
    return text[-EXCERPT_CHARS:] if text else None


def _from_segment(lines: list[str], source: Source) -> ResourceBundleAnalysis:
    """Interpret a segment already known to belong to the latest attempt."""
    headers = _headers(lines)
    if len(headers) > 1:
        return ResourceBundleAnalysis("segment_unresolved", source, (), None, False)
    items = _items_after(lines, headers[0]) if headers else []
    if not items:
        return ResourceBundleAnalysis("no_error_block", source, (), _excerpt(lines), False)
    truncated = len(items) > MAX_CAUSES
    causes = tuple(classify(item) for item in items[:MAX_CAUSES])
    return ResourceBundleAnalysis("parsed", source, causes, None, truncated)


def _from_report(text: str, cut: bool) -> ResourceBundleAnalysis:
    lines = text.splitlines()
    if cut and not _headers(lines):
        # The header may sit in the part that was not read.
        return ResourceBundleAnalysis("segment_unresolved", "report", (), None, True)
    return _from_segment(lines, "report")


def _from_log(text: str, cut: bool) -> ResourceBundleAnalysis:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _START_RE.match(line)]
    if not starts:
        # Without the start of the latest attempt, a block here could be an
        # older attempt's. Not confirmed as the current cause (FR-16).
        return ResourceBundleAnalysis("segment_unresolved", "pipeline_log", (), None, cut)
    return _from_segment(lines[starts[-1] + 1 :], "pipeline_log")


def _is_failed(checks: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(row, dict)
        and row.get("name") == CHECK_NAME
        and row.get("status") == "FAIL"
        for row in checks
    )


def analyze(
    run_dir: Path, step_id: str, checks: list[dict[str, Any]]
) -> ResourceBundleAnalysis | None:
    """Analyse one step. None for any step other than 00_input_validation.

    `checks` is the step's validation.results as step_reader.read() already
    returned it, so the step document is not read twice and nothing is opened
    unless resource_bundle actually failed (FR-1, FR-2).
    """
    if step_id != STEP_ID:
        return None
    if not _is_failed(checks):
        return ResourceBundleAnalysis("not_applicable", None, (), None, False)

    root = Path(run_dir)
    report = _try_read(root / REPORT_PATH)
    if isinstance(report, tuple):
        return _from_report(*report)

    log = _try_read(root / LOG_PATH)
    if isinstance(log, tuple):
        return _from_log(*log)

    if isinstance(report, _Missing) and isinstance(log, _Missing):
        return ResourceBundleAnalysis("source_unavailable", None, (), None, False)
    return ResourceBundleAnalysis("source_unreadable", None, (), None, False)


__all__ = [
    "CHECK_NAME",
    "MAX_CAUSES",
    "READ_LIMIT_BYTES",
    "RawCause",
    "ResourceBundleAnalysis",
    "STEP_ID",
    "analyze",
    "classify",
]
