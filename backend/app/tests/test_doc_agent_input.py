"""Official-document search results as agent input, and the trace of that (log 27).

No model and no process: the provider is replaced by a Python function that
records the prompt it was handed and returns a fixed answer (the pattern every
synthesis test here uses). Nothing below can tell whether a real model would
read or cite a document; what IS tested is

    search hit -> candidate (selected / not, why) -> placed in the request
    payload -> cited in an answer that passed every gate

and that each of those is stored as what it is. The manual corpus is the
synthetic one from test_doc_search; curated excerpts come from the synthetic
fixture.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from .. import config, db
from ..services.agent.privacy import Redactor
from ..services.doc_search import agent_input, engine, manual_corpus, store
from ..services.explanation import deterministic, run_context
from ..services.explanation.llm import contract, provider, trace
from ..services.explanation.llm import synthesis as llm_synthesis
from .doc_corpus_fixture import synthetic_passages  # noqa: F401  (fixture)
from .test_doc_search import SYNTHETIC_ROWS, _chunk, write_manual
from .test_resource_bundle_diagnosis import RUN_ID, SAMPLE, failed_precheck

VIEW = "COMMANDS AND OPTIONS > bcftools view [ OPTIONS ] file"
# A chunk of ANOTHER command that matches the failure's words far better than
# anything in the view section -- the shape of the noise seen on a real run.
NOISY = _chunk("m#sort#00", "COMMANDS AND OPTIONS > bcftools sort [ OPTIONS ] file.bcf",
               "errno such file directory unavailable errno directory file such unavailable tool vcf")
ROWS = [*SYNTHETIC_ROWS[:6], NOISY]


@pytest.fixture
def manual(tmp_path, monkeypatch):
    manual_corpus.clear_cache()
    path = write_manual(tmp_path, ROWS)
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", str(path))
    yield path
    manual_corpus.clear_cache()


@pytest.fixture
def failed_job(client, make_job, run, manual, synthetic_passages):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    return db.query_one("SELECT * FROM jobs WHERE job_id = ?", (RUN_ID,))


def _tool_input(record):
    return next(i for i in record.inputs if i.kind == "vcf_tool_unavailable")


# --- 1. ranking: the recorded command's section first ------------------------------


def test_fts_candidates_from_the_command_section_come_before_other_commands(failed_job):
    record = engine.run_search(failed_job)
    tool = _tool_input(record)
    manual_hits = [h for h in record.hits if h.input_id == tool.inputId and h.corpus == "manual"]
    relations = [h.relation for h in manual_hits]
    # option lookup first, then the rest of the view section, then the others
    assert manual_hits[0].evidence_id == "manual:m#view#00"
    assert manual_hits[1].evidence_id == "manual:m#view#01"
    assert relations.index("otherCommandSection") > relations.index("sameCommandSection")
    assert all(relations[i] == "sameCommandSection" for i in range(2))
    assert "same command section first" in record.method


# --- 2. which hits become candidates -------------------------------------------------


def test_only_structurally_related_hits_are_candidates(failed_job):
    record = engine.run_search(failed_job)
    built = agent_input.build(record, Redactor())
    by_id = {s.evidence_id: s for s in built.selections}
    assert by_id["manual:m#view#00"].selected is True
    assert by_id["manual:m#view#01"].selected is True
    assert by_id["doc:synthetic-htslib-provides-tabix"].selected is True  # filed under the kind
    assert by_id["manual:m#sort#00"].selected is False
    assert by_id["manual:m#sort#00"].reason == agent_input.REASON_RELATION
    ids = [item["evidenceId"] for item in built.section["items"]]
    assert ids == [s.evidence_id for s in built.selections if s.selected]
    assert len(ids) == len(set(ids))


def test_every_returned_hit_has_exactly_one_decision(failed_job):
    record = engine.run_search(failed_job)
    built = agent_input.build(record, Redactor())
    assert {s.evidence_id for s in built.selections} == {h.evidence_id for h in record.hits}
    assert all(s.reason for s in built.selections if not s.selected)
    assert all(s.reason is None for s in built.selections if s.selected)


def test_the_per_input_and_total_caps_are_reasons_not_silence(failed_job, monkeypatch):
    monkeypatch.setattr(agent_input, "MAX_PER_INPUT", 1)
    record = engine.run_search(failed_job)
    built = agent_input.build(record, Redactor())
    tool = _tool_input(record)
    chosen = [i for i in built.section["items"] if tool.inputId in [f["inputId"] for f in i["forFailures"]]]
    assert len(chosen) == 1
    capped = [s for s in built.selections if s.reason == agent_input.REASON_INPUT_CAP.format(n=1)]
    assert capped


def test_a_text_that_changed_after_the_search_is_not_sent(failed_job, manual):
    record = engine.run_search(failed_job)
    rows = [dict(r) for r in ROWS]
    rows[1] = _chunk("m#view#00", VIEW, "this body is not what the search returned")
    manual_corpus.clear_cache()
    manual.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    built = agent_input.build(record, Redactor())
    view = next(s for s in built.selections if s.evidence_id == "manual:m#view#00")
    assert view.selected is False and view.reason == agent_input.REASON_TEXT_CHANGED
    assert "manual:m#view#00" not in [i["evidenceId"] for i in built.section["items"]]


def test_an_excerpt_holding_a_job_identifier_is_not_sent(failed_job):
    record = engine.run_search(failed_job)
    built = agent_input.build(record, Redactor(literals=(("header", "<x>"),)))
    view = next(s for s in built.selections if s.evidence_id == "manual:m#view#00")
    assert view.selected is False and view.reason == agent_input.REASON_IDENTIFIER


def test_nothing_selected_means_no_section(failed_job, monkeypatch):
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", "")
    monkeypatch.setattr(agent_input, "MAX_TOTAL", 0)
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    assert built.section is None


def test_the_section_separates_run_records_from_documents(failed_job):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    section = built.section
    assert "not records of this run" in section["note"]
    for item in section["items"]:
        assert item["excerpt"]
        assert item["kind"] in ("curatedExcerpt", "toolManual")
        for f in item["forFailures"]:
            assert set(f) == {"inputId", "stepId", "failureKind", "command"}
    dumped = json.dumps(section, ensure_ascii=False)
    assert SAMPLE not in dumped and RUN_ID not in dumped
    assert "queryTerms" not in dumped  # the redacted evidence words stay out of the model input


# --- 3. the payload --------------------------------------------------------------------


@pytest.fixture
def explanation(failed_job):
    context = run_context.build_run_diagnostic_context(RUN_ID)
    return deterministic.build_run_explanation(context)


def test_without_documents_the_payload_is_byte_identical(explanation):
    before, refs = contract.build_payload(explanation)
    after, refs2 = contract.build_payload(explanation, official_docs=None)
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
    assert refs == refs2 and "officialDocs" not in after


def test_selected_documents_become_citable_and_nothing_else(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    payload, refs = contract.build_payload(explanation, official_docs=built.section)
    assert payload["officialDocs"] == built.section
    sent = {i["evidenceId"] for i in built.section["items"]}
    assert sent <= refs
    assert "manual:m#sort#00" not in refs  # returned by the search, not selected


# --- 4. citations ------------------------------------------------------------------------


def _answer(finding_refs, check_refs=("run:status",)):
    return {
        "summary": "실행이 입력 검증에서 멈췄습니다.",
        "importantFindings": [{"statement": "입력 검증 단계에서 실행이 멈췄습니다.", "evidenceRefs": list(finding_refs)}],
        "limitations": [{"statement": "결과 파일은 만들어지지 않았습니다.", "evidenceRefs": ["run:status"]}],
        "nextChecks": [{"statement": "매뉴얼의 헤더 출력 옵션 설명을 확인할 수 있습니다.", "evidenceRefs": list(check_refs)}],
        "uncertainties": [{"statement": "도구 설치 상태는 기록만으로 알 수 없습니다.", "evidenceRefs": ["run:status"]}],
    }


def _fake(answer, seen=None):
    def run(**kwargs):
        if seen is not None:
            seen.append(kwargs["user_prompt"])
        return provider.ProviderResult(payload=answer, models=["stub-not-a-model"])
    return run


def _synth(explanation, section, answer, traces):
    return llm_synthesis.build_run_synthesis(
        explanation, run_provider=_fake(answer), on_trace=traces.append,
        offer_tools=False, repair=False, official_docs=section,
    )


def test_a_cited_selected_document_is_recorded_as_cited(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    result = _synth(explanation, built.section, _answer(["run:status"], ["run:status", "manual:m#view#00"]), traces)
    assert result.available is True
    t = traces[0]
    assert set(t.docEvidenceIds) == {i["evidenceId"] for i in built.section["items"]}
    assert t.citedDocEvidenceIds == ("manual:m#view#00",)


def test_a_returned_but_unselected_document_cannot_be_cited(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    result = _synth(explanation, built.section, _answer(["run:status"], ["run:status", "manual:m#sort#00"]), traces)
    assert result.available is False and result.errorCategory == "unknownEvidenceRef"
    assert traces[0].citedDocEvidenceIds is None  # rejected: no citation is verified


def test_a_document_not_sent_in_this_request_cannot_be_cited(explanation):
    traces = []
    result = _synth(explanation, None, _answer(["run:status"], ["manual:m#view#00"]), traces)
    assert result.errorCategory == "unknownEvidenceRef"
    assert traces[0].docEvidenceIds == () and traces[0].citedDocEvidenceIds is None


def test_a_run_finding_resting_only_on_a_document_is_rejected(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    result = _synth(explanation, built.section, _answer(["manual:m#view#00"]), traces)
    assert result.available is False and result.errorCategory == "docEvidenceMisuse"
    assert result.errorMessage == llm_synthesis._SAFE_MESSAGES["docEvidenceMisuse"]


def test_a_run_finding_may_add_a_document_beside_a_run_record(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    result = _synth(explanation, built.section, _answer(["run:status", "manual:m#view#00"]), traces)
    assert result.available is True
    assert traces[0].citedDocEvidenceIds == ("manual:m#view#00",)


def test_a_knowledge_id_is_not_a_run_record(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    payload, refs = contract.build_payload(explanation, official_docs=built.section)
    knowledge = sorted(r for r in refs if r.split(":")[0] in ("src", "concept", "term"))
    if not knowledge:
        pytest.skip("this explanation carries no knowledge id")
    traces = []
    result = _synth(explanation, built.section, _answer([knowledge[0], "manual:m#view#00"]), traces)
    assert result.errorCategory == "docEvidenceMisuse"


def test_provider_failure_records_what_was_sent_and_no_citation(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []

    def fails(**_):
        raise provider.ProviderError("timeout", "x")
    llm_synthesis.build_run_synthesis(explanation, run_provider=fails, on_trace=traces.append,
                                      offer_tools=False, official_docs=built.section)
    assert traces[0].docEvidenceIds and traces[0].citedDocEvidenceIds is None


# --- 5. the route: search -> payload -> trace link ----------------------------------------


def _run_files(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def stub_provider(monkeypatch):
    seen: list[str] = []
    answer = _answer(["run:status", "manual:m#view#00"], ["run:status", "manual:m#view#00"])
    monkeypatch.setattr(llm_synthesis.provider, "run_structured", _fake(answer, seen))
    return seen


def test_flag_off_keeps_the_route_exactly_as_before(client, failed_job, stub_provider, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", False)
    r = client.post(f"/api/jobs/{RUN_ID}/synthesis")
    assert r.status_code == 200
    assert "officialDocs" not in stub_provider[0]
    assert db.query_one("SELECT COUNT(*) AS n FROM doc_search_runs")["n"] == 0
    assert db.query_one("SELECT COUNT(*) AS n FROM agent_doc_evidence")["n"] == 0


def test_flag_on_links_search_payload_and_citation(client, failed_job, stub_provider, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)
    run_dir = Path(failed_job["run_dir"])
    before = _run_files(run_dir)
    r = client.post(f"/api/jobs/{RUN_ID}/synthesis")
    assert r.status_code == 200 and r.json()["available"] is True
    assert '"officialDocs"' in stub_provider[0] and "manual:m#view#00" in stub_provider[0]
    assert "manual:m#sort#00" not in stub_provider[0]
    assert _run_files(run_dir) == before  # the run's own files are untouched

    runs = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"]
    assert len(runs) == 1 and runs[0]["purpose"] == "agentRequest"
    agent = runs[0]["agentRequest"]
    assert agent["outcome"] == "answerServed" and agent["citedCount"] == 1
    usage = {h["evidenceId"]: h["usage"] for h in runs[0]["hits"]}
    assert usage["manual:m#view#00"] == {
        "returnedBySearch": True, "selectedForAgent": True, "selectionReason": None,
        "inAgentInput": True, "readByModel": None, "citedInAnswer": True}
    assert usage["manual:m#sort#00"]["selectedForAgent"] is False
    assert usage["manual:m#sort#00"]["inAgentInput"] is False
    assert usage["manual:m#sort#00"]["citedInAnswer"] is False
    assert usage["manual:m#view#01"]["citedInAnswer"] is False
    assert all(u["readByModel"] is None for u in usage.values())


def test_a_rejected_answer_leaves_citations_unknown(client, failed_job, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)
    monkeypatch.setattr(llm_synthesis.provider, "run_structured",
                        _fake(_answer(["manual:m#view#00"])))
    monkeypatch.setattr(config, "SYNTHESIS_REPAIR", False)
    r = client.post(f"/api/jobs/{RUN_ID}/synthesis")
    assert r.json()["errorCategory"] == "docEvidenceMisuse"
    run = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]
    assert run["agentRequest"]["outcome"] == "answerRejected"
    assert run["agentRequest"]["citedCount"] is None
    assert all(h["usage"]["citedInAnswer"] is None for h in run["hits"])
    assert any(h["usage"]["inAgentInput"] for h in run["hits"])


def test_a_provider_failure_is_no_answer(client, failed_job, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)

    def fails(**_):
        raise provider.ProviderError("usageLimit", "x")
    monkeypatch.setattr(llm_synthesis.provider, "run_structured", fails)
    client.post(f"/api/jobs/{RUN_ID}/synthesis")
    run = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]
    assert run["agentRequest"]["outcome"] == "noAnswer"
    assert run["agentRequest"]["errorCategory"] == "usageLimit"


def test_a_failed_search_falls_back_to_the_existing_request(client, failed_job, stub_provider, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)

    def broken(*a, **k):
        raise RuntimeError("index exploded")
    monkeypatch.setattr(engine, "run_search", broken)
    monkeypatch.setattr(llm_synthesis.provider, "run_structured",
                        _fake(_answer(["run:status"]), stub_provider))
    r = client.post(f"/api/jobs/{RUN_ID}/synthesis")
    assert r.status_code == 200 and r.json()["available"] is True
    assert "officialDocs" not in stub_provider[-1]
    assert db.query_one("SELECT COUNT(*) AS n FROM agent_doc_evidence")["n"] == 0


def test_a_search_with_nothing_to_send_still_answers(client, failed_job, stub_provider, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)
    monkeypatch.setattr(agent_input, "MAX_TOTAL", 0)
    monkeypatch.setattr(llm_synthesis.provider, "run_structured",
                        _fake(_answer(["run:status"]), stub_provider))
    assert client.post(f"/api/jobs/{RUN_ID}/synthesis").json()["available"] is True
    assert "officialDocs" not in stub_provider[-1]
    run = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]
    assert run["agentRequest"]["inPayloadCount"] == 0
    assert all(h["usage"]["inAgentInput"] is False for h in run["hits"])


def test_stored_links_hold_ids_and_decisions_only(client, failed_job, stub_provider, monkeypatch):
    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)
    client.post(f"/api/jobs/{RUN_ID}/synthesis")
    rows = [dict(r) for r in db.connect().execute("SELECT * FROM agent_doc_evidence")]
    assert rows
    dumped = json.dumps(rows, ensure_ascii=False)
    assert SAMPLE not in dumped and RUN_ID not in dumped and "/srv/" not in dumped
    assert "header" not in dumped  # no excerpt text
    assert set(rows[0]) == {"trace_id", "search_id", "evidence_id", "selected",
                            "selection_reason", "in_payload", "cited"}


def test_a_user_search_says_no_agent_request(client, failed_job):
    client.post(f"/api/jobs/{RUN_ID}/doc-search")
    run = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]
    assert run["purpose"] == "userRequest" and run["agentRequest"] is None
    for h in run["hits"]:
        assert h["usage"]["selectedForAgent"] is None and h["usage"]["inAgentInput"] is None


def test_an_old_database_gains_the_link_table_and_purpose_column(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE doc_search_runs (search_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, created_at TEXT NOT NULL,"
        " method TEXT NOT NULL, duration_ms INTEGER, corpora TEXT NOT NULL, inputs TEXT NOT NULL,"
        " excluded TEXT NOT NULL, result_count INTEGER NOT NULL, error_category TEXT,"
        " model_called INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO doc_search_runs VALUES ('s1','j','2026-11-18','m',1,'[]','[]','[]',0,NULL,0);"
    )
    old.commit()
    old.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    previous, db._conn = db._conn, None
    try:
        conn = db.connect()
        assert conn.execute("SELECT purpose FROM doc_search_runs WHERE search_id='s1'").fetchone()[0] is None
        assert conn.execute("SELECT COUNT(*) FROM agent_doc_evidence").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM doc_search_runs").fetchone()[0] == 1
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous


# --- log 28: gate 8 against answers a real model actually wrote -------------
_EVALS = Path(__file__).resolve().parents[2] / "evals"
_RECORDED = sorted((_EVALS / "baselines").glob("*.json")) + sorted(
    (_EVALS / "experiments" / "ab_2026-11-04").glob("[AB]_r*.json")
)


def _answers(node):
    if isinstance(node, dict):
        if isinstance(node.get("importantFindings"), list):
            yield node
        for value in node.values():
            yield from _answers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _answers(value)


def test_gate_8_rejects_no_recorded_real_answer():
    # Gate 8 also covers the older WES_DOC_RAG doc: path. The recorded real
    # answers (read, never written) cite no document, so this pins the
    # baseline: the new gate must not discard an answer that was served
    # before it existed. It says nothing about answers that DO cite documents
    # -- none exist yet, that needs the approved real-model run.
    answers = [a for f in _RECORDED for a in _answers(json.loads(f.read_text(encoding="utf-8")))]
    assert answers, "the recorded answers moved; this check would pass vacuously"
    from ..services.explanation.llm import doc_citations

    assert [doc_citations.find_doc_only_findings(a) for a in answers if doc_citations.find_doc_only_findings(a)] == []


def test_the_ids_sent_are_exactly_the_ids_recorded_as_sent(client, failed_job, stub_provider, monkeypatch):
    # Not "the expected ids are there": the SET of document ids in the prompt
    # the provider received equals the set the search record says went in, and
    # nothing the record calls left out reached the prompt.
    import re

    monkeypatch.setattr(config, "AGENT_DOC_EVIDENCE", True)
    assert client.post(f"/api/jobs/{RUN_ID}/synthesis").status_code == 200
    sent = set(re.findall(r'"evidenceId":\s*"((?:doc|manual):[^"]+)"', stub_provider[0]))
    hits = client.get(f"/api/jobs/{RUN_ID}/doc-search").json()["runs"][0]["hits"]
    recorded_in = {h["evidenceId"] for h in hits if h["usage"]["inAgentInput"]}
    recorded_out = {h["evidenceId"] for h in hits if h["usage"]["inAgentInput"] is False}
    assert sent and sent == recorded_in
    assert not sent & recorded_out
    assert recorded_in <= {h["evidenceId"] for h in hits}  # nothing sent that the search did not return


# --- log 29: gate 8 also covers limitations ------------------------------------


def _answer_with(**groups):
    """_answer() with some groups' refs replaced: group name -> list of refs."""
    answer = _answer(["run:status"], ["run:status"])
    for group, refs in groups.items():
        answer[group][0]["evidenceRefs"] = list(refs)
    return answer


