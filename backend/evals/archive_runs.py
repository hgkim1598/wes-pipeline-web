"""Real failed WES runs, restored from the evidence archive into a throwaway copy.

Why a second real-run source next to real_runs.py
-------------------------------------------------

`real_runs.py` restores a *capture*: a directory holding the backend's `app.db`
and the run's documents. The two failed runs here (3a22c5, b94559) exist only in
`wes_failure_evidence_20261112.tar.gz`, which holds run documents and no
database. So this module does what a capture would have given for free -- it
builds the one `jobs` row -- and everything else is shared: the isolation is
`agent_cases.isolated_environment()`, the path pattern for leak counting is
`real_runs`'.

The archive is untrusted input
------------------------------

It is a file on disk that a person put there, and nothing about it has been
checked by this code before. So it is read ONCE, into memory, with caps:

    the file         at most MAX_ARCHIVE_BYTES compressed; its SHA-256 is taken
                     from the same bytes that are parsed
    the stream       decompressed at most MAX_STREAM_BYTES, BEFORE tarfile sees
                     it -- tarfile reads pax / GNU long-name header data into
                     memory before returning a member, so per-member checks
                     alone cannot stop a header bomb

and then, before a single byte is written:

    every member     a plain file or a directory; no symlink, hardlink, device
                     or FIFO anywhere in the archive
    every name       relative, '/'-separated, no '..' / '.' / empty segment,
                     no drive letter, no backslash, no duplicate
    the count        at most MAX_MEMBERS members are looked at
    what is taken    only REQUIRED_FILES (+ OPTIONAL_FILES) of the named run
    their size       each 0..MAX_MEMBER_BYTES, together MAX_TOTAL_BYTES, judged
                     from every header, and the bytes actually read must equal
                     what the header declared

Then the selected files are written one by one by this code into the
destination -- never `extractall` -- so nothing the archive says can choose a
path. The archive itself is only ever opened for reading.

The text inside the files is evidence. It is never interpreted as anything else.

The jobs row: what is known and what is assumed
-----------------------------------------------

    sample_id     `metrics/00_input_validation.json` -> metrics.sample, as the
                  run itself recorded it. It is what the privacy projection
                  redacts against, so it is required: no guessing, no
                  placeholder -- without it the run is refused.
    status        DONE: main.sh left a run_status.json, and that is exactly
                  when the worker closes a job as DONE (worker.py).
    run_mode,     NOT in the archive. Both reach the model (run.runMode,
    planned       steps.planned), so they are declared per run as
                  `assumptions` and written into every eval record.
    profile_id    NOT NULL in the schema, NOT in the archive, NOT in the
                  payload: a marker that says so.
    capture_kit_id  NULL. The kit is not asserted.

Disposable
----------

`materialise()` restores into a fresh temporary directory (its own runs root
and sqlite file, see agent_cases) and removes it afterwards, also on error.
The production database and runs root are never opened.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import zlib
import re
import tarfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app import config, db
from app.services import config_builder, worker
from app.services.explanation import deterministic, run_context
from app.services.explanation.deterministic import RunExplanation

from . import local_data
from .agent_cases import FULL_PLAN, active_isolated_root, isolated_environment
from .real_runs import count_paths, literal_hits

ARCHIVE = local_data.source_path("archive")
STEP = "00_input_validation"

# What a restored run needs, relative to its run directory: the documents the
# run status reader, the step reader and the resource_bundle analysis use for a
# run that stopped in 00. Optional: the resource report (when absent the
# analysis reads the log, which is what these two runs recorded) and the
# step's artifact registry (what get_step_detail reports as artifactCount).
# Other files in the archive (config snapshot, manifest, ...) are not taken.
REQUIRED_FILES = (
    "status/run_status.json",
    f"status/steps/{STEP}.json",
    f"metrics/{STEP}.json",
    "logs/pipeline.log",
)
OPTIONAL_FILES = (f"{STEP}/resource_validation.txt", f"artifacts/{STEP}.json")
# Read into memory to CHECK the jobs row's plan (optional_steps), never
# written to disk and never shown to the model: it holds paths and ids.
SNAPSHOT = "config/run_config.snapshot.json"
VERIFY_FILES = (SNAPSHOT,)

# Limits. The largest file in the real archive is under 8 KiB and the whole
# archive under 130 KiB, so these leave room without letting a crafted archive
# fill the disk.
MAX_ARCHIVE_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_MEMBERS = 2000

_RUN_ID = re.compile(r"wes-\d{8}-\d{6}-[0-9a-f]{6}")
_DRIVE = re.compile(r"^[A-Za-z]:")

# profile_id is NOT NULL but not recorded in the archive and not sent to the
# model. This value says exactly that instead of naming a real profile.
PROFILE_UNKNOWN = "unknown-not-in-archive"

_DEFAULT_ASSUMPTIONS = (
    "run_mode=full: 값 자체는 압축 파일에 없다. 기록에서 판단했다 -- status=failed이고 로그에 "
    "main.sh 전체 실행 경로에서만 나오는 'RUN FAILED at <step>'이 있으며 check-only 표지"
    "(PRECHECK, '--check-only: running preflight', status=check_only)는 없다. 복원할 때마다 "
    "recorded_plan()으로 대조한다. 증거 기반 복원 추론, 사용자 최종 승인 전. 미확인: 이 Run을 "
    "만든 main.sh의 정확한 버전(3a22c5는 저장소에 남은 가장 이른 main.sh 커밋보다 먼저 실행됨)과 "
    "웹 백엔드로 실행됐는지 여부(jobs 행은 압축 파일에 없음)",
    "planned_steps=8단계: 설정 스냅샷의 optional_steps(filtering/annotation/intervar)가 모두 "
    "false이고 로그에 --from-step 흔적이 없다. config_builder.planned_steps('full', False)와 "
    "같아야 복원한다. 증거 기반 복원 추론, 사용자 최종 승인 전",
    "profile_id는 출처가 없음을 뜻하는 표지이고 capture_kit_id는 NULL이다 (둘 다 모델에 보내지 않음)",
)


class ArchiveError(RuntimeError):
    """The archive cannot be used safely or does not hold what a run needs."""


class ArchiveMissing(ArchiveError):
    """The archive is not on this machine. It is not in git."""


@dataclass(frozen=True)
class LoadedRun:
    """One validated read of the archive: everything a restore uses."""

    run: "ArchiveRun"
    digest: str  # SHA-256 of exactly the bytes that were parsed
    files: dict[str, bytes]  # run-relative path -> bytes, validated; written out
    sample: str  # metrics.sample, as the run recorded it
    # VERIFY_FILES that were present: read for checks only, never written.
    evidence: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class ArchiveRun:
    """One failed run inside the evidence archive."""

    name: str
    intent: str
    run_id: str
    archive: Path = ARCHIVE
    # "dev": these runs were looked at while P0-1 was built. Not held out.
    split: str = "dev"
    run_mode: str = "full"
    planned: tuple[str, ...] = tuple(FULL_PLAN)
    # What the jobs row states that the archive does not. Recorded with
    # every eval, so a reader can see what the model was told on assumption.
    assumptions: tuple[str, ...] = field(default=_DEFAULT_ASSUMPTIONS)


ARCHIVE_RUNS: dict[str, ArchiveRun] = {
    "real_3a22c5": ArchiveRun(
        name="real_3a22c5",
        intent="실제 실패 Run -- 00 resource_bundle FAIL, 원인 2개(target BED, coverage BED)",
        run_id=local_data.run_id("real_3a22c5"),
    ),
    "real_b94559": ArchiveRun(
        name="real_b94559",
        intent="실제 실패 Run -- 00 required_tools FAIL + resource_bundle FAIL, 원인 4개",
        run_id=local_data.run_id("real_b94559"),
    ),
}


# --- availability and identity ----------------------------------------------


def archive_available(run: ArchiveRun) -> bool:
    return run.archive.is_file()


def archive_digest(path: Path) -> str:
    """SHA-256 of the archive file: equal before and after means untouched."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- safe selection ----------------------------------------------------------


