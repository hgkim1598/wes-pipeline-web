"""Deterministic checks a generated synthesis must pass before anyone sees it.

Pure functions over text and data. Nothing here knows about Pydantic models,
HTTP, CheckResult objects or eval reports -- callers decide what to do with the
findings. That is what lets the same rules run in two places that report very
differently:

    synthesis.py  ->  validation.py  <-  evals/evaluators.py

The direction matters. The runtime must never import from `evals/`: a test
harness cannot become a production dependency. So the shared part lives here,
in the application, and the eval layer imports it -- the way run_eval.py already
imports contract and prompt.

Why these two checks and not more
---------------------------------

Both answer a question with a mechanical answer:

    unsupported number   is this digit string anywhere in what the model saw?
    internal field name  is this camelCase token one of the payload's own keys?

Neither needs to understand a sentence. "Does this claim actually follow from
the evidence it cites" is a different kind of question and is deliberately not
attempted here -- a bad approximation of it would reject correct explanations
and lend false confidence to the ones it let through.

What counts as "known" at runtime
---------------------------------

The fact source is the **payload** -- the exact object handed to the model --
not the fuller RunExplanation it was built from. A number the model was never
shown cannot be something it legitimately quoted, and the payload additionally
carries the knowledge and grounding text, whose numbers are quotable and do not
appear in RunExplanation at all. Checking against the payload is therefore both
stricter where it matters and correct where the looser source would misfire.

(`evals/evaluators.py` passes the fixture for the number check for historical
reasons, and its baselines were recorded that way. Its behaviour is unchanged
by this module; only the implementation is now shared.)
"""

from __future__ import annotations

import re
from typing import Any

# Numbers as they appear in prose: 52,379 · 10.9967 · 7.2115 · 36,458,262.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# camelCase identifiers only: lowercase start, an uppercase letter later.
#
# The narrowing is the point. Forbidding every payload key would catch ordinary
# words like `assembly`, `scope` and `actions` -- and some of those genuinely
# appear in the canonical knowledge sentences the model is supposed to reuse
# (wes_failures.json has a scope claim written as "같은 assembly release에서").
#
# An internal capital, by contrast, is the mechanical signature of a schema
# identifier and does not collide with Korean prose or normal English words.
# `rawVariantRecords`, `coreEndpoint`, `basesInLowMeanDepthIntervalsPct` and
# `possibleCauses` all match.
#
# This is not a hand-maintained blocklist: what is forbidden is derived from the
# keys the payload actually has, so the check follows the schema when it changes.
_CAMEL = re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9]*(?:[A-Z][a-zA-Z0-9]*)+(?![A-Za-z0-9])")

# Small integers are allowed through the number check: the model counts its own
# list ("3개 항목") and such counts are not claims about the run. Deliberately
# low, so no real measurement can hide behind it -- every coverage and variant
# value in this project is far above it.
SMALL_ORDINAL_MAX = 20


def normalise_number(token: str) -> str:
    """`52,379` and `52379` are the same number; `10.9967` keeps its digits."""
    cleaned = token.replace(",", "")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"


def is_small_ordinal(value: str) -> bool:
    """True for a plain integer in [0, SMALL_ORDINAL_MAX]."""
    if "." in value:
        return False
    try:
        return 0 <= int(value) <= SMALL_ORDINAL_MAX
    except ValueError:
        return False


def collect_known_numbers(facts: Any) -> set[str]:
    """Every number reachable in `facts`, normalised.

    Walks the structure rather than naming fields, so a measurement added
    upstream is automatically quotable instead of being reported as invented.
    """
    known: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            known.add(normalise_number(str(node)))
            return
        if isinstance(node, dict):
            for key, value in node.items():
                # Keys carry facts too: coverage.breadth is {"30X": 2.6709}, so
                # the thresholds 30/50/100 exist only as **keys**. A first
                # version that walked values alone flagged a sentence quoting
                # "30X 2.6709%" exactly right as an invented number.
                walk(key)
                walk(value)
            return
        if isinstance(node, list):
            for value in node:
                walk(value)
            return
        if isinstance(node, str):
            # Pipeline messages and knowledge statements carry their own numbers
            # ("7.2115% of ..."). Quoting those back is not invention.
            for match in _NUMBER.findall(node):
                known.add(normalise_number(match))

    walk(facts)
    return known


def find_unsupported_numbers(
    statements: list[str],
    facts: Any,
    *,
    allow_small_ordinals: bool = True,
) -> list[str]:
    """Number tokens in `statements` that `facts` does not contain.

    Returns the offending tokens as they were written, sorted and deduplicated.
    An empty list means every number is accounted for.
    """
    known = collect_known_numbers(facts)
    invented: set[str] = set()
    for text in statements:
        for token in _NUMBER.findall(text):
            value = normalise_number(token)
            if value in known:
                continue
            if allow_small_ordinals and is_small_ordinal(value):
                continue
            invented.add(token)
    return sorted(invented)


def collect_property_names(payload: Any) -> set[str]:
    """Every dict key in the payload the model was shown."""
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                names.add(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return names


def camel_case_property_names(payload: Any) -> set[str]:
    """The payload keys this check can act on: the camelCase ones.

    Public because a caller may want to report how many names were in scope,
    not only which ones leaked.
    """
    return {name for name in collect_property_names(payload) if _CAMEL.fullmatch(name)}


def find_exposed_property_names(statements: list[str], payload: Any) -> list[str]:
    """Payload property names quoted in user-facing prose.

    Only camelCase names are inspected, so a single ordinary word that happens
    to be a key (`assembly`, `scope`) is not flagged; those stay a human
    judgement. Returns the exposed names, sorted; empty means none.
    """
    known = camel_case_property_names(payload)
    if not known:
        return []

    found: set[str] = set()
    for text in statements:
        for token in _CAMEL.findall(text):
            if token in known:
                found.add(token)
    return sorted(found)


__all__ = [
    "SMALL_ORDINAL_MAX",
    "camel_case_property_names",
    "collect_known_numbers",
    "collect_property_names",
    "find_exposed_property_names",
    "find_unsupported_numbers",
    "is_small_ordinal",
    "normalise_number",
]
