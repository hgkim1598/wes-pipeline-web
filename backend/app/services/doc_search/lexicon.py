"""Wording lexicon: a cause kind SUGGESTED for a sentence the rule table left unknown (log 62).

Why this exists
---------------
The rule table (services/resource_bundle_causes.py) matches main.sh's own
templates exactly. A sentence worded any other way -- an older script, a tool's
own message, a person's paraphrase -- is `unknown`, and the curated search, which
selects passages by exact kind key, returns nothing for it. All phrasing-variant
eval cases fail there (evals/rag_eval, log 61): not in ranking, in
classification.

What this is NOT
----------------
It is not a second classifier. The run's diagnosis keeps `unknown`; the
explanation, the facts and the AI request never see a suggested kind. Only the
document search uses it, and every passage found through it is returned with
its own relation (`suggestedByWording`), which agent_input.py does not put into
the model's input. A reader sees "this was guessed from the wording", never
"this is the cause".

It is not free search either. Free BM25 over every passage named the wrong cause
with confidence 8 times in 48 queries (log 17.2). Here a kind is suggested only
when ALL the concepts a rule names occur in the sentence, and when two kinds
fit, nothing is suggested.

How the vocabulary was chosen
-----------------------------
From the tools' documented vocabulary (file extensions, program names, the
words their messages use) and the DEV cases only: evals/rag_eval split=dev and
evals/experiments/retrieval_queries.json split=dev. Identifiers that appear only
in held-out cases (e.g. `bns_restore`, `hts_idx_load3`) are deliberately absent.
A held-out miss is reported, not fixed here.

Input is the already-redacted evidence sentence (paths are `<path>`), so a word
that only lived inside a path -- `.vcf.gz`, `.bed` -- is gone by design.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


def _any(*patterns: str) -> re.Pattern[str]:
    r"""One pattern for several surface forms.

    Every `\b` is rewritten to an ASCII-only word boundary: in Python a Hangul
    syllable is a word character, so `\bfai\b` would not match "fai랑" (a
    Korean particle written straight after the word). Found on dev query k03.
    """
    joined = "|".join(f"(?:{p})" for p in patterns)
    return re.compile(joined.replace(r"\b", _ASCII_BOUNDARY), re.IGNORECASE)


_W = "[A-Za-z0-9_]"
_ASCII_BOUNDARY = f"(?:(?<!{_W})(?={_W})|(?<={_W})(?!{_W}))"


# --- concepts ---------------------------------------------------------------
# Each concept is a set of surface forms with the same meaning in this domain.

VCF = _any(r"\bvcf\b", r"\.vcf\b", r"\bbcf\b", r"\bknown[_ ]sites\b", r"\bdbsnp\b")
VCF_INDEX = _any(r"\.tbi\b", r"\.csi\b", r"\btbi\b", r"\bcsi\b", r"\btabix index\b")
INDEX = _any(r"\bindex(?:es)?\b", r"\bidx\b", r"인덱스", r"색인")
MISSING = _any(
    r"\bnot found\b", r"\bcould not (?:retrieve|load|find|open)\b", r"\bfail(?:ed)? to (?:locate|load)\b",
    r"\bno such file\b", r"\bmissing\b", r"\bdoes not exist\b", r"\babsent\b",
    r"없", r"찾을 수 없", r"못 찾", r"누락",
)
TOOL_MISSING = _any(
    r"\bcommand not found\b", r"\bnot installed\b", r"\bnot (?:on|in) (?:the )?path\b",
    r"\bunavailable\b", r"\bnot available\b", r"명령을 찾을 수 없", r"설치되지 않",
)
VCF_TOOL = _any(r"\bbcftools\b", r"\btabix\b")
# `bwa` followed by `_` too: bwa's own function names (bwa_idx_load_from_disk).
BWA = _any(r"\bbwa(?:\b|_)")
BWA_COMPONENT = _any(r"\.(?:bwt|pac|ann|amb|sa)\b")
INCOMPLETE = _any(r"\bincomplete\b", r"\bpartial\b", r"불완전")
DICT = _any(r"\bdict\b", r"\.dict\b", r"\bdictionary\b", r"사전")
FAI = _any(r"\bfai\b", r"\.fai\b", r"\bfasta index\b", r"\bfaidx\b")
MISMATCH = _any(
    r"\bmismatch(?:es|ed)?\b", r"\bdisagree", r"\bdo(?:es)? not match\b", r"\bdid not match\b",
    r"\bdiffer", r"\bdifferent\b", r"\bincompatible\b", r"\binconsistent\b",
    r"불일치", r"안 맞", r"맞지 않", r"다르",
)
BED = _any(r"\bbed\b", r"\.bed\b")
BED_PROBLEM = _any(
    r"\bonly \d+ columns?\b", r"\bfewer than \d+ columns?\b", r"\binvalid\b", r"\bmalformed\b",
    r"\bnot integers?\b", r"\bout of range\b", r"\bgreater than end\b", r"\berror parsing\b",
)
CHECKSUM = _any(r"\bchecksum\b", r"\bsha-?256(?:sum)?\b", r"\bmd5(?:sum)?\b", r"체크섬", r"해시")
CHECK_FAILED = _any(
    r"\bmismatch\b", r"\bdid not match\b", r"\bdo(?:es)? not match\b", r"\bfailed\b", r"\bdiffer",
    r"불일치", r"안 맞", r"맞지 않", r"다르",
)
# An index of an ALIGNMENT file is not a VCF index; nothing curated covers it.
ALIGNMENT_INDEX = _any(r"\.bai\b", r"\bbai\b", r"\bbam\b", r"\bcram\b", r"\.crai\b")


@dataclass(frozen=True)
class Suggestion:
    kind: str
    rule_id: str


def _bwa_kind(t: str) -> str | None:
    bwa_index = bool(BWA.search(t) and INDEX.search(t)) or bool(BWA_COMPONENT.search(t))
    if not bwa_index:
        return None
    if INCOMPLETE.search(t):
        return "bwa_index_incomplete"
    if MISSING.search(t):
        return "bwa_index_not_found"
    return None


# (rule id, kind or callable) -- every rule is checked; see suggest().
_RULES: tuple[tuple[str, Callable[[str], str | None]], ...] = (
    ("L-VCF-TOOL", lambda t: "vcf_tool_unavailable" if VCF_TOOL.search(t) and TOOL_MISSING.search(t) else None),
    ("L-VCF-INDEX", lambda t: "vcf_index_missing" if (
        MISSING.search(t) and not TOOL_MISSING.search(t) and not ALIGNMENT_INDEX.search(t)
        and (VCF_INDEX.search(t) or (VCF.search(t) and INDEX.search(t)))) else None),
    ("L-BWA", _bwa_kind),
    ("L-DICT-FAI", lambda t: "reference_index_mismatch" if DICT.search(t) and FAI.search(t) and MISMATCH.search(t) else None),
    ("L-CHECKSUM", lambda t: "checksum_mismatch" if CHECKSUM.search(t) and CHECK_FAILED.search(t) else None),
    ("L-BED", lambda t: "bed_content_invalid" if BED.search(t) and BED_PROBLEM.search(t) else None),
)


def suggest(text: str) -> Suggestion | None:
    """The one kind every matching rule agrees on, or None.

    None when no rule matches AND when rules disagree: an ambiguous sentence
    gets no documents rather than the wrong ones.
    """
    if not text or not text.strip():
        return None
    found: dict[str, str] = {}
    for rule_id, rule in _RULES:
        kind = rule(text)
        if kind:
            found.setdefault(kind, rule_id)
    if len(found) != 1:
        return None
    kind, rule_id = next(iter(found.items()))
    return Suggestion(kind, rule_id)


RULE_IDS = tuple(rule_id for rule_id, _ in _RULES)
