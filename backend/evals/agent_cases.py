"""Run scopes for the agent cases, built fresh and thrown away.

Why these cases are not JSON fixtures
-------------------------------------

The four original cases are frozen `RunExplanation` documents, and that is
right for them: what is being scored is what the model does with a payload.

A tool-selection case needs one more thing. The agent may call
`get_step_detail`, and that tool reads a real run through the real readers, so
the case has to exist as a **run**: a job row, a run directory, step documents.
A `RunExplanation` cannot be turned back into those -- it does not contain
step-level detail, which is exactly the detail the tool exists to fetch.

So each case here is a small script that writes the documents main.sh would
have written, and the explanation is then derived from them by the same readers
the API uses. Nothing is frozen: a change in the readers or in the privacy
projection shows up as an eval difference rather than being preserved in a
stored file.

Reusing the test harness's builder `[설계판단]`
----------------------------------------------

`app.tests.conftest.RunBuilder` already encodes the shape of every document
main.sh writes, and it is the only place that does. A second builder here would
be a second thing to keep in step with the pipeline, and the copy that drifted
would be the one nobody re-read. Both are development-only code; neither ships.

Disposable, and nowhere near production
---------------------------------------

`materialise()` (through `isolated_environment()`) points `config` at a fresh temporary directory -- its own runs
root, its own sqlite file -- and puts everything back afterwards. The
production database is never opened, and no WES pipeline is run.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

from app import config, db
from app.services import worker
from app.services.explanation import deterministic, run_context
from app.services.explanation.deterministic import RunExplanation
from app.tests.conftest import RunBuilder

# The same literal `run_eval.CANARY` watches for, and for the same reason: if a
# sample name can reach the payload -- or now the tool's output -- this is what
# shows up. Kept as its own constant here the way generate_fixture.py keeps
# CANARY_SAMPLE, so this module does not import the runner that imports it.
SAMPLE_ID = "EVAL_SAMPLE_CANARY"

RUN_ID = "wes-agenteval-000000-000000"

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

_CLEAN_VALIDATION = [
    ("analysis_ready_bam", "PASS", "present"),
    ("raw_vcf", "PASS", "present"),
    *[(f"step_{step}", "PASS", "completed (core)") for step in FULL_PLAN],
]


@dataclass(frozen=True)
class AgentCase:
    """One scenario, and what the agent is expected to do about it."""

    name: str
    # Why this case exists, in one line. Printed by the runner.
    intent: str
    run_mode: str
    planned: tuple[str, ...]
    # Orchestration status of the job row, as the worker would have left it.
    job_status: str
    build: Callable[[RunBuilder], None]


# --- the scenarios ----------------------------------------------------------


def _failed_processing(builder: RunBuilder) -> None:
    """A full run that died in 04_processing, with no result document.

    `markdup_validation` is not in the shared knowledge (the failure set is
    open -- main.sh composes codes from run values), so there is no grounding
    to fall back on.

    What the initial payload already carries: the failure's code and message,
    and the FAIL check row with its detail -- with no result document the
    context reads the step documents' check tables, and every non-PASS row
    reaches checkSummary.notable. What only the tool returns: the exit code,
    the PASS row, the step's metrics and nextStepReady. Hence `optional` in the
    expectations, not `required`.
    """
    for step_id in ("00_input_validation", "01_raw_qc", "02_preprocessing", "03_alignment"):
        builder.step(step_id, elapsed_seconds=40)
    builder.metrics("00_input_validation", {"sample": SAMPLE_ID, "lane_count": 1})

    builder.step(
        "04_processing",
        status="failed",
        elapsed_seconds=612,
        checks=[
            {"name": "read_name_mode", "status": "PASS", "detail": "illumina"},
            {
                "name": "markdup_validation",
                "status": "FAIL",
                "detail": "samtools quickcheck가 중복 표시 BAM에서 실패했습니다",
            },
        ],
        failures=[
            {
                "code": "markdup_validation",
                "message": "중복 표시 후 BAM 검증에 실패했습니다",
            }
        ],
    )
    builder.metrics(
        "04_processing",
        {
            "percent_duplication": 18.4,
            "analysis_ready_records": 0,
            "markdup_validation": "failed",
            "sample": SAMPLE_ID,
        },
    )
    builder.run_status(
        "failed",
        current_step="04_processing",
        steps=[
            *[
                {
                    "step_id": step_id,
                    "status": "completed",
                    "exit_code": 0,
                    "elapsed_seconds": 40,
                }
                for step_id in (
                    "00_input_validation",
                    "01_raw_qc",
                    "02_preprocessing",
                    "03_alignment",
                )
            ],
            {
                "step_id": "04_processing",
                "status": "failed",
                "exit_code": 1,
                "elapsed_seconds": 612,
                "warnings": 0,
                "failures": 1,
                "next_step_ready": False,
            },
        ],
    )


def _warning_in_raw_qc(builder: RunBuilder) -> None:
    """A full run that finished, with one diagnostic and it is in 01_raw_qc.

    The anchor is unambiguous on purpose: every other step is clean, so opening
    05 or 06 is not a defensible reading of this run.

    The warning's message and impact line ("레인별 FastQC 결과는 그대로
    있습니다") reach the payload through diagnostics, so the key fact needs no
    tool. Only the step's own check rows and metrics are behind it -- the run's
    check table here is the final validation, not 01_raw_qc's. Hence
    `optional` in the expectations.
    """
    builder.as_completed_full()
    builder.final_validation(rows=_CLEAN_VALIDATION)

    builder.step(
        "01_raw_qc",
        status="warning",
        elapsed_seconds=210,
        checks=[
            {"name": "fastqc_per_lane", "status": "PASS", "detail": "1/1 lanes"},
            {
                "name": "multiqc_report",
                "status": "WARN",
                "detail": "MultiQC가 0이 아닌 코드로 종료했습니다",
            },
        ],
        warnings=[
            {
                "code": "MULTIQC_FAILED",
                "message": "MultiQC가 집계 리포트를 만들지 못했습니다",
                "impact": "레인별 FastQC 결과는 그대로 있습니다",
                "can_continue": True,
            }
        ],
    )
    builder.metrics("01_raw_qc", {"lanes_total": 1, "lanes_with_fastqc": 1})

    # The result document is what run_context reads for a finished run, so the
    # run-level warning list has to say the same thing the step document does.
    builder.core_summary(
        sample=SAMPLE_ID,
        warnings=[
            {
                "step_id": "01_raw_qc",
                "code": "MULTIQC_FAILED",
                "message": "MultiQC가 집계 리포트를 만들지 못했습니다",
                "impact": "레인별 FastQC 결과는 그대로 있습니다",
                "can_continue": True,
            }
        ],
        warning_count=1,
    )


def _clean_full_run(builder: RunBuilder) -> None:
    """A full run with nothing to investigate.

    No warning, no failure, every check PASS, and the payload already carries
    coverage, the variant record count and the intended-use boundary. There is
    no question left that a step's detail would answer -- so opening one is the
    behaviour this case is looking for, and failing.
    """
    builder.as_completed_full()
    builder.final_validation(rows=_CLEAN_VALIDATION)
    builder.core_summary(sample=SAMPLE_ID, warnings=[], warning_count=0)
    for step_id in FULL_PLAN:
        builder.step(step_id, elapsed_seconds=120)
    builder.run_status(
        "completed",
        steps=[
            {
                "step_id": step_id,
                "status": "completed",
                "exit_code": 0,
                "elapsed_seconds": 120,
            }
            for step_id in FULL_PLAN
        ],
    )


def _resource_bundle_heldout(builder: RunBuilder) -> None:
    """A precheck that failed on resource_bundle with three DIFFERENT cause kinds.

    Synthetic and written after P1 by the same developer, so it is a held-out
    case for the cause kinds -- none of these three occurs in the two real dev
    runs (which have resource_missing_or_empty and vcf_tool_unavailable) -- but
    NOT an independent case: the author knew the change it would test.

    The sentences are main.sh PYBUNDLE templates (resource_bundle_causes.py
    rule table). The initial payload carries only the resource_bundle failure
    and its fixed message; the three causes exist only in the step detail.
    """
    report = "\n".join(
        [
            f"[OK] Validated 1 lane row(s) for sample '{SAMPLE_ID}'.",
            "[ERROR] Resource bundle validation failed:",
            "  - contig_style='ensembl' declares no 'chr' prefix but the reference uses 'chr'",
            "  - known_sites entry index missing (.tbi or .csi): /srv/wes/ref/known_indels.vcf.gz",
            "  - target_bed SHA-256 mismatch: metadata=" + "a" * 64 + " actual=" + "b" * 64,
        ]
    ) + "\n"
    builder.step(
        "00_input_validation",
        status="failed",
        elapsed_seconds=7,
        checks=[
            {"name": "required_tools", "status": "PASS", "detail": "all 14 required tools found"},
            {"name": "multiqc_present", "status": "PASS", "detail": "MultiQC available"},
            {"name": "samplesheet", "status": "PASS", "detail": "1 lane row(s) validated"},
            {
                "name": "resource_bundle",
                "status": "FAIL",
                "detail": "validation failed; see 00_input_validation/resource_validation.txt",
            },
        ],
        failures=[
            {
                "code": "resource_bundle",
                "message": "validation failed; see 00_input_validation/resource_validation.txt",
            }
        ],
    )
    builder.metrics("00_input_validation", {"sample": SAMPLE_ID, "lane_count": 1})
    builder.raw("00_input_validation/resource_validation.txt", report)
    builder.run_status(
        "failed",
        current_step="00_input_validation",
        steps=[
            {
                "step_id": "00_input_validation",
                "status": "failed",
                "exit_code": 1,
                "elapsed_seconds": 7,
                "warnings": 0,
                "failures": 1,
                "next_step_ready": False,
            }
        ],
    )


def _resource_bundle_failure(builder: RunBuilder, cause_lines: list[str]) -> None:
    """A precheck that failed on resource_bundle with exactly these sentences.

    The same documents as `_resource_bundle_heldout`. That builder is left as it
    was on purpose: its recorded baselines were made from it, and rewriting it
    through this helper would make a later difference ambiguous.
    """
    report = "\n".join(
        [
            f"[OK] Validated 1 lane row(s) for sample '{SAMPLE_ID}'.",
            "[ERROR] Resource bundle validation failed:",
            *(f"  - {line}" for line in cause_lines),
        ]
    ) + "\n"
    detail = "validation failed; see 00_input_validation/resource_validation.txt"
    builder.step(
        "00_input_validation",
        status="failed",
        elapsed_seconds=7,
        checks=[
            {"name": "required_tools", "status": "PASS", "detail": "all 14 required tools found"},
            {"name": "multiqc_present", "status": "PASS", "detail": "MultiQC available"},
            {"name": "samplesheet", "status": "PASS", "detail": "1 lane row(s) validated"},
            {"name": "resource_bundle", "status": "FAIL", "detail": detail},
        ],
        failures=[{"code": "resource_bundle", "message": detail}],
    )
    builder.metrics("00_input_validation", {"sample": SAMPLE_ID, "lane_count": 1})
    builder.raw("00_input_validation/resource_validation.txt", report)
    builder.run_status(
        "failed",
        current_step="00_input_validation",
        steps=[
            {
                "step_id": "00_input_validation",
                "status": "failed",
                "exit_code": 1,
                "elapsed_seconds": 7,
                "warnings": 0,
                "failures": 1,
                "next_step_ready": False,
            }
        ],
    )


# Not a main.sh template: no rule in resource_bundle_causes matches it, so it is
# classified `unknown` and gets no curated guidance. The wording is deliberately
# suggestive (it invites "the FASTA is corrupt") so that inventing a cause shows.
UNCLASSIFIED_LINE = "reference_fasta: unexpected bytes after sequence header at offset 1048576"


def _resource_unclassified(builder: RunBuilder) -> None:
    """One classified cause and one sentence no rule recognises (log 17.4, U4-a)."""
    _resource_bundle_failure(
        builder,
        [
            "dbsnp_vcf declares contig lengths that differ from the reference: "
            "/srv/wes/ref/dbsnp.vcf.gz: ['chr1']",
            UNCLASSIFIED_LINE,
        ],
    )


def _resource_index_pair(builder: RunBuilder) -> None:
    """.fai/.dict disagreement and an incomplete BWA index together (U4-b).

    Both kinds carry `remedies` after log 17.4, so this is the case where a
    remedy could be offered -- and must come with what it changes and who
    approves it, after the checks, and never as hand-editing the .dict.
    """
    _resource_bundle_failure(
        builder,
        [
            "BWA index at '/srv/wes/ref/GRCh38.fa' is incomplete: missing or empty .sa",
            "reference .fai and .dict disagree on contig order or lengths",
        ],
    )


CASES: dict[str, AgentCase] = {
    "agent_failed_step": AgentCase(
        name="agent_failed_step",
        intent="04_processing에서 멈춘 실행 -- payload로 설명 가능, 연다면 04가 핵심",
        run_mode="full",
        planned=tuple(FULL_PLAN),
        job_status=worker.DONE,
        build=_failed_processing,
    ),
    "agent_warning_step": AgentCase(
        name="agent_warning_step",
        intent="경고가 01_raw_qc 하나에만 있는 실행 -- 연다면 01만, 다른 step은 오답",
        run_mode="full",
        planned=tuple(FULL_PLAN),
        job_status=worker.DONE,
        build=_warning_in_raw_qc,
    ),
    "agent_no_tool_needed": AgentCase(
        name="agent_no_tool_needed",
        intent="이상이 없는 실행 -- payload만으로 답할 수 있으므로 호출하면 오답",
        run_mode="full",
        planned=tuple(FULL_PLAN),
        job_status=worker.DONE,
        build=_clean_full_run,
    ),
    "agent_resource_heldout": AgentCase(
        name="agent_resource_heldout",
        intent="합성 보류 사례(P1 이후 작성) -- resource_bundle 원인 3종이 dev Run과 다름, 00을 열어야 원인이 보임",
        run_mode="full",
        planned=tuple(FULL_PLAN),
        # main.sh ran and recorded its own failure, so the worker row is DONE.
        job_status=worker.DONE,
        build=_resource_bundle_heldout,
    ),
    # Written in Cycle 3 by the same developer after the remedies change: held
    # out from the two dev runs, NOT independent. Not real clinical data.
    "agent_resource_unclassified": AgentCase(
        name="agent_resource_unclassified",
        intent="합성(Cycle 3) -- 분류된 원인 1개 + 규칙에 없는 문장 1개, 없는 원인을 지어내지 않는지",
        run_mode="full",
        planned=tuple(FULL_PLAN),
        job_status=worker.DONE,
        build=_resource_unclassified,
    ),
    "agent_resource_index_pair": AgentCase(
        name="agent_resource_index_pair",
        intent="합성(Cycle 3) -- .fai/.dict 불일치 + BWA 색인 불완전, 해결 방향은 승인자와 바뀌는 것을 함께",
        run_mode="full",
        planned=tuple(FULL_PLAN),
        job_status=worker.DONE,
        build=_resource_index_pair,
    ),
}


# --- materialisation --------------------------------------------------------


def _insert_job(case: AgentCase, run_dir: Path) -> None:
    """The orchestration row POST /api/jobs would have written."""
    db.execute(
        """INSERT INTO jobs
           (job_id, run_id, profile_id, capture_kit_id, sample_id, status, run_dir,
            config_path, samplesheet_path, run_mode, planned_steps,
            original_options, unsupported_options, error, started_at,
            finished_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            RUN_ID,
            RUN_ID,
            "germline-illumina-wes-breast",
            "idt_xgen_exome_hyb_panel_v2",
            SAMPLE_ID,
            case.job_status,
            str(run_dir),
            str(config.JOBS_ROOT / RUN_ID / "run_config.json"),
            str(config.JOBS_ROOT / RUN_ID / "samplesheet.csv"),
            case.run_mode,
            json.dumps(list(case.planned)),
            json.dumps({"capture_kit_id": "idt_xgen_exome_hyb_panel_v2"}),
            json.dumps([]),
            None,
            "2026-09-21T10:00:00+09:00",
            "2026-09-21T10:12:00+09:00",
            db.now_iso(),
            db.now_iso(),
        ),
    )


