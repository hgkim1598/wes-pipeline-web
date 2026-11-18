"""Shared-connection transactions and a Python build without FTS5 (log 29).

Everything runs on the `env` fixture's temporary database and synthetic corpora:
no real run, no process, no network. The concurrency tests use threads inside
this test process only.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import types

import pytest

from .. import config, db
from ..services.agent import doc_retrieval
from ..services.doc_search import engine, manual_corpus, store
from .doc_corpus_fixture import synthetic_passages  # noqa: F401  (fixture)
from .test_doc_search import write_manual
from .test_resource_bundle_diagnosis import RUN_ID, SAMPLE, failed_precheck


# --- db.transaction(): the same lock as every other access ---------------------


@pytest.fixture
def probe(env):
    db.connect()
    db.execute("CREATE TABLE probe (who TEXT NOT NULL)")
    return lambda: sorted(r["who"] for r in db.query_all("SELECT who FROM probe"))


def test_a_transaction_commits_on_success_and_rolls_back_only_itself(probe):
    db.execute("INSERT INTO probe VALUES ('committed before')")
    with db.transaction() as conn:
        conn.execute("INSERT INTO probe VALUES ('ours')")
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO probe VALUES ('rolled back')")
            raise RuntimeError("fail inside the transaction")
    assert probe() == ["committed before", "ours"]


def test_a_worker_write_waits_and_is_not_committed_or_undone_by_the_transaction(probe):
    """The interleaving the audit described. Without the lock the worker's commit
    would also commit 'ours' (and our rollback could undo the worker's row)."""
    inside, release, worker_done = threading.Event(), threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def search_saver():
        try:
            with db.transaction() as conn:
                conn.execute("INSERT INTO probe VALUES ('ours')")
                inside.set()
                release.wait(5)
                raise RuntimeError("the save fails after the worker tried to write")
        except RuntimeError:
            pass
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def worker():
        inside.wait(5)
        db.execute("INSERT INTO probe VALUES ('worker')")
        worker_done.set()

    a = threading.Thread(target=search_saver)
    b = threading.Thread(target=worker)
    a.start()
    b.start()
    assert inside.wait(5)
    # The worker is blocked while the transaction is open.
    assert not worker_done.wait(0.3)
    release.set()
    a.join(5)
    b.join(5)
    assert not errors and worker_done.is_set()
    assert probe() == ["worker"]


def _hit(rank=1):
    return engine.HitRecord(
        input_id="in-1", corpus="manual", rank=rank, evidence_id="manual:x", relation="sameCommandSection",
        matched_by=["fts5"], source_title="t", source_url=None, location="l", version=None,
        checked_on=None, item_sha256="0" * 64,
    )


def test_a_failed_search_save_leaves_no_half_written_search(env):
    db.connect()
    record = engine.SearchRecord(method="m", duration_ms=0, corpora=[], inputs=[], excluded=[],
                                 hits=[_hit(1), _hit(1)])  # same primary key twice
    with pytest.raises(sqlite3.IntegrityError):
        store.save("job-x", record)
    assert db.query_all("SELECT * FROM doc_search_runs") == []
    assert db.query_all("SELECT * FROM doc_search_hits") == []
    # The connection is usable afterwards: the lock was released.
    store.save("job-x", engine.SearchRecord(method="m", duration_ms=0, corpora=[], inputs=[],
                                            excluded=[], hits=[_hit(1)]))
    assert len(db.query_all("SELECT * FROM doc_search_runs")) == 1


# --- no FTS5 in this Python's SQLite --------------------------------------------


class _NoFts5Connection:
    def execute(self, sql, *args):
        if "fts5" in sql.lower():
            raise sqlite3.OperationalError("no such module: fts5")
        raise AssertionError(f"unexpected statement: {sql}")


def _without_fts5(monkeypatch, module):
    """Only `module`'s sqlite3 is replaced; the application database is untouched."""
    shim = types.SimpleNamespace(
        connect=lambda *a, **k: _NoFts5Connection(), Error=sqlite3.Error, Connection=sqlite3.Connection)
    monkeypatch.setattr(module, "sqlite3", shim)


@pytest.fixture
def manual_no_fts5(tmp_path, monkeypatch):
    manual_corpus.clear_cache()
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", str(write_manual(tmp_path)))
    _without_fts5(monkeypatch, manual_corpus)
    yield
    manual_corpus.clear_cache()


def test_without_fts5_the_manual_is_a_typed_error_and_the_cause_is_logged(manual_no_fts5, caplog):
    with caplog.at_level(logging.WARNING, logger=manual_corpus.__name__):
        with pytest.raises(manual_corpus.ManualCorpusError):
            manual_corpus.load(engine._manual_path())
    assert "fts5" in caplog.text


def test_without_fts5_the_run_page_search_reports_the_manual_unavailable(
        client, make_job, run, manual_no_fts5, synthetic_passages, tmp_path):
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    r = client.post(f"/api/jobs/{RUN_ID}/doc-search")
    assert r.status_code == 200, r.text
    body = r.json()
    info = {c["corpusId"]: c for c in body["corpora"]}
    assert info["manual"]["available"] is False
    assert info["manual"]["note"] == engine.REASON_MANUAL_ERROR
    assert not [h for h in body["hits"] if h["corpus"] == "manual"]
    g = client.get(f"/api/jobs/{RUN_ID}/doc-search")
    assert g.status_code == 200
    # Nothing internal reaches the browser: no path, no sqlite message.
    for text in (r.text, g.text):
        assert str(tmp_path) not in text and "no such module" not in text


def test_without_fts5_curated_excerpts_keep_their_filed_order(synthetic_passages, monkeypatch, caplog):
    doc_retrieval._index.cache_clear()
    kind = next(k for p in doc_retrieval.all_passages() for k in p.causeKinds)
    expected = [p.id for p in doc_retrieval.all_passages() if kind in p.causeKinds][
        : doc_retrieval.MAX_PASSAGES_PER_CAUSE]
    _without_fts5(monkeypatch, doc_retrieval)
    try:
        with caplog.at_level(logging.WARNING, logger=doc_retrieval.__name__):
            got = [p.id for p in doc_retrieval.retrieve(kind, "header parse failed")]
    finally:
        doc_retrieval._index.cache_clear()
    assert got == expected
    assert "fts5" in caplog.text
