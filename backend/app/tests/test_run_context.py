"""RunDiagnosticContext must carry runtime facts without distorting them.

This is the assembler that a later explanation layer -- deterministic first,
LLM after that -- will read instead of the raw endpoints. Everything it drops
or blurs here becomes something an explanation cannot say, or says wrongly.

Three properties are worth more than field-by-field coverage and most of these
tests are about them:

  the run kind is explicit      a missing coverage section means something
                                different for a precheck, a failed run and a
                                run still in flight
  checks and warnings stay apart  neither is derivable from the other
  the qualifiers survive        filteringApplied, coreEndpoint, intendedUse and
                                the meaningful nulls in coverage
"""

from __future__ import annotations

import json

import pytest

from ..api import jobs as jobs_api
from ..services import worker
from ..services.explanation import run_context


def build(job_id: str):
    return run_context.build_run_diagnostic_context(job_id)


# --- unknown job ------------------------------------------------------------


def test_unknown_job_raises(env):
    with pytest.raises(run_context.JobNotFound):
        build("wes-does-not-exist")


def test_fallback_table_matches_the_api_layer():
    """Two copies of the same mapping would drift.

    The service cannot import the API module (a service depending on a route
    module inverts the layering), so the table is duplicated deliberately and
    pinned here instead.
    """
    assert run_context._FALLBACK_STATUS == jobs_api._FALLBACK_STATUS


# --- full run ---------------------------------------------------------------


def test_full_run_is_marked_full_and_has_results(client, make_job, run):
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    assert ctx.contextKind == "full"
    assert ctx.resultsAvailable is True
    assert ctx.resultsUnavailableReason is None
    assert ctx.outcome.analysisOutputProduced is True


def test_full_run_keeps_checks_and_warnings_separate(client, make_job, run):
    """A WARN row says a step finished with warnings. A warning says which one
    and why. Collapsing either into the other loses the half the user needs."""
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    warn_rows = [c for c in ctx.checks if c.status == "WARN"]
    assert warn_rows, "the fixture must produce WARN check rows"
    assert ctx.warnings, "warnings must survive alongside them"

    # Different shapes, not two views of one list.
    assert set(warn_rows[0].model_dump()) == {"name", "status", "detail"}
    assert set(ctx.warnings[0].model_dump()) == {
        "stepId",
        "code",
        "message",
        "impact",
        "canContinue",
    }


def test_full_run_preserves_warning_codes_and_run_specific_text(
    client, make_job, run
):
    """message and impact are this occurrence's text, not general knowledge."""
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    by_code = {w.code: w for w in ctx.warnings}
    assert "MULTIQC_MISSING" in by_code
    warning = by_code["MULTIQC_MISSING"]
    assert warning.stepId == "01_raw_qc"
    assert warning.message
    assert warning.impact


def test_full_run_keeps_coverage_units_apart(client, make_job, run):
    """Base level and interval level are different measurements.

    The fixture is built so they disagree; if the assembler ever collapsed them
    the two would come out equal.
    """
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    cov = ctx.coverage
    assert cov is not None
    assert cov.zeroCoverageBasesPct == 0.9
    assert cov.basesInFullyUncoveredIntervalsPct == 0.42
    assert cov.basesInFullyUncoveredIntervalsPct < cov.zeroCoverageBasesPct
    assert cov.lowMeanDepthThresholdX == 20.0
    assert cov.lowMeanDepthIntervals == 812
    assert cov.breadth["20X"] == 94.2


def test_coverage_nulls_are_preserved_not_zeroed(client, make_job, run):
    """medianTargetDepth null means 'not measured', not 'zero'.

    mosdepth runs with --no-per-base, so the value was never materialised and
    medianNote carries the pipeline's own reason. Substituting 0 would invent a
    measurement.
    """
    builder = run().as_completed_full()
    builder.legacy_coverage_metrics()
    ctx = build(make_job(run_mode="full"))

    cov = ctx.coverage
    assert cov is not None
    assert cov.medianTargetDepth is None
    assert "no-per-base" in (cov.medianNote or "")
    # A legacy run cannot supply the count, only the percentage.
    assert cov.zeroCoverageBases is None
    assert cov.zeroCoverageBasesPct == pytest.approx(0.9, abs=1e-4)


def test_full_run_keeps_variant_calling_qualifiers(client, make_job, run):
    """A record count alone reads as a final variant list.

    filteringApplied and coreEndpoint are what stop that reading, so they must
    reach the context intact.
    """
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    vc = ctx.variantCalling
    assert vc is not None
    assert vc.filteringApplied is False
    assert "no filtering applied" in vc.coreEndpoint
    assert vc.rawVariantRecords is not None