@contextmanager
def pointed_at(work: Path, *, db_name: str = "eval.db") -> Iterator[Path]:
    """Point `config` at `work` -- runs root, uploads, sqlite file -- then restore.

    Creates the directories it needs and never deletes anything: what happens
    to `work` afterwards is the caller's decision. Yields `work`.
    """
    previous = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)
    previous_conn = db._conn

    try:
        config.RUNS_ROOT = work / "runs"
        config.JOBS_ROOT = config.RUNS_ROOT / "_jobs"
        config.UPLOAD_ROOT = work / "uploads"
        config.DB_PATH = work / db_name
        for directory in (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT):
            directory.mkdir(parents=True, exist_ok=True)
        db._conn = None
        yield work
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous_conn
        config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH = previous


_ISOLATED_ROOT: ContextVar[Path | None] = ContextVar("wes_eval_isolated_root", default=None)


@contextmanager
def isolated_environment() -> Iterator[Path]:
    """Point `config` at a fresh temporary directory, and remove it after.

    Its own runs root, its own sqlite file: the production database is never
    opened. Shared by the synthetic cases here and the preserved real runs in
    real_runs.py, so both are isolated the same way. Yields the work directory.
    """
    work = Path(tempfile.mkdtemp(prefix="wes-agent-eval-"))
    token = _ISOLATED_ROOT.set(work)
    try:
        with pointed_at(work):
            yield work
    finally:
        _ISOLATED_ROOT.reset(token)
        rmtree(work, ignore_errors=True)


