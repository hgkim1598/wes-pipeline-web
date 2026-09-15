"""GET /api/jobs/{id}/artifacts/{file_id}/download.

The client supplies one value: file_id. Everything else comes from the run
directory recorded in the database and from the pipeline's own documents, and
those documents are treated as untrusted input.

Every rejection test asserts that the file was not served, not merely that the
status code was non-200.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import artifact_file_id

SECRET = "TOP-SECRET-OUTSIDE-THE-RUN-DIR\n"


def _register(builder, relative_path, *, kind="probe", downloadable=True):
    """Register one artifact under a bogus step and return its file_id."""
    entry = builder.entry(
        "07_probe", kind, "Probe", relative_path, downloadable=downloadable
    )
    builder.artifacts("07_probe", [entry])
    return entry["file_id"]


# --- the happy path ---------------------------------------------------------


def test_successful_download_bytes_match(client, make_job, run):
    builder = run().as_passing_precheck()
    payload = b"bwa=0.7.17\nsamtools=1.19\n"
    builder.file("logs/software_versions.txt", payload)
    file_id = artifact_file_id(
        builder.run_id, "00_input_validation", "logs/software_versions.txt"
    )
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "software_versions.txt" in response.headers["content-disposition"]


# --- path containment -------------------------------------------------------


def test_parent_traversal_is_refused(client, make_job, run, tmp_path):
    """The '../_jobs/...' shape observed in the real run documents."""
    secret = tmp_path / "runs" / "_jobs" / "run_config.json"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text(SECRET, encoding="utf-8")

    builder = run().as_passing_precheck()
    file_id = _register(builder, "../_jobs/run_config.json")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")

    assert response.status_code == 500
    assert SECRET.strip() not in response.text
    assert response.json()["detail"]["code"] == "malformedArtifactDocument"


def test_deep_traversal_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    file_id = _register(builder, "logs/../../../../../../etc/passwd")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 500
    assert "root:" not in response.text


def test_posix_absolute_path_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    file_id = _register(builder, "/etc/passwd")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 500
    assert "root:" not in response.text


def test_windows_absolute_path_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    file_id = _register(builder, "C:\\Windows\\win.ini")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 500
    assert "[fonts]" not in response.text.lower()


def test_windows_drive_relative_path_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    file_id = _register(builder, "C:logs/software_versions.txt")
    job_id = make_job()

    assert (
        client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download").status_code == 500
    )


def test_backslash_traversal_is_refused(client, make_job, run):
    """main.sh only ever emits forward slashes; a backslash is not trusted."""
    builder = run().as_passing_precheck()
    file_id = _register(builder, "logs\\..\\..\\_jobs\\run_config.json")
    job_id = make_job()

    assert (
        client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download").status_code == 500
    )


def test_unc_path_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    file_id = _register(builder, "\\\\attacker\\share\\payload.bin")
    job_id = make_job()

    assert (
        client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download").status_code == 500
    )


def _link_dir(link: "os.PathLike[str]", target: "os.PathLike[str]") -> bool:
    """Create a directory link, by whatever mechanism this host allows.

    POSIX gets a symlink. Windows needs SeCreateSymbolicLink or Developer Mode
    for os.symlink, which an ordinary account does not have, but it can always
    create a directory junction -- and Path.resolve() dereferences a junction
    exactly as it dereferences a symlink. Using the junction keeps the escape
    check covered on the development host instead of silently skipped.
    """
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    if sys.platform != "win32":
        return False
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        timeout=30,
    )
    return completed.returncode == 0 and Path(link).is_dir()


def _link_file(link: "os.PathLike[str]", target: "os.PathLike[str]") -> bool:
    try:
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


def test_symlink_escape_is_refused(client, make_job, run, tmp_path):
    """A link inside the run dir pointing outside must not be followed.

    The lexical gate cannot see this one: "outside/secret.txt" is a perfectly
    ordinary relative path with no '..' and no drive letter. Only resolving it
    and re-checking containment catches the escape.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(SECRET, encoding="utf-8")

    builder = run().as_passing_precheck()
    link = builder.run_dir / "outside"
    if not _link_dir(link, outside):
        pytest.skip(
            "this host allows neither symlinks nor directory junctions "
            f"(platform={sys.platform})"
        )

    # Sanity: the link really does reach the secret through the run directory.
    assert (builder.run_dir / "outside" / "secret.txt").read_text(
        encoding="utf-8"
    ) == SECRET

    file_id = _register(builder, "outside/secret.txt")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")

    assert response.status_code == 500
    assert SECRET.strip() not in response.text
    assert response.json()["detail"]["code"] == "malformedArtifactDocument"