def test_full_run_keeps_intended_use(client, make_job, run):
    """The pipeline's own scope statement. Nothing downstream should have to
    invent the research-use boundary."""
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    assert ctx.intendedUse
    assert "research" in ctx.intendedUse


def test_full_run_reports_optional_steps(client, make_job, run):
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    assert ctx.optionalSteps == {
        "08_filtering": "not_run",
        "10_annotation": "not_run",
        "11_intervar": "not_run",
    }


# --- failed run -------------------------------------------------------------


def test_failed_run_builds_without_a_result_document(client, make_job, run):
    """The case the whole kind field exists for.

    /results is 409 for a run that failed before finalization, because
    core_summary.json is only written there. The context must still assemble --
    this is the run an explanation is most needed for.
    """
    builder = run()
    builder.step(
        "03_alignment",
        status="failed",
        checks=[
            {
                "name": "sort_order_DEMO_WES.L001",
                "status": "FAIL",
                "detail": "@HD does not report SO:coordinate",
            }
        ],
        failures=[
            {
                "code": "sort_order_DEMO_WES.L001",
                "message": "@HD does not report SO:coordinate",
            }
        ],
    )
    builder.run_status(
        "failed",
        steps=[
            {
                "step_id": "03_alignment",
                "status": "failed",
                "exit_code": 1,
                "elapsed_seconds": 52,
                "warnings": 0,
                "failures": 1,
                "next_step_ready": False,
            }
        ],
    )
    ctx = build(make_job(run_mode="full", status=worker.EXEC_FAILED))

    assert ctx.contextKind == "failed"
    assert ctx.resultsAvailable is False
    assert ctx.resultsUnavailableReason
    assert ctx.outcome.status == "failed"


def test_failed_run_identifies_the_failed_step_and_its_failure(
    client, make_job, run
):
    builder = run()
    builder.step(
        "03_alignment",
        status="failed",
        failures=[
            {
                "code": "sort_order_DEMO_WES.L001",
                "message": "@HD does not report SO:coordinate",
            }
        ],
    )
    builder.run_status("failed", steps=[{"step_id": "03_alignment", "status": "failed"}])
    ctx = build(make_job(run_mode="full", status=worker.EXEC_FAILED))

    failed_steps = [s.stepId for s in ctx.steps if s.status == "failed"]
    assert failed_steps == ["03_alignment"]

    assert len(ctx.failures) == 1
    failure = ctx.failures[0]
    assert failure.code == "sort_order_DEMO_WES.L001"
    assert failure.message == "@HD does not report SO:coordinate"
    # Step documents leave stepId null; the assembler fills it from the document
    # it actually read. Recording the source of a fact is not distorting it.
    assert failure.stepId == "03_alignment"


def test_failure_code_is_not_constrained_to_an_enum(client, make_job, run):
    """main.sh composes some codes from run values.

    `sort_order_DEMO_WES.L001` is an observed one. A closed enum would reject
    real failures, so the field stays a free string.
    """
    builder = run()
    builder.step(
        "03_alignment",
        status="failed",
        failures=[{"code": "alignment_SOMETHING_ODD.L999", "message": "boom"}],
    )
    builder.run_status("failed", steps=[{"step_id": "03_alignment", "status": "failed"}])
    ctx = build(make_job(run_mode="full", status=worker.EXEC_FAILED))

    assert ctx.failures[0].code == "alignment_SOMETHING_ODD.L999"


def test_failed_run_invents_no_analysis_sections(client, make_job, run):
    """None means 'this run has no such section', not 'measured, found none'."""
    builder = run()
    builder.step("03_alignment", status="failed", failures=[{"code": "x", "message": "y"}])
    builder.run_status("failed", steps=[{"step_id": "03_alignment", "status": "failed"}])
    ctx = build(make_job(run_mode="full", status=worker.EXEC_FAILED))

    assert ctx.coverage is None
    assert ctx.variantCalling is None
    assert ctx.optionalSteps == {}
    assert ctx.intendedUse is None
    assert ctx.outcome.analysisOutputProduced is None


