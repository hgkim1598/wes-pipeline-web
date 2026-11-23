"""Offline evaluation of the official-document search, end to end from a run. No model.

Each case in cases.public.json is turned into the run records main.sh would
have written (a step document, and for resource-check cases the
resource_validation.txt report), in a temporary directory. The production
search, services/doc_search/engine.run_search, then reads them exactly as
POST /api/jobs/{id}/doc-search does. Nothing is stored and no database is used.

What this measures, and what it cannot
--------------------------------------
The search selects passages by an exact cause-kind key and only ORDERS them
with FTS5 (services/agent/doc_retrieval.py). So with the public synthetic
corpus (app/tests/fixtures/doc_passages.synthetic.json, placeholder text) the
numbers measure the path run record -> rule table -> cause kind -> filed
passages, and whether the search stays silent when it should. They do not
measure the order inside a kind: placeholder text has nothing to rank.

The order inside a kind is scored only with `--corpus local` against the
non-public excerpt file (config/knowledge/wes_doc_passages.json) and the
graded `grades_local` judgments (0..2) in the cases, which are provisional. That result is
local evidence, not a CI number.

Run from backend/:
    .venv/Scripts/python.exe -m evals.rag_eval.run                 # public synthetic corpus
    .venv/Scripts/python.exe -m evals.rag_eval.run --corpus local  # adds the local ranking check
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app import config
from app.services.agent import doc_retrieval
from app.services.doc_search import engine
from app.tests.conftest import RunBuilder
from app.tests.doc_corpus_fixture import SYNTHETIC_CORPUS, clear_store

from . import metrics

CASES = Path(__file__).with_name("cases.public.json")
LOCAL_CORPUS = config.KNOWLEDGE_DIR / "wes_doc_passages.json"

PRECHECK = "00_input_validation"
REPORT = "00_input_validation/resource_validation.txt"
HEADER = "[ERROR] Resource bundle validation failed:"
RUN_ID = "wes-20261123-000000-ragev1"
SAMPLE = "SYNTH-SAMPLE-01"
CATEGORIES = ("positive", "coverage_gap", "negative")
REVIEW_STATES = ("unreviewed", "accepted", "rejected")
DESIGNS = ("rule_replicating", "independent_ranking", "phrasing_variant")
NDCG_K = 3
SYNTHETIC_PREFIX = "synthetic-"


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data["cases"]
    validate_cases(cases)
    return cases


def validate_cases(cases: list[dict[str, Any]]) -> None:
    """Shape checks; a malformed case is an error, never a silent skip."""
    seen: set[str] = set()
    for case in cases:
        cid = case.get("id")
        if not cid or cid in seen:
            raise ValueError(f"missing or duplicate case id: {cid!r}")
        seen.add(cid)
        if case.get("category") not in CATEGORIES:
            raise ValueError(f"{cid}: unknown category {case.get('category')!r}")
        review = case.get("review") or {}
        if review.get("status") not in REVIEW_STATES:
            raise ValueError(f"{cid}: review.status must be one of {REVIEW_STATES}")
        if review["status"] != "unreviewed" and not (review.get("reviewer") and review.get("date")):
            raise ValueError(f"{cid}: a reviewed case needs reviewer and date")
        expected = case.get("expected") or {}
        relevant = expected.get("relevant_kinds")
        if not isinstance(expected.get("input_kinds"), list) or not isinstance(relevant, list):
            raise ValueError(f"{cid}: expected.input_kinds and expected.relevant_kinds are lists")
        if (case["category"] == "positive") != bool(relevant):
            raise ValueError(f"{cid}: only positive cases have relevant kinds")
        if case.get("design") not in DESIGNS:
            raise ValueError(f"{cid}: design must be one of {DESIGNS}")
        grades = expected.get("grades_local")
        if grades is not None:
            if not isinstance(grades, dict) or not all(g in (0, 1, 2) for g in grades.values()):
                raise ValueError(f"{cid}: grades_local maps passage id -> 0, 1 or 2")
            if not expected.get("grade_basis"):
                raise ValueError(f"{cid}: grades_local needs grade_basis")
        if not case.get("basis"):
            raise ValueError(f"{cid}: every case states its basis")
        run = case.get("run") or {}
        if not (run.get("report_items") or run.get("step_checks") or run.get("completed")):
            raise ValueError(f"{cid}: run needs report_items, step_checks or completed")


@contextmanager
def corpus(path: Path) -> Iterator[None]:
    """Point the search at one excerpt file, with the manual corpus off."""
    saved = (config.DOC_PASSAGE_KNOWLEDGE, config.DOC_MANUAL_CHUNKS, config.RUNS_ROOT)
    clear_store()
    config.DOC_PASSAGE_KNOWLEDGE = path
    config.DOC_MANUAL_CHUNKS = ""
    try:
        yield
    finally:
        config.DOC_PASSAGE_KNOWLEDGE, config.DOC_MANUAL_CHUNKS, config.RUNS_ROOT = saved
        clear_store()


def _write_run(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    """The run records for one case, and the job row the engine reads."""
    run = case["run"]
    builder = RunBuilder(root, RUN_ID)
    if run.get("report_items"):
        planned, mode = [PRECHECK], "check_only"
        builder.step(PRECHECK, status="failed", checks=[{
            "name": "resource_bundle", "status": "FAIL",
            "detail": f"validation failed; see {REPORT}"}])
        builder.run_status("failed", current_step=PRECHECK)
        items = "\n".join(f"  - {s}" for s in run["report_items"])
        builder.raw(REPORT, f"[OK] Validated 1 lane row(s) for sample '{SAMPLE}'.\n{HEADER}\n{items}\n")
    elif run.get("step_checks"):
        spec = run["step_checks"]
        planned, mode = [spec["step"]], "full"
        builder.step(spec["step"], status=spec["status"], checks=spec["checks"])
        builder.run_status("failed" if spec["status"] == "failed" else "completed_with_warnings",
                           current_step=spec["step"])
    else:
        planned, mode = [PRECHECK], "check_only"
        builder.step(PRECHECK, status="completed", checks=[{"name": "resource_bundle", "status": "PASS"}])
        builder.run_status("completed", current_step=None)
    return {
        "job_id": RUN_ID, "run_id": RUN_ID, "sample_id": SAMPLE, "status": "DONE",
        "run_dir": str(builder.run_dir), "planned_steps": json.dumps(planned), "run_mode": mode,
    }


def canonical(evidence_id: str) -> str:
    pid = evidence_id.removeprefix(doc_retrieval.EVIDENCE_PREFIX)
    return pid.removeprefix(SYNTHETIC_PREFIX)


def _kinds_of(evidence_id: str) -> set[str]:
    item = doc_retrieval.by_evidence_id(evidence_id)
    return set(item.causeKinds) if item else set()


def evaluate_case(case: dict[str, Any], *, score_preferred: bool) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rag-eval-") as tmp:
        root = Path(tmp)
        config.RUNS_ROOT = root
        record = engine.run_search(_write_run(root, case))

    expected = case["expected"]
    relevant = set(expected["relevant_kinds"])
    curated = [h for h in record.hits if h.corpus == "curated"]
    by_input: dict[str, list[str]] = {}
    for hit in sorted(curated, key=lambda h: (h.input_id, h.rank)):
        by_input.setdefault(hit.input_id, []).append(hit.evidence_id)

    input_kinds = sorted(i.kind for i in record.inputs)
    queries = []
    for kind in expected["relevant_kinds"]:
        match = next((i for i in record.inputs if i.kind == kind), None)
        ranked = by_input.get(match.inputId, []) if match else []
        rank = metrics.first_relevant_rank(ranked, lambda e, k=kind: k in _kinds_of(e))
        query = {"kind": kind, "inputFound": match is not None,
                 "returned": [canonical(e) for e in ranked], "firstRelevantRank": rank}
        grades = expected.get("grades_local")
        if score_preferred and grades:
            query["ndcg"] = metrics.ndcg_at_k([canonical(e) for e in ranked], grades, NDCG_K)
            if 2 in grades.values():  # "best" is defined only where a grade-2 passage exists
                query["bestRank"] = metrics.first_relevant_rank(
                    [canonical(e) for e in ranked], lambda pid: grades.get(pid, 0) == 2)
        queries.append(query)

    return {
        "id": case["id"],
        "category": case["category"],
        "design": case["design"],
        "review": case["review"]["status"],
        "errorCategory": record.error_category,
        "inputKinds": input_kinds,
        "inputKindsMatch": input_kinds == sorted(expected["input_kinds"]),
        "hitCount": len(curated),
        "wrongKindHits": sum(1 for h in curated if not (_kinds_of(h.evidence_id) & relevant)),
        "abstained": not curated,
        "queries": queries,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ranks = [q["firstRelevantRank"] for r in results if r["category"] == "positive" for q in r["queries"]]
    abstain = [r["abstained"] for r in results if r["category"] != "positive"]
    out = metrics.summarize(ranks, abstain)
    out["cases"] = len(results)
    out["inputKindAccuracy"] = metrics.mean([1.0 if r["inputKindsMatch"] else 0.0 for r in results])
    out["wrongKindHits"] = sum(r["wrongKindHits"] for r in results)
    out["coverageGapCases"] = sum(1 for r in results if r["category"] == "coverage_gap")
    graded = [q for r in results for q in r["queries"] if q.get("ndcg") is not None]
    if graded:
        best = [q["bestRank"] for q in graded if "bestRank" in q]
        out["gradedLocal"] = {
            "queries": len(graded),
            f"ndcgAt{NDCG_K}": metrics.mean([q["ndcg"] for q in graded]),
            "bestQueries": len(best),
            "mrrBest": metrics.mean([metrics.reciprocal(b) for b in best]),
            "bestAt1": metrics.mean([metrics.recall_at_k(b, 1) for b in best]),
            "note": "order inside a cause kind; local corpus; grades provisional (AI-proposed, unreviewed)",
        }
    return out


# A directory name made of words the excerpts use (bgzip, sorted, csi, force,
# overwrite, genome, columns, coordinate...). Where a file lives says nothing
# about the failure, so moving it there must not change the order (log 61).
NOISE_DIR = "bgzip_sorted_csi_force_overwrite_whole_genome_columns_coordinate_rename_chrs"


def _with_noisy_paths(case: dict[str, Any]) -> dict[str, Any] | None:
    items = case["run"].get("report_items") or []
    if not any("/data/wes/" in i for i in items):
        return None
    noisy = json.loads(json.dumps(case))
    noisy["run"]["report_items"] = [i.replace("/data/wes/", f"/data/wes/{NOISE_DIR}/") for i in items]
    return noisy


def path_stability(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Share of path-carrying positive queries whose ranked list is unchanged by the path."""
    stable, changed = 0, []
    for case in cases:
        if case["category"] != "positive":
            continue
        noisy = _with_noisy_paths(case)
        if noisy is None:
            continue
        a = [q["returned"] for q in evaluate_case(case, score_preferred=False)["queries"]]
        b = [q["returned"] for q in evaluate_case(noisy, score_preferred=False)["queries"]]
        if a == b:
            stable += 1
        else:
            changed.append(case["id"])
    total = stable + len(changed)
    return {"cases": total, "stable": metrics.mean([1.0] * stable + [0.0] * len(changed)), "changed": changed}


