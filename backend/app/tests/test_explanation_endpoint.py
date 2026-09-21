"""GET /api/jobs/{id}/explanation must expose the service output, unchanged.

The route is deliberately three calls deep and adds nothing. These tests pin
that: whatever build_run_explanation produces for a job is what the endpoint
returns, field for field. If the route ever starts computing something, the
deterministic tests would no longer cover what users actually receive.

The other half is status codes. A failed run, a run still going and a
check-only run are all legitimate explanations -- returning 4xx for any of them
would hide exactly the case a reader needs most.
"""

from __future__ import annotations

from ..services import worker
from ..services.explanation import deterministic, run_context


def explanation(client, job_id: str):
    response = client.get(f"/api/jobs/{job_id}/explanation")
    assert response.status_code == 200, response.text
    return response.json()


# --- the route adds nothing -------------------------------------------------


def test_endpoint_returns_the_service_output_verbatim(client, make_job, run):
    """The strongest guarantee available: compare against the service directly."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    from_service = deterministic.build_run_explanation(
        run_context.build_run_diagnostic_context(job_id)
    )
    from_http = explanation(client, job_id)

    assert from_http == from_service.model_dump()


def test_response_carries_the_expected_sections(client, make_job, run):
    run().as_completed_full()
    body = explanation(client, make_job(run_mode="full"))

    assert set(body) == {
        "contextKind",
        "status",
        "resultsAvailable",
        "resultsUnavailableReason",
        "identity",
        "checkSummary",
        # Added when the synthesis layer gained a step-detail tool: an agent
        # that may open one step has to be told which step ids exist, and the
        # deterministic explanation is where that list is carried (stepId,
        # status, elapsedSeconds -- no detail). It is additive for this GET;
        # the same three values are already in GET /api/jobs/{id}.
        "steps",
        "diagnostics",
        "failures",
        "coverage",
        "variantCalling",
        "limitations",
        "intendedUse",
        "sources",
    }


# --- the four run kinds are all 200 ----------------------------------------


def test_full_run(client, make_job, run):
    run().as_completed_full()
    body = explanation(client, make_job(run_mode="full"))

    assert body["contextKind"] == "full"
    assert body["resultsAvailable"] is True
    assert body["checkSummary"]["counts"] == {"PASS": 8, "WARN": 3}
    assert body["coverage"] is not None
    assert body["variantCalling"]["filteringApplied"] is False
    assert any(
        limit["code"] == "UNFILTERED_VARIANTS" for limit in body["limitations"]
    )


def test_failed_run_is_200_not_an_error(client, make_job, run):
    """/results 409s for this run. This endpoint is the one that can describe it."""
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
    job_id = make_job(run_mode="full", status=worker.EXEC_FAILED)

    # The contrast that motivates this endpoint.
    assert client.get(f"/api/jobs/{job_id}/results").status_code == 409

    body = explanation(client, job_id)
    assert body["contextKind"] == "failed"
    assert body["resultsAvailable"] is False
    assert body["failures"][0]["code"] == "sort_order_DEMO_WES.L001"
    assert body["failures"][0]["actualStepId"] == "03_alignment"
    assert body["failures"][0]["actualStepLabel"] == "참조 유전체 정렬"
    # Nothing invented to fill the gap.
    assert body["coverage"] is None
    assert body["variantCalling"] is None


def test_precheck_run(client, make_job, run):
    run().as_passing_precheck()
    body = explanation(client, make_job())

    assert body["contextKind"] == "precheck"
    assert body["coverage"] is None
    assert any(
        limit["code"] == "NO_ANALYSIS_OUTPUT" for limit in body["limitations"]
    )


def test_in_progress_run(client, make_job, run):
    builder = run()
    builder.step("00_input_validation", status="completed")
    builder.run_status(
        "running",
        current_step="03_alignment",
        steps=[{"step_id": "00_input_validation", "status": "completed"}],
    )
    body = explanation(client, make_job(run_mode="full", status=worker.RUNNING))

    assert body["contextKind"] == "in_progress"
    assert body["status"] == "running"
    assert body["failures"] == []
    assert any(limit["code"] == "RUN_IN_PROGRESS" for limit in body["limitations"])


# --- errors -----------------------------------------------------------------


def test_unknown_job_is_404(client, env):
    response = client.get("/api/jobs/wes-does-not-exist/explanation")
    assert response.status_code == 404


def test_malformed_job_id_is_400(client, env):
    response = client.get("/api/jobs/..%2Fetc/explanation")
    assert response.status_code in (400, 404)


def test_malformed_pipeline_document_is_500(client, make_job, run):
    """A data fault is reported, not turned into a thinner-looking explanation."""
    builder = run().as_completed_full()
    builder.raw("core_summary.json", "{not json")
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/explanation")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedPipelineDocument"


# --- safety -----------------------------------------------------------------


def test_response_leaks_no_server_paths(client, make_job, run):
    run().as_completed_full()
    response = client.get(f"/api/jobs/{make_job(run_mode='full')}/explanation")

    assert "logTail" not in response.text
    assert "/home/" not in response.text
    assert "run_dir" not in response.text
