"""The dev copy for the web UI: created safely, readable by the real API.

No model is called and no pipeline is run. The synthesis route is exercised
with a fake provider, through the same code the button reaches. The backend's
lifespan is not entered, so the pipeline worker never starts.

Every copy here goes under pytest's tmp_path -- never the default target -- and
leak assertions compare counts, never the leaked strings.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import synthesis as synthesis_api
from app.main import app
from app.services.explanation.llm import provider

from . import dev_restore, real_runs
from .agent_cases import pointed_at

RUN = real_runs.REAL_RUNS["real_cba73e"]

needs_capture = pytest.mark.skipif(
    not real_runs.capture_available(RUN),
    reason=(
        f"보존된 실제 Run capture({RUN.capture_dir.name})가 이 환경에 없음 -- "
        ".capture_* 폴더는 git에 포함되지 않는다"
    ),
)


def _restore(tmp_path: Path) -> tuple[Path, dev_restore.Restored]:
    # tmp_path is outside the repository, so git cannot be asked about it.
    target = tmp_path / "dev"
    return target, dev_restore.restore(RUN, target, require_ignored=False)


# --- the copy -----------------------------------------------------------------


@needs_capture
def test_the_copy_holds_one_job_and_nothing_else(tmp_path):
    target, result = _restore(tmp_path)

    assert (result.jobs, result.uploads, result.traces) == (1, 0, 0)
    assert result.status == "completed_with_warnings"
    assert result.payload_leaks == 0
    assert result.evidence_leaks == 0
    assert result.capture_unchanged
    assert (target / dev_restore.DB_NAME).is_file()
    assert (target / "runs" / RUN.run_id).is_dir()
    assert not any((target / "uploads").iterdir())


@needs_capture
def test_restoring_leaves_config_where_it_was(tmp_path):
    before = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)
    _restore(tmp_path)
    assert (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH) == before


@needs_capture
def test_an_existing_target_is_refused_and_left_alone(tmp_path):
    target = tmp_path / "dev"
    target.mkdir()
    keep = target / "mine.txt"
    keep.write_text("do not touch", encoding="utf-8")

    with pytest.raises(dev_restore.Refused):
        dev_restore.restore(RUN, target, require_ignored=False)

    assert [p.name for p in target.iterdir()] == ["mine.txt"]
    assert keep.read_text(encoding="utf-8") == "do not touch"


@needs_capture
def test_a_target_inside_the_capture_is_refused(tmp_path):
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore(RUN, RUN.capture_dir / "dev", require_ignored=False)
    assert not (RUN.capture_dir / "dev").exists()


@needs_capture
def test_a_target_git_would_track_is_refused(tmp_path):
    tracked = config.ROOT / "backend" / "evals" / "dev_copy_must_not_exist"
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore(RUN, tracked)
    assert not tracked.exists()


def test_a_missing_capture_is_refused_before_anything_is_created(tmp_path):
    absent = real_runs.RealRun(
        name="absent",
        intent="",
        capture_dir=tmp_path / "no_capture",
        run_id=RUN.run_id,
        split="dev",
    )
    target = tmp_path / "dev"
    with pytest.raises(dev_restore.Refused):
        dev_restore.restore(absent, target, require_ignored=False)
    assert not target.exists()


@needs_capture
def test_a_failure_after_creation_removes_only_what_it_created(tmp_path, monkeypatch):
    def broken(_run, _target):
        raise RuntimeError("check failed")

    monkeypatch.setattr(dev_restore, "_check", broken)
    target = tmp_path / "dev"
    with pytest.raises(RuntimeError):
        dev_restore.restore(RUN, target, require_ignored=False)
    assert not target.exists()
    assert tmp_path.exists()


def test_the_default_target_is_ignored_by_git():
    target = dev_restore.default_target(RUN)
    assert dev_restore.ignored_by_git(target)
    assert dev_restore.shown(target) == f"runs/dev_{RUN.name}"


def test_the_default_target_is_not_the_developers_database():
    target = dev_restore.default_target(RUN)
    assert (target / dev_restore.DB_NAME).resolve() != (
        config.ROOT / "backend" / "data" / "app.db"
    ).resolve()


# --- what the web UI will call --------------------------------------------------


@pytest.fixture
def api(tmp_path):
    """The real app, pointed at a fresh dev copy, without its lifespan."""
    if not real_runs.capture_available(RUN):
        pytest.skip("capture 없음")
    target, _result = _restore(tmp_path)
    with pointed_at(target, db_name=dev_restore.DB_NAME):
        yield target, TestClient(app, raise_server_exceptions=False)


def test_the_run_list_shows_the_restored_run(api):
    _target, client = api
    response = client.get("/api/jobs")
    assert response.status_code == 200
    ids = [job["jobId"] for job in response.json()["jobs"]]
    assert ids == [RUN.run_id]


def test_the_run_detail_routes_answer(api):
    _target, client = api
    base = f"/api/jobs/{RUN.run_id}"

    state = client.get(base)
    assert state.status_code == 200
    assert state.json()["status"] == "completed_with_warnings"

    explanation = client.get(f"{base}/explanation")
    assert explanation.status_code == 200
    assert explanation.json()["status"] == "completed_with_warnings"

    for step in ("04_processing", "05_coverage_qc", "06_variant_calling"):
        assert client.get(f"{base}/steps/{step}").status_code == 200


def test_results_and_artifacts_answer(api):
    _target, client = api
    base = f"/api/jobs/{RUN.run_id}"
    assert client.get(f"{base}/results").status_code == 200
    assert client.get(f"{base}/artifacts").status_code == 200


def test_the_synthesis_route_reaches_the_provider_with_a_redacted_prompt(api, monkeypatch):
    target, client = api
    seen: dict = {}

    def fake_provider(**kwargs):
        seen.update(kwargs)
        return provider.ProviderResult(
            payload={
                "summary": "실행을 확인했습니다.",
                "importantFindings": [
                    {"statement": "실행이 끝났습니다.", "evidenceRefs": ["run:status"]}
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
    # Counted on the prompt text itself: JSON-encoding it again would turn
    # "word:\n" into "word:\\n", which the drive-path pattern reads as "X:\".
    prompt = seen["user_prompt"]
    assert isinstance(prompt, str) and prompt
    assert real_runs.count_leaks(prompt, RUN, extra=[str(target)]) == 0


@needs_capture
def test_the_capture_is_unchanged_by_the_whole_module(tmp_path):
    before = real_runs.capture_manifest(RUN.capture_dir)
    _restore(tmp_path)
    assert real_runs.capture_manifest(RUN.capture_dir) == before


def test_git_still_ignores_the_runs_folder():
    done = subprocess.run(
        ["git", "check-ignore", "-q", "runs/anything"],
        cwd=config.ROOT,
        capture_output=True,
        timeout=10,
    )
    assert done.returncode == 0
