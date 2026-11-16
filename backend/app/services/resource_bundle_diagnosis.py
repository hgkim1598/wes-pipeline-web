"""The one way out of the resource_bundle analysis (P0-1, ADR-001 D2).

services/resource_bundle_causes.py keeps raw sentences. This module turns that
internal value into schemas.ResourceBundleDiagnosis, the shape both the public
step detail API and the agent's StepEvidence carry. Both call this function
with the same job redactor, so the two values are identical by construction
(spec FR-15).

What survives
-------------

The structured fields -- state, source, truncated, and each cause's kind,
resourceRole, tool and ruleId -- come from the rule table's fixed vocabulary,
not from the log, so they are always kept (spec NFR-2, policy P3).

Raw strings -- each cause's evidenceText and the no_error_block excerpt -- are
cleaned of control characters, run through the job's Redactor, and then
released only if BOTH hold (fail-closed; policy P4/P5):

  * the job knows its sample identifier, so the redactor can replace it. An
    old job row without sample_id cannot, and the log names the sample
    ("[OK] Validated 1 lane row(s) for sample '...'"), so its text is withheld;
  * nothing path-shaped, digest-shaped or identifier-shaped is left after
    redaction. The redactor's patterns are not assumed to be complete.

A withheld string becomes None and is counted in withheldTextCount. This is a
check for the KNOWN risks only; it does not prove that free text carries no
other identifying content (spec §10.3 U5).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from ..schemas import ResourceBundleCause, ResourceBundleDiagnosis
from . import resource_bundle_causes
from .agent.privacy import Redactor
from .agent.run_scope import SAMPLE_PLACEHOLDER
from .resource_bundle_causes import ResourceBundleAnalysis

# ANSI/VT escape sequences (colour codes and the like), removed whole.
_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")

# What must not be left after redaction. Deliberately broader than the
# redactor's own patterns: a backslash at all, a "/" that starts a path, or two
# separators in one token; and any long hex run.
_RESIDUAL_PATH = re.compile(r"\\|(?:^|[\s'\"(=:,\[])/[\w.\-~]|/[^\s/]+/")
_RESIDUAL_HEX = re.compile(r"[0-9a-fA-F]{32,}")


def _clean(text: str, *, keep_newlines: bool) -> str:
    """Remove escape sequences and every control/format character.

    Format characters (Unicode Cf) include zero-width and bidi-override marks
    that can make a string read differently from what it contains.
    """
    text = _ESCAPE.sub("", text)
    out = []
    for char in text:
        if keep_newlines and char == "\n":
            out.append(char)
        elif char == "\t":
            out.append(" ")
        elif unicodedata.category(char) in ("Cc", "Cf"):
            continue
        else:
            out.append(char)
    return "".join(out)


def _sample_known(redactor: Redactor) -> bool:
    return any(placeholder == SAMPLE_PLACEHOLDER for _, placeholder in redactor.literals)


def _release(raw: str | None, redactor: Redactor, *, keep_newlines: bool) -> str | None:
    """The cleaned, redacted text -- or None when it cannot be released safely."""
    if raw is None or not _sample_known(redactor):
        return None
    cleaned = _clean(raw, keep_newlines=keep_newlines)
    text = redactor.text(cleaned)
    if _RESIDUAL_PATH.search(text) or _RESIDUAL_HEX.search(text):
        return None
    # The model path's own check too (encoded or look-alike separators, a name
    # glued to a placeholder, the two literal orders disagreeing): anything it
    # would change or withhold is not released here, so this field is never
    # the weaker one.
    if redactor.release(cleaned) != text:
        return None
    if redactor.contains_literal(text):
        return None
    return text


def project(
    analysis: ResourceBundleAnalysis | None, redactor: Redactor
) -> ResourceBundleDiagnosis | None:
    """Internal analysis -> the external model. None stays None (other steps)."""
    if analysis is None:
        return None

    withheld = 0
    causes: list[ResourceBundleCause] = []
    for cause in analysis.causes:
        text = _release(cause.raw_text, redactor, keep_newlines=False)
        withheld += text is None
        causes.append(
            ResourceBundleCause(
                kind=cause.kind,
                resourceRole=cause.resource_role,
                tool=cause.tool,
                ruleId=cause.rule_id,
                evidenceText=text,
            )
        )

    excerpt = None
    if analysis.excerpt is not None:
        excerpt = _release(analysis.excerpt, redactor, keep_newlines=True)
        withheld += excerpt is None

    return ResourceBundleDiagnosis(
        state=analysis.state,
        source=analysis.source,
        causes=causes,
        unparsedExcerpt=excerpt,
        truncated=analysis.truncated,
        withheldTextCount=withheld,
    )


def diagnose(
    run_dir: Path, step_id: str, checks: list[dict[str, Any]], redactor: Redactor
) -> ResourceBundleDiagnosis | None:
    """Analyse and project in one call -- what both consumers use.

    The API and the agent call this with the job's redactor, so neither can
    reach the internal analysis or apply a different rule (ADR-001 E1, E4).
    `checks` is the step's validation.results from step_reader.read().
    """
    return project(resource_bundle_causes.analyze(run_dir, step_id, checks), redactor)


__all__ = ["diagnose", "project"]
