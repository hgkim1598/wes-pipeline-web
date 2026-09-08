"""Runtime facts and shared knowledge meet here for the first time.

The merge has one rule and most of these tests exist to hold it:

    what happened  ->  runtime wins
    what it means  ->  knowledge supplies it

The rule is easy to state and easy to violate by accident, because both halves
describe the same code. `relatedSteps` in particular looks like it answers
"where did this happen" and does not -- MULTIQC_MISSING can be raised from two
different steps, so only the run knows which one applies.

The rest of the suite covers the cases where being wrong would be worse than
being silent: an unregistered code, a run with no results, and any statement
that would let unfiltered variants read as final ones.
"""

from __future__ import annotations

import pytest

from ..services import worker
from ..services.explanation import deterministic, run_context


def context_of(job_id: str):
    return run_context.build_run_diagnostic_context(job_id)


def explain(job_id: str):
    return deterministic.build_run_explanation(context_of(job_id))


# --- merge rule -------------------------------------------------------------


def test_known_repaired_diagnostic_keeps_both_halves(client, make_job, run):
    """NM_MD_REPAIRED is the one entry that exercises both axes at once.

    severity=info and resolution=repaired together mean "worth knowing, already
    handled". Collapsing them into a single value would lose exactly that case.
    """
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
    builder.run_status("failed", steps=[{"step_id": "04_processing", "status": "warning"}])
    result = explain(make_job(run_mode="full", status=worker.EXEC_FAILED))

    item = next(d for d in result.diagnostics if d.code == "NM_MD_REPAIRED")

    # knowledge half
    assert item.knowledgeAvailable is True
    assert item.severity == "info"
    assert item.resolution == "repaired"
    assert item.knowledgeStatus == "active"
    assert item.title
    assert item.meaning

    # runtime half, untouched
    assert item.actualStepId == "04_processing"
    assert item.message == "NM and MD tags were recalculated with samtools calmd"
    assert item.impact == "Only the NM and MD tags changed"
    assert item.canContinue is True

    # convenience, from step knowledge
    assert item.actualStepLabel == "BAM 정리·보정"


def test_runtime_step_wins_over_knowledge_related_steps(client, make_job, run):
    """The rule that is easiest to break.

    The fixture raises NM_MD_REPAIRED from a step its knowledge entry does not
    list. `relatedSteps` says where a code CAN occur; only the run says where it
    did. If the merge ever preferred knowledge, actualStepId would come back as
    04_processing here.
    """
    entry = deterministic.knowledge.diagnostic("NM_MD_REPAIRED")
    assert entry is not None
    assert entry.relatedSteps == ["04_processing"]

    builder = run()
    builder.step(
        "06_variant_calling",
        status="warning",
        warnings=[
            {
                "code": "NM_MD_REPAIRED",
                "message": "raised somewhere else in this run",
                "impact": "",
                "can_continue": True,
            }
        ],
    )
    builder.run_status(
        "failed", steps=[{"step_id": "06_variant_calling", "status": "warning"}]
    )
    result = explain(make_job(run_mode="full", status=worker.EXEC_FAILED))

    item = next(d for d in result.diagnostics if d.code == "NM_MD_REPAIRED")
    assert item.actualStepId == "06_variant_calling"
    assert item.actualStepLabel == "변이 검출"
    assert item.message == "raised somewhere else in this run"


def test_unknown_code_does_not_break_the_explanation(client, make_job, run):
    """A pipeline code can be added before the knowledge entry exists.

    The runtime facts must survive intact and nothing may be guessed to fill
    the gap: an invented severity would be indistinguishable from a real one.
    """
    builder = run()
    builder.step(
        "04_processing",
        status="warning",
        warnings=[
            {
                "code": "BRAND_NEW_PIPELINE_CODE",
                "message": "something the registry has never seen",
                "impact": "unknown to the registry",
                "can_continue": False,
            }
        ],
    )
    builder.run_status("failed", steps=[{"step_id": "04_processing", "status": "warning"}])
    result = explain(make_job(run_mode="full", status=worker.EXEC_FAILED))

    item = next(d for d in result.diagnostics if d.code == "BRAND_NEW_PIPELINE_CODE")
    assert item.knowledgeAvailable is False
    assert item.severity is None
    assert item.resolution is None
    assert item.title is None
    assert item.meaning is None
    assert item.knowledgeStatus is None

    # runtime survives
    assert item.actualStepId == "04_processing"
    assert item.message == "something the registry has never seen"
    assert item.impact == "unknown to the registry"
    assert item.canContinue is False


