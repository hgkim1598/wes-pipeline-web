"""Public code is usable without private identities, keys, excerpts or queries."""

import json

import pytest

from app import config
from app.schemas import ResourceBundleCause, ResourceBundleDiagnosis
from app.services.agent import doc_retrieval
from app.services.agent.step_evidence import cause_guidance
from app.tests.doc_corpus_fixture import clear_store

from . import archive_runs, local_data, run_eval
from .experiments.retrieval_compare import Bm25, bm25_kind


def test_absent_local_registration_never_guesses_a_real_run(monkeypatch, tmp_path):
    monkeypatch.delenv("WES_EVAL_LOCAL_CONFIG", raising=False)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert local_data.run_id("real_3a22c5") == ""
    assert not local_data.source_path("archive").exists()
    assert not local_data.source_path("captureDir", case="real_cba73e").exists()
    assert list(tmp_path.iterdir()) == []


def test_private_values_are_resolved_without_rewriting_them(monkeypatch, tmp_path):
    path = tmp_path / "private.json"
    row = {"runId": "wes-20990101-000000-000001", "captureDir": "a-capture"}
    path.write_text(json.dumps({"schemaVersion": 1, "archive": "a-source.tar.gz", "runs": {"case": row}}))
    before = path.read_bytes()
    monkeypatch.setenv("WES_EVAL_LOCAL_CONFIG", str(path))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert local_data.run_id("case") == row["runId"]
    assert local_data.source_path("archive") == tmp_path / "a-source.tar.gz"
    assert local_data.source_path("captureDir", case="case") == tmp_path / "a-capture"
    assert path.read_bytes() == before


def test_bad_local_configuration_does_not_print_its_values(monkeypatch, tmp_path):
    path = tmp_path / "private.json"
    path.write_text('{"runs": "SYNTHETIC_PRIVATE_CANARY"}')
    monkeypatch.setenv("WES_EVAL_LOCAL_CONFIG", str(path))
    with pytest.raises(local_data.LocalDataError) as err:
        local_data.settings()
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(err.value)
    assert str(path) not in str(err.value)


def test_explicit_missing_configuration_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("WES_EVAL_LOCAL_CONFIG", str(tmp_path / "absent.json"))
    with pytest.raises(local_data.LocalDataError):
        local_data.settings()


def test_corpus_selection_preserves_local_data_and_has_a_public_fallback(tmp_path):
    public = tmp_path / "wes_doc_passages.public.json"
    public.write_text('{"passages": []}')
    assert config.document_passage_path(tmp_path) == public
    local = tmp_path / "wes_doc_passages.json"
    local.write_text('{"passages": []}')
    assert config.document_passage_path(tmp_path) == local
    assert config.document_passage_path(tmp_path, str(public)) == public


def test_empty_public_corpus_keeps_the_service_and_guidance_usable(monkeypatch):
    clear_store()
    monkeypatch.setattr(config, "DOC_PASSAGE_KNOWLEDGE", config.PUBLIC_DOC_PASSAGES)
    try:
        assert doc_retrieval.all_passages() == []
        assert doc_retrieval.retrieve("bwa_index_incomplete", "anything") == []
        assert doc_retrieval.search_all("anything") == []
        diagnosis = ResourceBundleDiagnosis(state="parsed", causes=[
            ResourceBundleCause(kind="bwa_index_incomplete", resourceRole="bwa_index")
        ])
        entries = cause_guidance(diagnosis, with_docs=True)
        assert entries and entries[0].checks
        assert entries[0].officialDocs is None
        assert "officialDocs" not in entries[0].model_dump()
    finally:
        clear_store()


def test_public_bm25_implementation_needs_no_private_query_file():
    index = Bm25.build({"a": "synthetic alpha", "b": "synthetic beta"})
    assert bm25_kind(index, "alpha", 0)[0] == "a"
    assert bm25_kind(index, "unknown", 0)[0] is None


@pytest.mark.parametrize("field", ["runId", "archive"])
def test_archive_source_exemption_requires_the_registered_value(field):
    run = archive_runs.ArchiveRun(name="synthetic", intent="test", run_id="wes-20990101-000000-000001")
    loaded = archive_runs.LoadedRun(run=run, digest="0" * 64, files={}, sample="SYNTHETIC_CANARY")
    record = {"runId": run.run_id, "archive": run.archive.name}
    assert run_eval.archive_record_leaks(run, record, loaded) == 0
    record[field] = "SYNTHETIC_CANARY"
    assert run_eval.archive_record_leaks(run, record, loaded) > 0
