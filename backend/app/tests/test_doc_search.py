"""Official-document search on the run page (development log 26).

No downloaded text is a test dependency: the manual corpus below is SYNTHETIC
text written for these tests (same JSONL shape as the wes-rag-lab chunks), and
the curated excerpts come from fixtures/doc_passages.synthetic.json.

Nothing here can reach a model: the package never imports the LLM provider
(asserted statically), and the API tests make process creation raise.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from .. import config, db
from ..services.doc_search import commands, engine, manual_corpus, store
from .doc_corpus_fixture import synthetic_passages  # noqa: F401  (fixture)
from .test_resource_bundle_diagnosis import RUN_ID, SAMPLE, failed_precheck

SNAP = "a" * 64
BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent


def _chunk(cid, context, body, *, snapshot=SNAP, bad_hash=False):
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return {
        "chunk_id": cid, "source_id": "bcftools-manual", "source_sha256": snapshot,
        "anchor": cid.split("#")[1], "url": f"https://example.invalid/manual.html#{cid.split('#')[1]}",
        "context": context, "body": body, "block_ids": [0], "kinds": ["paragraph"],
        "split_block": False, "body_sha256": ("0" * 64 if bad_hash else digest),
        "search_text": f"{context}\n{body}",
    }


# Synthetic: invented wording, only the SHAPE of a manual.
SYNTHETIC_ROWS = [
    _chunk("m#intro#00", "DESCRIPTION", "The toolkit reads variant files; indexed files work everywhere."),
    _chunk("m#view#00", "COMMANDS AND OPTIONS > bcftools view [ OPTIONS ] file",
           "-h, --header-only print only the header of the variant file\n-H, --no-header omit the header"),
    _chunk("m#view#01", "COMMANDS AND OPTIONS > bcftools view [ OPTIONS ] file",
           "view converts between formats and subsets records by region."),
    _chunk("m#head#00", "COMMANDS AND OPTIONS > bcftools head [ OPTIONS ] [ FILE ]",
           "-h, --header-only is listed here too, but for a different command."),
    _chunk("m#index#00", "COMMANDS AND OPTIONS > bcftools index [ OPTIONS ] file",
           "index creates an index for a compressed variant file; header lines are read first."),
    _chunk("m#common#00", "COMMANDS AND OPTIONS > Common Options",
           "Options shared by every command: threads, output type, header handling."),
    _chunk("m#bad#00", "COMMANDS AND OPTIONS > bcftools view [ OPTIONS ] file",
           "this body was altered after hashing", bad_hash=True),
    _chunk("m#other#00", "DESCRIPTION", "from another snapshot", snapshot="b" * 64),
]


def write_manual(tmp_path: Path, rows=SYNTHETIC_ROWS, title="bcftools(1)") -> Path:
    path = tmp_path / "manual" / f"{SNAP}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (path.parent / f"{SNAP}.meta.json").write_text(
        json.dumps({"title": title, "version_text": "synthetic manual for tests"}), encoding="utf-8")
    return path


@pytest.fixture
def manual(tmp_path, monkeypatch):
    manual_corpus.clear_cache()
    path = write_manual(tmp_path)
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", str(path))
    yield path
    manual_corpus.clear_cache()


@pytest.fixture
def no_process(monkeypatch):
    """Any process creation during the request fails the test."""
    def refuse(*a, **k):
        raise AssertionError("document search must not start a process")
    monkeypatch.setattr(subprocess, "Popen", refuse)


def search(client, job=RUN_ID):
    r = client.post(f"/api/jobs/{job}/doc-search")
    assert r.status_code == 200, r.text
    return r.json()


# --- provenance of the pieces ------------------------------------------------


def test_the_package_never_imports_the_model_path():
    pkg = BACKEND / "app" / "services" / "doc_search"
    sources = [p.read_text(encoding="utf-8") for p in pkg.glob("*.py")]
    sources.append((BACKEND / "app" / "api" / "doc_search.py").read_text(encoding="utf-8"))
    for text in sources:
        assert "explanation.llm" not in text and "provider" not in text.split('"""', 2)[-1]
        assert "import subprocess" not in text