def test_failed_run_collects_warnings_from_step_documents(client, make_job, run):
    """Structured warnings exist only in the step documents when there is no
    result. GET /api/jobs/{id} flattens them into strings, which loses the
    distinction between a warning and a failure."""
    builder = run()
    builder.step(
        "04_processing",
        status="warning",
        warnings=[
            {
                "code": "NM_MD_REPAIRED",
                "message": "NM and MD tags were recalculated with samtools calmd",
                "impact": "Only the NM and MD tags changed",
                "can_continue": True,
            }
        ],
    )
    builder.step("05_coverage_qc", status="failed", failures=[{"code": "boom", "message": "m"}])
    builder.run_status(
        "failed",
        steps=[
            {"step_id": "04_processing", "status": "warning"},
            {"step_id": "05_coverage_qc", "status": "failed"},
        ],
    )
    ctx = build(make_job(run_mode="full", status=worker.EXEC_FAILED))

    codes = {w.code: w for w in ctx.warnings}
    assert "NM_MD_REPAIRED" in codes
    assert codes["NM_MD_REPAIRED"].stepId == "04_processing"
    assert codes["NM_MD_REPAIRED"].canContinue is True
    assert [f.stepId for f in ctx.failures] == ["05_coverage_qc"]


def test_a_run_still_going_is_not_reported_as_failed(client, make_job, run):
    """`in_progress` and `failed` both lack results for different reasons.

    Calling a running job failed would be a factual error, and the explanation
    built on it would be wrong rather than merely thin.
    """
    builder = run()
    builder.step("00_input_validation", status="completed")
    builder.run_status(
        "running",
        current_step="03_alignment",
        steps=[{"step_id": "00_input_validation", "status": "completed"}],
    )
    ctx = build(make_job(run_mode="full", status=worker.RUNNING))

    assert ctx.contextKind == "in_progress"
    assert ctx.resultsAvailable is False
    assert ctx.outcome.status == "running"
    assert ctx.coverage is None


# --- precheck ---------------------------------------------------------------


def test_precheck_is_marked_precheck(client, make_job, run):
    run().as_passing_precheck()
    ctx = build(make_job())

    assert ctx.contextKind == "precheck"
    assert ctx.resultsAvailable is True
    assert ctx.identity.runMode == "check_only"


def test_precheck_produces_no_analysis_output(client, make_job, run):
    """A check-only run executes no analysis tool at all. Presenting it as a
    full result would be the single most misleading thing this layer could do."""
    run().as_passing_precheck()
    ctx = build(make_job())

    assert ctx.outcome.analysisOutputProduced is False
    assert ctx.coverage is None
    assert ctx.variantCalling is None


def test_precheck_keeps_its_own_validation_rows(client, make_job, run):
    """A precheck's verdict is its check table. That is a result, not silence."""
    run().as_passing_precheck()
    ctx = build(make_job())

    assert ctx.checks
    names = {c.name for c in ctx.checks}
    assert "raw_vcf" not in names


# --- provenance and exclusions ---------------------------------------------


def test_sources_distinguish_run_level_from_step_level_facts(
    client, make_job, run
):
    """Not a provenance framework -- just enough that a later reader can tell
    a final validation table from a step's own rows."""
    run().as_completed_full()
    full = build(make_job(run_mode="full"))
    assert full.sources["checks"] == "result_reader"
    assert full.sources["identity"] == "db.jobs"

    builder = run("wes-20260904-172826-68aa20")
    builder.step(
        "03_alignment",
        status="failed",
        checks=[{"name": "sort_order", "status": "FAIL", "detail": "d"}],
        failures=[{"code": "sort_order", "message": "d"}],
    )
    builder.run_status("failed", steps=[{"step_id": "03_alignment", "status": "failed"}])
    failed = build(
        make_job(
            "wes-20260904-172826-68aa20", run_mode="full", status=worker.EXEC_FAILED
        )
    )
    assert failed.sources["checks"].startswith("step documents")
    assert failed.sources["failures"] == "step documents"


def test_context_carries_no_logs_or_server_paths(client, make_job, run):
    """logTail is the one place this API leaks absolute server paths.

    It is excluded for that reason, not to save tokens. The assertion scans the
    serialised context so a future field cannot reintroduce one unnoticed.
    """
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    payload = run_context.as_json(ctx)
    assert "logTail" not in payload
    assert "/home/" not in payload
    assert "C:\\\\" not in payload
    # run_dir is an absolute path on the jobs row and must not be copied in.
    assert "run_dir" not in payload
    assert json.loads(payload)["contextKind"] == "full"


def test_context_does_not_merge_shared_knowledge(client, make_job, run):
    """Runtime facts and meaning stay apart until the explanation step.

    severity / resolution / title / meaning belong to the shared knowledge
    source. Merging them here would make it impossible to say later which half
    a statement came from.
    """
    run().as_completed_full()
    ctx = build(make_job(run_mode="full"))

    warning_fields = set(ctx.warnings[0].model_dump())
    assert warning_fields.isdisjoint({"severity", "resolution", "title", "meaning"})
