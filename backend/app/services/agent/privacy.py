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
# How much of one string the patterns are run over. Some of them take time
# that grows with the square of a long unbroken token (a long plain word, or
# "a\a\a\..."), so an unbounded string must not reach them. Output is cut at
# MAX_TEXT anyway. The cut is made at whitespace and never inside a known
# literal (see Redactor._scan_cut), so no identifier is left half-matched.
MAX_SCAN = 4 * MAX_TEXT

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
#
# A segment name may hold any character but whitespace, a separator, quotes,
# "<>|", the backtick and ":". It used to be [\w.-] only, and a punctuation
# character then ended the match and left the first folder name in front of
# the placeholder ("/lab+private/run/x.bed" -> "/lab+private<path>").
# ":" still ends a path, as before, so "/a/b.bam:12" and "/a/b:ENOENT" keep
# what the tool said after the colon (a colon inside a folder name is the
# known cost). Trailing sentence punctuation is handed back to the text by
# _posix_path_sub so "(see /a/b)" still reads; a ")" in the middle of a token
# is part of the name ("(see /a/b)retry" loses ")retry").
# A name glued to the first separator is taken too, so a relative path of three
# or more parts ("lab+private/run/x.bed", "qc/sub/x.bed") is not cut in front
# of its first "/" and its first folder left behind.
# A match may only start where a name starts (the lookbehind). That changes
# no result -- a match found later in the same name is also found from its
# start -- but stops every position of one long word from being retried, which
# made a long "ab+ab+..." string quadratic.
# Known limit: a space inside a folder name still ends the path.
_POSIX_PATH = re.compile(r"(?<![\w.\-+@%~])(?:[\w.\-+@%~]+)?(?:/[^\s/\\\"'<>|`:]+){2,}/?")
_TRAILER_CHARS = frozenset("),.;!?]}*")
# A relative path: at least one separator AND a dotted filename at the end.
# Both conditions matter -- "PASS/FAIL" has no extension and survives, while
# the documented "../_jobs/<run>/run_config.json" form does not. Segment names
# also admit "+@%~" (a folder like "lab+private"), but not "=" or ",", so
# prose such as "reads/sec=1.5" is not taken for a path.
_RELATIVE_PATH = re.compile(
    r"(?<![\w.\-+@%~])(?:\.{1,2}[/\\])?[\w.\-+@%~]+(?:[/\\][\w.\-+@%~]+)*[/\\][\w.\-+@%~]+\.[A-Za-z0-9]{1,10}"
    r"(?:\.(?:gz|bgz|zip))?"
)


def _trailer_start(raw: str) -> int:
    # One backward pass, not a regex search: searching "[...]*$" retried from
    # every position of a long ")))...X" run (Codex review r4).
    end = len(raw)
    while end > 0 and raw[end - 1] in _TRAILER_CHARS:
        end -= 1
    return end


def _posix_path_sub(match: re.Match[str]) -> str:
    raw = match.group(0)
    return "<path>" + raw[_trailer_start(raw) :]


def _url_sub(match: re.Match[str]) -> str:
    raw = match.group(0)
    return "<url>" + raw[_trailer_start(raw) :]


def _continuation_sub(match: re.Match[str]) -> str:
    raw = match.group(0)
    return "<path>" + raw[_trailer_start(raw) :]


# A URL names a host and a path on it; neither explains a pipeline failure.
# Taken before the path rules, which would otherwise read "s://" as a drive.
_URL = re.compile(r"(?<![\w+.\-])[A-Za-z][A-Za-z0-9+.\-]*://[^\s\"'<>`]+")
# "%2F" and "%5C" are a separator written another way. They are turned back
# into one, once, so the path rules see the path ("a%2Fb%2Fx.bed"). A second
# encoding ("%252F") leaves "%2F" behind, which release() refuses.
_ENCODED_SEP = re.compile(r"%(2[fF]|5[cC])")
# A rooted name of one segment ("/SYNTH"), which the POSIX rule leaves alone
# because it needs two. Not after a name character, so "mg/dL", "3/4", "+/-"
# and "PASS/WARN" are untouched; after ">" it is, so "<path>/x" is taken too.
_ROOTED_NAME = re.compile(r"(?<![\w.\-+@%~/])/[\w.\-+@%~]+")
# The rest of a path whose folder name held a space: "/data/my lab/x" leaves
# "<path> lab/x". A following word that itself holds a separator (and some
# other character) is taken as part of the same path. Prose that happens to
# follow a path and contain a "/" ("and/or") is lost with it; that is the cost.
_CONTINUATION = re.compile(
    r"<path>(?: (?=[^\s]*[^\s/\\])[^\s/\\\"'<>|`:]*(?:[/\\][^\s/\\\"'<>|`:]*)+)+"
)
_ADJACENT_PATHS = re.compile(r"(?:<path>){2,}")