@pytest.mark.parametrize("rule_id", sorted(commands.RULE_COMMANDS))
def test_each_rule_command_is_the_one_main_sh_runs(rule_id):
    """The mapping is a fact about the pipeline code; it must not drift from it."""
    cmd = commands.RULE_COMMANDS[rule_id]
    main_sh = (REPO / "script" / "main.sh").read_text(encoding="utf-8")
    words = [cmd.tool] + ([cmd.subcommand] if cmd.subcommand else []) + [cmd.options[0]]
    assert "[" + ", ".join(f'"{w}"' for w in words) in main_sh


@pytest.mark.parametrize(
    "check, shell",
    [
        ("vcf_parse_x.vcf.gz", 'bcftools view -h "$vcf"'),
        ("vcf_index_x.vcf.gz", 'tabix -l "$vcf"'),
        ("vcf_sample", 'bcftools query -l "$RAW_VCF"'),
        ("raw_vcf_records", 'bcftools view -H "$RAW_VCF"'),
        ("raw_vcf_ref_match", 'bcftools norm -f "$REF_FASTA" -c e'),
        ("BCFTOOLS_STATS_FAILED", 'bcftools stats "$RAW_VCF"'),
    ],
)
def test_each_check_family_command_is_in_main_sh(check, shell):
    family, cmd = commands.for_check(check)
    main_sh = (REPO / "script" / "main.sh").read_text(encoding="utf-8")
    assert shell in main_sh
    assert shell.startswith(cmd.display().split(" -")[0])
    assert SAMPLE not in family and "." not in family


def test_checks_that_run_no_command_have_none():
    for name in ("required_tools", "resource_bundle", "MULTIQC_MISSING", "DBSNP_NOT_CONFIGURED"):
        assert commands.for_check(name) is None
    assert commands.for_rule("R-VCF-INDEX") is None  # a file-existence test
    assert commands.for_rule(None) is None


# --- the manual corpus ----------------------------------------------------------


def test_manual_corpus_checks_every_hash_and_snapshot(manual):
    corpus = manual_corpus.load(manual)
    assert corpus.tool == "bcftools"
    assert corpus.source_sha256 == SNAP
    assert len(corpus.order) == 6
    assert corpus.excluded == 2  # altered body + other snapshot
    assert "m#bad#00" not in corpus.chunks and "m#other#00" not in corpus.chunks


def test_sections_are_read_from_the_manual_heading_path(manual):
    corpus = manual_corpus.load(manual)
    assert corpus.chunks["m#view#00"].section_command == "view"
    assert corpus.chunks["m#head#00"].section_command == "head"
    assert corpus.chunks["m#common#00"].section_command is None
    assert corpus.chunks["m#intro#00"].section_command is None


def test_option_lookup_stays_inside_the_command_section(manual):
    corpus = manual_corpus.load(manual)
    # `head` lists the same option; it is a different command, so not returned.
    assert corpus.option_lookup("view", ("-h", "--header-only")) == ["m#view#00"]
    assert corpus.option_lookup("view", ("-x",)) == []
    assert corpus.option_lookup("view", ()) == []


def test_fts_query_is_data_not_syntax(manual):
    corpus = manual_corpus.load(manual)
    assert corpus.search(['NEAR("a" b)', "header*", "OR"], 5)  # no FTS error, plain words
    assert corpus.search([], 5) == []