def _check_name(name: str) -> str:
    """The member's name if it is a safe relative POSIX path, else refuse."""
    stripped = name[:-1] if name.endswith("/") else name
    if (
        not stripped
        or "\\" in stripped
        or "\0" in stripped
        or stripped.startswith("/")
        or _DRIVE.match(stripped)
    ):
        raise ArchiveError("압축 파일에 허용되지 않는 경로가 있습니다")
    parts = stripped.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ArchiveError("압축 파일에 허용되지 않는 경로가 있습니다")
    return stripped


def _select(tar: tarfile.TarFile, run_id: str) -> dict[str, tarfile.TarInfo]:
    """Validate every member, then pick the run's files. Writes nothing."""
    wanted = set(REQUIRED_FILES) | set(OPTIONAL_FILES) | set(VERIFY_FILES)
    seen: set[str] = set()
    picked: dict[str, tarfile.TarInfo] = {}
    declared_total = 0

    for count, member in enumerate(tar, start=1):
        if count > MAX_MEMBERS:
            raise ArchiveError("압축 파일의 항목 수가 허용 범위를 넘습니다")
        name = _check_name(member.name)
        if name in seen:
            raise ArchiveError("압축 파일에 같은 경로가 두 번 있습니다")
        seen.add(name)
        if not (member.isfile() or member.isdir()):
            # Links, devices and FIFOs are refused anywhere in the archive,
            # not only among the files taken: an archive that carries them
            # is not the plain document set this loader was written for.
            raise ArchiveError("압축 파일에 일반 파일이 아닌 항목(링크·장치 등)이 있습니다")
        if member.size < 0 or member.size > MAX_MEMBER_BYTES:
            raise ArchiveError("압축 파일의 항목 크기가 허용 범위를 벗어납니다")
        declared_total += member.size
        if declared_total > MAX_TOTAL_BYTES:
            raise ArchiveError("압축 파일의 전체 크기가 허용 범위를 넘습니다")
        prefix, _, rel = name.partition("/")
        if prefix == run_id and rel in wanted and member.isfile():
            picked[rel] = member

    if not any(name == run_id or name.startswith(run_id + "/") for name in seen):
        raise ArchiveError("요청한 Run이 압축 파일에 없습니다")
    missing = [rel for rel in REQUIRED_FILES if rel not in picked]
    if missing:
        raise ArchiveError(f"Run에 필요한 파일이 없습니다: {', '.join(missing)}")
    return picked


