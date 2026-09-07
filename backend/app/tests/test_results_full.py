"""GET /api/jobs/{id}/results for a full run.

No full run has executed on real resources yet, so these fixtures are built
from the writer code in script/main.sh rather than from observed output. That
is recorded as an assumption: once a real full run exists, the fixtures must be
diffed against it before these tests are trusted as a contract.

Coverage numbers are passed through exactly as mosdepth and main.sh produced
them. Nothing here recomputes a depth, a breadth or a median.
"""

from __future__ import annotations

import pytest


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
    # base level
    assert coverage["zeroCoverageBases"] == 311111
    assert coverage["zeroCoverageBasesPct"] == 0.9
    # interval level
    assert coverage["basesInLowMeanDepthIntervalsPct"] == 5.8
    assert coverage["lowMeanDepthThresholdX"] == 20.0
    assert coverage["lowMeanDepthIntervals"] == 812
    assert coverage["basesInLowMeanDepthIntervals"] == 200000
    assert coverage["fullyUncoveredIntervals"] == 91
    assert coverage["basesInFullyUncoveredIntervals"] == 14500
    assert coverage["basesInFullyUncoveredIntervalsPct"] == 0.42


def test_zero_coverage_pct_is_the_complement_of_1x_breadth(client, make_job, run):
    """The base-level identity that gives zeroCoverageBasesPct its meaning.

    zero_coverage_bases_pct = 100 - target_bases_ge_1X_pct

    Both come from the same thresholds.bed.gz counts, so they must agree. If
    this drifts, one of the two is being computed from the wrong denominator.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    assert coverage["zeroCoverageBasesPct"] == pytest.approx(
        100.0 - coverage["breadth"]["1X"], abs=1e-4
    )


def test_zero_coverage_count_matches_its_own_percentage(client, make_job, run):
    """The count and the percentage describe the same bases.

    Guards against the count being derived from a rounded percentage, or the
    two being taken from different denominators.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    derived = 100.0 * coverage["zeroCoverageBases"] / coverage["targetNonoverlapBases"]
    assert derived == pytest.approx(coverage["zeroCoverageBasesPct"], abs=1e-3)


