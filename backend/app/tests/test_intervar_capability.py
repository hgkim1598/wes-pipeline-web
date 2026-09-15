"""InterVar (11_intervar) capability handling.

The frontend ships run_acmg with a default of true, so an untouched submission
asks for ACMG classification. main.sh's run_intervar() needs three settings
this backend used to omit entirely, which made the step a guaranteed failure on
every full run.

What must hold now:

  * the recorded plan and the generated run_config never disagree about
    11_intervar -- both come from resolve_intervar();
  * a request this server cannot honour is reported, not dropped;
  * installing InterVar enables it through configuration alone.
"""

from __future__ import annotations

import json

import pytest

from app import config
from app.services import config_builder


@pytest.fixture
def intervar_installed(tmp_path, monkeypatch):
    """A server with a complete, existing InterVar bundle."""
    install_dir = tmp_path / "intervar"
    humandb = tmp_path / "humandb"
    install_dir.mkdir()
    humandb.mkdir()
    profile = {
        "install_dir": str(install_dir),
        "build": "hg38",
        "humandb_dir": str(humandb),
    }
    monkeypatch.setattr(config, "INTERVAR", profile)
    return profile


def submit(client, make_upload, *, run_acmg):
    r1 = make_upload("demo_R1.fastq.gz")
    r2 = make_upload("demo_R2.fastq.gz")
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "germline-illumina-wes-breast",
            "captureKitId": "idt_xgen_exome_hyb_panel_v2",
            "options": {
                "capture_kit_id": "idt_xgen_exome_hyb_panel_v2",
                "run_acmg": run_acmg,
                "min_gq": 10,
            },
            "samples": [{"sampleId": "DEMO01", "files": {"r1": r1, "r2": r2}}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["jobId"]


def generated_config(job_id: str) -> dict:
    path = config.JOBS_ROOT / job_id / "run_config.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- the decision itself ----------------------------------------------------


def test_not_requested_is_disabled(monkeypatch):
    monkeypatch.setattr(config, "INTERVAR", None)
    assert config_builder.resolve_intervar({"run_acmg": False}) == (False, False)


def test_requested_without_capability_is_flagged(monkeypatch):
    monkeypatch.setattr(config, "INTERVAR", None)
    assert config_builder.resolve_intervar({"run_acmg": True}) == (False, True)


def test_requested_with_capability_is_enabled(intervar_installed):
    assert config_builder.resolve_intervar({"run_acmg": True}) == (True, False)


def test_not_requested_stays_off_even_when_installed(intervar_installed):
    assert config_builder.resolve_intervar({"run_acmg": False}) == (False, False)


# --- A: server not configured, user asked for it -----------------------------


def test_unconfigured_server_does_not_plan_intervar(
    client, make_upload, reference_configured, monkeypatch
):
    monkeypatch.setattr(config, "INTERVAR", None)

    job_id = submit(client, make_upload, run_acmg=True)
    body = client.get(f"/api/jobs/{job_id}").json()
    doc = generated_config(job_id)

    assert doc["optional_steps"]["intervar"] is False
    assert "intervar" not in doc
    assert [s["stepId"] for s in body["steps"]] == [
        "00_input_validation",
        "01_raw_qc",
        "02_preprocessing",
        "03_alignment",
        "04_processing",
        "05_coverage_qc",
        "06_variant_calling",
        "99_finalization",
    ]


def test_unconfigured_server_reports_run_acmg_as_unsupported(
    client, make_upload, reference_configured, monkeypatch
):
    """The request is refused honestly rather than silently ignored."""
    monkeypatch.setattr(config, "INTERVAR", None)

    job_id = submit(client, make_upload, run_acmg=True)

    unsupported = client.get(f"/api/jobs/{job_id}").json()["unsupportedOptions"]
    assert "run_acmg" in unsupported
    # Options that were never supported are still reported alongside it.
    assert "min_gq" in unsupported


# --- B: server configured, user asked for it ---------------------------------


def test_configured_server_plans_and_configures_intervar(
    client, make_upload, reference_configured, intervar_installed
):
    job_id = submit(client, make_upload, run_acmg=True)
    body = client.get(f"/api/jobs/{job_id}").json()
    doc = generated_config(job_id)

    assert doc["optional_steps"]["intervar"] is True
    assert doc["intervar"] == intervar_installed
    assert "11_intervar" in [s["stepId"] for s in body["steps"]]
    assert "run_acmg" not in body["unsupportedOptions"]


def test_configured_server_writes_the_three_keys_main_sh_reads(
    client, make_upload, reference_configured, intervar_installed
):
    """run_intervar() reads exactly install_dir, build and humandb_dir."""
    job_id = submit(client, make_upload, run_acmg=True)

    assert set(generated_config(job_id)["intervar"]) == {
        "install_dir",
        "build",
        "humandb_dir",
    }


# --- C: server configured, user declined -------------------------------------


def test_user_declining_wins_over_an_installed_bundle(
    client, make_upload, reference_configured, intervar_installed
):
    job_id = submit(client, make_upload, run_acmg=False)
    body = client.get(f"/api/jobs/{job_id}").json()
    doc = generated_config(job_id)

    assert doc["optional_steps"]["intervar"] is False
    assert "intervar" not in doc
    assert "11_intervar" not in [s["stepId"] for s in body["steps"]]
    assert "run_acmg" not in body["unsupportedOptions"]


# --- plan / config consistency ----------------------------------------------


@pytest.mark.parametrize("run_acmg", [True, False])
def test_plan_and_config_never_disagree(
    client, make_upload, reference_configured, intervar_installed, run_acmg
):
    job_id = submit(client, make_upload, run_acmg=run_acmg)
    planned = [s["stepId"] for s in client.get(f"/api/jobs/{job_id}").json()["steps"]]

    configured = generated_config(job_id)["optional_steps"]["intervar"]
    assert ("11_intervar" in planned) == configured


def test_build_run_config_refuses_to_enable_what_it_cannot_configure(
    tmp_path, reference_configured, monkeypatch
):
    """The guard that keeps the two halves of the decision from drifting."""
    monkeypatch.setattr(config, "INTERVAR", None)

    with pytest.raises(config_builder.ConfigBuildError):
        config_builder.build_run_config(
            run_id="wes-20260822-120000-aaaaaa",
            samplesheet=tmp_path / "samplesheet.csv",
            capture_kit_id="idt_xgen_exome_hyb_panel_v2",
            intervar=True,
        )


# --- server configuration validation -----------------------------------------


def test_no_intervar_env_means_no_capability(monkeypatch):
    for name in ("WES_INTERVAR_DIR", "WES_INTERVAR_BUILD", "WES_INTERVAR_HUMANDB"):
        monkeypatch.delenv(name, raising=False)
    assert config._resolve_intervar() is None


def test_partial_intervar_env_is_a_configuration_error(tmp_path, monkeypatch):
    """Half-configured means the operator meant to enable this and got it wrong."""
    monkeypatch.setenv("WES_INTERVAR_DIR", str(tmp_path))
    monkeypatch.setenv("WES_INTERVAR_HUMANDB", str(tmp_path))
    monkeypatch.delenv("WES_INTERVAR_BUILD", raising=False)

    with pytest.raises(config.ConfigError) as excinfo:
        config._resolve_intervar()
    assert "WES_INTERVAR_BUILD" in str(excinfo.value)


def test_intervar_dir_must_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("WES_INTERVAR_DIR", str(tmp_path / "nope"))
    monkeypatch.setenv("WES_INTERVAR_BUILD", "hg38")
    monkeypatch.setenv("WES_INTERVAR_HUMANDB", str(tmp_path))

    with pytest.raises(config.ConfigError) as excinfo:
        config._resolve_intervar()
    assert "WES_INTERVAR_DIR" in str(excinfo.value)


def test_complete_intervar_env_resolves(tmp_path, monkeypatch):
    install_dir = tmp_path / "intervar"
    humandb = tmp_path / "humandb"
    install_dir.mkdir()
    humandb.mkdir()
    monkeypatch.setenv("WES_INTERVAR_DIR", str(install_dir))
    monkeypatch.setenv("WES_INTERVAR_BUILD", "hg38")
    monkeypatch.setenv("WES_INTERVAR_HUMANDB", str(humandb))

    assert config._resolve_intervar() == {
        "install_dir": str(install_dir),
        "build": "hg38",
        "humandb_dir": str(humandb),
    }