def _read(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    """The member's bytes, never more than its header declared."""
    handle = tar.extractfile(member)
    if handle is None:
        raise ArchiveError("압축 파일의 항목을 읽을 수 없습니다")
    with handle:
        data = handle.read(member.size + 1)
    if len(data) != member.size:
        raise ArchiveError("압축 파일 항목의 크기가 헤더와 다릅니다")
    return data


def _inflate(raw: bytes) -> bytes:
    """gunzip `raw`, refusing a stream longer than MAX_STREAM_BYTES."""
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
        inflated = stream.read(MAX_STREAM_BYTES + 1)
    if len(inflated) > MAX_STREAM_BYTES:
        raise ArchiveError("압축을 푼 크기가 허용 범위를 넘습니다")
    return inflated


def load(run: ArchiveRun) -> LoadedRun:
    """Read the archive once, validate it, and return the run's files.

    The file is read into memory a single time (capped), its digest is taken
    from those bytes, the gzip stream is inflated with a cap before tarfile
    parses it, every member is validated, and only then are the selected
    members read -- all from the same in-memory copy. Touches no disk.
    """
    if not _RUN_ID.fullmatch(run.run_id or ""):
        raise ArchiveError("Run 식별자 형식이 올바르지 않습니다")
    if not archive_available(run):
        raise ArchiveMissing(f"{run.name}: 증거 압축 파일이 이 환경에 없습니다 ({run.archive.name})")
    try:
        if run.archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveError("압축 파일 크기가 허용 범위를 넘습니다")
        with run.archive.open("rb") as handle:
            raw = handle.read(MAX_ARCHIVE_BYTES + 1)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ArchiveError("압축 파일 크기가 허용 범위를 넘습니다")
        digest = hashlib.sha256(raw).hexdigest()
        inflated = _inflate(raw)
        with tarfile.open(fileobj=io.BytesIO(inflated), mode="r:") as tar:
            picked = _select(tar, run.run_id)
            read = {rel: _read(tar, member) for rel, member in picked.items()}
    except ArchiveError:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError, KeyError, zlib.error) as exc:
        # The exception's own text can quote member names or paths; only the
        # type is carried.
        raise ArchiveError(f"압축 파일을 읽을 수 없습니다 ({type(exc).__name__})") from None
    files = {rel: data for rel, data in read.items() if rel not in VERIFY_FILES}
    evidence = {rel: data for rel, data in read.items() if rel in VERIFY_FILES}
    sample = _sample_from(files[f"metrics/{STEP}.json"])
    return LoadedRun(run=run, digest=digest, files=files, sample=sample, evidence=evidence)


_RUN_FAILED_AT = re.compile(r"RUN FAILED at \S+")
_CHECK_ONLY_MARKS = ("PRECHECK FAILED", "PRECHECK PASSED", "--check-only: running preflight")


def _json_doc(data: bytes, what: str) -> dict:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ArchiveError(f"{what}를 읽을 수 없습니다") from None
    if not isinstance(doc, dict):
        raise ArchiveError(f"{what}의 형식이 올바르지 않습니다")
    return doc


