"""GET /api/jobs/{id}/results for a --check-only run.

A check-only run produces no BAM and no VCF, but it is not an empty result. It
records a named check table, warnings, failures and the resource metadata it
verified. These tests pin that this evidence reaches the client instead of
being reduced to an availability flag.

The reference is the successful 2026-08-21 Linux slice: status
completed_with_warnings, pipelineStatus check_only, one warning
(MULTIQC_MISSING), 00_input_validation at 23 seconds.
"""

from __future__ import annotations


def test_precheck_returns_200_not_404(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()
    assert client.get(f"/api/jobs/{job_id}/results").status_code == 200


def test_precheck_envelope(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/results").json()

    assert body["jobId"] == job_id
    assert body["runId"] == job_id
    assert body["resultType"] == "precheck"
    assert body["analysisOutputProduced"] is False
    assert body["status"] == "completed_with_warnings"
    assert body["pipelineStatus"] == "check_only"
    assert body["schemaVersion"] == "1.0"
    assert body["sample"] == "SRR2962669.subset_5M"
    assert body["elapsedSeconds"] == 23
    assert body["coverage"] is None
    assert body["variantCalling"] is None
    assert body["optionalSteps"] == {}
    assert body["availableViews"] == []
    assert body["artifactCount"] == 3


def test_precheck_keeps_passing_checks(client, make_job, run):
    """The PASS rows are the evidence; GET /api/jobs/{id} discards them."""
    run().as_passing_precheck()
    job_id = make_job()

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]

    by_name = {c["name"]: c for c in checks}
    assert by_name["samplesheet"]["status"] == "PASS"
    assert by_name["resource_bundle"]["status"] == "PASS"
    assert by_name["MULTIQC_MISSING"]["status"] == "WARN"
    assert "consistent" in by_name["samplesheet"]["detail"]

    timeline = client.get(f"/api/jobs/{job_id}").json()["steps"][0]["messages"]
    assert len(timeline) == 1  # only the warning survives there
    assert len(checks) == 3  # all three rows survive here


def test_precheck_warning_detail(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    warnings = client.get(f"/api/jobs/{job_id}/results").json()["warnings"]
    assert len(warnings) == 1
    assert warnings[0]["code"] == "MULTIQC_MISSING"
    assert warnings[0]["message"] == "MultiQC is not installed"
    assert warnings[0]["canContinue"] is True
    assert "FastQC" in warnings[0]["impact"]


def test_precheck_input_summary(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    summary = client.get(f"/api/jobs/{job_id}/results").json()["inputSummary"]
    assert summary["sample"] == "SRR2962669.subset_5M"
    assert summary["laneCount"] == 1
    assert summary["assembly"] == "GRCh38"
    assert summary["contigStyle"] == "chr"
    assert summary["captureKitId"] == "idt_xgen_exome_hyb_panel_v2"
    assert len(summary["targetBedSha256"]) == 64


def test_failed_precheck_is_still_a_result(client, make_job, run):
    run().as_failing_precheck()
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/results").json()

    assert body["resultType"] == "precheck"
    assert body["status"] == "failed"
    assert body["analysisOutputProduced"] is False
    assert body["elapsedSeconds"] == 4
    assert [f["code"] for f in body["failures"]] == ["required_tools"]
    # The PASS row is kept even on a failed precheck.
    assert any(c["status"] == "PASS" for c in body["checks"])


def test_korean_text_survives_the_round_trip(client, make_job, run):
    """Explicit encoding="utf-8" everywhere; the cp949 default would raise."""
    run().as_failing_precheck()
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/results").json()
    message = body["failures"][0]["message"]
    assert "실행 전에 직접 설치하세요" in message
    assert "이 파이프라인은 도구를 스스로 설치하지 않습니다" in message


def test_partial_input_metrics_are_tolerated(client, make_job, run):
    """A precheck that died on required_tools never recorded the bundle fields."""
    run().as_failing_precheck()
    job_id = make_job()

    summary = client.get(f"/api/jobs/{job_id}/results").json()["inputSummary"]
    assert summary["sample"] == "DEMO01_S1"
    assert summary["laneCount"] == 1
    assert summary["assembly"] is None
    assert summary["targetBedSha256"] is None


def test_no_absolute_path_in_the_response(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    text = client.get(f"/api/jobs/{job_id}/results").text
    assert "_jobs" not in text
    assert "C:\\" not in text
    for marker in ("/srv/", "/home/", "/Users/", "/tmp/"):
        assert marker not in text


# --- not ready --------------------------------------------------------------


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/wes-nope/results").status_code == 404


def test_missing_run_directory_is_409(client, make_job):
    job_id = make_job()
    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resultsNotReady"


def test_no_run_status_document_is_409(client, make_job, run):
    builder = run()
    builder.file("logs/pipeline.log", "starting\n")
    job_id = make_job(status="RUNNING")

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resultsNotReady"


def test_check_only_without_step_document_is_409(client, make_job, run):
    builder = run()
    builder.run_status("check_only", current_step="00_input_validation")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 409


def test_malformed_run_status_is_500_without_detail_leak(client, make_job, run):
    builder = run()
    builder.raw("status/run_status.json", "{ truncated")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"]["code"] == "malformedPipelineDocument"
    assert "Traceback" not in response.text
    assert "run_status.json" not in response.text
    assert str(builder.run_dir) not in response.text