def run(corpus_name: str = "synthetic", cases_path: Path = CASES) -> dict[str, Any]:
    cases = load_cases(cases_path)
    path = SYNTHETIC_CORPUS if corpus_name == "synthetic" else LOCAL_CORPUS
    if not path.is_file():
        raise FileNotFoundError(f"corpus not found: {path}")
    with corpus(path):
        results = [evaluate_case(c, score_preferred=corpus_name == "local") for c in cases]
        stability = path_stability(cases)
    by_review = {
        state: summarize([r for r in results if r["review"] == state])
        for state in REVIEW_STATES if any(r["review"] == state for r in results)
    }
    by_design = {
        design: summarize([r for r in results if r["design"] == design])
        for design in DESIGNS if any(r["design"] == design for r in results)
    }
    return {
        "corpus": corpus_name,
        "byDesign": by_design,
        "pathStability": stability,
        "method": engine.METHOD,
        "summary": summarize(results),
        "byReviewStatus": by_review,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", choices=("synthetic", "local"), default="synthetic")
    parser.add_argument("--json", action="store_true", help="print every case, not only the summary")
    args = parser.parse_args(argv)
    report = run(args.corpus)
    shown = report if args.json else {k: report[k] for k in ("corpus", "method", "summary", "byDesign", "pathStability", "byReviewStatus")}
    json.dump(shown, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