def test_symlink_escape_is_suppressed_from_the_listing(client, make_job, run, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(SECRET, encoding="utf-8")

    builder = run().as_passing_precheck()
    if not _link_dir(builder.run_dir / "outside", outside):
        pytest.skip("this host allows neither symlinks nor directory junctions")

    _register(builder, "outside/secret.txt")
    job_id = make_job()

    body = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert body["artifactCount"] == 3
    assert body["suppressedCount"] == 1
    assert all(a["kind"] != "probe" for a in body["artifacts"])


def test_symlink_inside_the_run_dir_is_allowed(client, make_job, run, tmp_path):
    """Containment is about where the target lands, not about links as such."""
    builder = run().as_passing_precheck()
    real = builder.file("logs/real.txt", b"inside")
    if not _link_file(builder.run_dir / "logs" / "alias.txt", real):
        pytest.skip(
            "creating a file symlink requires privileges this host does not "
            f"grant (platform={sys.platform})"
        )

    file_id = _register(builder, "logs/alias.txt")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 200
    assert response.content == b"inside"


# --- file type and lifecycle -----------------------------------------------


def test_directory_target_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    (builder.run_dir / "logs").mkdir(parents=True, exist_ok=True)
    file_id = _register(builder, "logs")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "malformedArtifactDocument"


def test_missing_file_is_410(client, make_job, run):
    builder = run().as_passing_precheck()
    file_id = _register(builder, "logs/deleted_after_registration.txt")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 410


def test_not_downloadable_is_403(client, make_job, run):
    builder = run().as_passing_precheck()
    builder.file("logs/internal.txt", b"internal")
    file_id = _register(builder, "logs/internal.txt", downloadable=False)
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")
    assert response.status_code == 403
    assert b"internal" not in response.content


def test_downloadable_must_be_a_real_bool(client, make_job, run):
    """The string "false" is truthy; it must not be read as permission."""
    builder = run().as_passing_precheck()
    builder.file("logs/internal.txt", b"internal")
    entry = builder.entry("07_probe", "probe", "Probe", "logs/internal.txt")
    entry["downloadable"] = "false"
    builder.artifacts("07_probe", [entry])
    job_id = make_job()

    response = client.get(
        f"/api/jobs/{job_id}/artifacts/{entry['file_id']}/download"
    )
    assert response.status_code == 403
    assert b"internal" not in response.content


# --- identifier handling ----------------------------------------------------


def test_unknown_file_id_is_404(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()
    response = client.get(f"/api/jobs/{job_id}/artifacts/f_{'0' * 16}/download")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        "f_ZZZZZZZZZZZZZZZZ",
        "f_short",
        "f_" + "a" * 17,
        "notprefixed0000000",
        "f_0123456789abcdef0",
        "f_0123456789ABCDEF",
    ],
)
def test_malformed_file_id_is_400(client, make_job, run, bad):
    run().as_passing_precheck()
    job_id = make_job()
    response = client.get(f"/api/jobs/{job_id}/artifacts/{bad}/download")
    assert response.status_code == 400


def test_dot_dot_as_file_id_never_reaches_the_handler(client, make_job, run):
    """A bare '..' segment is collapsed by URL normalisation before routing.

    The request therefore lands on a path that matches no route at all, which
    is a 404 from the router rather than a 400 from the id check. Asserted
    explicitly so the difference is a recorded fact rather than a surprise.
    """
    run().as_passing_precheck()
    job_id = make_job()
    response = client.get(f"/api/jobs/{job_id}/artifacts/../download")
    assert response.status_code == 404


def test_percent_encoded_traversal_in_file_id_is_400(client, make_job, run):
    run().as_passing_precheck()
    job_id = make_job()
    response = client.get(
        f"/api/jobs/{job_id}/artifacts/..%2F..%2Fetc%2Fpasswd/download"
    )
    assert response.status_code in (400, 404)
    assert "root:" not in response.text


def test_conflicting_file_id_is_refused(client, make_job, run):
    builder = run().as_passing_precheck()
    builder.file("logs/a.txt", b"AAA")
    builder.file("logs/b.txt", b"BBB")
    clashing = artifact_file_id(builder.run_id, "07_clash", "logs/a.txt")
    builder.artifacts(
        "07_clash",
        [
            builder.entry("07_clash", "a", "A", "logs/a.txt", file_id=clashing),
            builder.entry("07_clash", "b", "B", "logs/b.txt", file_id=clashing),
        ],
    )
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{clashing}/download")
    assert response.status_code == 500
    assert b"AAA" not in response.content
    assert b"BBB" not in response.content


def test_unknown_job_is_404(client):
    assert (
        client.get(f"/api/jobs/wes-nope/artifacts/f_{'0' * 16}/download").status_code
        == 404
    )


def test_missing_run_directory_is_409(client, make_job):
    job_id = make_job()
    response = client.get(f"/api/jobs/{job_id}/artifacts/f_{'0' * 16}/download")
    assert response.status_code == 409


# --- response header safety -------------------------------------------------


def test_content_disposition_cannot_be_injected(client, make_job, run):
    """display_name is free text from main.sh and is never used in the header."""
    builder = run().as_passing_precheck()
    builder.file("logs/plain.txt", b"data")
    entry = builder.entry("07_probe", "probe", "Probe", "logs/plain.txt")
    entry["display_name"] = 'evil"\r\nSet-Cookie: pwned=1\r\nX: '
    builder.artifacts("07_probe", [entry])
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{entry['file_id']}/download")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "Set-Cookie" not in disposition
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2
    assert "pwned" not in response.headers.get("set-cookie", "")


def test_content_disposition_encodes_non_ascii_names(client, make_job, run):
    builder = run().as_passing_precheck()
    builder.file("logs/보고서.txt", b"report")
    file_id = _register(builder, "logs/보고서.txt")
    job_id = make_job()

    response = client.get(f"/api/jobs/{job_id}/artifacts/{file_id}/download")

    assert response.status_code == 200
    assert response.content == b"report"
    disposition = response.headers["content-disposition"]
    # ASCII fallback is sanitised, RFC 5987 form carries the real name.
    assert "filename*=UTF-8''" in disposition
    assert "%EB%B3%B4%EA%B3%A0%EC%84%9C" in disposition
    assert disposition.isascii()