def test_interval_and_base_measures_are_not_the_same_number(client, make_job, run):
    """The distinction this whole metric rename exists for.

    A partially covered interval has a mean above 0, so it is NOT a fully
    uncovered interval -- yet the 0x bases inside it still count towards the
    base-level measure. The interval measure therefore understates zero
    coverage and the two must never be substituted for one another.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    assert coverage["basesInFullyUncoveredIntervalsPct"] == 0.42
    assert coverage["zeroCoverageBasesPct"] == 0.9
    assert (
        coverage["basesInFullyUncoveredIntervalsPct"]
        < coverage["zeroCoverageBasesPct"]
    )


# --- legacy runs ------------------------------------------------------------
#
# Runs written before the rename only have the old interval-level keys. They
# must keep reading, and the old keys must not be re-interpreted as base-level
# numbers.


def test_legacy_run_maps_old_interval_keys_to_the_new_names(client, make_job, run):
    builder = run().as_completed_full()
    builder.legacy_coverage_metrics()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    # Same measurement, new name. This is a rename bridge.
    assert coverage["lowMeanDepthThresholdX"] == 20.0
    assert coverage["lowMeanDepthIntervals"] == 812
    assert coverage["basesInLowMeanDepthIntervals"] == 200000
    assert coverage["basesInLowMeanDepthIntervalsPct"] == 5.8
    assert coverage["fullyUncoveredIntervals"] == 91
    assert coverage["basesInFullyUncoveredIntervals"] == 14500
    assert coverage["basesInFullyUncoveredIntervalsPct"] == 0.42


def test_legacy_run_derives_zero_coverage_pct_from_1x_breadth(client, make_job, run):
    """The percentage is recoverable from 1X breadth; the count is not."""
    builder = run().as_completed_full()
    builder.legacy_coverage_metrics()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    assert coverage["zeroCoverageBasesPct"] == pytest.approx(0.9, abs=1e-4)
    # Never invented from a rounded percentage.
    assert coverage["zeroCoverageBases"] is None


def test_legacy_uncovered_bases_pct_is_never_read_as_zero_coverage(
    client, make_job, run
):
    """The one mapping that must not happen.

    `uncovered_bases_pct` is interval level. Mapping it onto
    zeroCoverageBasesPct would silently understate zero coverage -- exactly the
    confusion this change removes. Here the legacy document has 0.42 for the
    interval measure and 99.1 for 1X breadth, so the two candidate answers are
    distinguishable: 0.9 is correct, 0.42 is the bug.
    """
    builder = run().as_completed_full()
    builder.legacy_coverage_metrics()
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    assert coverage["zeroCoverageBasesPct"] != 0.42


def test_legacy_run_without_1x_breadth_leaves_zero_coverage_null(
    client, make_job, run
):
    """No 1X column, no honest way to derive it. Null, not a guess."""
    builder = run().as_completed_full()
    builder.legacy_coverage_metrics(**{"target_bases_ge_1X_pct": None})
    job_id = make_job(run_mode="full")

    coverage = client.get(f"/api/jobs/{job_id}/results").json()["coverage"]

    assert coverage["zeroCoverageBasesPct"] is None
    assert coverage["zeroCoverageBases"] is None


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


def test_full_check_table_comes_from_final_validation_tsv(client, make_job, run):
    """The full run's table is final_validation.tsv, not the step document.

    main.sh records the three verdicts through vpass / vwarn / vfail, and only
    vpass and vfail also call step_check_*. The WARN rows therefore exist only
    in the TSV. Reading the step document returned a table that was silently
    short by every warning.

    The fixture makes the two sources differ on purpose: the TSV has 11 rows,
    the 99_finalization document has 2.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]

    assert len(checks) == 11
    by_status: dict[str, int] = {}
    for check in checks:
        by_status[check["status"]] = by_status.get(check["status"], 0) + 1
    assert by_status == {"PASS": 8, "WARN": 3}


def test_full_check_table_includes_the_warn_rows(client, make_job, run):
    """The rows the old implementation dropped."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]
    by_name = {c["name"]: c for c in checks}

    for step_id in ("step_04_processing", "step_05_coverage_qc", "step_06_variant_calling"):
        assert by_name[step_id]["status"] == "WARN", step_id
        assert by_name[step_id]["detail"] == "completed with warnings (core)"

    # PASS rows are still there, with their detail intact.
    assert by_name["raw_vcf"]["status"] == "PASS"
    assert by_name["analysis_ready_bam"]["status"] == "PASS"
    assert by_name["raw_vcf"]["detail"] == "present"


def test_a_warn_check_is_never_reported_as_pass(client, make_job, run):
    """Guard against 'fixing' the count by relabelling."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]

    assert {c["name"] for c in checks if c["status"] == "PASS"}.isdisjoint(
        {"step_04_processing", "step_05_coverage_qc", "step_06_variant_calling"}
    )


def test_checks_and_warnings_stay_separate_contracts(client, make_job, run):
    """A WARN row in `checks` does not replace or duplicate `warnings`.

    They answer different questions:

        checks    the final validation table: name / status / detail
        warnings  structured diagnostics: code / message / impact / canContinue

    A WARN row naming a step is not the same object as the diagnostic that
    made that step warn, and neither is derivable from the other.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/results").json()

    warn_checks = [c for c in body["checks"] if c["status"] == "WARN"]
    assert warn_checks, "the fixture must produce WARN rows"
    assert body["warnings"], "warnings must survive alongside them"

    # Different shapes, not two views of one list.
    assert set(warn_checks[0]) == {"name", "status", "detail"}
    assert set(body["warnings"][0]) == {
        "stepId",
        "code",
        "message",
        "impact",
        "canContinue",
    }
    assert body["warnings"][0]["code"] == "MULTIQC_MISSING"


def test_step_detail_still_reports_the_step_document(client, make_job, run):
    """GET /steps/99_finalization reports the STEP, not the run.

    It must keep returning the step document's own validation.results even
    though /results now reads the fuller TSV. The two endpoints answer
    different questions and are deliberately not unified.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/99_finalization").json()

    results = body["validation"]["results"]
    assert len(results) == 2
    assert {r["name"] for r in results} == {"raw_vcf", "analysis_ready_bam"}
    assert all(r["status"] == "PASS" for r in results)


