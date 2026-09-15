"""Read the pipeline's artifact registry, and resolve one artifact to a file.

Source of truth is the union of ``<run_dir>/artifacts/<step_id>.json``, NOT
``artifact_manifest.json``. In main.sh, ``write_artifact_manifest`` runs inside
``run_finalization`` *before* ``complete_step`` publishes that step's own
artifacts, so the manifest on disk structurally cannot contain
``final_validation.tsv``, ``provenance.json``, ``core_summary.json`` or
``methods.md``. The per-step documents have no such gap. The manifest is read
only to report whether it agrees (``manifest_consistent``).

Every path that arrives from a pipeline document is untrusted. That is not a
theoretical stance: the step documents in the existing runs under runs/ contain

    "inputs": [{"type": "run_config", "path": "../_jobs/<run>/run_config.json"}]

because main.sh computes these with ``os.path.relpath`` against the run
directory and the backend's own inputs live in a sibling directory. The same
writer produces ``relative_path`` for artifacts, so containment is enforced
here rather than assumed.

The only value a client ever supplies is ``file_id``.
"""

from __future__ import annotations

import json
import logging
import ntpath
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

log = logging.getLogger(__name__)

# main.sh builds this as "f_" + sha256(run_id:step_id:relative_path)[:16].
FILE_ID_RE = re.compile(r"^f_[0-9a-f]{16}$")

REQUIRED_FIELDS = ("file_id", "relative_path")


class ArtifactError(Exception):
    """Base class for every failure this module reports."""


class RunDirNotReady(ArtifactError):
    """The run directory does not exist yet (or is not a directory)."""


class ArtifactNotFound(ArtifactError):
    """No registered artifact carries this file_id."""


class ArtifactNotDownloadable(ArtifactError):
    """Registered, but the pipeline marked it as not downloadable."""


class ArtifactFileMissing(ArtifactError):
    """Registered, and the file is gone from disk."""


class ArtifactPathRejected(ArtifactError):
    """The registered path is unusable: escapes the run dir, or is not a file.

    The client cannot construct one of these -- the only input is a file_id --
    so reaching this state means the artifact document itself is wrong. The
    offending path is logged, never returned.
    """


class MalformedArtifactDocument(ArtifactError):
    """The requested file_id is registered ambiguously and cannot be served."""


@dataclass
class ArtifactCollection:
    entries: list[dict[str, Any]] = field(default_factory=list)
    manifest_present: bool = False
    manifest_consistent: bool = False
    suppressed_count: int = 0
    # file_ids registered more than once with different paths. Listed nowhere
    # and refused on download, because there is no way to know which was meant.
    conflicted_ids: set[str] = field(default_factory=set)


def resolve_run_root(run_dir: Path | str) -> Path:
    """Canonicalise the run directory recorded in the database.

    ``.resolve()`` matters on both sides of the later containment check: the
    database stores ``RUNS_ROOT / run_id`` unresolved, while main.sh works from
    a realpath'd ``output_root``. If RUNS_ROOT is reached through a symlink,
    comparing an unresolved root against a resolved target would reject every
    legitimate artifact.
    """
    try:
        root = Path(run_dir).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise RunDirNotReady(f"run directory is not available: {exc}") from exc
    if not root.is_dir():
        raise RunDirNotReady("run path exists but is not a directory")
    return root


