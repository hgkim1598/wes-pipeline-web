"""GET /api/jobs/{job_id}/steps/{step_id}.

The point of these tests is that one step's whole story -- what went in, what
the checks said, what it measured, what it produced, and whether the pipeline
was willing to continue -- comes back in one response, and that a step which
has not finished (or has failed) is a normal 200 rather than an error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import step_reader

from .conftest import artifact_file_id

FULL_PLAN = [
    "00_input_validation",
    "01_raw_qc",
    "02_preprocessing",
    "03_alignment",
    "04_processing",
    "05_coverage_qc",
    "06_variant_calling",
    "99_finalization",
]

ALIGNMENT_METRICS = {
    "sample": "SRR2962669.subset_5M",
    "lane_count": 1,
    "total_alignment_records": 41283922,
    "mapped_pct": 99.1,
    "properly_paired_pct": 97.8,
}


def iso_ago(seconds: int) -> str:
    """A stage_status timestamp in main.sh's `date -Is` format."""
    moment = datetime.now(timezone.utc).astimezone() - timedelta(seconds=seconds)
    return moment.replace(microsecond=0).isoformat()


def in_flight(builder, current_step: str, finished: list[str] | None = None):
    """A run that is mid-pipeline, with `current_step` still executing."""
    finished = finished or []
    for step_id in finished:
        builder.step(step_id, elapsed_seconds=30)
    builder.run_status(
        "running",
        current_step=current_step,
        steps=[
            {"step_id": s, "status": "completed", "exit_code": 0, "elapsed_seconds": 30}
            for s in finished
        ],
    )
    return builder


# --- addressing -------------------------------------------------------------


def test_unknown_job_is_404(client):
    response = client.get("/api/jobs/wes-does-not-exist/steps/03_alignment")
    assert response.status_code == 404


def test_step_outside_the_plan_is_404(client, make_job, run):
    """11_intervar is a real main.sh step, but this run never planned it."""
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/steps/11_intervar")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "stepNotPlanned"
    assert detail["plannedSteps"] == FULL_PLAN


