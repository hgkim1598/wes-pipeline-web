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
def isolated_environment() -> Iterator[Path]:
    """Point `config` at a fresh temporary directory, and put it all back after.

    Its own runs root, its own sqlite file: the production database is never
    opened. Shared by the synthetic cases here and the preserved real runs in
    real_runs.py, so both are isolated the same way. Yields the work directory.
    """
    work = Path(tempfile.mkdtemp(prefix="wes-agent-eval-"))
    previous = (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH)
    previous_conn = db._conn

    try:
        config.RUNS_ROOT = work / "runs"
        config.JOBS_ROOT = config.RUNS_ROOT / "_jobs"
        config.UPLOAD_ROOT = work / "uploads"
        config.DB_PATH = work / "eval.db"
        for directory in (config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT):
            directory.mkdir(parents=True, exist_ok=True)
        db._conn = None
        yield work
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous_conn
        config.RUNS_ROOT, config.JOBS_ROOT, config.UPLOAD_ROOT, config.DB_PATH = previous
        rmtree(work, ignore_errors=True)


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
    "isolated_environment",
    "materialise",
]
