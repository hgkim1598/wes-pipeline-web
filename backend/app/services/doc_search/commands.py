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
)


def for_rule(rule_id: str | None) -> Command | None:
    return RULE_COMMANDS.get(rule_id or "")


def for_check(name: str) -> tuple[str, Command] | None:
    """(family, command) for a step check name, or None when no command ran."""
    for pattern, family, command in _CHECK_FAMILIES:
        if pattern.match(name):
            return family, command
    return None


__all__ = ["Command", "RULE_COMMANDS", "for_check", "for_rule"]