def _read_json(path: Path) -> Any:
    """Read one JSON document as UTF-8.

    encoding is explicit everywhere in this module. main.sh writes UTF-8 and
    embeds Korean in check details and failure messages; on a cp949 Windows
    host the locale default raises UnicodeDecodeError on those exact files.

    Returns None when the document is unreadable or unparseable. Callers decide
    whether that is tolerable -- for a single step's artifact document it is
    (that step is suppressed), for a requested download it is not.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _validate_relative_path(raw: Any) -> str:
    """Lexical gate, applied before the filesystem is touched at all.

    Rejects, in order: non-strings, empty strings, backslashes, POSIX absolute
    paths, Windows absolute and drive-relative paths, and any '..' component.
    """
    if not isinstance(raw, str):
        raise ArtifactPathRejected("relative_path is not a string")
    value = raw.strip()
    if not value:
        raise ArtifactPathRejected("relative_path is empty")

    # main.sh always emits forward slashes (it applies .replace(os.sep, "/")).
    # A backslash therefore never belongs here, and on Windows it would open a
    # second traversal syntax that the checks below would not see.
    if "\\" in value:
        raise ArtifactPathRejected("relative_path contains a backslash")

    if PurePosixPath(value).is_absolute():
        raise ArtifactPathRejected("relative_path is absolute")
    if ntpath.isabs(value):
        raise ArtifactPathRejected("relative_path is absolute (windows form)")
    if ntpath.splitdrive(value)[0]:
        raise ArtifactPathRejected("relative_path carries a drive letter")

    parts = PurePosixPath(value).parts
    if ".." in parts:
        raise ArtifactPathRejected("relative_path escapes the run directory")
    return value


def _contained_target(run_root: Path, relative_path: str) -> Path:
    """Resolve inside the run root and prove the result stayed there.

    strict=False so that a registered-but-deleted artifact still resolves to a
    checkable path -- that case is a 410, not a security event. Symlinked
    parents are dereferenced either way, which is what makes the containment
    check meaningful against a symlink that points outside.
    """
    try:
        target = (run_root / relative_path).resolve()
    except (OSError, ValueError) as exc:
        raise ArtifactPathRejected(f"path could not be resolved: {exc}") from exc

    if not target.is_relative_to(run_root):
        log.warning(
            "artifact path escapes its run directory; refusing. "
            "run_root=%s relative_path=%s resolved=%s",
            run_root,
            relative_path,
            target,
        )
        raise ArtifactPathRejected("resolved path is outside the run directory")
    return target


def _normalise(raw: Any, run_root: Path) -> dict[str, Any] | None:
    """Turn one registry record into a listable entry, or drop it.

    Returns None for anything that cannot be represented safely; the caller
    counts those in ``suppressed_count`` rather than failing the whole listing.
    """
    if not isinstance(raw, dict):
        return None
    for key in REQUIRED_FIELDS:
        if not raw.get(key):
            return None

    file_id = raw["file_id"]
    if not isinstance(file_id, str) or not FILE_ID_RE.fullmatch(file_id):
        return None

    try:
        relative_path = _validate_relative_path(raw["relative_path"])
        target = _contained_target(run_root, relative_path)
    except ArtifactPathRejected:
        return None

    size = raw.get("size_bytes")
    sha256 = raw.get("sha256")
    return {
        "fileId": file_id,
        "stepId": str(raw.get("step_id") or ""),
        "kind": str(raw.get("kind") or ""),
        "displayName": str(raw.get("display_name") or ""),
        "relativePath": relative_path,
        "sizeBytes": size if isinstance(size, int) else None,
        "sha256": sha256 if isinstance(sha256, str) else None,
        # Explicit identity check: main.sh writes a real bool, and a truthy
        # string like "false" must never be read as permission to serve.
        "downloadable": raw.get("downloadable") is True,
        "description": str(raw.get("description") or ""),
        "available": target.is_file(),
    }


def _manifest_count(run_root: Path) -> tuple[bool, int | None]:
    doc = _read_json(run_root / "artifact_manifest.json")
    if not isinstance(doc, dict):
        return (run_root / "artifact_manifest.json").exists(), None
    artifacts = doc.get("artifacts")
    return True, len(artifacts) if isinstance(artifacts, list) else None


def _iter_raw(run_root: Path) -> tuple[list[dict[str, Any]], int]:
    """Every raw record from every per-step document, plus a skip count.

    A document that is unreadable, unparseable or shaped wrongly contributes to
    the skip count instead of aborting the scan: one bad step document must not
    hide the artifacts of every other step.
    """
    artifact_dir = run_root / "artifacts"
    records: list[dict[str, Any]] = []
    skipped = 0
    if not artifact_dir.is_dir():
        return records, skipped

    # sorted() keeps the result deterministic across filesystems.
    for document in sorted(artifact_dir.glob("*.json")):
        doc = _read_json(document)
        if not isinstance(doc, dict):
            log.warning("unreadable artifact document, skipping: %s", document.name)
            skipped += 1
            continue
        raw_list = doc.get("artifacts")
        if not isinstance(raw_list, list):
            log.warning("artifact document has no artifacts list: %s", document.name)
            skipped += 1
            continue
        records.extend(item for item in raw_list if isinstance(item, dict))
    return records, skipped


def collect(run_dir: Path | str) -> ArtifactCollection:
    """Union every per-step artifact document into a listing.

    Records that cannot be represented safely -- malformed, or pointing outside
    the run directory -- are dropped from the listing and counted in
    ``suppressed_count``. They are NOT silently forgotten: a download request
    for one of them is refused explicitly by resolve_for_download(), which
    validates raw records itself rather than trusting this filtered view.
    """
    run_root = resolve_run_root(run_dir)
    raw_records, skipped = _iter_raw(run_root)

    collection = ArtifactCollection(suppressed_count=skipped)
    by_id: dict[str, dict[str, Any]] = {}

    for raw in raw_records:
        entry = _normalise(raw, run_root)
        if entry is None:
            collection.suppressed_count += 1
            continue

        file_id = entry["fileId"]
        previous = by_id.get(file_id)
        if previous is None:
            by_id[file_id] = entry
        elif previous["relativePath"] != entry["relativePath"]:
            # Same id, two different files. file_id is a digest of the path, so
            # this cannot happen by accident; serving either one could serve
            # the wrong file. Drop both and refuse the id on download.
            log.warning("conflicting registrations for file_id %s", file_id)
            collection.conflicted_ids.add(file_id)
            del by_id[file_id]
            collection.suppressed_count += 2
        # An identical re-registration (a step that ran twice) is not a
        # conflict; the first record is kept.

    collection.entries = sorted(
        by_id.values(), key=lambda e: (e["stepId"], e["relativePath"])
    )
    manifest_present, manifest_count = _manifest_count(run_root)
    collection.manifest_present = manifest_present
    collection.manifest_consistent = (
        manifest_present
        and manifest_count is not None
        and manifest_count == len(collection.entries)
    )
    return collection


def resolve_for_download(
    run_dir: Path | str, file_id: str
) -> tuple[dict[str, Any], Path]:
    """Map a client-supplied file_id to a file that is safe to send.

    This deliberately re-reads the raw records rather than searching collect()'s
    output. collect() drops unsafe entries, so looking there would turn a
    traversal or symlink escape into an indistinguishable "not found" and lose
    the fact that the registry itself is wrong.

    Raises, in the order the checks run:
        ValueError                  malformed file_id (the disk is not touched)
        RunDirNotReady              run directory absent
        ArtifactNotFound            id not registered
        MalformedArtifactDocument   id registered ambiguously
        ArtifactNotDownloadable     downloadable is not true
        ArtifactPathRejected        containment or file-type violation
        ArtifactFileMissing         registered, gone from disk
    """
    if not isinstance(file_id, str) or not FILE_ID_RE.fullmatch(file_id):
        raise ValueError("malformed file id")

    run_root = resolve_run_root(run_dir)
    raw_records, _ = _iter_raw(run_root)

    matches = [r for r in raw_records if r.get("file_id") == file_id]
    if not matches:
        raise ArtifactNotFound(file_id)

    distinct_paths = {
        r.get("relative_path") for r in matches if isinstance(r.get("relative_path"), str)
    }
    if len(distinct_paths) > 1:
        log.warning("conflicting registrations for file_id %s", file_id)
        raise MalformedArtifactDocument(
            "this file id is registered more than once with different paths"
        )

    raw = matches[0]
    # Explicit identity check: a truthy string like "false" must never be read
    # as permission to serve.
    if raw.get("downloadable") is not True:
        raise ArtifactNotDownloadable(file_id)

    # The full path gate runs here on the raw value, independently of collect().
    relative_path = _validate_relative_path(raw.get("relative_path"))
    target = _contained_target(run_root, relative_path)

    if not target.exists():
        raise ArtifactFileMissing(relative_path)
    if not target.is_file():
        # A directory, FIFO or device node registered as an artifact means the
        # document is wrong. Never stream it.
        log.warning("artifact target is not a regular file: %s", target)
        raise ArtifactPathRejected("registered target is not a regular file")

    entry = _normalise(raw, run_root)
    if entry is None:  # pragma: no cover - every gate above already passed
        raise ArtifactPathRejected("artifact record could not be normalised")
    return entry, target
