"""Offline evaluation: analysis-step failures (01-06) -> manual sections. No model.

Separate from run.py on purpose: cases.public.json (resource causes, curated
excerpts) is not touched, and its numbers must not move (development log 65).

What a case is
--------------
One FAIL check as main.sh records it in an analysis step -- a `require_cmd_ok`
label or a `fail_step` code -- with what the search SHOULD do:
  positive  an input with this tool/command, and a hit in that command's manual
            section when a manual of the same tool is configured;
  abstain   no document at all: no command produced the check (presence / size
            test, a two-command pipe, the ERR trap), or no manual covers the
            tool / a subcommand is needed and there is none.

Corpus
------
Two SYNTHETIC manuals (samtools, bcftools): invented sentences in the shape of
a man page, nothing quoted from real documentation. A server holds ONE manual,
so every case is run once per manual. A hit from the other tool's manual is a
false positive; a positive case is answerable only under its own tool's manual.

What the numbers mean -- and do not
-----------------------------------
`inputAccuracy` and `abstain` measure the routing record -> command -> corpus.
The section metrics (Recall@k, MRR) measure whether the FIRST hit sits in the
command's own section; with a synthetic manual that is mostly structural
(option lookup / section intro come first), so it is a regression guard, not a
ranking-quality claim. Ranking quality on real manual text is not measured here.

`--ablate` turns the analysis-step command families off (the state before log
65) to give the before number on the same cases.

    .venv/Scripts/python.exe -m evals.rag_eval.analysis
    .venv/Scripts/python.exe -m evals.rag_eval.analysis --ablate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app import config
from app.services.doc_search import commands, engine, manual_corpus
from app.tests.conftest import RunBuilder
from app.tests.doc_corpus_fixture import SYNTHETIC_CORPUS, clear_store

from . import metrics

CASES = Path(__file__).with_name("cases.analysis.public.json")
RUN_ID = "wes-20261123-000000-ragan1"
SAMPLE = "SYNTH-SAMPLE-01"
CATEGORIES = ("positive", "abstain")
SNAP = {"samtools": "5" * 64, "bcftools": "b" * 64}

# Invented wording, man-page shape only (title "<tool>(1)", heading path with
# "<tool> <command> [" so manual_corpus reads the section command).
_MANUALS: dict[str, list[tuple[str, str, str]]] = {
    "samtools": [
        ("desc", "DESCRIPTION", "SYNTHETIC. The toolkit reads and writes alignment files."),
        ("index", "COMMANDS AND OPTIONS > samtools index [ -bc ] in.bam",
         "SYNTHETIC. index builds an index of a coordinate-sorted compressed alignment file."),
        ("quickcheck", "COMMANDS AND OPTIONS > samtools quickcheck [ -qv ] in.bam",
         "SYNTHETIC. quickcheck tests that a file looks intact: a header and an end-of-file block."),
        ("merge", "COMMANDS AND OPTIONS > samtools merge [ options ] out.bam in.bam",
         "SYNTHETIC. merge combines sorted alignment files into one sorted file."),
        ("calmd", "COMMANDS AND OPTIONS > samtools calmd [ -Ee ] in.bam ref.fasta",
         "SYNTHETIC. calmd recomputes MD and NM tags against the reference."),
        ("sort", "COMMANDS AND OPTIONS > samtools sort [ options ] in.bam",
         "SYNTHETIC. sort orders alignments by coordinate; an index needs sorted input."),
    ],
    "bcftools": [
        ("desc", "DESCRIPTION", "SYNTHETIC. The toolkit reads and writes variant files."),
        ("view", "COMMANDS AND OPTIONS > bcftools view [ OPTIONS ] file",
         "SYNTHETIC. -h, --header-only prints the header. -i, --include keeps matching records."),
        ("norm", "COMMANDS AND OPTIONS > bcftools norm [ OPTIONS ] file",
         "SYNTHETIC. -m, --multiallelics splits or joins multiallelic records."),
        ("index", "COMMANDS AND OPTIONS > bcftools index [ OPTIONS ] file",
         "SYNTHETIC. -f, --force overwrites an existing index of a compressed variant file."),
        ("annotate", "COMMANDS AND OPTIONS > bcftools annotate [ OPTIONS ] file",
         "SYNTHETIC. -a, --annotations names the file whose columns are added."),
        ("stats", "COMMANDS AND OPTIONS > bcftools stats [ OPTIONS ] file",
         "SYNTHETIC. stats summarises a variant file."),
    ],
}


def write_manual(root: Path, tool: str) -> Path:
    path = root / f"manual-{tool}" / f"{SNAP[tool]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for anchor, context, body in _MANUALS[tool]:
        cid = f"{tool}#{anchor}#00"
        rows.append({
            "chunk_id": cid, "source_id": f"{tool}-manual", "source_sha256": SNAP[tool],
            "anchor": anchor, "url": f"https://example.invalid/{tool}.html#{anchor}",
            "context": context, "body": body, "block_ids": [0], "kinds": ["paragraph"],
            "split_block": False, "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "search_text": f"{context}\n{body}",
        })
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (path.parent / f"{SNAP[tool]}.meta.json").write_text(
        json.dumps({"title": f"{tool}(1)", "version_text": "SYNTHETIC manual for evaluation, not documentation"}),
        encoding="utf-8")
    return path


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    seen: set[str] = set()
    for c in cases:
        cid = c.get("id")
        if not cid or cid in seen:
            raise ValueError(f"missing or duplicate case id: {cid!r}")
        seen.add(cid)
        if c.get("category") not in CATEGORIES:
            raise ValueError(f"{cid}: category must be one of {CATEGORIES}")
        if (c.get("review") or {}).get("status") != "unreviewed":
            raise ValueError(f"{cid}: analysis cases are provisional (review.status unreviewed)")
        if not c.get("basis"):
            raise ValueError(f"{cid}: every case states its main.sh basis")
        exp = c.get("expected") or {}
        if c["category"] == "positive" and not (exp.get("tool") and exp.get("section")):
            raise ValueError(f"{cid}: a positive case names the tool and the manual section")
        if c["category"] == "abstain" and exp.get("section"):
            raise ValueError(f"{cid}: an abstain case has no section")
    return cases


@contextmanager
def _ablated(on: bool) -> Iterator[None]:
    """Without the analysis families: the command map as it was before log 65."""
    if not on:
        yield
        return
    saved = commands._CHECK_FAMILIES
    analysis = {id(f) for f in commands._ANALYSIS_FAMILIES}
    commands._CHECK_FAMILIES = tuple(f for f in saved if id(f) not in analysis)
    try:
        yield
    finally:
        commands._CHECK_FAMILIES = saved


def _row(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    step = case["step"]
    builder = RunBuilder(root, RUN_ID)
    name = case["check"].replace("<SAMPLE>", SAMPLE)
    builder.step(step, status="failed", checks=[{"name": name, "status": "FAIL", "detail": "synthetic"}],
                 failures=[{"code": name, "message": "synthetic"}])
    builder.run_status("failed", current_step=step)
    return {"job_id": RUN_ID, "run_id": RUN_ID, "sample_id": SAMPLE, "status": "DONE",
            "run_dir": str(builder.run_dir), "planned_steps": json.dumps([step]), "run_mode": "full"}


def evaluate(case: dict[str, Any], manual_tool: str, root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rag-an-") as tmp:
        config.RUNS_ROOT = Path(tmp)
        config.DOC_MANUAL_CHUNKS = str(write_manual(root, manual_tool))
        record = engine.run_search(_row(Path(tmp), case))
    exp = case["expected"]
    inputs = [{"kind": i.kind, "tool": i.tool, "display": i.command.display if i.command else None}
              for i in record.inputs]
    hits = sorted(record.hits, key=lambda h: (h.input_id, h.rank))
    serialized = json.dumps([inputs, [h.__dict__ for h in hits]])
    section = exp.get("section")
    in_section = [h for h in hits if h.corpus == "manual" and h.evidence_id.startswith(f"manual:{manual_tool}#{section}#")]
    rank = None
    if section and exp.get("tool") == manual_tool:
        ids = [h.evidence_id for h in hits if h.corpus == "manual"]
        rank = metrics.first_relevant_rank(ids, lambda e: e.startswith(f"manual:{manual_tool}#{section}#"))
    candidates = [h for h in hits if h.relation in ("filedUnderCauseKind", "sameCommandSection")]
    return {
        "id": case["id"],
        "category": case["category"],
        "manual": manual_tool,
        "answerable": case["category"] == "positive" and exp.get("tool") == manual_tool,
        "inputs": inputs,
        "inputMatch": (inputs == [{"kind": exp["kind"], "tool": exp["tool"], "display": exp["display"]}]
                       if exp.get("kind") else inputs == []),
        "hits": len(hits),
        "curatedHits": sum(1 for h in hits if h.corpus == "curated"),
        "firstSectionRank": rank,
        "inSectionHits": len(in_section),
        # agent candidates that are NOT in the command's own section: must be 0.
        "candidatesOutsideSection": sum(1 for h in candidates if h not in in_section),
        "sampleLeaked": SAMPLE in serialized,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if r["answerable"]]
    ranks = [r["firstSectionRank"] for r in answerable]
    silent = [r for r in rows if not r["answerable"]]
    return {
        "cases": len({r["id"] for r in rows}),
        "runs": len(rows),
        "inputAccuracy": metrics.mean([1.0 if r["inputMatch"] else 0.0 for r in rows]),
        "answerableQueries": len(answerable),
        "recallAt1": metrics.mean([metrics.recall_at_k(k, 1) for k in ranks]),
        "recallAt3": metrics.mean([metrics.recall_at_k(k, 3) for k in ranks]),
        "mrr": metrics.mean([metrics.reciprocal(k) for k in ranks]),
        "abstainRuns": len(silent),
        "abstainAccuracy": metrics.mean([1.0 if r["hits"] == 0 else 0.0 for r in silent]),
        "falsePositiveRuns": [f"{r['id']}@{r['manual']}" for r in silent if r["hits"]],
        "curatedHits": sum(r["curatedHits"] for r in rows),
        "candidatesOutsideSection": sum(r["candidatesOutsideSection"] for r in rows),
        "sampleLeaks": sum(1 for r in rows if r["sampleLeaked"]),
    }


def run(*, ablate: bool = False, cases_path: Path = CASES) -> dict[str, Any]:
    cases = load_cases(cases_path)
    saved = (config.DOC_PASSAGE_KNOWLEDGE, config.DOC_MANUAL_CHUNKS, config.RUNS_ROOT)
    clear_store()
    manual_corpus.load.cache_clear() if hasattr(manual_corpus.load, "cache_clear") else None
    config.DOC_PASSAGE_KNOWLEDGE = SYNTHETIC_CORPUS
    rows: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="rag-an-manuals-") as mroot, _ablated(ablate):
            for tool in _MANUALS:
                rows += [evaluate(c, tool, Path(mroot)) for c in cases]
    finally:
        config.DOC_PASSAGE_KNOWLEDGE, config.DOC_MANUAL_CHUNKS, config.RUNS_ROOT = saved
        clear_store()
    return {
        "corpus": "synthetic manuals (samtools, bcftools) + synthetic curated excerpts",
        "ablated": ablate,
        "review": "all cases unreviewed (AI-drafted, provisional)",
        "summary": summarize(rows),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ablate", action="store_true", help="analysis-step command families off (before log 65)")
    parser.add_argument("--json", action="store_true", help="print every run, not only the summary")
    args = parser.parse_args(argv)
    report = run(ablate=args.ablate)
    shown = report if args.json else {k: v for k, v in report.items() if k != "rows"}
    json.dump(shown, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