def recorded_plan(loaded: LoadedRun) -> tuple[str, tuple[str, ...]]:
    """(run_mode, planned steps) as the run's own record shows them.

    script/main.sh, for a run that stopped in a step:
      --check-only   writes run_status "check_only" after validation and logs
                     "PRECHECK FAILED" / "PRECHECK PASSED"
      full run       writes run_status "failed" and logs "RUN FAILED at <step>"
                     -- a line only the full run's step loop emits
    and the full plan follows from the snapshot's optional_steps.intervar
    exactly as config_builder.planned_steps() derives it for a new job.
    Anything else, or both at once, is refused rather than guessed.
    """
    status = _json_doc(loaded.files["status/run_status.json"], "run_status").get("status")
    log = loaded.files["logs/pipeline.log"].decode("utf-8", "replace")
    check_only = status == "check_only" or any(mark in log for mark in _CHECK_ONLY_MARKS)
    full = status == "failed" and bool(_RUN_FAILED_AT.search(log))
    if check_only and not full:
        return "check_only", tuple(config_builder.planned_steps("check_only", False))
    if full and not check_only:
        snapshot = loaded.evidence.get(SNAPSHOT)
        if snapshot is None:
            raise ArchiveError("설정 스냅샷이 없어 계획 단계를 판단할 수 없습니다")
        optional = _json_doc(snapshot, "설정 스냅샷").get("optional_steps")
        intervar = optional.get("intervar") if isinstance(optional, dict) else None
        if not isinstance(intervar, bool):
            raise ArchiveError("설정 스냅샷에 optional_steps.intervar가 없습니다")
        return "full", tuple(config_builder.planned_steps("full", intervar))
    raise ArchiveError("실행 모드를 기록에서 판단할 수 없어 복원하지 않습니다")


def _check_declared_plan(run: "ArchiveRun", loaded: LoadedRun) -> None:
    if recorded_plan(loaded) != (run.run_mode, tuple(run.planned)):
        raise ArchiveError("Run 정의의 실행 모드·계획 단계가 Run 기록과 다릅니다")


def _loaded(run: ArchiveRun, loaded: LoadedRun | None) -> LoadedRun:
    if loaded is None:
        return load(run)
    if loaded.run != run:
        raise ArchiveError("다른 Run의 읽기 결과입니다")
    return loaded


def extract_run(run: ArchiveRun, dest_root: Path, loaded: LoadedRun | None = None) -> Path:
    """Write the run's needed files under `dest_root/<run_id>/`. Returns that dir.

    Everything is validated and read before the first file is written, so a
    refused archive leaves `dest_root` as it was.
    """
    files = _loaded(run, loaded).files
    run_dir = (dest_root / run.run_id).resolve()
    root = dest_root.resolve()
    for rel, data in sorted(files.items()):
        target = (run_dir / PurePosixPath(rel)).resolve()
        if root not in target.parents:
            raise ArchiveError("추출 경로가 대상 폴더를 벗어납니다")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:  # never overwrite
            handle.write(data)
    return dest_root / run.run_id


# --- what the run recorded ---------------------------------------------------


