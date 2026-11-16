"""The local demo of a real FAILED run (log 18). No model, no pipeline.

dev_restore.restore_archive puts a copy of an archived failed run OUTSIDE the
repository (the archive restore's own guard is unchanged and still runs) and
the real FastAPI app is pointed at it -- the routes the run-detail page calls
are exercised as the browser would call them. The synthesis route is reached
with a fake provider only: a real answer needs an approved model call.

Nothing about the run's contents is printed; assertions use kinds and counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import synthesis as synthesis_api
from app.main import app
from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.explanation.llm import provider

from . import archive_runs, dev_restore
from .agent_cases import pointed_at

from app.tests.doc_corpus_fixture import synthetic_passages

pytestmark = pytest.mark.usefixtures("synthetic_passages")

RUN = archive_runs.ARCHIVE_RUNS["real_3a22c5"]

needs_archive = pytest.mark.skipif(
    not archive_runs.archive_available(RUN),
    reason="실패 기록 압축 파일이 이 환경에 없음 (git에 포함되지 않음)",
)


def _restore(tmp_path: Path) -> tuple[Path, dev_restore.Restored]:
    target = tmp_path / "dev_failed"
    return target, dev_restore.restore_archive(RUN, target)


@needs_archive
def test_the_copy_holds_the_failed_run_and_nothing_else(tmp_path):
    target, result = _restore(tmp_path)
    assert (result.jobs, result.uploads, result.traces) == (1, 0, 0)
    assert result.status == "failed"
    assert result.payload_leaks == 0 and result.evidence_leaks == 0
    assert result.capture_unchanged  # the archive's digest, before == after
    assert (target / dev_restore.DB_NAME).is_file()


@needs_archive
def test_restoring_leaves_config_and_isolation_where_they_were(tmp_path):
    from .agent_cases import active_isolated_root

    before = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)
    _restore(tmp_path)
    assert (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH) == before
    assert active_isolated_root() is None


@needs_archive
def test_a_target_inside_the_repository_is_refused_and_not_created():
    inside = config.ROOT / "runs" / "dev_failed_must_not_exist"
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore_archive(RUN, inside)
    assert not inside.exists()


@needs_archive
def test_an_existing_target_is_refused_and_left_alone(tmp_path):
    target = tmp_path / "dev_failed"
    target.mkdir()
    (target / "mine.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore_archive(RUN, target)
    assert [p.name for p in target.iterdir()] == ["mine.txt"]


@needs_archive
def test_a_failure_after_creation_removes_only_what_it_created(tmp_path, monkeypatch):
    def broken(*_args):
        raise RuntimeError("check failed")

    monkeypatch.setattr(dev_restore, "_check_archive", broken)
    target = tmp_path / "dev_failed"
    with pytest.raises(RuntimeError):
        dev_restore.restore_archive(RUN, target)
    assert not target.exists() and tmp_path.exists()


@needs_archive
def test_a_copy_that_fails_its_own_checks_is_removed(tmp_path, monkeypatch):
    """A written copy whose leak check fails must not stay on disk."""
    real = dev_restore._check_archive

    def leaky(*args):
        return {**real(*args), "evidence_leaks": 1}

    monkeypatch.setattr(dev_restore, "_check_archive", leaky)
    target = tmp_path / "dev_failed"
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore_archive(RUN, target)
    assert not target.exists()


@needs_archive
def test_a_failure_entering_the_environment_removes_the_folder(tmp_path, monkeypatch):
    from . import agent_cases

    def broken_pointed_at(*_a, **_k):
        raise OSError("cannot create runs/")

    monkeypatch.setattr(agent_cases, "pointed_at", broken_pointed_at)
    target = tmp_path / "dev_failed"
    with pytest.raises(OSError):
        dev_restore.restore_archive(RUN, target)
    assert not target.exists()


def test_the_copy_problems_are_judged_without_the_archive():
    ok = dev_restore.Restored("r", "failed", 1, 0, 0, 0, 0, True)
    assert dev_restore.archive_copy_problems(ok) == []
    bad = dev_restore.Restored("r", "failed", 2, 0, 0, 0, 1, False)
    assert len(dev_restore.archive_copy_problems(bad)) == 3


def test_persistent_environment_refuses_the_repository_and_existing_folders(tmp_path):
    from .agent_cases import persistent_environment

    inside = config.ROOT / "runs" / "persistent_must_not_exist"
    with pytest.raises(ValueError):
        with persistent_environment(inside):
            pass
    assert not inside.exists()
    existing = tmp_path / "x"
    existing.mkdir()
    with pytest.raises(ValueError):
        with persistent_environment(existing):
            pass


# --- cleanup ownership, without the archive (Codex round 2) ---------------------
#
# The archive operations are stubbed so these run everywhere; the steps that
# decide what gets created and removed are the real ones.


@pytest.fixture
def stub_archive(monkeypatch):
    good = {"run_id": "r", "status": "failed", "jobs": 1, "uploads": 0, "traces": 0,
            "payload_leaks": 0, "evidence_leaks": 0}
    monkeypatch.setattr(archive_runs, "archive_available", lambda run: True)
    monkeypatch.setattr(archive_runs, "load", lambda run: None)
    monkeypatch.setattr(archive_runs, "archive_digest", lambda path: "same")

    def write_copy(run, loaded=None):
        Path(config.DB_PATH).write_bytes(b"copy")

    monkeypatch.setattr(archive_runs, "restore_into_current_config", write_copy)
    monkeypatch.setattr(dev_restore, "_check_archive", lambda run, target, loaded: dict(good))
    return good


def test_stubbed_restore_keeps_a_good_copy(tmp_path, stub_archive):
    target = tmp_path / "dev_failed"
    dev_restore.restore_archive(RUN, target)
    assert (target / dev_restore.DB_NAME).read_bytes() == b"copy"


def test_a_folder_someone_else_creates_meanwhile_is_never_removed(tmp_path, stub_archive, monkeypatch):
    """Absent at the first look, present at creation: not ours, so refused
    and left alone -- ownership comes from our own mkdir, not from timing."""
    from . import agent_cases

    target = tmp_path / "dev_failed"
    real = agent_cases.persistent_environment

    def other_party_first(path, **kwargs):
        path.mkdir()
        (path / "theirs.txt").write_text("keep", encoding="utf-8")
        return real(path, **kwargs)

    monkeypatch.setattr(dev_restore, "persistent_environment", other_party_first)
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore_archive(RUN, target)
    assert [p.name for p in target.iterdir()] == ["theirs.txt"]


def test_a_failure_entering_the_environment_removes_the_folder_without_the_archive(
    tmp_path, stub_archive, monkeypatch
):
    from . import agent_cases

    def broken_pointed_at(*_a, **_k):
        raise OSError("cannot create runs/")

    monkeypatch.setattr(agent_cases, "pointed_at", broken_pointed_at)
    target = tmp_path / "dev_failed"
    with pytest.raises(OSError):
        dev_restore.restore_archive(RUN, target)
    assert not target.exists()


def test_a_leaky_copy_is_removed_without_the_archive(tmp_path, stub_archive, monkeypatch):
    monkeypatch.setattr(dev_restore, "_check_archive",
                        lambda run, target, loaded: {**stub_archive, "payload_leaks": 2})
    target = tmp_path / "dev_failed"
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore_archive(RUN, target)
    assert not target.exists()


def test_a_removal_that_fails_is_reported_not_claimed(tmp_path, stub_archive, monkeypatch):
    """If the leaky copy cannot be removed, say so -- never 'removed'."""
    from . import agent_cases

    monkeypatch.setattr(dev_restore, "_check_archive",
                        lambda run, target, loaded: {**stub_archive, "payload_leaks": 2})

    def cannot_remove(path, *a, **k):
        raise PermissionError("in use")

    monkeypatch.setattr(agent_cases, "rmtree", cannot_remove, raising=False)
    monkeypatch.setattr(dev_restore, "rmtree", cannot_remove)
    target = tmp_path / "dev_failed"
    with pytest.raises(Exception) as caught:
        dev_restore.restore_archive(RUN, target)
    assert target.exists()
    assert "지우지 못" in str(caught.value)
    assert "지웠습니다" not in str(caught.value)


def test_a_folder_replaced_after_creation_is_not_removed(tmp_path):
    from .agent_cases import _remove_owned

    target = tmp_path / "dev_failed"
    target.mkdir()
    made = target.stat()
    target.rmdir()
    (tmp_path / "placeholder").mkdir()  # keep the old file id from being reused at once
    target.mkdir()
    (target / "theirs.txt").write_text("keep", encoding="utf-8")
    cause = RuntimeError("check failed")
    _remove_owned(target, made, cause)
    assert (target / "theirs.txt").exists()
    assert any("지우지 않았습니다" in n for n in cause.__notes__)


def test_an_unrelated_value_error_is_not_turned_into_a_refusal(tmp_path, stub_archive, monkeypatch):
    def bad(*_a):
        raise ValueError("bug")

    monkeypatch.setattr(dev_restore, "_check_archive", bad)
    target = tmp_path / "dev_failed"
    with pytest.raises(ValueError):
        dev_restore.restore_archive(RUN, target)
    assert not target.exists()


def test_the_cli_requires_an_explicit_target_for_a_failed_run(capsys):
    assert dev_restore.main(["--case", "real_3a22c5"]) == 2
    assert "--target" in capsys.readouterr().out


# --- what the web UI will call --------------------------------------------------


@pytest.fixture
def api(tmp_path):
    if not archive_runs.archive_available(RUN):
        pytest.skip("압축 파일 없음")
    target, _result = _restore(tmp_path)
    with pointed_at(target, db_name=dev_restore.DB_NAME):
        yield target, TestClient(app, raise_server_exceptions=False)


def test_the_run_list_and_detail_show_the_failed_run(api):
    _target, client = api
    jobs = client.get("/api/jobs").json()["jobs"]
    assert [j["jobId"] for j in jobs] == [RUN.run_id]
    base = f"/api/jobs/{RUN.run_id}"
    assert client.get(base).json()["status"] == "failed"
    explanation = client.get(f"{base}/explanation").json()
    assert [f["code"] for f in explanation["failures"]] == ["resource_bundle"]


def test_the_failed_step_detail_carries_the_classified_causes(api):
    _target, client = api
    detail = client.get(f"/api/jobs/{RUN.run_id}/steps/00_input_validation")
    assert detail.status_code == 200
    causes = detail.json()["resourceBundleDiagnosis"]["causes"]
    assert [c["kind"] for c in causes] == ["resource_missing_or_empty"] * 2


def test_with_the_switch_on_this_run_gets_no_borrowed_excerpt(api, monkeypatch):
    """This run's only cause kind, resource_missing_or_empty, has no verified
    official excerpt, so the RAG adds nothing here -- rather than a passage
    filed under some other kind. (b94559 gets one: htslib-provides-tabix.)"""
    monkeypatch.setattr(config, "DOC_RAG", True)
    evidence = read_step_evidence(run_scope.for_job(RUN.run_id), "00_input_validation")
    assert {g.kind for g in evidence.causeGuidance} == {"resource_missing_or_empty"}
    assert all(g.officialDocs is None for g in evidence.causeGuidance)


def test_the_synthesis_route_reaches_the_provider_with_a_redacted_prompt(api, monkeypatch):
    target, client = api
    seen: dict = {}

    def fake_provider(**kwargs):
        seen.update(kwargs)
        return provider.ProviderResult(
            payload={
                "summary": "실행이 사전 검사에서 멈췄습니다.",
                "importantFindings": [
                    {"statement": "리소스 검사가 실패했습니다.", "evidenceRefs": ["fail:resource_bundle"]}
                ],
                "limitations": [],
                "nextChecks": [],
                "uncertainties": [],
            },
            models=["test-model"],
        )

    real_build = synthesis_api.llm_synthesis.build_run_synthesis

    def build(explanation, **kwargs):
        return real_build(explanation, run_provider=fake_provider, **kwargs)

    monkeypatch.setattr(synthesis_api.llm_synthesis, "build_run_synthesis", build)
    response = client.post(f"/api/jobs/{RUN.run_id}/synthesis")
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert archive_runs.count_leaks(seen["user_prompt"], RUN, extra=[str(target)]) == 0
