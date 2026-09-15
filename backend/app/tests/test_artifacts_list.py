"""GET /api/jobs/{id}/artifacts.

The point of these tests is that the listing comes from artifacts/*.json, not
from artifact_manifest.json, and that nothing unsafe or absolute ever appears
in a response.
"""

from __future__ import annotations

from .conftest import artifact_file_id


def test_lists_registered_artifacts(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()

    assert body["jobId"] == job_id
    assert body["artifactCount"] == 3
    assert len(body["artifacts"]) == 3
    assert {a["kind"] for a in body["artifacts"]} == {
        "software_versions",
        "manifest",
        "validation_report",
    }


def test_entry_shape(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()

    entry = client.get(f"/api/jobs/{job_id}/artifacts").json()["artifacts"][0]
    assert set(entry) == {
        "fileId",
        "stepId",
        "kind",
        "displayName",
        "relativePath",
        "sizeBytes",
        "sha256",
        "downloadable",
        "description",
        "available",
    }


def test_union_includes_finalization_artifacts_missing_from_manifest(
    client, make_job, run
):
    """The main.sh ordering gap must not hide the final artifacts.

    write_artifact_manifest() runs before finish_step() publishes the
    finalization step's own artifacts, so artifact_manifest.json is short by
    exactly those. Reading artifacts/*.json instead recovers them.
    """
    builder = run().as_completed_full()
    job_id = make_job(run_mode="full")

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    kinds = {a["kind"] for a in body["artifacts"]}

    # Present in artifact_manifest.json.
    assert "raw_vcf" in kinds
    # Absent from artifact_manifest.json, recovered from artifacts/99_*.json.
    assert "final_validation" in kinds
    assert "methods" in kinds

    manifest_count = (builder.run_dir / "artifact_manifest.json").read_text(
        encoding="utf-8"
    )
    assert '"artifact_count": 3' in manifest_count
    assert body["artifactCount"] == 5
    assert body["manifestPresent"] is True
    # Expected on a full run: the manifest genuinely disagrees.
    assert body["manifestConsistent"] is False


def test_manifest_consistent_when_it_agrees(client, make_job, run):
    builder = run().as_passing_precheck()
    entries = [
        builder.entry(
            "00_input_validation",
            "software_versions",
            "Software versions",
            "logs/software_versions.txt",
        ),
        builder.entry(
            "00_input_validation",
            "manifest",
            "Normalized run manifest",
            "config/normalized_manifest.json",
        ),
        builder.entry(
            "00_input_validation",
            "validation_report",
            "Samplesheet validation report",
            "00_input_validation/samplesheet_validation.txt",
        ),
    ]
    builder.manifest(entries)
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert body["manifestPresent"] is True
    assert body["manifestConsistent"] is True


def test_no_artifact_directory_is_empty_200(client, make_job, run):
    builder = run()
    builder.run_status("check_only")
    builder.step("00_input_validation", status="warning")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts")
    assert response.status_code == 200
    body = response.json()
    assert body["artifactCount"] == 0
    assert body["artifacts"] == []
    assert body["manifestPresent"] is False
    assert body["manifestConsistent"] is False


def test_missing_run_directory_is_409(client, make_job):
    job_id = make_job()  # no run directory was ever created
    response = client.get(f"/api/jobs/{job_id}/artifacts")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resultsNotReady"


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/wes-nope/artifacts").status_code == 404


def test_malformed_step_document_suppresses_only_that_step(client, make_job, run):
    builder = run().as_passing_precheck()
    builder.raw("artifacts/03_alignment.json", "{ this is not json")
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    # The three good entries survive; the broken document is counted.
    assert body["artifactCount"] == 3
    assert body["suppressedCount"] == 1


def test_unsafe_paths_are_suppressed_from_the_listing(client, make_job, run):
    builder = run().as_passing_precheck()
    builder.artifacts(
        "07_bogus",
        [
            builder.entry("07_bogus", "escape", "Escape", "../_jobs/run_config.json"),
            builder.entry("07_bogus", "posix", "Posix", "/etc/passwd"),
            builder.entry("07_bogus", "win", "Win", "C:\\Windows\\win.ini"),
        ],
    )
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert body["artifactCount"] == 3
    assert body["suppressedCount"] == 3
    for entry in body["artifacts"]:
        assert ".." not in entry["relativePath"]


def test_no_absolute_path_anywhere_in_the_response(client, make_job, run):
    run().as_completed_full()
    job_id = make_job(run_mode="full")

    text = client.get(f"/api/jobs/{job_id}/artifacts").text
    assert "/srv/wes" not in text
    assert "C:\\" not in text
    assert "\\\\" not in text
    for marker in ("/tmp/", "/home/", "/Users/"):
        assert marker not in text


def test_missing_file_is_listed_as_unavailable(client, make_job, run):
    builder = run().as_passing_precheck()
    builder.artifacts(
        "07_gone",
        [builder.entry("07_gone", "ghost", "Ghost", "logs/never_written.txt")],
    )
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    ghost = next(a for a in body["artifacts"] if a["kind"] == "ghost")
    # Registered, so it is listed; reported honestly as gone.
    assert ghost["available"] is False
    assert body["suppressedCount"] == 0


def test_conflicting_file_id_drops_both_registrations(client, make_job, run):
    builder = run().as_passing_precheck()
    clashing = artifact_file_id(builder.run_id, "07_clash", "logs/software_versions.txt")
    builder.file("logs/other.txt", "other")
    builder.artifacts(
        "07_clash",
        [
            builder.entry(
                "07_clash", "a", "A", "logs/software_versions.txt", file_id=clashing
            ),
            builder.entry("07_clash", "b", "B", "logs/other.txt", file_id=clashing),
        ],
    )
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert clashing not in {a["fileId"] for a in body["artifacts"]}
    assert body["suppressedCount"] == 2


def test_identical_reregistration_is_not_a_conflict(client, make_job, run):
    """A step that ran twice registers the same artifact twice; that is fine."""
    builder = run().as_passing_precheck()
    duplicate = builder.entry(
        "00_input_validation",
        "software_versions",
        "Software versions",
        "logs/software_versions.txt",
    )
    builder.artifacts("07_again", [duplicate])
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert body["artifactCount"] == 3
    assert body["suppressedCount"] == 0