def test_check_only_run_plans_one_step(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    assert client.get(f"/api/jobs/{job_id}/steps/00_input_validation").status_code == 200
    assert client.get(f"/api/jobs/{job_id}/steps/03_alignment").status_code == 404


# --- path safety ------------------------------------------------------------


@pytest.mark.parametrize(
    "step_id",
    [
        "..%2F..%2Fetc%2Fpasswd",
        "%2Fetc%2Fpasswd",
        "..%5C..%5Cwindows",
        "%2E%2E%2F%2E%2E%2Fapp.db",
    ],
)
def test_traversal_shaped_step_id_never_returns_a_step(client, make_job, run, step_id):
    """No traversal attempt may come back as a step detail.

    These are rejected by the router before the handler runs, because a decoded
    separator stops the path matching this route at all. The assertion is on
    what the client can observe: never a step body.
    """
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/steps/{step_id}")

    assert response.status_code != 200
    assert "stepId" not in response.text


@pytest.mark.parametrize(
    "step_id", ["../../etc/passwd", "..", "/etc/passwd", "03 alignment", "", "-leading"]
)
def test_service_refuses_a_step_id_that_is_not_one(step_id):
    """The service contract, checked where it is reachable.

    step_reader is the layer that would assemble a path, so it validates the id
    itself rather than trusting the router to have done it.
    """
    with pytest.raises(ValueError):
        step_reader.read(Path("/nonexistent"), FULL_PLAN, "full", step_id)


def test_service_refuses_an_unplanned_step_before_touching_the_disk():
    with pytest.raises(step_reader.StepNotPlanned):
        step_reader.read(Path("/nonexistent"), FULL_PLAN, "full", "11_intervar")


@pytest.mark.parametrize(
    "leaked",
    [
        "/BiO/Access/refs/GRCh38.fa",
        "D:/refs/GRCh38.fa",
        "D:\\refs\\GRCh38.fa",
        "\\\\fileserver\\refs\\GRCh38.fa",
        "C:refs/GRCh38.fa",
    ],
)
def test_absolute_input_path_never_reaches_the_response(client, make_job, run, leaked):
    """main.sh's rel() falls back to the raw path when relpath() raises.

        def rel(p):
            try:    return os.path.relpath(p, run_dir).replace(os.sep, "/")
            except ValueError: return p

    On Windows that happens whenever an input is on another drive than the run
    directory, so a step document can legitimately carry an absolute server
    path. This response must not repeat it.
    """
    builder = run()
    builder.step(
        "03_alignment",
        inputs=[
            {"type": "reference_fasta", "path": leaked},
            {"type": "fastq_manifest", "path": "02_preprocessing/fastq_manifest.tsv"},
        ],
    )
    builder.run_status("running", current_step="04_processing")
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/steps/03_alignment")

    assert leaked not in response.text
    assert response.json()["inputs"] == [
        {"type": "fastq_manifest", "path": "02_preprocessing/fastq_manifest.tsv"}
    ]


def test_run_relative_provenance_is_still_reported(client, make_job, run):
    """The '../_jobs/...' form is legitimate and must survive the filter.

    main.sh computes it with relpath against the run directory, and the
    backend's own generated inputs live in a sibling directory. It names no
    absolute location, so it stays.
    """
    builder = run()
    builder.step("03_alignment")  # default inputs are the ../_jobs/... pair
    builder.run_status("running", current_step="04_processing")
    job_id = make_job(run_mode="full")

    paths = [i["path"] for i in
             client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()["inputs"]]

    assert paths == [
        "../_jobs/wes-20260821-142659-c66d6e/run_config.json",
        "../_jobs/wes-20260821-142659-c66d6e/samplesheet.csv",
    ]


# --- states that are not errors ---------------------------------------------


def test_queued_job_reports_every_step_pending(client, make_job, run):
    """No run_status.json at all: the pipeline has not started writing."""
    run()  # creates the directory and nothing else
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["status"] == "pending"
    assert body["elapsedSeconds"] == 0
    assert body["metrics"] == {}
    assert body["artifacts"] == []
    assert body["nextStepReady"] is False
    assert body["startedAt"] is None


def test_step_ahead_of_the_current_one_is_pending(client, make_job, run):
    in_flight(run(), "03_alignment", finished=["00_input_validation"])
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/05_coverage_qc").json()

    assert body["status"] == "pending"
    assert body["metrics"] == {}


def test_running_step_is_200_not_404(client, make_job, run):
    """finish_step() has not run, so none of its three documents exist yet."""
    in_flight(run(), "03_alignment", finished=["00_input_validation"])
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/steps/03_alignment")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["metrics"] == {}
    assert body["artifacts"] == []
    assert body["failures"] == []
    assert body["nextStepReady"] is False


def test_failed_step_is_200_with_its_failures(client, make_job, run):
    builder = run()
    builder.step(
        "03_alignment",
        status="failed",
        failures=[{"code": "missing_fastq_manifest", "message": "no manifest"}],
    )
    builder.run_status(
        "failed",
        steps=[{"step_id": "03_alignment", "status": "failed", "exit_code": 1}],
    )
    job_id = make_job(run_mode="full")

    response = client.get(f"/api/jobs/{job_id}/steps/03_alignment")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["exitCode"] == 1
    assert body["failures"][0]["code"] == "missing_fastq_manifest"
    assert body["nextStepReady"] is False


def test_warning_step_maps_to_warning(client, make_job, run):
    builder = run()
    builder.step(
        "05_coverage_qc",
        status="warning",
        warnings=[
            {
                "code": "LOW_MEAN_COVERAGE",
                "message": "mean target depth 18x is below 30x",
                "impact": "sensitivity may be reduced",
                "can_continue": True,
            }
        ],
    )
    builder.run_status("running", current_step="06_variant_calling")
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/05_coverage_qc").json()

    assert body["status"] == "warning"
    assert body["warnings"][0]["code"] == "LOW_MEAN_COVERAGE"
    assert body["warnings"][0]["canContinue"] is True
    assert body["nextStepReady"] is True


# --- a finished step's full story -------------------------------------------


def completed_alignment(builder):
    """03_alignment as main.sh leaves it: status, metrics and artifacts."""
    builder.file("03_alignment/sample_bam/DEMO01.bam", b"BAM")
    builder.file("03_alignment/sample_bam/DEMO01.flagstat.txt", "41283922 + 0 total\n")
    builder.step(
        "03_alignment",
        elapsed_seconds=2531,
        checks=[
            {"name": "bam_quickcheck", "status": "PASS", "detail": "BAM is complete"}
        ],
        outputs=[{"type": "sample_bam", "path": "03_alignment/sample_bam/DEMO01.bam"}],
    )
    builder.metrics("03_alignment", dict(ALIGNMENT_METRICS))
    builder.artifacts(
        "03_alignment",
        [
            builder.entry(
                "03_alignment",
                "aligned_bam",
                "Coordinate-sorted sample BAM",
                "03_alignment/sample_bam/DEMO01.bam",
            ),
            builder.entry(
                "03_alignment",
                "sample_qc",
                "Sample flagstat",
                "03_alignment/sample_bam/DEMO01.flagstat.txt",
            ),
        ],
    )
    builder.run_status("running", current_step="04_processing")
    return builder


def test_completed_step_maps_the_status_document(client, make_job, run):
    completed_alignment(run())
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["stepId"] == "03_alignment"
    assert body["jobId"] == job_id
    assert body["status"] == "completed"
    assert body["elapsedSeconds"] == 2531
    assert body["exitCode"] == 0
    assert body["startedAt"] == "2026-08-21T14:26:59+09:00"
    assert body["finishedAt"] == "2026-08-21T14:27:22+09:00"
    assert body["nextStepReady"] is True


def test_completed_step_carries_validation_and_io(client, make_job, run):
    completed_alignment(run())
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["validation"]["status"] == "pass"
    assert body["validation"]["results"] == [
        {"name": "bam_quickcheck", "status": "PASS", "detail": "BAM is complete"}
    ]
    assert body["outputs"] == [
        {"type": "sample_bam", "path": "03_alignment/sample_bam/DEMO01.bam"}
    ]
    # main.sh records the backend's own inputs as "../_jobs/..." because they
    # live in a sibling directory. Reported verbatim; never opened.
    assert body["inputs"][0]["type"] == "run_config"


def test_metrics_are_passed_through_untouched(client, make_job, run):
    """The metric namespace stays the pipeline's, not the API's."""
    completed_alignment(run())
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["metrics"] == ALIGNMENT_METRICS
    assert body["metrics"]["mapped_pct"] == 99.1


def test_metrics_document_missing_is_an_empty_object(client, make_job, run):
    builder = run()
    builder.step("03_alignment")
    builder.run_status("running", current_step="04_processing")
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["status"] == "completed"
    assert body["metrics"] == {}


def test_only_this_steps_artifacts_are_returned(client, make_job, run):
    builder = completed_alignment(run())
    builder.file("logs/software_versions.txt", "bwa=0.7.17\n")
    builder.artifacts(
        "00_input_validation",
        [
            builder.entry(
                "00_input_validation",
                "software_versions",
                "Software versions",
                "logs/software_versions.txt",
            )
        ],
    )
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert {a["stepId"] for a in body["artifacts"]} == {"03_alignment"}
    assert {a["kind"] for a in body["artifacts"]} == {"aligned_bam", "sample_qc"}


def test_artifact_entries_keep_the_shared_shape(client, make_job, run):
    """Reused from the artifact reader, so download ids line up with /artifacts."""
    completed_alignment(run())
    job_id = make_job(run_mode="full")

    entry = next(
        a
        for a in client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()["artifacts"]
        if a["kind"] == "aligned_bam"
    )

    assert entry["fileId"] == artifact_file_id(
        "wes-20260821-142659-c66d6e",
        "03_alignment",
        "03_alignment/sample_bam/DEMO01.bam",
    )
    assert entry["available"] is True
    assert entry["downloadable"] is True
    assert entry["relativePath"] == "03_alignment/sample_bam/DEMO01.bam"


def test_artifact_id_is_downloadable_through_the_existing_endpoint(
    client, make_job, run
):
    completed_alignment(run())
    job_id = make_job(run_mode="full")

    entry = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()["artifacts"][0]
    download = client.get(
        f"/api/jobs/{job_id}/artifacts/{entry['fileId']}/download"
    )

    assert download.status_code == 200


# --- running elapsed --------------------------------------------------------


def test_running_step_reports_elapsed_from_stage_status(client, make_job, run):
    builder = in_flight(run(), "03_alignment", finished=["00_input_validation"])
    builder.stage_status(
        [
            (iso_ago(700), "00_input_validation", "STARTED"),
            (iso_ago(670), "00_input_validation", "COMPLETED"),
            (iso_ago(600), "03_alignment", "STARTED"),
        ]
    )
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["status"] == "running"
    assert 590 <= body["elapsedSeconds"] <= 660
    assert body["startedAt"] is not None


def test_running_elapsed_also_reaches_the_polled_job_endpoint(client, make_job, run):
    """The job page polls GET /api/jobs/{id}; it must see the same number."""
    builder = in_flight(run(), "03_alignment", finished=["00_input_validation"])
    builder.stage_status([(iso_ago(600), "03_alignment", "STARTED")])
    job_id = make_job(run_mode="full")

    steps = client.get(f"/api/jobs/{job_id}").json()["steps"]
    alignment = next(s for s in steps if s["stepId"] == "03_alignment")

    assert alignment["status"] == "running"
    assert 590 <= alignment["elapsedSeconds"] <= 660


def test_completed_step_ignores_stage_status(client, make_job, run):
    """A finished step's elapsed_seconds is the pipeline's own measurement."""
    builder = completed_alignment(run())
    builder.stage_status([(iso_ago(99999), "03_alignment", "STARTED")])
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/03_alignment").json()

    assert body["elapsedSeconds"] == 2531


def test_pending_step_has_no_elapsed_even_with_a_stale_started_row(
    client, make_job, run
):
    """A --resume run can carry STARTED rows for steps that are pending again."""
    builder = in_flight(run(), "03_alignment")
    builder.stage_status(
        [
            (iso_ago(9000), "05_coverage_qc", "STARTED"),
            (iso_ago(600), "03_alignment", "STARTED"),
        ]
    )
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/steps/05_coverage_qc").json()

    assert body["status"] == "pending"
    assert body["elapsedSeconds"] == 0