def _sample_from(metrics_bytes: bytes) -> str:
    try:
        doc = json.loads(metrics_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ArchiveError("00 단계 metrics 문서를 읽을 수 없습니다") from None
    sample = (doc.get("metrics") or {}).get("sample") if isinstance(doc, dict) else None
    if not isinstance(sample, str) or not sample.strip():
        raise ArchiveError(
            "00 단계 metrics에 샘플 식별자가 없습니다. 추측한 값으로 대신하지 않고 중단합니다"
        )
    return sample


def read_sample(run: ArchiveRun) -> str:
    """The sample name the run recorded. For redaction and leak counting only."""
    return load(run).sample


def forbidden_literals(run: ArchiveRun, loaded: LoadedRun | None = None) -> list[str]:
    """What must never reach the model: sample, ids and locations.

    A saved eval record states the run id on purpose in its `runId` field (it
    says which run was scored); record scans exclude that field and hold the
    rest of the record to this list.
    """
    sample = _loaded(run, loaded).sample
    return [run.run_id, sample, str(run.archive), str(run.archive.parent)]


def count_leaks(
    text: str, run: ArchiveRun, extra: Iterable[str] = (), loaded: LoadedRun | None = None
) -> int:
    """How many forbidden things `text` contains. A count, never the matches."""
    literals = [*forbidden_literals(run, loaded), *(str(value) for value in extra)]
    return literal_hits(text, literals) + count_paths(text)


# --- restoration -------------------------------------------------------------


def _insert_job(run: ArchiveRun, run_dir: Path, sample: str) -> None:
    jobs_dir = config.JOBS_ROOT / run.run_id
    db.execute(
        """INSERT INTO jobs
           (job_id, run_id, profile_id, capture_kit_id, sample_id, status, run_dir,
            config_path, samplesheet_path, run_mode, planned_steps,
            original_options, unsupported_options, error, started_at,
            finished_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run.run_id,
            run.run_id,
            PROFILE_UNKNOWN,
            None,
            sample,
            worker.DONE,
            str(run_dir),
            str(jobs_dir / "run_config.json"),
            str(jobs_dir / "samplesheet.csv"),
            run.run_mode,
            json.dumps(list(run.planned)),
            json.dumps({}),
            json.dumps([]),
            None,
            None,
            None,
            db.now_iso(),
            db.now_iso(),
        ),
    )


def _require_isolation() -> None:
    """Refuse unless config AND the open database are inside the active
    isolated_environment() work directory.

    Not a string test on config alone: the work directory comes from the
    context isolated_environment() set, every target is resolved and must lie
    under it, and the database file is the one the live connection reports
    (PRAGMA database_list) -- a connection left open on another file would
    otherwise receive the row while config looked right.
    """
    root = active_isolated_root()
    if root is None:
        raise ArchiveError("격리된 임시 환경 밖에서는 복원하지 않습니다")
    root = root.resolve()
    repo = config.ROOT.resolve()
    if root == repo or repo in root.parents:
        raise ArchiveError("임시 환경이 저장소 안에 있어 복원하지 않습니다")
    # Every directory db.connect() -> config.ensure_dirs() would create.
    for target in (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH):
        if root not in Path(target).resolve().parents:
            raise ArchiveError("설정이 격리된 임시 환경 밖을 가리켜 복원하지 않습니다")
    # An already-open connection is inspected as it is. db.connect() is not
    # called here: with no connection it would run ensure_dirs() (mkdir) --
    # harmless now that every target was checked, but a check should not write.
    if db._conn is not None:
        rows = db._conn.execute("PRAGMA database_list").fetchall()
        main = [row[2] for row in rows if row[1] == "main"]
        if not main or not main[0] or root not in Path(main[0]).resolve().parents:
            raise ArchiveError("열린 DB 연결이 격리된 임시 환경 밖을 가리켜 복원하지 않습니다")


def restore_into_current_config(run: ArchiveRun, loaded: LoadedRun | None = None) -> None:
    """Extract under `config.RUNS_ROOT` and insert the row into `config.DB_PATH`.

    Only inside isolated_environment(): checked by _require_isolation() before
    anything is written. The sample (by load) and the declared run mode and
    plan (against the run's record) are checked first as well.
    """
    loaded = _loaded(run, loaded)
    _check_declared_plan(run, loaded)
    _require_isolation()
    run_dir = extract_run(run, Path(config.RUNS_ROOT), loaded=loaded)
    _insert_job(run, run_dir, loaded.sample)


@contextmanager
def materialise(run: ArchiveRun, loaded: LoadedRun | None = None) -> Iterator[RunExplanation]:
    """Restore the run into a throwaway environment and explain it.

    Same isolation as the synthetic cases and the capture, so the agent's MCP
    server resolves the restored copy. Outside the block nothing remains.
    """
    if not archive_available(run):
        raise ArchiveMissing(f"{run.name}: 증거 압축 파일이 이 환경에 없습니다 ({run.archive.name})")

    loaded = _loaded(run, loaded)  # validated before the environment exists
    _check_declared_plan(run, loaded)
    with isolated_environment():
        restore_into_current_config(run, loaded)
        context = run_context.build_run_diagnostic_context(run.run_id)
        yield deterministic.build_run_explanation(context)


__all__ = [
    "ARCHIVE",
    "ARCHIVE_RUNS",
    "MAX_ARCHIVE_BYTES",
    "MAX_MEMBERS",
    "MAX_MEMBER_BYTES",
    "MAX_STREAM_BYTES",
    "MAX_TOTAL_BYTES",
    "OPTIONAL_FILES",
    "REQUIRED_FILES",
    "ArchiveError",
    "ArchiveMissing",
    "ArchiveRun",
    "LoadedRun",
    "archive_available",
    "archive_digest",
    "count_leaks",
    "extract_run",
    "forbidden_literals",
    "load",
    "recorded_plan",
    "materialise",
    "read_sample",
    "restore_into_current_config",
]