def test_unreadable_or_missing_manual_raises_a_typed_error(tmp_path):
    manual_corpus.clear_cache()
    with pytest.raises(manual_corpus.ManualCorpusError):
        manual_corpus.load(tmp_path / "absent.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    with pytest.raises(manual_corpus.ManualCorpusError) as caught:
        manual_corpus.load(bad)
    assert str(tmp_path) not in str(caught.value)  # no path in the message
    assert manual_corpus.load(None) is None


# --- inputs from the run ----------------------------------------------------------


def test_inputs_come_from_the_recorded_causes(client, make_job, run, manual, synthetic_passages, no_process):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    by_kind = {}
    for item in body["inputs"]:
        by_kind.setdefault(item["kind"], []).append(item)
    assert set(by_kind) == {"resource_missing_or_empty", "vcf_tool_unavailable", "unknown"}
    tool_input = by_kind["vcf_tool_unavailable"][0]
    assert tool_input["tool"] == "bcftools" and tool_input["ruleId"] == "R-VCF-TOOL-B"
    assert tool_input["command"]["display"] == "bcftools view -h"
    assert "main.sh" in tool_input["command"]["recordedBy"]
    assert {"bcftools", "view"} <= set(tool_input["queryTerms"])
    # required_tools ran no tool command: not a query, and the reason is kept.
    assert [e["kind"] for e in body["excludedObservations"]] == ["required_tools"]
    assert body["excludedObservations"][0]["reason"]


def test_query_terms_never_carry_a_path_or_the_sample(client, make_job, run, manual, synthetic_passages):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    terms = [t for i in body["inputs"] for t in i["queryTerms"]]
    joined = " ".join(terms).lower()
    assert SAMPLE.lower() not in joined and "patient" not in joined
    assert not any(re.search(r"[\\/:]", t) for t in terms)
    for word in ("srv", "wes", "known", "indels", "targets"):  # path pieces of the raw sentences
        assert word not in terms


def test_identical_causes_become_one_input_with_a_count(client, make_job, run, manual, synthetic_passages):
    report = "\n".join([
        "[ERROR] Resource bundle validation failed:",
        "  - bcftools unavailable for /a/x.vcf.gz: [Errno 2] No such file or directory: 'bcftools'",
        "  - bcftools unavailable for /b/y.vcf.gz: [Errno 2] No such file or directory: 'bcftools'",
    ]) + "\n"
    failed_precheck(run, report=report)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    assert len(body["inputs"]) == 1 and body["inputs"][0]["occurrences"] == 2


def test_labelled_check_names_keep_only_the_family(client, make_job, run, manual, synthetic_passages):
    builder = run(RUN_ID)
    builder.step("06_variant_calling", status="failed", checks=[
        {"name": f"vcf_parse_{SAMPLE}.raw.vcf.gz", "status": "FAIL", "detail": f"{SAMPLE} cannot parse"},
        {"name": f"custom_{SAMPLE}", "status": "FAIL", "detail": "x"},
    ], failures=[{"code": "vcf_parse", "message": "x"}])
    builder.run_status("failed", current_step="06_variant_calling", steps=[])
    make_job(RUN_ID, sample_id=SAMPLE, run_mode="full", planned=["06_variant_calling"])
    body = search(client)
    assert SAMPLE not in json.dumps(body)
    assert body["inputs"][0]["kind"] == "vcf_parse"
    assert body["inputs"][0]["command"]["display"] == "bcftools view -h"
    assert body["excludedObservations"][0]["kind"] == "<withheld>"


# --- hits and their relation ---------------------------------------------------------


def test_hits_carry_structural_relations_and_no_score(client, make_job, run, manual, synthetic_passages):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    tool_id = next(i["inputId"] for i in body["inputs"] if i["kind"] == "vcf_tool_unavailable")
    manual_hits = [h for h in body["hits"] if h["inputId"] == tool_id and h["corpus"] == "manual"]
    assert manual_hits[0]["evidenceId"] == "manual:m#view#00"
    assert manual_hits[0]["relation"] == "sameCommandSection"
    assert "optionLookup" in manual_hits[0]["matchedBy"]
    assert [h["rank"] for h in manual_hits] == list(range(1, len(manual_hits) + 1))
    ids = [h["evidenceId"] for h in manual_hits]
    assert len(ids) == len(set(ids))  # one hit per chunk even when two paths found it
    for h in manual_hits:
        assert h["relation"] in {"sameCommandSection", "otherCommandSection", "generalSection"}
        assert h["sourceMatches"] is True and h["excerpt"]
    # `method` names the ordering ("FTS5 bm25"); no number from it is exposed.
    fields = {k.lower() for h in body["hits"] for k in h} | {k.lower() for i in body["inputs"] for k in i}
    assert not any(w in f for f in fields for w in ("score", "confidence", "bm25", "probab"))
    assert not re.search(r"\d\.\d{3,}", json.dumps(body["hits"]))
    curated = [h for h in body["hits"] if h["corpus"] == "curated"]
    assert [h["evidenceId"] for h in curated] == ["doc:synthetic-htslib-provides-tabix"]
    assert curated[0]["relation"] == "filedUnderCauseKind" and curated[0]["checkedOn"]


def test_usage_says_returned_and_nothing_else(client, make_job, run, manual, synthetic_passages):
    # A search from the run page: only "returned" is known. The agent-side
    # fields (log 27) exist in the contract and stay null here.
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    assert body["modelCalled"] is False
    assert body["purpose"] == "userRequest" and body["agentRequest"] is None
    assert body["hits"]
    for h in body["hits"]:
        assert h["usage"] == {"returnedBySearch": True, "selectedForAgent": None,
                              "selectionReason": None, "inAgentInput": None,
                              "readByModel": None, "citedInAnswer": None}


def test_corpora_that_do_not_apply_are_skipped_with_a_reason(client, make_job, run, manual, synthetic_passages):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    missing = next(i for i in body["inputs"] if i["kind"] == "resource_missing_or_empty")
    reasons = {s["corpus"]: s["reason"] for s in missing["skipped"]}
    assert set(reasons) == {"curated", "manual"}  # not filed; no tool recorded
    assert not [h for h in body["hits"] if h["inputId"] == missing["inputId"]]


def test_a_tool_the_manual_does_not_cover_is_not_searched(client, make_job, run, manual, synthetic_passages):
    report = "[ERROR] Resource bundle validation failed:\n  - cannot read tabix contig list: /a/x.vcf.gz\n"
    failed_precheck(run, report=report)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    item = body["inputs"][0]
    assert item["tool"] == "tabix" and item["command"]["display"] == "tabix -l"
    assert any(s["corpus"] == "manual" and "tabix" in s["reason"] for s in item["skipped"])
    assert not [h for h in body["hits"] if h["corpus"] == "manual"]


def test_without_a_manual_the_corpus_is_reported_unavailable(client, make_job, run, synthetic_passages, monkeypatch):
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", "")
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    info = {c["corpusId"]: c for c in body["corpora"]}
    assert info["manual"]["available"] is False and info["manual"]["note"]
    assert info["curated"]["available"] is True
    assert body["errorCategory"] is None
    assert not [h for h in body["hits"] if h["corpus"] == "manual"]


def test_no_corpus_at_all_is_an_error_category(client, make_job, run, monkeypatch):
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", "")
    monkeypatch.setattr(engine, "_curated_info", lambda: (engine.CorpusInfo(
        corpusId="curated", title="t", available=False, officialStatus="s", note="n"), False))
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    body = search(client)
    assert body["errorCategory"] == "noCorpusAvailable" and body["errorMessage"]
    assert body["hits"] == []


def test_a_run_with_nothing_searchable_is_an_empty_result(client, make_job, run, manual, synthetic_passages):
    builder = run(RUN_ID)
    builder.step("06_variant_calling", status="warning", checks=[
        {"name": "DBSNP_NOT_CONFIGURED", "status": "WARN", "detail": "no dbSNP"}])
    builder.run_status("succeeded", current_step=None, steps=[])
    make_job(RUN_ID, sample_id=SAMPLE, run_mode="full", planned=["06_variant_calling"])
    body = search(client)
    assert body["inputs"] == [] and body["hits"] == [] and body["errorCategory"] is None
    assert body["excludedObservations"][0]["kind"] == "DBSNP_NOT_CONFIGURED"


def test_unreadable_run_records_are_reported_not_raised(client, make_job, run, manual, monkeypatch):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)

    def broken(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(engine.step_reader, "read", broken)
    body = search(client)
    assert body["errorCategory"] == "runRecordUnreadable" and body["errorMessage"]


# --- trace storage ---------------------------------------------------------------------


def test_the_trace_is_stored_and_read_back(client, make_job, run, manual, synthetic_passages):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    first = search(client)
    second = search(client)
    listed = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"]
    assert [r["searchId"] for r in listed] == [second["searchId"], first["searchId"]]
    assert listed[1] == first  # what POST returned is exactly what was stored
    row = db.query_one("SELECT model_called, result_count FROM doc_search_runs WHERE search_id = ?",
                       (first["searchId"],))
    assert row["model_called"] == 0 and row["result_count"] == len(first["hits"])


def test_nothing_identifying_is_stored(client, make_job, run, manual, synthetic_passages):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    search(client)
    conn = db.connect()
    dumped = json.dumps([list(r) for t in ("doc_search_runs", "doc_search_hits")
                         for r in conn.execute(f"SELECT * FROM {t}")], ensure_ascii=False)
    # job_id is the internal link column; check everything else.
    dumped = dumped.replace(json.dumps(RUN_ID)[1:-1], "", -1)
    assert SAMPLE not in dumped and "PATIENT" not in dumped
    assert "/srv/" not in dumped and "C:\\\\wes" not in dumped and "Errno" not in dumped
    response = client.get(f"/api/jobs/{RUN_ID}/doc-search").text
    assert RUN_ID not in response and SAMPLE not in response


def test_a_changed_or_removed_corpus_is_visible_on_old_traces(client, make_job, run, manual, synthetic_passages, monkeypatch, tmp_path):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    search(client)
    rows = [dict(r) for r in SYNTHETIC_ROWS[:6]]
    rows[1] = _chunk("m#view#00", rows[1]["context"], "the text of this section was revised")
    manual_corpus.clear_cache()
    manual.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    hits = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]["hits"]
    view = next(h for h in hits if h["evidenceId"] == "manual:m#view#00")
    assert view["sourceMatches"] is False
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", "")
    hits = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]["hits"]
    view = next(h for h in hits if h["evidenceId"] == "manual:m#view#00")
    assert view["sourceMatches"] is None and view["excerpt"] is None