# What must not be left in a string an external model receives. Broader than
# the patterns above on purpose -- it describes what a path LOOKS like after
# masking, not how to find one:
#   a backslash; an encoded separator; a long hex run;
#   a "/" that starts a word and is followed by a name ("/x", "(/x");
#   a "/" against a placeholder ("lab\u0301/<file>", "<path>/");
#   two separators in one word ("a/b/c" that no rule took);
#   a name glued in front of a placeholder ("x%<file>", "SYNTH)<path>").
# Every alternative matches inside one whitespace-separated word.
_RESIDUAL = re.compile(
    r"\\"
    r"|%(?:25)*(?:2[fF]|5[cC])"
    r"|[0-9a-fA-F]{32,}"
    r"|(?<![^\s\"'(\[{=,;<>*`])/(?=[^\s/)\]},;:!?*'\"<>])"
    r"|/(?=<(?:path|file|url)>)|(?<=>)/"
    r"|/[^\s/]*/"
    r"|[^\s\"'(\[{=,;:<>*`]<(?:path|file|url)>"
    r"|[\u2215\u2044\uff0f\u29f8\u2571\u29f5\u29f9\uff3c\ufe68\u2572]"
)
_WORD = re.compile(r"\S+")
_LEADING_CHARS = frozenset("([{\"'*`")

# (The last _RESIDUAL alternative: a separator drawn differently -- division,
# fraction, fullwidth, small and big forms of "/" and "\". They are refused
# rather than turned into ASCII: "a\uff0fb" as "a/b" would look like "mg/dL"
# and pass (Codex review r5).)
#
# A known identifier is swapped for a mark "<tag><n>QZ" BEFORE any shape rule,
# and back to its placeholder at the end. Word characters only, so a path that
# contained the name is still taken whole as before -- but nothing a rule does
# (decoding "%2F", cutting a filename, the MAX_SCAN cut) can split the name or
# change it so the final literal match misses it (Codex review r5). The tag is
# chosen per call so that neither the input nor any literal contains it: a
# producer writing a mark-shaped string cannot have it turned into a
# placeholder, and a literal cannot rewrite a mark (Codex review r6).
def _mark_tag(raw: str, literals: list[tuple[str, str]]) -> str:
    haystack = [raw.lower()] + [literal.lower() for literal, _ in literals]
    k = 0
    while True:
        tag = "QZ" + "X" * k + "LIT"
        if not any(tag.lower() in text for text in haystack):
            return tag
        k += 1


def _shapes(out: str) -> str:
    """The shape rules, in order. Known literals are not handled here."""
    if "%" in out:
        out = _ENCODED_SEP.sub(lambda m: "/" if m.group(1) in ("2f", "2F") else "\\", out)
    out = _URL.sub(_url_sub, out)
    out = _WINDOWS_PATH.sub("<path>", out)
    out = _POSIX_PATH.sub(_posix_path_sub, out)
    out = _RELATIVE_PATH.sub("<path>", out)
    out = _ROOTED_NAME.sub("<path>", out)
    out = _CONTINUATION.sub(_continuation_sub, out)
    out = _ADJACENT_PATHS.sub("<path>", out)
    out = _DATA_FILENAME.sub("<file>", out)
    return _DIGEST.sub("<digest>", out)


def _error_suffix_start(core: str) -> int:
    """Start of a trailing ":ENOENT" / ":12:34" run, or len(core) if none.

    A backward scan, not a "(...)+$" search, which retried from every colon of
    a long ":1:1:1...X" run (Codex review r5).
    """
    keep = len(core)
    pos = len(core)
    while True:
        colon = core.rfind(":", 0, pos)
        if colon < 0:
            return keep
        part = core[colon + 1 : pos]
        if not (part.isdigit() or (part[:1].isupper() and all(c.isupper() or c.isdigit() or c == "_" for c in part))):
            return keep
        if not part.isascii():
            return keep
        keep = pos = colon

# What a string becomes when it cannot be shown to be safe. A fixed token, so
# the model can say that something was withheld instead of guessing at it.
WITHHELD = "<withheld>"


