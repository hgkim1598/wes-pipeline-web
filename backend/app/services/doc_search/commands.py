"""Which tool command produced a recorded failure -- read from the pipeline code.

A run records sentences and check names, not the command line. But each
resource-check rule and each step check below is produced by exactly one fixed
command in script/main.sh, so the command is a fact about the check, not a
guess about the failure. Rules and checks that run no command (a file-existence
test, a `command -v` presence test) are absent on purpose: inventing a command
for them would put words in the run's mouth.

`recordedBy` names the place in main.sh (function / block, never a line number:
lines move and the citation would quietly go wrong).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    tool: str
    subcommand: str | None
    # Short and long spellings of the option as the manual lists them.
    options: tuple[str, ...]
    recordedBy: str

    def display(self) -> str:
        parts = [self.tool]
        if self.subcommand:
            parts.append(self.subcommand)
        if self.options:
            parts.append(self.options[0])
        return " ".join(parts)


_BUNDLE = "script/main.sh validate_reference_bundle (embedded Python check)"
_CALL = "script/main.sh variant-calling step checks"

_VIEW_HEADER_BUNDLE = Command("bcftools", "view", ("-h", "--header-only"), _BUNDLE)
_TABIX_LIST_BUNDLE = Command("tabix", None, ("-l", "--list-chroms"), _BUNDLE)

# resource_bundle_causes rule id -> the command whose outcome the sentence reports.
RULE_COMMANDS: dict[str, Command] = {
    # `bcftools view -h <vcf>`: non-zero exit -> "cannot parse VCF header",
    # OSError -> "bcftools unavailable for", header lengths -> R-VCF-LEN.
    "R-VCF-HEADER": _VIEW_HEADER_BUNDLE,
    "R-VCF-TOOL-B": _VIEW_HEADER_BUNDLE,
    "R-VCF-LEN": _VIEW_HEADER_BUNDLE,
    # `tabix -l <vcf>`.
    "R-TABIX-LIST": _TABIX_LIST_BUNDLE,
    "R-VCF-TOOL-T": _TABIX_LIST_BUNDLE,
    "R-VCF-ABSENT": _TABIX_LIST_BUNDLE,
}

# Analysis steps 01-06 (development log 65). main.sh records a failed tool
# command as `require_cmd_ok <label> <argv...>` -> a FAIL check named <label>,
# and a few `fail_step <code>` checks report the outcome of the one command
# right before them. Both are facts of the code, like the VCF families below.
#
# Deliberately NOT here (a command would be invented):
#   fastp_missing (presence test), fastp_empty_output / norm_empty /
#   filter_empty (output-size tests), recal_table (grep), coverage_metrics
#   (embedded Python), alignment_<lane> (a bwa | samtools sort pipe -- which one
#   failed is in the message, not the check), bam_validation (several commands
#   share the name), unexpected_error (the ERR trap's shell text).
#
# Exact names come before the lane-labelled `index_<lane>` / `fastqc_<lane>` /
# `fastp_<lane>` patterns; a lane unit can carry the sample name, so for those
# only the family is kept.
_RAWQC = "script/main.sh 01_raw_qc (require_cmd_ok fastqc_<lane>)"
_TRIM = "script/main.sh 02_preprocessing (require_cmd_ok fastp_<lane>)"
_ALIGN = "script/main.sh 03_alignment"
_PROC = "script/main.sh 04_processing"
_COV = "script/main.sh 05_coverage_qc (require_cmd_ok mosdepth)"
_VAR = "script/main.sh 06_variant_calling"
_FILT = "script/main.sh optional filtering / normalisation / annotation"

_SAMTOOLS_INDEX = ("samtools", "index", ())
_QUICKCHECK = ("samtools", "quickcheck", ())


def _exact(name: str, tool: str, sub: str | None, options: tuple[str, ...], where: str):
    return (re.compile(rf"^{re.escape(name)}$"), name, Command(tool, sub, options, where))


_ANALYSIS_FAMILIES: tuple[tuple[re.Pattern[str], str, Command], ...] = (
    # 02 -- presence/size tests first so the lane pattern below cannot take them.
    (re.compile(r"^fastp_(missing|empty_output)$"), "", Command("", None, (), "")),
    # 03
    _exact("merge", "samtools", "merge", (), _ALIGN),
    _exact("index_sample", *_SAMTOOLS_INDEX, _ALIGN),
    _exact("merge_quickcheck", *_QUICKCHECK, _ALIGN),
    _exact("invalid_lane_bam", *_QUICKCHECK, _ALIGN),
    # 04
    _exact("markduplicates", "gatk", "MarkDuplicates", (), _PROC),
    _exact("index_markdup", *_SAMTOOLS_INDEX, _PROC),
    _exact("markdup_quickcheck", *_QUICKCHECK, _PROC),
    _exact("calmd_failed", "samtools", "calmd", (), _PROC),
    _exact("calmd_quickcheck", *_QUICKCHECK, _PROC),
    _exact("base_recalibrator", "gatk", "BaseRecalibrator", (), _PROC),
    _exact("apply_bqsr", "gatk", "ApplyBQSR", (), _PROC),
    _exact("apply_bqsr_quickcheck", *_QUICKCHECK, _PROC),
    _exact("index_analysis_ready", *_SAMTOOLS_INDEX, _PROC),
    # 05
    _exact("mosdepth", "mosdepth", None, (), _COV),
    # 06
    _exact("haplotypecaller", "gatk", "HaplotypeCaller", (), _VAR),
    _exact("index_gvcf", "tabix", None, ("-p", "--preset"), _VAR),
    _exact("gvcf_parse", "bcftools", "view", ("-h", "--header-only"), _VAR),
    _exact("genotype_gvcfs", "gatk", "GenotypeGVCFs", (), _VAR),
    _exact("index_raw_vcf", "tabix", None, ("-p", "--preset"), _VAR),
    _exact("raw_vcf_parse", "bcftools", "view", ("-h", "--header-only"), _VAR),
    # optional filtering / normalisation / annotation
    _exact("bcftools_filter", "bcftools", "view", ("-i", "--include"), _FILT),
    _exact("index_filtered", "bcftools", "index", ("-f", "--force"), _FILT),
    _exact("bcftools_norm", "bcftools", "norm", ("-m", "--multiallelics"), _FILT),
    _exact("index_normalized", "bcftools", "index", ("-f", "--force"), _FILT),
    _exact("bcftools_annotate", "bcftools", "annotate", ("-a", "--annotations"), _FILT),
    # lane-labelled (family only)
    (re.compile(r"^index_"), "index_lane", Command(*_SAMTOOLS_INDEX, _ALIGN)),
    (re.compile(r"^fastqc_"), "fastqc", Command("fastqc", None, (), _RAWQC)),
    (re.compile(r"^fastp_"), "fastp", Command("fastp", None, (), _TRIM)),
)

# Step-check FAMILY -> command. A labelled check name (`vcf_parse_<file>`)
# carries a file name, so only the family is ever kept or shown.
_CHECK_FAMILIES: tuple[tuple[re.Pattern[str], str, Command], ...] = (
    (re.compile(r"^vcf_parse_"), "vcf_parse",
     Command("bcftools", "view", ("-h", "--header-only"), _CALL)),
    (re.compile(r"^vcf_index_"), "vcf_index",
     Command("tabix", None, ("-l", "--list-chroms"), _CALL)),
    (re.compile(r"^vcf_sample$"), "vcf_sample",
     Command("bcftools", "query", ("-l", "--list-samples"), _CALL)),
    (re.compile(r"^raw_vcf_records$"), "raw_vcf_records",
     Command("bcftools", "view", ("-H", "--no-header"), _CALL)),
    (re.compile(r"^raw_vcf_ref_match$"), "raw_vcf_ref_match",
     Command("bcftools", "norm", ("-c", "--check-ref"), _CALL)),
    (re.compile(r"^BCFTOOLS_STATS_FAILED$"), "BCFTOOLS_STATS_FAILED",
     Command("bcftools", "stats", (), _CALL)),
    *_ANALYSIS_FAMILIES,
)


def for_rule(rule_id: str | None) -> Command | None:
    return RULE_COMMANDS.get(rule_id or "")


def for_check(name: str) -> tuple[str, Command] | None:
    """(family, command) for a step check name, or None when no command ran."""
    for pattern, family, command in _CHECK_FAMILIES:
        if pattern.match(name):
            # An empty family marks a name that must NOT fall through to a
            # broader pattern (a presence / size test that ran no command).
            return (family, command) if family else None
    return None


__all__ = ["Command", "RULE_COMMANDS", "for_check", "for_rule"]