def test_a_search_that_cannot_be_stored_is_not_returned(client, make_job, run, manual, synthetic_passages, monkeypatch):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)

    def fail(*a, **k):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(store, "save", fail)
    r = client.post(f"/api/jobs/{RUN_ID}/doc-search")
    assert r.status_code == 500 and r.json()["detail"]["code"] == "searchNotRecorded"


def test_missing_and_malformed_jobs(client, env):
    assert client.get("/api/jobs/wes-20990101-000000-abcdef/doc-search").status_code == 404
    assert client.post("/api/jobs/wes-20990101-000000-abcdef/doc-search").status_code == 404
    assert client.post("/api/jobs/not%20a%20job/doc-search").status_code == 400


def test_get_for_a_job_never_searched_is_empty(client, make_job, run):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    assert client.get(f"/api/jobs/{RUN_ID}/doc-search").json() == {"runs": []}


def test_an_existing_database_gains_the_tables_and_keeps_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE synthesis_traces (trace_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, created_at TEXT NOT NULL, "
        "models TEXT NOT NULL, duration_ms INTEGER, num_turns INTEGER, opened_step_ids TEXT NOT NULL, "
        "available INTEGER NOT NULL, error_category TEXT);"
        "INSERT INTO synthesis_traces VALUES ('t1','j','2026-11-01','[]',1,1,'[]',1,NULL);"
    )
    old.commit()
    old.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    previous, db._conn = db._conn, None
    try:
        conn = db.connect()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"doc_search_runs", "doc_search_hits"} <= tables
        assert conn.execute("SELECT COUNT(*) FROM synthesis_traces").fetchone()[0] == 1
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous
