"""Stored AI explanations (development log 66).

Until now a served explanation lived only in the browser tab that asked for it.
This stores the ones that passed every gate, as numbered versions per run, so a
reload shows the latest and the history stays readable.

What these tests pin:
  * storing is OFF unless WES_SYNTHESIS_STORE_ANSWERS=1 -- the retention policy
    is a user decision not yet made, so nothing is kept by default;
  * only a served (gate-passed) answer is stored; a rejection or a provider
    failure leaves no body anywhere;
  * a new request is a new version: v1 is never overwritten, v2 supersedes it;
  * the body is re-checked for the run's identifiers and path shapes right
    before the insert, and refused (with the reason on the trace) if any remain;
  * a version remembers the hash of the input it was built from and of the run
    record it described, so a later record change is flagged, not hidden;
  * deleting a version clears its body and keeps the hashes; numbers are not
    reused;
  * the existing database keeps every row when the table is added.

No model is called: the provider is the fake from test_tool_using_synthesis.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from .. import config, db
from ..services.explanation import run_context
from ..services.explanation.llm import answers, contract, trace
from ..services.explanation.llm import synthesis as llm_synthesis
from ..services.explanation.llm.synthesis import SynthesisProvenance, SynthesisResult
from .test_tool_using_synthesis import FULL_PLAN, JOB_ID, _answer, provider_that

SAMPLE = "DEMO01"
GOOD = _answer("경고가 기록되었습니다.", "run:status")


@pytest.fixture
def finished(client, make_job, run):
    job = make_job(JOB_ID, run_mode="full", planned=FULL_PLAN, sample_id=SAMPLE)
    builder = run(job)
    builder.as_completed_full()
    return builder


@pytest.fixture
def storing(monkeypatch):
    monkeypatch.setattr(config, "SYNTHESIS_STORE_ANSWERS", True)


def _post(client, monkeypatch, answer=GOOD):
    monkeypatch.setattr(llm_synthesis.provider, "run_structured", provider_that(answer))
    response = client.post(f"/api/jobs/{JOB_ID}/synthesis")
    assert response.status_code == 200, response.text
    return response.json()


def _list(client):
    response = client.get(f"/api/jobs/{JOB_ID}/synthesis/answers")
    assert response.status_code == 200, response.text
    return response.json()


def _rows():
    return db.query_all("SELECT * FROM synthesis_answers ORDER BY version")


# --- off by default ------------------------------------------------------------


def test_nothing_is_stored_while_the_policy_is_undecided(client, finished, monkeypatch):
    assert config.SYNTHESIS_STORE_ANSWERS is False
    assert _post(client, monkeypatch)["available"] is True
    assert _rows() == []
    body = _list(client)
    assert body == {"storing": False, "latestVersion": None, "versions": []}


# --- what is stored --------------------------------------------------------------


def test_the_response_names_the_version_it_became(client, finished, monkeypatch, storing):
    assert _post(client, monkeypatch)["storedVersion"] == 1
    assert _post(client, monkeypatch)["storedVersion"] == 2
    rejected = _post(client, monkeypatch, _answer("이 단계는 987654초가 걸렸습니다.", "run:status"))
    assert rejected["storedVersion"] is None


def test_with_storing_off_the_response_names_no_version(client, finished, monkeypatch):
    assert _post(client, monkeypatch)["storedVersion"] is None


def test_a_served_answer_becomes_version_1(client, finished, monkeypatch, storing):
    served = _post(client, monkeypatch)
    [row] = _rows()
    assert row["version"] == 1 and row["supersedes"] is None and row["status"] == "served"
    assert json.loads(row["body_json"]) == served["synthesis"]
    assert row["contract_version"] == answers.CONTRACT_VERSION
    assert len(row["input_sha256"]) == 64 and len(row["run_record_sha256"]) == 64
    # 1:1 with the trace of the attempt that produced it.
    [t] = trace.recent(JOB_ID)
    assert row["trace_id"] == t["traceId"]
    assert db.query_one("SELECT answer_store FROM synthesis_traces")["answer_store"] == "stored"


def test_a_second_request_is_a_new_version_and_the_first_is_untouched(
        client, finished, monkeypatch, storing):
    _post(client, monkeypatch)
    first = dict(_rows()[0])
    _post(client, monkeypatch, _answer("두 번째 설명입니다.", "run:status"))
    v1, v2 = _rows()
    assert dict(v1) == first
    assert v2["version"] == 2 and v2["supersedes"] == v1["answer_id"]
    listing = _list(client)
    assert listing["storing"] is True and listing["latestVersion"] == 2
    assert [v["version"] for v in listing["versions"]] == [2, 1]
    assert listing["versions"][0]["supersedesVersion"] == 1
    # same run record, same input: neither flag is raised.
    assert listing["versions"][0]["inputChangedFromPrevious"] is False
    assert all(v["recordChanged"] is False for v in listing["versions"])


def test_a_rejected_answer_stores_no_body(client, finished, monkeypatch, storing):
    result = _post(client, monkeypatch, _answer("이 단계는 987654초가 걸렸습니다.", "run:status"))
    assert result["available"] is False
    assert _rows() == []
    assert db.query_one("SELECT answer_store FROM synthesis_traces")["answer_store"] is None


def test_a_provider_failure_stores_nothing(client, finished, monkeypatch, storing):
    def failing(**_kwargs):
        raise llm_synthesis.provider.ProviderError("timeout", "boom")

    monkeypatch.setattr(llm_synthesis.provider, "run_structured", failing)
    assert client.post(f"/api/jobs/{JOB_ID}/synthesis").json()["available"] is False
    assert _rows() == []


def test_the_unique_version_constraint_exists(client, finished, monkeypatch, storing):
    _post(client, monkeypatch)
    row = dict(_rows()[0])
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO synthesis_answers (answer_id, trace_id, job_id, version, created_at, models,"
            " contract_version, input_sha256, run_record_sha256, provenance_json, body_json, status)"
            " VALUES ('a_dup','t_dup',?,1,'x','[]','c','i','r','{}','{}','served')",
            (row["job_id"],),
        )


# --- the re-check right before the insert --------------------------------------


def _served(statement: str) -> SynthesisResult:
    return SynthesisResult(
        available=True,
        synthesis=contract.RunSynthesis(**_answer(statement, "run:status")),
        provenance=SynthesisProvenance(
            models=["test-model"], generatedAt="2026-11-23T00:00:00+00:00",
            contextKind="completedFull", runStatus="completed"),
    )


def _store(finished, result):
    t = trace.SynthesisTrace(models=("test-model",), available=True, inputSha256="0" * 64)
    trace_id = trace.record(JOB_ID, t)
    context = run_context.build_run_diagnostic_context(JOB_ID)
    redactor = answers.redactor_for(context)
    return trace_id, answers.store(
        JOB_ID, trace_id, result, t, redactor=redactor,
        run_record_sha256=answers.record_digest(context), doc_search_id=None)


@pytest.mark.parametrize("statement", [
    f"{SAMPLE} 샘플의 경고가 기록되었습니다.",
    "결과는 /home/user/runs/out.vcf.gz 에 있습니다.",
    "체크섬은 " + "ab12" * 16 + " 입니다.",
])
def test_a_body_that_still_carries_an_identifier_or_a_path_is_refused(
        client, finished, storing, statement):
    trace_id, outcome = _store(finished, _served(statement))
    assert outcome == "refusedSensitive"
    assert _rows() == []
    row = db.query_one("SELECT answer_store FROM synthesis_traces WHERE trace_id = ?", (trace_id,))
    assert row["answer_store"] == "refusedSensitive"


def test_a_clean_body_passes_the_re_check(client, finished, storing):
    _, outcome = _store(finished, _served("경고가 기록되었습니다."))
    assert outcome == "stored"


# --- reading versions back -------------------------------------------------------


def test_a_version_reads_back_with_its_provenance_and_no_internal_ids(
        client, finished, monkeypatch, storing):
    served = _post(client, monkeypatch)
    response = client.get(f"/api/jobs/{JOB_ID}/synthesis/answers/1")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["synthesis"] == served["synthesis"]
    assert body["provenance"]["models"] == ["test-model"]
    assert body["contractVersion"] == answers.CONTRACT_VERSION
    assert body["docEvidence"] == [] and body["citedDocIds"] == []
    assert body["citationsOutsidePayload"] == []
    text = json.dumps(body)
    for internal in ("traceId", "trace_id", "jobId", "answer_id", "answerId", "searchId"):
        assert internal not in text
    assert SAMPLE not in text


def test_an_unknown_version_is_404(client, finished, storing):
    assert client.get(f"/api/jobs/{JOB_ID}/synthesis/answers/7").status_code == 404


def test_a_record_change_after_the_answer_is_flagged(client, finished, monkeypatch, storing):
    _post(client, monkeypatch)
    finished.final_validation([("late_check", "WARN", "written after the explanation")])
    [v1] = _list(client)["versions"]
    assert v1["recordChanged"] is True
    assert client.get(f"/api/jobs/{JOB_ID}/synthesis/answers/1").json()["recordChanged"] is True


def test_the_record_digest_is_stable_for_an_unchanged_run(client, finished):
    first = answers.record_digest(run_context.build_run_diagnostic_context(JOB_ID))
    assert first == answers.record_digest(run_context.build_run_diagnostic_context(JOB_ID))


# --- citations against what was delivered ------------------------------------------


def test_cited_documents_are_compared_with_what_the_request_carried(client, finished, storing):
    answer = _answer("경고가 기록되었습니다.", "run:status")
    answer["importantFindings"][0]["evidenceRefs"].append("doc:samtools-index")
    result = SynthesisResult(
        available=True, synthesis=contract.RunSynthesis(**answer),
        provenance=SynthesisProvenance(models=["m"], generatedAt="x",
                                       contextKind="completedFull", runStatus="completed"))
    t = trace.SynthesisTrace(models=("m",), available=True, inputSha256="1" * 64)
    trace_id = trace.record(JOB_ID, t)
    db.execute(
        "INSERT INTO doc_search_runs (search_id, job_id, created_at, method, corpora, inputs,"
        " excluded, result_count) VALUES ('ds_1', ?, 'x', 'm', '[]', '[]', '[]', 2)", (JOB_ID,))
    db.execute(
        "INSERT INTO doc_search_hits (search_id, input_id, corpus, rank, evidence_id, relation,"
        " matched_by, source_title, location, item_sha256) VALUES"
        " ('ds_1','i1','curated',1,'doc:samtools-index','filedUnderCauseKind','[]','SYNTHETIC samtools','loc','h')")
    for evidence_id, selected, in_payload, cited in (
            ("doc:samtools-index", 1, 1, 1), ("doc:other", 0, 0, None)):
        db.execute(
            "INSERT INTO agent_doc_evidence VALUES (?, 'ds_1', ?, ?, NULL, ?, ?)",
            (trace_id, evidence_id, selected, in_payload, cited))
    context = run_context.build_run_diagnostic_context(JOB_ID)
    answers.store(JOB_ID, trace_id, result, t, redactor=answers.redactor_for(context),
                  run_record_sha256=answers.record_digest(context), doc_search_id="ds_1")

    body = client.get(f"/api/jobs/{JOB_ID}/synthesis/answers/1").json()
    assert body["citedDocIds"] == ["doc:samtools-index"]
    assert body["citationsOutsidePayload"] == []
    by_id = {d["evidenceId"]: d for d in body["docEvidence"]}
    assert by_id["doc:samtools-index"] == {
        "evidenceId": "doc:samtools-index", "title": "SYNTHETIC samtools",
        "selected": True, "selectionReason": None, "inPayload": True, "cited": True}
    assert by_id["doc:other"]["inPayload"] is False and by_id["doc:other"]["cited"] is None
    assert _list(client)["versions"][0]["docSearchLinked"] is True


# --- manual deletion ------------------------------------------------------------------


def test_deleting_a_version_clears_the_body_and_keeps_the_record(
        client, finished, monkeypatch, storing):
    _post(client, monkeypatch)
    response = client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/1")
    assert response.status_code == 200
    [row] = _rows()
    assert row["body_json"] is None and row["deleted_at"]
    assert row["input_sha256"] and row["run_record_sha256"]
    got = client.get(f"/api/jobs/{JOB_ID}/synthesis/answers/1").json()
    assert got["deleted"] is True and got["synthesis"] is None
    # a deleted number is never reused
    _post(client, monkeypatch)
    assert [r["version"] for r in _rows()] == [1, 2]
    assert _list(client)["latestVersion"] == 2


def test_deleting_the_newest_makes_the_previous_one_latest_and_both_stay_listed(
        client, finished, monkeypatch, storing):
    _post(client, monkeypatch)
    _post(client, monkeypatch)
    client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/2")
    listing = _list(client)
    assert listing["latestVersion"] == 1
    assert [(v["version"], v["deleted"]) for v in listing["versions"]] == [(2, True), (1, False)]


def test_an_out_of_range_version_is_rejected_not_a_server_error(client, finished, storing):
    huge = 10**20
    assert client.get(f"/api/jobs/{JOB_ID}/synthesis/answers/{huge}").status_code == 422
    assert client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/{huge}").status_code == 422
    assert client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/0").status_code == 422


@pytest.mark.parametrize("where", ["store", "stored_version", "record_digest"])
def test_a_storage_failure_never_fails_the_response(client, finished, monkeypatch, storing, where):
    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(answers, where, broken)
    body = _post(client, monkeypatch)
    assert body["available"] is True and body["storedVersion"] is None


def test_deleting_twice_is_harmless_and_unknown_is_404(client, finished, monkeypatch, storing):
    _post(client, monkeypatch)
    assert client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/1").status_code == 200
    assert client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/1").status_code == 200
    assert client.delete(f"/api/jobs/{JOB_ID}/synthesis/answers/9").status_code == 404


# --- the migration -----------------------------------------------------------------------


def test_an_existing_database_gains_the_table_and_keeps_its_rows(tmp_path, monkeypatch):
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
    before = path.read_bytes()
    assert before
    monkeypatch.setattr(config, "DB_PATH", path)
    previous, db._conn = db._conn, None
    try:
        conn = db.connect()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "synthesis_answers" in tables
        row = conn.execute("SELECT * FROM synthesis_traces").fetchone()
        assert row["trace_id"] == "t1" and row["available"] == 1
        assert row["answer_store"] is None  # unknown for an older row, not "not stored"
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous
