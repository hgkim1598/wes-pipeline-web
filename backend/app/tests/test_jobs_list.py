"""GET /api/jobs — the run list contract.

The list exists so the run list screen reads server state instead of keeping a
history in the browser. These tests pin what a row carries, what it deliberately
does not, and that the list agrees with GET /api/jobs/{id} about a status.

They also cover the two things that are easy to get wrong once a column is added
after the fact: a row written before jobs.sample_id existed must still render,
and an existing database must gain the column without losing its rows.
"""

from __future__ import annotations

import sqlite3

from app import config, db


# --- empty ------------------------------------------------------------------


def test_list_is_empty_when_no_jobs(client):
    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert response.json() == {"jobs": []}


# --- item contract ----------------------------------------------------------


def test_list_item_field_set(client, make_job, run):
    """The row shape, field by field.

    Pinned as an exact set so neither a silent addition nor a silent removal
    reaches the frontend unnoticed.
    """
    run().as_passing_precheck()
    make_job(sample_id="NA12878")

    item = client.get("/api/jobs").json()["jobs"][0]

    assert set(item) == {
        "jobId",
        "runId",
        "status",
        "sampleId",
        "profileId",
        "captureKitId",
        "runMode",
        "createdAt",
        "startedAt",
        "finishedAt",
        "error",
        "plannedStepCount",
        "completedStepCount",
    }


def test_list_item_values(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job(sample_id="NA12878")

    item = client.get("/api/jobs").json()["jobs"][0]

    assert item["jobId"] == job_id
    assert item["runId"] == job_id
    assert item["sampleId"] == "NA12878"
    assert item["profileId"] == "germline-illumina-wes-breast"
    assert item["captureKitId"] == "idt_xgen_exome_hyb_panel_v2"
    assert item["runMode"] == "check_only"
    assert item["status"] == "completed_with_warnings"
    assert item["startedAt"] == "2026-08-21T14:26:59+09:00"
    assert item["finishedAt"] == "2026-08-21T14:27:22+09:00"
    assert item["createdAt"]
    assert item["error"] is None


def test_list_omits_detail_payload(client, make_job, run):
    """A list row is not a JobStateResponse.

    steps and logTail are what make the single-job response expensive; the list
    must not carry them once per row.
    """
    run().as_passing_precheck()
    make_job()

    item = client.get("/api/jobs").json()["jobs"][0]

    for absent in ("steps", "logTail", "progress", "currentStep", "unsupportedOptions"):
        assert absent not in item


def test_list_step_counts(client, make_job, run):
    """Counts, not a percentage.

    plannedStepCount is the recorded plan; completedStepCount comes from the
    pipeline's own completed_steps list.
    """
    run().as_passing_precheck()
    make_job()

    item = client.get("/api/jobs").json()["jobs"][0]

    assert item["plannedStepCount"] == 1
    assert item["completedStepCount"] == 1


def test_list_status_matches_single_job_endpoint(client, make_job, run):
    """The two endpoints must never disagree about the same job."""
    run().as_passing_precheck()
    job_id = make_job()

    listed = client.get("/api/jobs").json()["jobs"][0]["status"]
    detail = client.get(f"/api/jobs/{job_id}").json()["status"]

    assert listed == detail == "completed_with_warnings"


def test_list_reports_failed_precheck(client, make_job, run):
    run("wes-20260822-090000-aaaaaa").as_failing_precheck()
    make_job("wes-20260822-090000-aaaaaa")

    item = client.get("/api/jobs").json()["jobs"][0]

    assert item["status"] == "failed"
    assert item["completedStepCount"] == 0


def test_list_falls_back_when_pipeline_wrote_nothing(client, make_job):
    """No run_status.json: report the backend's own orchestration state."""
    make_job(status="QUEUED")

    item = client.get("/api/jobs").json()["jobs"][0]

    assert item["status"] == "queued"
    assert item["completedStepCount"] == 0


def test_list_reports_cancelled_even_without_a_status_document(client, make_job):
    """Windows cancel cannot let main.sh record anything; get_job() overrides
    the same way, and the list must not contradict it."""
    make_job(status="CANCELLED")

    assert client.get("/api/jobs").json()["jobs"][0]["status"] == "cancelled"


# --- ordering ---------------------------------------------------------------


def test_list_is_newest_first(client, make_job):
    make_job("wes-20260820-100000-aaaaaa", created_at="2026-08-20T10:00:00+09:00")
    make_job("wes-20260822-100000-cccccc", created_at="2026-08-22T10:00:00+09:00")
    make_job("wes-20260821-100000-bbbbbb", created_at="2026-08-21T10:00:00+09:00")

    ids = [job["jobId"] for job in client.get("/api/jobs").json()["jobs"]]

    assert ids == [
        "wes-20260822-100000-cccccc",
        "wes-20260821-100000-bbbbbb",
        "wes-20260820-100000-aaaaaa",
    ]


def test_list_order_is_stable_when_created_at_ties(client, make_job):
    """Same timestamp: job_id decides, so the order does not shuffle."""
    same = "2026-08-22T10:00:00+09:00"
    make_job("wes-20260822-100000-aaaaaa", created_at=same)
    make_job("wes-20260822-100000-cccccc", created_at=same)
    make_job("wes-20260822-100000-bbbbbb", created_at=same)

    first = [job["jobId"] for job in client.get("/api/jobs").json()["jobs"]]
    second = [job["jobId"] for job in client.get("/api/jobs").json()["jobs"]]

    assert first == second
    assert first == [
        "wes-20260822-100000-cccccc",
        "wes-20260822-100000-bbbbbb",
        "wes-20260822-100000-aaaaaa",
    ]


def test_list_returns_every_job(client, make_job):
    for index in range(5):
        make_job(f"wes-2026082{index}-100000-aaaaa{index}")

    assert len(client.get("/api/jobs").json()["jobs"]) == 5


# --- sampleId persistence ---------------------------------------------------


def test_submitted_sample_id_survives_to_the_list(
    client, make_upload, reference_configured
):
    """The name the submission carried is stored, not re-derived.

    POST /api/jobs is the only place that knows it; before jobs.sample_id
    existed it reached the generated samplesheet and nowhere else.
    """
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "germline-illumina-wes-breast",
            "captureKitId": "idt_xgen_exome_hyb_panel_v2",
            "samples": [
                {
                    "sampleId": "NA12878",
                    "files": {
                        "r1": make_upload("NA12878_R1.fastq.gz"),
                        "r2": make_upload("NA12878_R2.fastq.gz"),
                    },
                }
            ],
        },
    )
    assert response.status_code == 201
    job_id = response.json()["jobId"]

    item = client.get("/api/jobs").json()["jobs"][0]
    assert item["jobId"] == job_id
    assert item["sampleId"] == "NA12878"


def test_stored_sample_id_is_the_sanitised_name(
    client, make_upload, reference_configured
):
    """What is stored is what main.sh will see in the samplesheet.

    _sanitize_sample_id() replaces characters main.sh's ID_RE rejects, so the
    stored value has to be the cleaned one or the list would label a row with a
    name the run never used.
    """
    response = client.post(
        "/api/jobs",
        json={
            "profileId": "p",
            "captureKitId": "idt_xgen_exome_hyb_panel_v2",
            "samples": [
                {
                    "sampleId": "NA 12878/x",
                    "files": {
                        "r1": make_upload("a_R1.fastq.gz"),
                        "r2": make_upload("a_R2.fastq.gz"),
                    },
                }
            ],
        },
    )
    assert response.status_code == 201

    item = client.get("/api/jobs").json()["jobs"][0]
    assert item["sampleId"] == "NA_12878_x"

    samplesheet = (config.JOBS_ROOT / item["runId"] / "samplesheet.csv").read_text(
        encoding="utf-8"
    )
    assert samplesheet.splitlines()[1].split(",")[0] == "NA_12878_x"


def test_row_without_sample_id_is_served_as_null(client, make_job, run):
    """A job created before the column existed must not break the list."""
    run().as_passing_precheck()
    make_job()  # sample_id defaults to None

    item = client.get("/api/jobs").json()["jobs"][0]

    assert item["sampleId"] is None
    assert item["jobId"] != ""
    # The run id is never substituted for a missing sample name.
    assert item["sampleId"] != item["runId"]


