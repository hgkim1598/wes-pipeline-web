"""Regression guard for the endpoints that already worked before this change.

The result layer is additive: it adds a router and appends to schemas.py. These
tests pin the observable behaviour of everything that existed before, so a
regression shows up here rather than on the Linux box.

The reference is the successful 2026-08-21 vertical slice:

    job    wes-20260821-142659-c66d6e
    status completed_with_warnings, progress 100
    step   00_input_validation, warning, elapsedSeconds 23
    error  null
"""

from __future__ import annotations


# --- GET /api/health --------------------------------------------------------


def test_health_keys_unchanged(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert set(response.json()) == {
        "status",
        "runMode",
        "pipelineScript",
        "pipelineScriptPresent",
        "captureKitRegistryPresent",
        "referenceConfigured",
    }


def test_health_reports_ok(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["runMode"] in ("check_only", "full")
    assert isinstance(body["pipelineScriptPresent"], bool)


# --- GET /api/jobs/{id} -----------------------------------------------------


def test_job_state_contract_unchanged(client, make_job, run):
    """Field-by-field snapshot of the shape the frontend polls."""
    run().as_passing_precheck()
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}").json()

    assert set(body) == {
        "jobId",
        "profileId",
        "status",
        "progress",
        "steps",
        "logTail",
        "startedAt",
        "finishedAt",
        "error",
        "runId",
        "runMode",
        "pipelineStatus",
        "currentStep",
        "unsupportedOptions",
    }
    assert body["jobId"] == job_id
    assert body["runId"] == job_id
    assert body["profileId"] == "germline-illumina-wes-breast"
    assert body["status"] == "completed_with_warnings"
    assert body["progress"] == 100
    assert body["pipelineStatus"] == "check_only"
    assert body["currentStep"] is None
    assert body["error"] is None
    assert body["runMode"] == "check_only"
    assert body["unsupportedOptions"] == ["min_depth", "min_gq", "variant_caller"]

    assert len(body["steps"]) == 1
    step = body["steps"][0]
    assert set(step) == {"stepId", "status", "elapsedSeconds", "messages"}
    assert step["stepId"] == "00_input_validation"
    assert step["status"] == "warning"
    assert step["elapsedSeconds"] == 23
    assert step["messages"] == ["[MULTIQC_MISSING] MultiQC is not installed"]


def test_job_state_still_returns_profile_id(client, make_job, run):
    """profileId already comes from the backend.

    The results screen reads it from router state instead, which is a frontend
    matter; the backend must not start compensating for that.
    """
    run().as_passing_precheck()
    job_id = make_job(profile_id="germline-illumina-wes-breast")
    assert client.get(f"/api/jobs/{job_id}").json()["profileId"] == (
        "germline-illumina-wes-breast"
    )


def test_job_state_unknown_id_is_404(client):
    assert client.get("/api/jobs/wes-does-not-exist").status_code == 404


def test_job_state_malformed_id_is_400(client):
    assert client.get("/api/jobs/..%2F..%2Fetc").status_code in (400, 404)


def test_job_stream_still_404(client, make_job, run):
    """useJobStream depends on this to select the polling path."""
    run().as_passing_precheck()
    job_id = make_job()
    assert client.get(f"/api/jobs/{job_id}/stream").status_code == 404


# --- POST /api/jobs validation ---------------------------------------------


def test_create_job_rejects_empty_samples(client):
    response = client.post(
        "/api/jobs", json={"profileId": "p", "captureKitId": "x", "samples": []}
    )
    assert response.status_code == 400
    assert "at least one sample" in response.json()["detail"]


def test_create_job_rejects_multiple_samples(client):
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "p",
            "samples": [
                {"sampleId": "A", "files": {"r1": "upl_a", "r2": "upl_b"}},
                {"sampleId": "B", "files": {"r1": "upl_c", "r2": "upl_d"}},
            ],
        },
    )
    assert response.status_code == 400
    assert "one sample per submission" in response.json()["detail"]


def test_create_job_requires_both_reads(client):
    response = client.post(
        "/api/jobs",
        json={"profileId": "p", "samples": [{"sampleId": "A", "files": {"r1": "upl_a"}}]},
    )
    assert response.status_code == 400
    assert "r2" in response.json()["detail"]


def test_create_job_rejects_unregistered_capture_kit(client):
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "p",
            "captureKitId": "not_a_real_kit",
            "samples": [{"sampleId": "A", "files": {"r1": "upl_a", "r2": "upl_b"}}],
        },
    )
    assert response.status_code == 400
    assert "not registered" in response.json()["detail"]


def test_create_job_rejects_unconfirmed_capture_kit(client):
    """main.sh only accepts 'confirmed' profiles; the backend refuses earlier."""
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "p",
            "captureKitId": "agilent_sureselect_human_all_exon_v8",
            "samples": [{"sampleId": "A", "files": {"r1": "upl_a", "r2": "upl_b"}}],
        },
    )
    assert response.status_code == 400
    assert "unconfirmed" in response.json()["detail"]


def test_create_job_rejects_mismatched_assembly(client):
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "p",
            "captureKitId": "idt_xgen_exome_hyb_panel_v2",
            "options": {"assembly": "GRCh37"},
            "samples": [{"sampleId": "A", "files": {"r1": "upl_a", "r2": "upl_b"}}],
        },
    )
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]
