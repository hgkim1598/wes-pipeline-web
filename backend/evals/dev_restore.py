"""Restore a preserved real run into a persistent dev copy for the local web UI.

    cd backend
    .venv/Scripts/python.exe -m evals.dev_restore            # real_cba73e -> runs/dev_real_cba73e/

The Windows dev backend has no real run of its own -- the full runs live on
the Ubuntu VM. This makes one available to the local FastAPI + Vite pair
without touching the capture or the developer's own database:

    <target>/app.db                 a new sqlite file holding ONE jobs row
    <target>/runs/<run_id>/         a copy of the run's documents
    <target>/runs/_jobs/<run_id>/   a copy of its generated inputs
    <target>/uploads/               empty

The backend is then started with WES_DB_PATH / WES_RUNS_ROOT / WES_UPLOAD_ROOT
pointing here. Any synthesis trace the UI causes is written to this copy.

What it refuses to do
---------------------

    the target already exists           stop; nothing is deleted or replaced
    the target is not ignored by git    stop; a dev copy must not be committable
    the target overlaps the capture     stop
    the database would be the default   stop; that is the developer's own DB
    the capture changed while copying   report it and exit non-zero

The same restoration code as the evals (`real_runs.restore_into_current_config`)
does the copying, so the dev copy and the eval copy cannot drift apart. Nothing
here calls a model or runs the pipeline.

Output names the run id and paths relative to the repository, never an
absolute path or the sample name.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

from app import config, db
from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.explanation import deterministic, run_context
from app.services.explanation.llm import contract

from . import real_runs
from .agent_cases import pointed_at

DEFAULT_CASE = "real_cba73e"
DB_NAME = "app.db"


def default_target(run: real_runs.RealRun) -> Path:
    # Under /runs/, which .gitignore already ignores.
    return config.ROOT / "runs" / f"dev_{run.name}"


def shown(path: Path) -> str:
    """A path as it may be printed: relative to the repository, or not at all."""
    try:
        return path.resolve().relative_to(config.ROOT.resolve()).as_posix()
    except ValueError:
        return "<저장소 밖 경로>"


def ignored_by_git(path: Path) -> bool:
    """True when git would not track `path`. Works for a path not yet created."""
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=config.ROOT,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


class Refused(RuntimeError):
    """The restore was not started. Nothing was created."""


@dataclass(frozen=True)
class Restored:
    run_id: str
    status: str
    jobs: int
    uploads: int
    traces: int
    payload_leaks: int
    evidence_leaks: int
    capture_unchanged: bool


def _overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _refuse_unless_safe(run: real_runs.RealRun, target: Path, *, require_ignored: bool) -> None:
    if not real_runs.capture_available(run):
        raise Refused(f"capture가 이 환경에 없습니다: {run.capture_dir.name}/")
    if target.exists():
        raise Refused(
            f"대상 폴더가 이미 있습니다: {shown(target)} -- 삭제하거나 덮어쓰지 않았습니다. "
            "다른 --target을 주거나, 직접 확인한 뒤 옮기세요."
        )
    if _overlaps(target, run.capture_dir):
        raise Refused("대상 폴더가 capture와 겹칩니다.")
    if (target / DB_NAME).resolve() == Path(config.DB_PATH).resolve():
        raise Refused("대상 DB가 현재 backend가 쓰는 DB와 같습니다.")
    if require_ignored and not ignored_by_git(target):
        raise Refused(f"대상 폴더가 git에서 무시되지 않습니다: {shown(target)}")


def restore(
    run: real_runs.RealRun, target: Path, *, require_ignored: bool = True
) -> Restored:
    """Create the dev copy at `target` and check it without calling a model.

    `target` must not exist. If anything fails after it was created, the
    directory this call created is removed -- it held nothing before.
    """
    target = target.resolve()
    _refuse_unless_safe(run, target, require_ignored=require_ignored)

    before = real_runs.capture_manifest(run.capture_dir)
    target.mkdir(parents=True)
    try:
        with pointed_at(target, db_name=DB_NAME):
            real_runs.restore_into_current_config(run)
            result = _check(run, target)
        after = real_runs.capture_manifest(run.capture_dir)
    except BaseException:
        rmtree(target, ignore_errors=True)
        raise
    return Restored(**result, capture_unchanged=before == after)


def _check(run: real_runs.RealRun, target: Path) -> dict[str, object]:
    """What the backend will read, read the way the backend reads it."""

    def count(table: str) -> int:
        return db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]

    explanation = deterministic.build_run_explanation(
        run_context.build_run_diagnostic_context(run.run_id)
    )
    payload, _allowed = contract.build_payload(explanation)
    scope = run_scope.for_job(run.run_id)
    evidence = json.dumps(
        [
            read_step_evidence(scope, step.stepId).model_dump(mode="json")
            for step in explanation.steps
        ],
        ensure_ascii=False,
    )
    extra = [str(target)]
    return {
        "run_id": run.run_id,
        "status": explanation.status,
        "jobs": count("jobs"),
        "uploads": count("uploads"),
        "traces": count("synthesis_traces"),
        "payload_leaks": real_runs.count_leaks(
            json.dumps(payload, ensure_ascii=False), run, extra
        ),
        "evidence_leaks": real_runs.count_leaks(evidence, run, extra),
    }


def instructions(target: Path) -> str:
    rel = shown(target)
    return f"""
다음 단계 (Git Bash, 저장소 루트에서):

  # 1) backend -- 이 복사본을 읽도록 세 경로를 지정한다. pwd -W 는 Windows 경로를 준다.
  DEV="$(pwd -W)/{rel}"
  WES_DB_PATH="$DEV/{DB_NAME}" WES_RUNS_ROOT="$DEV/runs" WES_UPLOAD_ROOT="$DEV/uploads" \\
    backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8000

  # 2) frontend (다른 터미널)
  cd front && npm run dev

  # 3) 브라우저: http://localhost:5173/runs -> 실행 선택 -> AI 설명 패널

  AI 설명 버튼을 누르면 Claude 구독 사용량을 1회 사용한다.
  이 backend로 새 분석을 제출하지 말 것 (Windows에서 파이프라인이 실행된다).
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", choices=sorted(real_runs.REAL_RUNS), default=DEFAULT_CASE)
    parser.add_argument("--target", type=Path, default=None, help="기본값: runs/dev_<case>/")
    args = parser.parse_args(argv)

    run = real_runs.REAL_RUNS[args.case]
    target = args.target if args.target is not None else default_target(run)

    try:
        result = restore(run, target)
    except Refused as exc:
        print(f"중단: {exc}")
        return 2

    print(f"개발용 복사본 생성: {shown(target)}")
    print(f"  run           {result.run_id} ({result.status})")
    print(f"  DB 행         jobs {result.jobs} · uploads {result.uploads} · traces {result.traces}")
    print(f"  개인정보      payload {result.payload_leaks}건 · step 근거 {result.evidence_leaks}건")
    print(f"  capture 불변  {result.capture_unchanged}")
    ok = (
        result.jobs == 1
        and result.uploads == 0
        and result.traces == 0
        and result.payload_leaks == 0
        and result.evidence_leaks == 0
        and result.capture_unchanged
    )
    if not ok:
        print("오류: 검증에 실패했습니다. 복사본을 쓰지 마세요.")
        return 1
    print(instructions(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
