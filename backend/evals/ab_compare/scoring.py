"""Automatic, fixed-pattern scoring of one answer against the frozen protocol.

What this is NOT: a judgement of factual accuracy. The detectors count fixed
sentence shapes written down before any call; zero means "none of these shapes",
not "no error". Every number here is shown as automatic, next to the human
grade, never in its place.

The claim list (`claims`) is the unit the human grades: one statement of
importantFindings / limitations / nextChecks / uncertainties, in that order.
The summary is scanned by the detectors but is not a claim.
"""

from __future__ import annotations

import re
from typing import Any

from . import contract

SECTIONS = ("importantFindings", "limitations", "nextChecks", "uncertainties")

# Same split as front/src/features/run-detail/evidenceSource.ts.
_SOURCE_BY_PREFIX = {
    "run": "record",
    "lim": "record",
    "step": "record",
    "dx": "mixed",
    "fail": "mixed",
    "doc": "doc",
    "manual": "doc",
    "src": "knowledge",
    "concept": "knowledge",
    "term": "knowledge",
}


def evidence_source(ref: str) -> str:
    head, sep, tail = ref.partition(":")
    if not sep or not head or not tail:
        return "other"
    return _SOURCE_BY_PREFIX.get(head, "other")


def claims(answer: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(answer, dict):
        return out
    for section in SECTIONS:
        for index, item in enumerate(answer.get(section) or []):
            if not isinstance(item, dict):
                continue
            refs = [r for r in item.get("evidenceRefs") or [] if isinstance(r, str)]
            out.append(
                {
                    "section": section,
                    "index": index,
                    "statement": str(item.get("statement") or ""),
                    "evidenceRefs": refs,
                }
            )
    return out


def _texts(answer: dict[str, Any]) -> list[tuple[str, str]]:
    """(where, text) pairs: the summary, then every claim."""
    out: list[tuple[str, str]] = []
    if isinstance(answer.get("summary"), str):
        out.append(("summary", answer["summary"]))
    for claim in claims(answer):
        out.append((f"{claim['section']}.{claim['index']}", claim["statement"]))
    return out


def _active(detector: dict[str, Any], case: dict[str, Any]) -> bool:
    steps = {s["stepId"]: s["state"] for s in case["facts"]["steps"]}
    not_run = {k for k, v in steps.items() if v.startswith("notRun")}
    run_failed = any(v == "ranFailed" for v in steps.values())
    if detector.get("activeWhenRunFailed"):
        return run_failed
    return bool(not_run & set(detector.get("activeWhenNotRun") or []))


def _excerpt(text: str, match: re.Match[str]) -> str:
    return text[max(0, match.start() - 24) : match.end() + 24]


def score_answer(answer: dict[str, Any] | None, case: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    """Automatic counts for one answer. None answer -> nothing measured."""
    if not isinstance(answer, dict):
        return {"measured": False}
    texts = _texts(answer)
    hits: list[dict[str, Any]] = []
    for detector in protocol["detectors"]:
        if not _active(detector, case):
            continue
        rx = re.compile(detector["pattern"], re.I)
        for where, text in texts:
            match = rx.search(text)
            if match:
                hits.append(
                    {"detector": detector["id"], "metric": detector["metric"], "where": where, "excerpt": _excerpt(text, match)}
                )
    wrong: list[dict[str, Any]] = []
    for candidate in protocol["wrongCauseCandidates"]:
        rx = re.compile(candidate["pattern"], re.I)
        for where, text in texts:
            match = rx.search(text)
            if match:
                wrong.append({"candidate": candidate["id"], "where": where, "excerpt": _excerpt(text, match)})
    whole = "\n".join(text for _, text in texts)
    causes = {
        cause["id"]: bool(re.search(cause["pattern"], whole, re.I))
        for cause in case["facts"]["requiredCauses"]
    }
    claim_list = claims(answer)
    cited = sorted({ref for claim in claim_list for ref in claim["evidenceRefs"]})
    by_source: dict[str, int] = {}
    for ref in cited:
        source = evidence_source(ref)
        by_source[source] = by_source.get(source, 0) + 1
    return {
        "measured": True,
        "claimCount": len(claim_list),
        "nonRunClaims": sum(1 for h in hits if h["metric"] == "nonRunClaims"),
        "execContradictions": sum(1 for h in hits if h["metric"] == "execContradictions"),
        "detectorHits": hits,
        "wrongCauseCandidates": wrong,
        "requiredCauses": {"mentioned": sum(causes.values()), "required": len(causes), "byCause": causes},
        "citedRefs": cited,
        "citedBySource": by_source,
    }


SCORING_VERSION = 2


def score_record(record: dict[str, Any], case: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    """Scores for the served answer and, separately, for a gate-rejected one.

    `outcome` comes from contract.classify_outcome. The gate block describes a
    gate decision only when there was one: after a provider error no gate ran,
    so `gate.evaluated` is False and `gate.passed` is None -- never False
    (scoring version 1 wrote `passed: not available`, which counted a timeout
    as a gate rejection). Latency is a provider time for every outcome; the
    aggregation decides which outcomes it uses.
    """
    outcome = contract.classify_outcome(record)
    rejected = record.get("rejectedOutput") or {}
    rejected_answer = rejected.get("answer") if isinstance(rejected, dict) else None
    trace = record.get("trace") or {}
    evaluated = outcome["outcome"] in contract.ANSWER_OUTCOMES
    return {
        "scoringVersion": SCORING_VERSION,
        "outcome": outcome,
        "gate": {
            "evaluated": evaluated,
            "passed": (outcome["outcome"] == "served") if evaluated else None,
            "errorCategory": record.get("errorCategory"),
            "firstRejection": trace.get("firstRejection"),
        },
        "durationMs": record.get("durationMs") if record.get("durationMs") is not None else trace.get("durationMs"),
        "wallMs": record.get("wallMs"),
        "served": score_answer(record.get("output"), case, protocol),
        "rejected": score_answer(rejected_answer, case, protocol) if rejected_answer else {"measured": False},
    }
