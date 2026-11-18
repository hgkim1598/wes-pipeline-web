"""Free text from the pipeline, as the job API may show it to a browser.

GET /api/jobs/{id} carries three kinds of text that main.sh wrote and nobody
structured:

    logTail            the last lines of logs/pipeline.log
    error              a failed step's messages joined, or the backend's own
                       launch error plus up to 40 lines of executor.log
    steps[].messages   each step's warning and failure messages

main.sh puts absolute server paths in all three (run_dir, samplesheet, the
reference bundle, the report it gave up on) and the sample name in filenames
and progress lines. Until 2026-11-17 they were sent verbatim, and the run
detail page printed them in its log panel (ADR-001 F6 / §8 deferred this).

Why the agent's redactor, and why `release`
-------------------------------------------

There is already one definition of "what a run's text may contain once it
leaves the server": ``agent.privacy.Redactor`` with the literals that
``run_scope.redactor_for_row`` takes from the job row. The step detail
endpoint uses the same pair for resourceBundleDiagnosis (ADR-001 D4). A
second, log-only rule set would drift from it, and the drift would show up as
a path that one screen hides and another prints.

``release`` rather than ``text``: ``text`` applies the shape rules and returns
whatever is left; ``release`` then checks the result and replaces a line it
cannot show to be clean with ``<withheld>``. A browser is outside the server
for this purpose just as a model is, so the fail-closed variant is the one that
fits. On the two restored real runs checked on 2026-11-17 the two agree on
every line (0 lines withheld), so the stricter choice costs nothing today.

Line by line
------------

A redacted string is capped at ``privacy.MAX_TEXT`` characters. ``error`` can
hold 40 log lines, which would be cut short if redacted as one string, and one
unprovable line would withhold all of them. So text is always split into
lines, each line projected on its own, and the line structure kept: one output
line per input line, in the same order.

What is lost
------------

Every relative path and every bare data filename becomes ``<path>`` /
``<file>``, including harmless ones such as the guide document the pipeline
names in its tool-installation message. That is the redactor's existing rule,
not a new one, and the structured views (failure cards, resource causes) are
where the screen explains a failure; the log is the supporting record.
"""

from __future__ import annotations

from collections.abc import Iterable

from .agent.privacy import Redactor


def project_lines(lines: Iterable[str], redactor: Redactor) -> list[str]:
    """One projected line per input line, in order."""
    return [redactor.release(line) for line in lines]


def project_error(error: str | None, redactor: Redactor) -> str | None:
    """`error` projected line by line, keeping its line breaks."""
    if error is None:
        return None
    return "\n".join(project_lines(error.split("\n"), redactor))


__all__ = ["project_error", "project_lines"]