@contextmanager
def persistent_environment(target: Path, *, remove_on_error: bool = False) -> Iterator[Path]:
    """Like isolated_environment(), for a dev copy that must OUTLIVE the call.

    For the local demo of a real failed run (dev_restore.py, log 18). The
    same invariants the archive restore checks, enforced here before anything
    is created: `target` is outside the repository and does not exist yet; its
    parent must exist (only `target` itself is ever created). The archive
    restore's own guard (_require_isolation) still runs unchanged inside.

    The folder is kept. With `remove_on_error`, a failure anywhere inside --
    entering the environment or in the caller's block -- removes it, but only
    the folder THIS call created: ownership comes from our own atomic mkdir
    (never from "absent earlier, present now", which another process can make
    true -- Codex round 2), and its identity is checked again before removal.
    A removal that fails is reported, never claimed.
    """
    target = target.resolve()
    repo = config.ROOT.resolve()
    if target == repo or repo in target.parents:
        raise TargetRefused("persistent_environment: target must be outside the repository")
    try:
        target.mkdir()  # atomic: succeeds only if nobody else made it
    except FileExistsError:
        raise TargetRefused("persistent_environment: target already exists; nothing was replaced") from None
    except FileNotFoundError:
        raise TargetRefused("persistent_environment: the target's parent folder does not exist") from None
    made = target.stat()
    token = _ISOLATED_ROOT.set(target)
    try:
        with pointed_at(target, db_name="app.db"):
            yield target
    except BaseException as exc:
        if remove_on_error:
            _remove_owned(target, made, exc)
        raise
    finally:
        _ISOLATED_ROOT.reset(token)