def test_mixed_rows_with_and_without_sample_id(client, make_job):
    make_job("wes-20260822-100000-aaaaaa", created_at="2026-08-22T10:00:00+09:00")
    make_job(
        "wes-20260821-100000-bbbbbb",
        created_at="2026-08-21T10:00:00+09:00",
        sample_id="HG002",
    )

    jobs = client.get("/api/jobs").json()["jobs"]

    assert [job["sampleId"] for job in jobs] == [None, "HG002"]


# --- additive schema upgrade ------------------------------------------------


# The jobs table exactly as it was before sample_id was introduced. Kept
# verbatim so the test exercises a real pre-upgrade database rather than a
# guess at one.
SCHEMA_BEFORE_SAMPLE_ID = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    profile_id        TEXT NOT NULL,
    capture_kit_id    TEXT,
    status            TEXT NOT NULL,
    run_dir           TEXT NOT NULL,
    config_path       TEXT NOT NULL,
    samplesheet_path  TEXT NOT NULL,
    run_mode          TEXT NOT NULL,
    planned_steps     TEXT NOT NULL,
    original_options  TEXT NOT NULL,
    unsupported_options TEXT NOT NULL,
    command           TEXT,
    pid               INTEGER,
    pgid              INTEGER,
    exit_code         INTEGER,
    error             TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
"""


def _write_legacy_database(path) -> None:
    """A database in the pre-upgrade shape, with one row already in it."""
    legacy = sqlite3.connect(path)
    legacy.executescript(SCHEMA_BEFORE_SAMPLE_ID)
    legacy.execute(
        """INSERT INTO jobs
           (job_id, run_id, profile_id, capture_kit_id, status, run_dir,
            config_path, samplesheet_path, run_mode, planned_steps,
            original_options, unsupported_options, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "wes-20260101-000000-legacy",
            "wes-20260101-000000-legacy",
            "legacy-profile",
            "idt_xgen_exome_hyb_panel_v2",
            "DONE",
            str(path.parent / "runs" / "wes-20260101-000000-legacy"),
            "config.json",
            "samplesheet.csv",
            "check_only",
            '["00_input_validation"]',
            "{}",
            "[]",
            "2026-01-01T00:00:00+09:00",
            "2026-01-01T00:00:00+09:00",
        ),
    )
    legacy.commit()
    legacy.close()


def test_connect_adds_sample_id_to_an_existing_database(env):
    """The column appears without the database being recreated."""
    _write_legacy_database(config.DB_PATH)

    before = sqlite3.connect(config.DB_PATH)
    assert "sample_id" not in {
        row[1] for row in before.execute("PRAGMA table_info(jobs)")
    }
    before.close()

    db.connect()

    present = {row["name"] for row in db.query_all("PRAGMA table_info(jobs)")}
    assert "sample_id" in present


def test_upgrade_preserves_existing_rows(env):
    """No row is lost and no value is rewritten; the new column reads NULL."""
    _write_legacy_database(config.DB_PATH)

    db.connect()

    row = db.query_one(
        "SELECT * FROM jobs WHERE job_id = ?", ("wes-20260101-000000-legacy",)
    )
    assert row is not None
    assert row["profile_id"] == "legacy-profile"
    assert row["capture_kit_id"] == "idt_xgen_exome_hyb_panel_v2"
    assert row["created_at"] == "2026-01-01T00:00:00+09:00"
    assert row["sample_id"] is None


def test_upgrade_is_idempotent(env):
    """Reconnecting must not try to add the column twice."""
    _write_legacy_database(config.DB_PATH)

    db.connect()
    db._conn.close()
    db._conn = None
    db.connect()  # would raise "duplicate column name" without the guard

    assert db.query_one("SELECT COUNT(*) AS n FROM jobs")["n"] == 1


def test_upgraded_database_serves_the_list(client, env):
    """End to end: a pre-upgrade database is listable after startup."""
    _write_legacy_database(config.DB_PATH)

    jobs = client.get("/api/jobs").json()["jobs"]

    assert len(jobs) == 1
    assert jobs[0]["jobId"] == "wes-20260101-000000-legacy"
    assert jobs[0]["sampleId"] is None
    assert jobs[0]["profileId"] == "legacy-profile"
