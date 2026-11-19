"""Stored search hits stay readable by the release before sectionIntro (log 32).

92c7e12 builds every stored hit into a SearchHit whose matchedBy is
Literal["causeKindKey", "optionLookup", "fts5"]; one unknown value raises and
GET doc-search fails for the whole job. That rule is pinned here as a copy (the
old code is not importable next to the current one); the real 92c7e12 code was
run against a temporary database by hand, recorded in the development log.

Temporary database and a synthetic manual only: no run, no process, no network.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

import pytest
from pydantic import TypeAdapter, ValidationError

from .. import config, db
from ..services.doc_search import engine, store
from ..services.doc_search.models import SearchInput
from .doc_corpus_fixture import synthetic_passages  # noqa: F401 -- fixture
from .test_doc_search import manual  # noqa: F401 -- fixture
from .test_doc_section_intro import _item, corpus  # noqa: F401 -- fixture
from .test_resource_bundle_diagnosis import RUN_ID, SAMPLE, failed_precheck

# Copied from 92c7e12 backend/app/services/doc_search/models.py. Never update it.
OLD_RULE = TypeAdapter(list[Literal["causeKindKey", "optionLookup", "fts5"]])
# The INSERT 92c7e12 runs (store.save), verbatim: it does not name the new column.
OLD_INSERT = (
    "INSERT INTO doc_search_hits (search_id, input_id, corpus, rank, evidence_id, relation, "
    "matched_by, source_title, source_url, location, version, checked_on, item_sha256) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _hit(rank: int, how: list[str]) -> engine.HitRecord:
    return engine.HitRecord("in-1", "manual", rank, f"manual:m#concat#0{rank}", "sameCommandSection",
                            how, "synthetic manual", None, "X > bcftools concat", None, None, "0" * 64)


def _save(hits: list[engine.HitRecord]) -> str:
    inp = SearchInput(inputId="in-1", origin="stepCheck", stepId="s", kind="test", tool="bcftools")
    return store.save("job-1", engine.SearchRecord("synthetic", 1, [], [inp], [], hits))


def _stored(search_id: str) -> list[tuple[str, str | None]]:
    return [tuple(r) for r in db.connect().execute(
        "SELECT matched_by, matched_by_full FROM doc_search_hits WHERE search_id = ? ORDER BY rank",
        (search_id,))]


def test_the_legacy_vocabulary_is_exactly_what_the_old_release_accepts():
    assert set(store.LEGACY_MATCHED_BY) == set(OLD_RULE.validate_python(list(store.LEGACY_MATCHED_BY)))
    with pytest.raises(ValidationError):  # the reproduced failure, as the old rule sees it
        OLD_RULE.validate_python(["sectionIntro", "fts5"])


def test_a_hit_without_a_new_reason_is_stored_as_before(env):
    sid = _save([_hit(1, ["optionLookup", "fts5"]), _hit(2, ["fts5"])])
    assert _stored(sid) == [('["optionLookup", "fts5"]', None), ('["fts5"]', None)]
    assert [h.matchedBy for h in store.get_run(sid).hits] == [["optionLookup", "fts5"], ["fts5"]]


def test_a_section_intro_hit_is_served_in_full_and_stored_readable_by_the_old_rule(env):
    sid = _save([_hit(1, ["sectionIntro", "fts5"]), _hit(2, ["sectionIntro"])])
    rows = _stored(sid)
    for legacy, _full in rows:
        OLD_RULE.validate_python(json.loads(legacy))  # the old release can serve the row
    assert rows == [('["fts5"]', '["sectionIntro", "fts5"]'), ("[]", '["sectionIntro"]')]
    # What the run page shows is the full reason, the same as what was found.
    assert [h.matchedBy for h in store.get_run(sid).hits] == [["sectionIntro", "fts5"], ["sectionIntro"]]


def test_a_row_the_old_release_wrote_after_the_column_exists_reads_as_before(env):
    sid = _save([])
    db.connect().execute(OLD_INSERT, (sid, "in-1", "manual", 1, "manual:m#concat#01", "sameCommandSection",
                                      '["optionLookup"]', "synthetic manual", None, "X", None, None, "0" * 64))
    assert [h.matchedBy for h in store.get_run(sid).hits] == [["optionLookup"]]


def test_an_existing_hits_table_gains_the_column_and_keeps_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(  # the 92c7e12 table, one row in it
        "CREATE TABLE doc_search_hits (search_id TEXT NOT NULL, input_id TEXT NOT NULL, corpus TEXT NOT NULL, "
        "rank INTEGER NOT NULL, evidence_id TEXT NOT NULL, relation TEXT NOT NULL, matched_by TEXT NOT NULL, "
        "source_title TEXT NOT NULL, source_url TEXT, location TEXT NOT NULL, version TEXT, checked_on TEXT, "
        "item_sha256 TEXT NOT NULL, PRIMARY KEY (search_id, input_id, corpus, rank));"
        "INSERT INTO doc_search_hits VALUES ('s','i','manual',1,'manual:x','sameCommandSection','[\"fts5\"]',"
        "'t',NULL,'l',NULL,NULL,'h');"
    )
    old.commit()
    old.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    previous, db._conn = db._conn, None
    try:
        for _ in range(2):  # the second start finds the column already there
            if db._conn is not None:
                db._conn.close()
            db._conn = None
            rows = db.connect().execute("SELECT matched_by, matched_by_full FROM doc_search_hits").fetchall()
            assert [tuple(r) for r in rows] == [('["fts5"]', None)]
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous


def test_the_search_improvement_survives_the_round_trip(env, corpus):  # noqa: F811
    hits = engine._search_manual(_item("concat", sentence="Different sample names in b.vcf.gz."), corpus)
    assert hits[0].matched_by[0] == "sectionIntro"
    served = store.get_run(_save(hits)).hits
    assert served[0].evidenceId == "manual:m#concat#00"
    assert served[0].matchedBy == hits[0].matched_by
    assert [h.matchedBy for h in served] == [h.matched_by for h in hits]


def test_the_api_serves_the_full_reason_and_stores_the_old_readable_one(
        client, make_job, run, manual, synthetic_passages):  # noqa: F811
    failed_precheck(run)
    make_job(RUN_ID, sample_id=SAMPLE)
    posted = client.post(f"/api/jobs/{RUN_ID}/doc-search")
    assert posted.status_code == 200, posted.text
    listed = client.get(f"/api/jobs/{RUN_ID}/doc-search")
    assert listed.status_code == 200
    served = {(h["inputId"], h["evidenceId"]): h["matchedBy"] for h in listed.json()["runs"][0]["hits"]}
    assert served == {(h["inputId"], h["evidenceId"]): h["matchedBy"] for h in posted.json()["hits"]}
    with_intro = [k for k, how in served.items() if "sectionIntro" in how]
    assert with_intro  # the view section opening (it also lists the recorded -h)
    for legacy, full in db.connect().execute("SELECT matched_by, matched_by_full FROM doc_search_hits"):
        OLD_RULE.validate_python(json.loads(legacy))
        assert (full is None) == ("sectionIntro" not in json.loads(full or legacy))