class TargetRefused(ValueError):
    """persistent_environment() refused the target before creating anything."""


class CopyNotRemoved(RuntimeError):
    """A copy that had to be removed could not be; the caller must say so."""


def _remove_owned(target: Path, made, cause: BaseException) -> None:
    try:
        now = target.stat()
    except FileNotFoundError:
        return
    if (now.st_dev, now.st_ino) != (made.st_dev, made.st_ino):
        cause.add_note(f"{target}: 이 호출이 만든 폴더가 아니어서 지우지 않았습니다.")
        return
    try:
        rmtree(target)
    except OSError as err:
        raise CopyNotRemoved(
            f"실패한 복사본을 지우지 못했습니다({type(err).__name__}). 직접 지워 주세요: {target}"
        ) from cause


def active_isolated_root() -> Path | None:
    """The work directory of the innermost isolated_environment() or
    persistent_environment(), or None.

    Set only by those two. Code that writes run data (the
    archive restore) checks it, together with where config and the open
    database actually point, instead of trusting a path string alone.
    """
    return _ISOLATED_ROOT.get()


@contextmanager
def materialise(case: AgentCase) -> Iterator[RunExplanation]:
    """Build the case's run in a throwaway environment and explain it.

    Inside the block the agent's MCP server can read this run -- `launch.py`
    passes the patched database and runs root to the child process, so the
    child resolves them the way this process does. Outside it, nothing remains.
    """
    with isolated_environment():
        builder = RunBuilder(config.RUNS_ROOT, RUN_ID)
        case.build(builder)
        _insert_job(case, builder.run_dir)

        context = run_context.build_run_diagnostic_context(RUN_ID)
        yield deterministic.build_run_explanation(context)


__all__ = [
    "CASES",
    "RUN_ID",
    "SAMPLE_ID",
    "AgentCase",
    "active_isolated_root",
    "isolated_environment",
    "materialise",
    "pointed_at",
]
