"""What a pipeline string may look like by the time a model sees it.

Two kinds of identifier reach this layer, and they need different treatment:

  known literals   the sample id, run id and job id. The server knows them, so
                   they can be matched exactly and replaced with a placeholder
                   that still reads as a thing ("<sample>"), rather than being
                   deleted and leaving a sentence that no longer parses.

  shapes           paths and digests. main.sh composes these from values the
                   backend never sees -- a reference bundle under
                   /srv/wes/reference, a lane unit named after the submitter's
                   own file -- so there is no literal to match. They are
                   recognised by shape and replaced wholesale.

Both are needed. Removing only the known literals would leave
"/srv/wes/runs/.../06_variant_calling/PATIENT_A.raw.vcf.gz" intact whenever the
sample id column is null, which it is for every job row written before that
column existed.

Metrics are filtered rather than scrubbed
-----------------------------------------

A metric is a name and a value that a reader will quote as a measurement.
Rewriting one would be worse than dropping it: "<sample>_records = 41283922"
invites a model to explain a metric that does not exist. So a metric is kept
whole or not at all, under two rules:

  the key    must be the snake_case identifier main.sh's step_metric writes,
             and must not contain a known literal. That is what rejects
             `reads_before_DEMO_WES.L001`, whose key embeds the lane unit --
             which is derived from the submitted sample.

  the value  numbers and booleans always pass: a float cannot carry a name.
             A string passes only if its key is on the allowlist below, so a
             future `step_metric some_new_label "$SOMETHING" str` is withheld
             until someone decides it is safe, instead of being sent because
             nobody noticed it was added.

None of this is a substitute for the projection in ``step_evidence.py``. That
module decides which fields exist at all; this one decides what the surviving
strings may contain.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Long enough for the pipeline's longest real message (the Korean
# required_tools detail), short enough that one runaway string cannot become
# the bulk of a prompt.
MAX_TEXT = 1000

# Extensions main.sh actually produces or names, plus the plain-text ones its
# messages mention. Used only to recognise a *bare* filename; anything with a
# separator is caught by the path rules regardless of extension.
_DATA_EXTENSION = (
    "fastq|fq|bam|bai|cram|crai|sam|vcf|gvcf|bcf|tbi|idx|bed|dict|"
    "fa|fasta|fai|tsv|csv|txt|log|json|html|zip|md|pdf|png|gz|bgz"
)

# C:\..., \\server\share, and anything else carrying a drive letter.
_WINDOWS_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s\"']*")
# A rooted POSIX path. Two segments minimum, so a lone "/" in prose is not
# mistaken for one. The optional leading dots are what make the documented
# "../_jobs/<run>/run_config.json" form disappear whole instead of leaving a
# stranded ".." behind.
_POSIX_PATH = re.compile(r"(?:\.{1,2})?(?:/[\w.\-]+){2,}/?")
# A relative path: at least one separator AND a dotted filename at the end.
# Both conditions matter -- "PASS/FAIL" has no extension and survives, while
# the documented "../_jobs/<run>/run_config.json" form does not.
_RELATIVE_PATH = re.compile(
    r"(?:\.{1,2}[/\\])?[\w.\-]+(?:[/\\][\w.\-]+)*[/\\][\w.\-]+\.[A-Za-z0-9]{1,10}"
    r"(?:\.(?:gz|bgz|zip))?"
)
# A bare filename with a data extension. This is where the sample name lives
# once the directory part is gone: SRR2962669.subset_5M.raw.vcf.gz.
_DATA_FILENAME = re.compile(rf"[\w.\-]+\.(?:{_DATA_EXTENSION})(?:\.(?:gz|bgz))?\b")
# sha256 and friends. A checksum is never part of an explanation, and a full
# one is the kind of value that gets copied into a prompt and never used.
_DIGEST = re.compile(r"\b[0-9a-fA-F]{32,}\b")

_METRIC_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# String metrics that describe the RUN's configuration, not its subject. Each
# is either an enum-like label main.sh picks from a fixed set, or a reference /
# capture-kit identifier that belongs to the lab rather than to a person.
#
# Deliberately absent, and why:
#   sample                 the submitted sample name
#   *_sha256               a digest; see _DIGEST above
#   filter_expression      a bcftools expression; no explanatory value here
#   optional_failed_steps  a space-joined list, not a single label
_SAFE_STRING_METRICS = frozenset(
    {
        "annotation_input",
        "assembly",
        "bundle_id",
        "capture_kit_id",
        "capture_kit_mode",
        "contig_style",
        "fastq_gzip_verification",
        "filter_preset",
        "intervar_build",
        "markdup_validation",
        "markdup_validation_after_calmd",
        "nm_md_repaired",
        "read_name_mode",
        "target_bed_capture_kit_name",
        "target_bed_capture_kit_version",
        "target_bed_design_id",
        "target_bed_genome_build",
        "target_bed_manufacturer",
        "target_bed_source",
        "target_bed_status",
        "trim_mode",
    }
)

MetricValue = bool | int | float | str


@dataclass(frozen=True)
class Redactor:
    """The literals one run must not disclose, plus the shape rules.

    ``literals`` is (value, placeholder), and the caller supplies it longest
    value first so a shorter identifier that happens to be a prefix of a longer
    one cannot replace half of it. An empty tuple is a valid redactor: the
    shape rules still apply, and a job row with no sample_id is exactly that
    case.
    """

    literals: tuple[tuple[str, str], ...] = ()

    def text(self, value: Any) -> str:
        """One pipeline string, with paths, digests and known ids removed."""
        out = "" if value is None else str(value)
        out = _WINDOWS_PATH.sub("<path>", out)
        out = _POSIX_PATH.sub("<path>", out)
        out = _RELATIVE_PATH.sub("<path>", out)
        out = _DATA_FILENAME.sub("<file>", out)
        out = _DIGEST.sub("<digest>", out)
        for literal, placeholder in self.literals:
            out = re.sub(re.escape(literal), placeholder, out, flags=re.IGNORECASE)
        if len(out) > MAX_TEXT:
            out = out[:MAX_TEXT] + " ...(truncated)"
        return out

    def contains_literal(self, value: str) -> bool:
        """True when a known identifier is embedded in this string."""
        lowered = value.lower()
        return any(literal.lower() in lowered for literal, _ in self.literals)

    def metrics(self, raw: Mapping[str, Any]) -> tuple[dict[str, MetricValue], int]:
        """(kept metrics, number withheld).

        The count is reported rather than the withheld keys: some are withheld
        *because* the key itself carries the sample name, and naming them would
        undo the filtering.
        """
        kept: dict[str, MetricValue] = {}
        withheld = 0

        for key, value in raw.items():
            if not isinstance(key, str) or not _METRIC_KEY.fullmatch(key):
                withheld += 1
                continue
            if self.contains_literal(key):
                withheld += 1
                continue

            # bool before int: bool is an int subclass, and `mapped_pct: True`
            # must not be reported as the number 1.
            if isinstance(value, bool):
                kept[key] = value
            elif isinstance(value, int):
                kept[key] = value
            elif isinstance(value, float):
                # A non-finite float is not JSON, and main.sh never means one.
                if math.isfinite(value):
                    kept[key] = value
                else:
                    withheld += 1
            elif isinstance(value, str) and key in _SAFE_STRING_METRICS:
                # The allowlist says the key is safe to send; this says the
                # value is what that key is supposed to hold, and not a path
                # that ended up in the wrong metric.
                if len(value) <= 64 and self.text(value) == value:
                    kept[key] = value
                else:
                    withheld += 1
            else:
                withheld += 1

        return kept, withheld


__all__ = ["MAX_TEXT", "MetricValue", "Redactor"]