# --- legacy and fault handling ----------------------------------------------


def test_missing_final_validation_falls_back_to_the_step_document(
    client, make_job, run
):
    """Runs written before this file was read must keep working.

    Absent file -> fall back. The fallback table is the shorter one, and that
    is the honest answer for such a run: nothing else recorded those rows.
    """
    builder = run().as_completed_full()
    (builder.run_dir / "final_validation.tsv").unlink()
    job_id = make_job(run_mode="full")

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]

    assert len(checks) == 2
    assert {c["name"] for c in checks} == {"raw_vcf", "analysis_ready_bam"}


def test_header_only_final_validation_is_an_empty_table_not_a_fallback(
    client, make_job, run
):
    """Present and well formed but with no rows means the table is empty.

    Falling back here would report a table the run did not write.
    """
    builder = run().as_completed_full()
    builder.final_validation(rows=[])
    job_id = make_job(run_mode="full")

    assert client.get(f"/api/jobs/{job_id}/results").json()["checks"] == []


def test_malformed_final_validation_is_reported_not_hidden(client, make_job, run):
    """A present-but-unusable file is a data fault, like malformed JSON.

    Silently falling back would hide a broken run behind a shorter table that
    still looks valid.
    """
    builder = run().as_completed_full()
    builder.raw("final_validation.tsv", "name\toutcome\tnote\nraw_vcf\tPASS\tpresent\n")
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedPipelineDocument"


def test_truncated_row_is_reported_as_malformed(client, make_job, run):
    """A partial row is a damaged table, not a shorter one.

    main.sh appends here without an atomic replace, so a crash mid-write can
    leave an incomplete final line. Skipping it would return a table that
    looks complete while understating the verdict -- and the row most likely
    lost is a WARN or FAIL, which is the same silent omission this whole fix
    exists to remove.
    """
    builder = run().as_completed_full()
    builder.raw(
        "final_validation.tsv",
        "check\tstatus\tdetail\nraw_vcf\tPASS\tpresent\nstep_04_proc",
    )
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedPipelineDocument"


def test_row_without_a_check_name_is_reported_as_malformed(client, make_job, run):
    """Same rule for a row this reader cannot represent for another reason.

    A nameless row cannot be shown or matched, so dropping it would be the
    same silent loss by a different route.
    """
    builder = run().as_completed_full()
    builder.raw(
        "final_validation.tsv",
        "check\tstatus\tdetail\nraw_vcf\tPASS\tpresent\n\tWARN\tno name\n",
    )
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/results")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedPipelineDocument"


def test_blank_lines_are_still_ignored(client, make_job, run):
    """A blank line carries no verdict, so it is not damage."""
    builder = run().as_completed_full()
    builder.raw(
        "final_validation.tsv",
        "check\tstatus\tdetail\n\nraw_vcf\tPASS\tpresent\n\nstep_04\tWARN\twarned\n\n",
    )
    job_id = make_job(run_mode="full")

    checks = client.get(f"/api/jobs/{job_id}/results").json()["checks"]

    assert checks == [
        {"name": "raw_vcf", "status": "PASS", "detail": "present"},
        {"name": "step_04", "status": "WARN", "detail": "warned"},
    ]


def test_precheck_checks_are_unchanged(client, make_job, run):
    """A check-only run still reports 00_input_validation's own table.

    final_validation.tsv belongs to finalization, which a precheck never
    reaches. This contract is untouched.
    """
    run().as_passing_precheck()
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/results").json()

    assert body["resultType"] == "precheck"
    names = {c["name"] for c in body["checks"]}
    assert names
    assert "raw_vcf" not in names


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