def _mask_word(match: re.Match[str]) -> str:
    """One word that failed the residual check, replaced by <path>.

    Opening and closing punctuation and an error suffix are kept, so
    "(lab/x.bed:ENOENT)" reads "(<path>:ENOENT)" rather than losing the error.
    """
    word = match.group(0)
    if not _RESIDUAL.search(word):
        return word
    start = 0
    while start < len(word) and word[start] in _LEADING_CHARS:
        start += 1
    end = max(start, _trailer_start(word))
    core = word[start:end]
    keep = core[_error_suffix_start(core) :]
    return word[:start] + "<path>" + keep + word[end:]
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
        return self._render(value)[0]

    def _render(self, value: Any) -> tuple[str, str]:
        """(literals-first result, literals-last result) for one string.

        Literals first: each known identifier becomes a mark before any shape
        rule, so no rule can split or alter it (Codex review r5). Literals
        last, the order used before: the shape rules see the identifier's own
        characters, so a "/" or a hex run inside it still lets the enclosing
        path or digest be recognised (Codex review r6). `release` sends a
        string only when the two agree.
        """
        raw = "" if value is None else str(value)
        literals = [(literal, placeholder) for literal, placeholder in self.literals if literal]
        tag = _mark_tag(raw, literals)
        marks = re.compile(re.escape(tag) + r"(\d+)QZ")
        marked = raw
        for index, (literal, _) in enumerate(literals):
            marked = re.sub(re.escape(literal), f"{tag}{index}QZ", marked, flags=re.IGNORECASE)
        capped = len(marked) > MAX_SCAN
        if capped:
            marked = marked[: self._scan_cut(marked, marks, len(tag) + 12)]

        first = _shapes(marked)
        first = marks.sub(lambda m: literals[int(m.group(1))][1], first)
        last = _shapes(marks.sub(lambda m: literals[int(m.group(1))][0], marked))
        results = []
        for out in (first, last):
            # Again on the result: a literal can also be FORMED by a rule
            # (decoding "a%2Fb" when the literal is "a/b").
            for literal, placeholder in literals:
                out = re.sub(re.escape(literal), placeholder, out, flags=re.IGNORECASE)
            if capped or len(out) > MAX_TEXT:
                out = out[:MAX_TEXT] + " ...(truncated)"
            results.append(out)
        return results[0], results[1]

    def release(self, value: Any) -> str:
        """`text`, checked before it may go to an external model (fail-closed).

        The patterns in `text` are not assumed complete. If the two literal
        orders disagree, an identifier interacted with a shape and neither
        result is trusted. After that, any word that still looks like part of
        a path is replaced whole; if the string still fails the check, or
        still holds a known identifier, none of it is sent. The agent's model
        path calls this, and since 2026-11-17 so does the job API for the free
        text it sends a browser -- logTail, error, steps[].messages -- one
        line at a time (services/public_text.py). The step detail endpoint's
        structured fields (check detail, failure message) are still sent
        unredacted; only its resourceBundleDiagnosis goes through `text`.
        """
        out, other = self._render(value)
        if out != other:
            return WITHHELD
        if _RESIDUAL.search(out):
            out = _WORD.sub(_mask_word, out)
            if _RESIDUAL.search(out):
                return WITHHELD
        if self.contains_literal(out):
            return WITHHELD
        return out

    def _scan_cut(self, text: str, marks: re.Pattern[str], width: int) -> int:
        """Where to cut a (marked) string longer than MAX_SCAN.

        At the last whitespace, else hard at MAX_SCAN; then moved back to the
        start of a mark the cut would split. Known literals are already marks
        here (word characters, no spaces), so a literal holding a space cannot
        be split at that space (Codex review r4), and positions are taken in
        the string itself rather than in a lower-cased copy whose length can
        differ (Codex review r5).
        """
        cut = max(text.rfind(" ", 0, MAX_SCAN), text.rfind("\n", 0, MAX_SCAN))
        if cut <= MAX_TEXT:
            cut = MAX_SCAN
        for mark in marks.finditer(text, max(0, cut - width), min(len(text), cut + width)):
            if mark.start() < cut < mark.end():
                cut = mark.start()
        return cut

    @staticmethod
    def has_residual(value: str) -> bool:
        """True when a string still looks like part of a path (see _RESIDUAL)."""
        return bool(_RESIDUAL.search(value))

    def contains_literal(self, value: str) -> bool:
        """True when a known identifier is embedded in this string.

        The same case-insensitive match the replacement uses: str.lower() and
        re.IGNORECASE disagree on characters such as "İ" (Codex review r6).
        """
        return any(
            re.search(re.escape(literal), value, flags=re.IGNORECASE)
            for literal, _ in self.literals
            if literal
        )

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
                if len(value) <= 64 and self.release(value) == value:
                    kept[key] = value
                else:
                    withheld += 1
            else:
                withheld += 1

        return kept, withheld


__all__ = ["MAX_TEXT", "WITHHELD", "MetricValue", "Redactor"]
