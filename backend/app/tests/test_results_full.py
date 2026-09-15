"""GET /api/jobs/{id}/results for a full run.

No full run has executed on real resources yet, so these fixtures are built
from the writer code in script/main.sh rather than from observed output. That
is recorded as an assumption: once a real full run exists, the fixtures must be
diffed against it before these tests are trusted as a contract.

Coverage numbers are passed through exactly as mosdepth and main.sh produced
them. Nothing here recomputes a depth, a breadth or a median.
"""

from __future__ import annotations


def test_full_envelope(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/results").json()

    assert body["resultType"] == "full"
    assert body["analysisOutputProduced"] is True
    assert body["status"] == "completed_with_warnings"
    assert body["pipelineStatus"] == "completed_with_warnings"
    assert body["sample"] == "SRR2962669.subset_5M"
    assert body["elapsedSeconds"] == 923  # 23 + 900, as core_summary recorded
    assert body["intendedUse"].startswith("research and education only")
    assert body["availableViews"] == ["coverage-summary"]


def test_coverage_is_passed_through_verbatim(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    assert coverage["meanTargetDepth"] == 85.2
    assert coverage["targetNonoverlapBases"] == 34567890
    assert coverage["uncoveredBasesPct"] == 0.42
    assert coverage["lowCoverageBasesPct"] == 5.8
    assert coverage["lowCoverageThresholdX"] == 20.0
    assert coverage["uncoveredIntervals"] == 91


def test_breadth_keys_come_from_the_document(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    breadth = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]["breadth"]

    assert list(breadth) == ["1X", "10X", "20X", "30X", "50X", "100X"]
    assert breadth["20X"] == 94.2
    assert breadth["30X"] == 89.0


def test_breadth_adapts_to_a_different_thresholds_list(client, make_job, run):
    """mosdepth --thresholds drives these key names; nothing is hard-coded."""
    builder = run().as_completed_full()
    builder.coverage_metrics(
        **{
            "target_bases_ge_1X_pct": None,
            "target_bases_ge_10X_pct": None,
            "target_bases_ge_20X_pct": None,
            "target_bases_ge_30X_pct": None,
            "target_bases_ge_50X_pct": None,
            "target_bases_ge_100X_pct": None,
            "target_bases_ge_5X_pct": 98.0,
            "target_bases_ge_15X_pct": 95.5,
            "target_bases_ge_200X_pct": 12.5,
        }
    )
    job_id = make_job(run_mode="full")

    breadth = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]["breadth"]
    assert list(breadth) == ["5X", "15X", "200X"]
    assert breadth["200X"] == 12.5


def test_median_stays_null(client, make_job, run):
    """main.sh writes null on purpose; a median must never be invented."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]
    assert coverage["medianTargetDepth"] is None
    assert "no-per-base" in coverage["medianNote"]


def test_missing_coverage_does_not_break_the_response(client, make_job, run):
    builder = run().as_completed_full()
    (builder.run_dir / "05_coverage_qc" / "coverage_metrics.json").unlink()
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] is None
    assert body["availableViews"] == []
    # The rest of the summary is unaffected.
    assert body["variantCalling"]["rawVariantRecords"] == 48210


def test_malformed_coverage_is_500_not_silently_normalised(client, make_job, run):
    builder = run().as_completed_full()
    builder.raw("05_coverage_qc/coverage_metrics.json", "{ not json at all")
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedPipelineDocument"


def test_variant_calling_exposes_only_relative_paths(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")
    variant_calling = response.json()["variantCalling"]

    assert variant_calling["rawVariantRecords"] == 48210
    assert variant_calling["filteringApplied"] is False
    assert variant_calling["coreEndpoint"] == "raw VCF (no filtering applied)"
    assert variant_calling["rawVcfRelative"].startswith("06_variant_calling/")
    assert variant_calling["gvcfRelative"].startswith("06_variant_calling/")
    # variant_calling_output.json also carries absolute server paths under the
    # keys raw_vcf and gvcf. Those values must not appear anywhere.
    # ("raw_vcf" as a *check name* is pipeline vocabulary and is fine.)
    assert "/srv/wes" not in response.text
    assert "\"raw_vcf\":" not in response.text
    for marker in ("C:\\", "/home/", "/Users/", "/tmp/"):
        assert marker not in response.text


def test_full_input_summary_comes_from_core_summary_metrics(client, make_job, run):
    """core_summary.json aggregates every metrics/*.json, including preflight."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    summary = client.get(f"/api/jobs/{job_id}/results").json()["inputSummary"]
    assert summary["assembly"] == "GRCh38"
    assert summary["contigStyle"] == "chr"
    assert summary["captureKitId"] == "idt_xgen_exome_hyb_panel_v2"


def test_full_input_summary_falls_back_to_the_metrics_document(
    client, make_job, run
):
    """An older core_summary without the preflight block still resolves."""
    builder = run().as_completed_full()
    builder.core_summary(metrics={"05_coverage_qc": {"mean_target_depth": 85.2}})
    job_id = make_job(run_mode="full")

    summary = client.get(f"/api/jobs/{job_id}/results").json()["inputSummary"]
    assert summary["assembly"] == "GRCh38"
    assert summary["sample"] == "SRR2962669.subset_5M"


def test_full_check_table_comes_from_finalization(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]
    by_name = {c["name"]: c["status"] for c in checks}
    assert by_name["raw_vcf"] == "PASS"
    assert by_name["analysis_ready_bam"] == "PASS"


def test_full_warnings_carry_their_step(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    warnings = client.get(f"/api/jobs/{job_id}/results").json()["warnings"]
    assert warnings[0]["stepId"] == "01_raw_qc"
    assert warnings[0]["code"] == "MULTIQC_MISSING"


def test_optional_steps_default_to_not_run(client, make_job, run):
    """The backend currently pins filtering and annotation off in the config."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    optional = client.get(f"/api/jobs/{job_id}/results").json()["optionalSteps"]
    assert optional == {
        "08_filtering": "not_run",
        "10_annotation": "not_run",
        "11_intervar": "not_run",
    }


def test_enabled_but_failed_optional_step_is_reported_as_failed(
    client, make_job, run
):
    """The InterVar case: requested, planned, and it failed.

    Reproduces what a run_acmg submission produces today, since the backend
    writes optional_steps.intervar true without an intervar config block.
    """
    builder = run().as_completed_full()
    builder.snapshot(intervar=True)
    builder.step(
        "11_intervar",
        status="failed",
        failures=[
            {
                "code": "intervar_not_installed",
                "message": "intervar.install_dir is not set or does not exist.",
            }
        ],
    )
    job_id = make_job(run_mode="full")

    optional = client.get(f"/api/jobs/{job_id}/results").json()["optionalSteps"]
    assert optional["11_intervar"] == "failed"


def test_enabled_optional_step_never_reached_is_not_run(client, make_job, run):
    builder = run().as_completed_full()
    builder.snapshot(intervar=True)
    job_id = make_job(run_mode="full")

    optional = client.get(f"/api/jobs/{job_id}/results").json()["optionalSteps"]
    assert optional["11_intervar"] == "not_run"


def test_completed_optional_step_with_a_vanished_output_is_file_missing(
    client, make_job, run
):
    builder = run().as_completed_full()
    builder.snapshot(annotation=True)
    builder.step(
        "10_annotation",
        status="completed",
        outputs=[{"type": "variant_tsv", "path": "optional/annotation/gone.tsv"}],
    )
    job_id = make_job(run_mode="full")

    optional = client.get(f"/api/jobs/{job_id}/results").json()["optionalSteps"]
    assert optional["10_annotation"] == "file_missing"


def test_completed_optional_step_with_its_output_present_is_completed(
    client, make_job, run
):
    builder = run().as_completed_full()
    builder.snapshot(annotation=True)
    builder.file("optional/annotation/variants.tsv", "chrom\tpos\n")
    builder.step(
        "10_annotation",
        status="completed",
        outputs=[{"type": "variant_tsv", "path": "optional/annotation/variants.tsv"}],
    )
    job_id = make_job(run_mode="full")

    optional = client.get(f"/api/jobs/{job_id}/results").json()["optionalSteps"]
    assert optional["10_annotation"] == "completed"


# --- not ready --------------------------------------------------------------


def test_running_full_run_without_core_summary_is_409(client, make_job, run):
    builder = run()
    builder.run_status("running", current_step="03_alignment")
    builder.step("00_input_validation")
    job_id = make_job(run_mode="full", status="RUNNING")

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resultsNotReady"


def test_failed_full_run_without_core_summary_is_409(client, make_job, run):
    builder = run()
    builder.run_status(
        "failed",
        steps=[
            {
                "step_id": "03_alignment",
                "status": "failed",
                "exit_code": 1,
                "elapsed_seconds": 12,
                "warnings": 0,
                "failures": 1,
                "next_step_ready": False,
            }
        ],
    )
    builder.step("03_alignment", status="failed",
                 failures=[{"code": "bwa", "message": "bwa exited 1"}])
    job_id = make_job(run_mode="full")

    assert client.get(f"/api/jobs/{job_id}/results").status_code == 409


def test_malformed_core_summary_is_500(client, make_job, run):
    builder = run().as_completed_full()
    builder.raw("core_summary.json", '{"sample": "x", ')
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedPipelineDocument"
    assert "core_summary" not in response.text
    assert str(builder.run_dir) not in response.text


def test_cancelled_run_with_readable_results_is_200(client, make_job, run):
    """Partial results are still results; the status carries the truth."""
    builder = run().as_completed_full()
    job_id = make_job(run_mode="full", status="CANCELLED")

    response = client.get(f"/api/jobs/{job_id}/results")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_results_status_matches_the_job_endpoint(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    job = client.get(f"/api/jobs/{job_id}").json()
    results = client.get(f"/api/jobs/{job_id}/results").json()
    assert job["status"] == results["status"]
    assert job["pipelineStatus"] == results["pipelineStatus"]