# --- ordering ---------------------------------------------------------------


def _warn(code: str, message: str = "m") -> dict:
    return {"code": code, "message": message, "impact": "", "can_continue": True}


def test_attention_sorts_before_unknown_and_info(client, make_job, run):
    """Ordering only. It is not a severity claim about the unknown code --
    `severity` stays None -- but burying a new code under routine notes would
    be the wrong default."""
    builder = run()
    builder.step(
        "05_coverage_qc",
        status="warning",
        warnings=[
            _warn("DBSNP_NOT_CONFIGURED"),          # info
            _warn("SOME_UNREGISTERED_CODE"),        # unknown
            _warn("ZERO_COVERAGE_TARGET_BASES"),    # attention
        ],
    )
    builder.run_status("failed", steps=[{"step_id": "05_coverage_qc", "status": "warning"}])
    result = explain(make_job(run_mode="full", status=worker.EXEC_FAILED))

    assert [d.code for d in result.diagnostics] == [
        "ZERO_COVERAGE_TARGET_BASES",
        "SOME_UNREGISTERED_CODE",
        "DBSNP_NOT_CONFIGURED",
    ]


def test_sort_is_stable_within_a_severity(client, make_job, run):
    """Equal rank keeps the pipeline's own order."""
    builder = run()
    builder.step(
        "10_annotation",
        status="warning",
        warnings=[
            _warn("CLINVAR_MISSING"),
            _warn("CLINVAR_INCOMPATIBLE"),
            _warn("CLINVAR_ANNOTATE_FAILED"),
        ],
    )
    builder.run_status("failed", steps=[{"step_id": "10_annotation", "status": "warning"}])
    # 10_annotation is optional and absent from the default plan. The assembler
    # only reads steps the run planned, so it has to be planned here.
    result = explain(
        make_job(
            run_mode="full",
            status=worker.EXEC_FAILED,
            planned=["00_input_validation", "10_annotation", "99_finalization"],
        )
    )

    assert all(d.severity == "attention" for d in result.diagnostics)
    assert [d.code for d in result.diagnostics] == [
        "CLINVAR_MISSING",
        "CLINVAR_INCOMPATIBLE",
        "CLINVAR_ANNOTATE_FAILED",
    ]


def test_the_same_context_always_explains_the_same_way(client, make_job, run):
    """Determinism is the property that makes this layer worth having."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    first = explain(job_id)
    second = explain(job_id)
    assert first.model_dump() == second.model_dump()


# --- checks stay separate from warnings ------------------------------------


def test_check_summary_counts_without_inventing_diagnostics(
    client, make_job, run
):
    """A WARN row does not say which warning. No diagnostic may be built from
    one, so the counts and the diagnostic list are independent."""
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    assert result.checkSummary.total == 11
    assert result.checkSummary.counts == {"PASS": 8, "WARN": 3}
    # Only the rows that are not PASS are carried forward, verbatim.
    assert {c.name for c in result.checkSummary.notable} == {
        "step_04_processing",
        "step_05_coverage_qc",
        "step_06_variant_calling",
    }

    # None of those names became a diagnostic.
    assert "step_04_processing" not in {d.code for d in result.diagnostics}
    assert [d.code for d in result.diagnostics] == ["MULTIQC_MISSING"]


# --- full run ---------------------------------------------------------------


def test_full_run_keeps_coverage_units_unchanged(client, make_job, run):
    """Coverage is passed through, not re-derived. Re-deriving would create a
    second place where base-level and interval-level could be confused."""
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    cov = result.coverage
    assert cov is not None
    assert cov.zeroCoverageBasesPct == 0.9
    assert cov.basesInFullyUncoveredIntervalsPct == 0.42
    assert cov.basesInFullyUncoveredIntervalsPct < cov.zeroCoverageBasesPct
    assert cov.medianTargetDepth is None


def test_unfiltered_variants_produce_a_limitation(client, make_job, run):
    """52,379 records must never read as a final variant list.

    The limitation is selected by filteringApplied being False and names that
    field as its basis, so it can be checked against the run rather than
    trusted.
    """
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    assert result.variantCalling is not None
    assert result.variantCalling.filteringApplied is False

    limitation = next(
        limit for limit in result.limitations if limit.code == "UNFILTERED_VARIANTS"
    )
    assert limitation.basis == "variantCalling.filteringApplied"
    assert "품질 필터가 적용되지 않았습니다" in limitation.statement
    assert result.variantCalling.coreEndpoint in limitation.statement


def test_intended_use_is_carried_verbatim(client, make_job, run):
    """The pipeline's own scope statement, not a rewrite of it."""
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    limitation = next(
        limit for limit in result.limitations if limit.code == "INTENDED_USE"
    )
    assert limitation.statement == result.intendedUse
    assert "research" in limitation.statement