def test_a_run_limitation_resting_only_on_a_document_is_rejected(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    result = _synth(explanation, built.section, _answer_with(limitations=["manual:m#view#00"]), traces)
    assert result.available is False and result.errorCategory == "docEvidenceMisuse"
    assert traces[0].citedDocEvidenceIds is None


def test_a_limitation_may_add_a_document_beside_a_run_record(failed_job, explanation):
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    answer = _answer_with(limitations=["run:status", "manual:m#view#00"])
    result = _synth(explanation, built.section, answer, traces)
    assert result.available is True
    assert traces[0].citedDocEvidenceIds == ("manual:m#view#00",)


def test_general_document_statements_stay_allowed_in_next_checks_and_uncertainties(failed_job, explanation):
    """The general-knowledge groups are not tightened: a document may stand alone there."""
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    answer = _answer_with(nextChecks=["manual:m#view#00"], uncertainties=["manual:m#view#00"])
    result = _synth(explanation, built.section, answer, traces)
    assert result.available is True
    assert traces[0].citedDocEvidenceIds == ("manual:m#view#00",)


def test_gate_order_is_unchanged_an_unsupplied_id_is_still_gate_3(failed_job, explanation):
    """A document-only limitation citing an id this request did not carry fails both
    gate 3 and gate 8; the reported category stays the earlier gate's."""
    built = agent_input.build(engine.run_search(failed_job), Redactor())
    traces = []
    result = _synth(explanation, built.section, _answer_with(limitations=["manual:m#sort#00"]), traces)
    assert result.errorCategory == "unknownEvidenceRef"


def test_gate_8_names_the_limitation_it_rejects():
    from ..services.explanation.llm import doc_citations
    answer = _answer_with(limitations=["manual:x"], importantFindings=["doc:y"])
    found = doc_citations.find_doc_only_findings(answer)
    assert [f["location"] for f in found] == ["importantFindings.0", "limitations.0"]
    assert doc_citations.find_doc_only_findings(_answer_with(nextChecks=["manual:x"])) == []