def test_no_quality_verdict_is_produced(client, make_job, run):
    """This layer reports; it does not grade.

    Deciding whether coverage is adequate needs thresholds this project has not
    established. A verdict here would put a number behind an opinion.
    """
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    text = " ".join(limit.statement for limit in result.limitations)
    for verdict in ("충분", "양호", "우수", "나쁨", "불충분", "권장", "해야 합니다"):
        assert verdict not in text, verdict
    # No scoring field exists at all.
    assert "score" not in result.model_dump()


# --- failed / precheck / in-progress ---------------------------------------


def test_failed_run_explains_failures_without_inventing_sections(
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
    result = explain(make_job(run_mode="full", status=worker.EXEC_FAILED))

    assert result.contextKind == "failed"
    assert len(result.failures) == 1
    failure = result.failures[0]
    # Dynamic code, kept as written. No knowledge lookup is attempted.
    assert failure.code == "sort_order_DEMO_WES.L001"
    assert failure.message == "@HD does not report SO:coordinate"
    assert failure.actualStepId == "03_alignment"
    assert failure.actualStepLabel == "참조 유전체 정렬"

    assert result.coverage is None
    assert result.variantCalling is None
    assert result.intendedUse is None


def test_precheck_is_not_explained_as_a_full_analysis(client, make_job, run):
    run().as_passing_precheck()
    result = explain(make_job())

    assert result.contextKind == "precheck"
    assert result.coverage is None
    assert result.variantCalling is None
    # The absence of analysis output is stated, not left to be inferred.
    limitation = next(
        limit for limit in result.limitations if limit.code == "NO_ANALYSIS_OUTPUT"
    )
    assert limitation.basis == "outcome.analysisOutputProduced"
    assert not any(limit.code == "UNFILTERED_VARIANTS" for limit in result.limitations)


def test_no_analysis_output_does_not_claim_the_run_was_a_precheck(
    client, make_job, run
):
    """analysisOutputProduced=False does not mean --check-only.

    result_reader derives it from core_summary.core_complete for a full run,
    and core_summary.json is written by write_final_report *before*
    finalization can fail. So a full run whose raw VCF went missing lands here
    too, and describing it as a precheck would be wrong.

    The fixture is that run: run_mode=full, core_complete=False.
    """
    builder = run().as_completed_full()
    builder.core_summary(core_complete=False)
    result = explain(make_job(run_mode="full"))

    assert result.contextKind == "full"
    assert result.identity.runMode == "full"

    limitation = next(
        limit for limit in result.limitations if limit.code == "NO_ANALYSIS_OUTPUT"
    )
    assert limitation.basis == "outcome.analysisOutputProduced"
    # States what the field establishes, and nothing about the run mode.
    assert "사전 점검" not in limitation.statement
    assert limitation.statement == "이 실행은 분석 산출물(BAM·VCF)을 만들지 않았습니다."


def test_every_limitation_basis_names_a_field_that_exists(client, make_job, run):
    """`basis` is what makes a statement checkable.

    A basis naming a field the rule does not actually test would look like
    provenance while providing none -- MEDIAN_NOT_MEASURED pointed at
    medianTargetDepth (always null) while being selected by medianNote.
    """
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    payload = result.model_dump()
    for limitation in result.limitations:
        cursor = payload
        for part in limitation.basis.split("."):
            assert isinstance(cursor, dict), limitation.code
            assert part in cursor, f"{limitation.code} basis {limitation.basis}"
            cursor = cursor[part]

    median = next(
        limit for limit in result.limitations if limit.code == "MEDIAN_NOT_MEASURED"
    )
    assert median.basis == "coverage.medianNote"
    assert result.coverage is not None
    assert result.coverage.medianNote in median.statement


def test_in_progress_run_is_not_explained_as_failed(client, make_job, run):
    """A run still going and a run that failed both lack results, for different
    reasons. Saying the wrong one is a factual error, not a thin explanation."""
    builder = run()
    builder.step("00_input_validation", status="completed")
    builder.run_status(
        "running",
        current_step="03_alignment",
        steps=[{"step_id": "00_input_validation", "status": "completed"}],
    )
    result = explain(make_job(run_mode="full", status=worker.RUNNING))

    assert result.contextKind == "in_progress"
    assert result.status == "running"
    assert result.failures == []
    assert any(limit.code == "RUN_IN_PROGRESS" for limit in result.limitations)


def test_a_queued_run_is_not_described_as_running(client, make_job, run):
    """in_progress covers `queued` as well.

    A queued job has no run directory, so run_status_reader returns None and
    the status falls back to "queued". Saying such a run is "진행 중" would
    claim it had started.
    """
    result = explain(make_job(run_mode="full", status=worker.QUEUED))

    assert result.contextKind == "in_progress"
    assert result.status == "queued"

    limitation = next(
        limit for limit in result.limitations if limit.code == "RUN_IN_PROGRESS"
    )
    assert "진행 중" not in limitation.statement
    assert limitation.statement == "이 실행은 아직 끝나지 않아 결과가 확정되지 않았습니다."


# --- evidence and safety ----------------------------------------------------


def test_each_item_can_be_traced_back(client, make_job, run):
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    item = result.diagnostics[0]
    assert item.evidence.section == "warnings"
    assert item.evidence.code == item.code
    assert item.evidence.stepId == item.actualStepId
    assert item.evidence.source == "result_reader"
    # The context's section-to-reader map survives at the top level too.
    assert result.sources["identity"] == "db.jobs"


def test_explanation_carries_no_logs_or_server_paths(client, make_job, run):
    """Same guard as the context. A later field must not reintroduce a leak."""
    run().as_completed_full()
    result = explain(make_job(run_mode="full"))

    payload = result.model_dump_json()
    assert "logTail" not in payload
    assert "/home/" not in payload
    assert "run_dir" not in payload


def test_shared_knowledge_source_was_not_modified():
    """This step reads knowledge; enriching it is a separate piece of work.

    If the deterministic layer needed a cause or an action field, the honest
    move is to add it deliberately -- not to discover later that it appeared
    while something else was being built.
    """
    entry = deterministic.knowledge.diagnostic("NM_MD_REPAIRED")
    assert entry is not None
    assert set(entry.model_dump()) == {
        "code",
        "severity",
        "resolution",
        "relatedSteps",
        "status",
        "title",
        "meaning",
    }


@pytest.mark.parametrize(
    "code", ["ZERO_COVERAGE_TARGET_BASES", "DBSNP_NOT_CONFIGURED", "UNCOVERED_TARGETS"]
)
def test_representative_codes_resolve(code):
    """Spot check across the severity axis and the legacy flag."""
    entry = deterministic.knowledge.diagnostic(code)
    assert entry is not None
    assert entry.severity in ("attention", "info")
