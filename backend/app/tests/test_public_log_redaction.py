"""The log tail and error text the job API sends to a browser.

GET /api/jobs/{id} used to return the last 200 lines of logs/pipeline.log
verbatim. main.sh writes absolute server paths into that log (run_dir,
samplesheet, the reference bundle, the report it failed on) and the sample name
into filenames and progress lines, so the run detail page showed both
(ADR-001 F6, deferred there as a separate task). The same was true of
`error`, which carries up to 40 lines of executor.log when main.sh dies before
it creates a run directory.

What these tests pin:

  hidden      absolute paths (POSIX and Windows), relative data paths, the
              job's sample / run / job identifiers -- in every string of the
              response, not only the field the screen reads
  kept        what a person needs to read the failure: the step, the check,
              the tool, the error number, the verdict, counts and durations
  stable      one output line per input line, in order; ordinary lines
              byte-identical; re-projecting projected text changes nothing

All fixtures are synthetic. Nothing here runs the pipeline or calls a model.
"""

from __future__ import annotations

import re

import pytest

from app.services import worker
from app.services.agent.privacy import WITHHELD, Redactor
from app.services.public_text import project_error, project_lines

SAMPLE = "PATIENT_A01"
RUN_ID = "wes-20260917-223831-b94559"

# A failed 00_input_validation tail in the shape main.sh writes. The sample is
# planted in a path, a filename, a quoted progress line and a lane unit.
FAILED_TAIL = [
    "[2026-09-17 22:38:31] ============================================================",
    f"[2026-09-17 22:38:31] run_id     : {RUN_ID}",
    f"[2026-09-17 22:38:31] run_dir    : /home/labuser/wes/runs/{RUN_ID}",
    f"[2026-09-17 22:38:31] samplesheet: /home/labuser/wes/runs/_jobs/{RUN_ID}/samplesheet.csv",
    "[2026-09-17 22:38:32] START 00_input_validation",
    f"[OK] Validated 1 lane row(s) for sample '{SAMPLE}'.",
    "[NOTE] reference contigs: 3366",
    "[NOTE] contig style: declared='chr', chr-prefixed=2841/3366",
    "[ERROR] Resource bundle validation failed:",
    "  - target_bed missing or empty: /srv/wes/reference/grch38/capture/target.bed",
    "  - coverage_bed missing or empty: /srv/wes/reference/grch38/capture/coverage.bed",
    "  - bcftools unavailable for /srv/wes/reference/known/dbsnp.vcf.gz: [Errno 2] No such file or directory: 'bcftools'",
    f"  - bcftools unavailable for C:\\wes\\runs\\{RUN_ID}\\{SAMPLE}.raw.vcf.gz: [Errno 2] No such file or directory: 'bcftools'",
    f"[2026-09-17 22:38:33] [WARN] [00_input_validation] FAIL resource_bundle: validation failed; see /home/labuser/wes/runs/{RUN_ID}/reports/resource_validation.txt",
    f"[2026-09-17 22:38:33]   run: fastqc_{SAMPLE}.L001",
    "[2026-09-17 22:38:33] DONE  00_input_validation status=failed exit=1 (1s)",
    "[2026-09-17 22:38:33] RUN FAILED at 00_input_validation",
    f"[2026-09-17 22:38:33]   log     : runs/{RUN_ID}/logs/pipeline.log",
]

# Lines that hold nothing to hide. They must come back byte-identical: a
# redaction that rewrites ordinary prose would cost diagnosis for nothing.
ORDINARY = [
    "[2026-09-17 22:38:32] START 00_input_validation",
    "[NOTE] reference contigs: 3366",
    "[NOTE] contig style: declared='chr', chr-prefixed=2841/3366",
    "[ERROR] Resource bundle validation failed:",
    "[2026-09-17 22:38:33] DONE  00_input_validation status=failed exit=1 (1s)",
    "[2026-09-17 22:38:33] RUN FAILED at 00_input_validation",
    "[2026-09-19 01:33:25] [WARN] [NM_MD_REPAIRED] NM and MD tags were recalculated with samtools calmd",
    "Tool returned:",
    "0",
    "PASS/FAIL ratio 3/4, depth >= 20x",
]

# Diagnostic content that must survive projection of FAILED_TAIL.
MUST_KEEP = [
    "START 00_input_validation",
    "Resource bundle validation failed",
    "target_bed missing or empty",
    "coverage_bed missing or empty",
    "bcftools unavailable for",
    "[Errno 2] No such file or directory: 'bcftools'",
    "FAIL resource_bundle: validation failed",
    "DONE  00_input_validation status=failed exit=1 (1s)",
    "RUN FAILED at 00_input_validation",
    "reference contigs: 3366",
]

_ABS_POSIX = re.compile(r"(?<![\w<>])/(?:home|srv|data|mnt|opt|tmp|Users|var|root)/")
_ABS_WINDOWS = re.compile(r"[A-Za-z]:\\|[A-Za-z]:/")


def _leaks(text: str, *literals: str) -> list[str]:
    found = []
    if _ABS_POSIX.search(text):
        found.append("posix path")
    if _ABS_WINDOWS.search(text):
        found.append("windows path")
    for literal in literals:
        if literal and literal.lower() in text.lower():
            found.append(f"literal {literal!r}")
    return found


def _redactor(sample: str | None = SAMPLE) -> Redactor:
    from app.services.agent.run_scope import redactor_for_row

    return redactor_for_row({"sample_id": sample, "run_id": RUN_ID, "job_id": RUN_ID})


# --- the projection itself --------------------------------------------------


def test_projection_hides_paths_and_identifiers():
    out = project_lines(FAILED_TAIL, _redactor())
    joined = "\n".join(out)
    assert _leaks(joined, SAMPLE, RUN_ID) == []
    assert "<path>" in joined and "<sample>" in joined


def test_projection_keeps_what_explains_the_failure():
    joined = "\n".join(project_lines(FAILED_TAIL, _redactor()))
    missing = [needle for needle in MUST_KEEP if needle not in joined]
    assert missing == []


def test_projection_keeps_one_line_per_line_in_order():
    out = project_lines(FAILED_TAIL, _redactor())
    assert len(out) == len(FAILED_TAIL)
    # The step markers stay where they were: a viewer reads the log in order.
    assert out.index(next(l for l in out if "START 00_input_validation" in l)) == 4
    assert out[-2].endswith("RUN FAILED at 00_input_validation")


def test_ordinary_lines_are_untouched():
    assert project_lines(ORDINARY, _redactor()) == ORDINARY


def test_projection_is_idempotent():
    once = project_lines(FAILED_TAIL, _redactor())
    assert project_lines(once, _redactor()) == once


def test_already_redacted_text_passes_through():
    already = [
        "  - target_bed missing or empty: <path>",
        "[OK] Validated 1 lane row(s) for sample '<sample>'.",
        "[NOTE] target BED SHA-256 verified: <digest>",
    ]
    assert project_lines(already, _redactor()) == already


def test_row_without_sample_id_still_hides_paths():
    """A row written before jobs.sample_id existed has no sample literal.

    Paths and data filenames are recognised by shape, so they still go. A bare
    sample name in prose cannot be recognised without the literal -- that gap
    is ADR-001 K1 and is not closed here; this test pins only what IS covered.
    """
    out = "\n".join(project_lines(FAILED_TAIL, _redactor(sample=None)))
    assert _leaks(out, RUN_ID) == []
    assert f"{SAMPLE}.raw.vcf.gz" not in out


def test_unprovable_line_is_withheld_not_sent_raw():
    # A separator drawn as a fullwidth slash is refused by the residual check
    # rather than guessed at (privacy.py _RESIDUAL, last alternative).
    line = "copy failed: data\uff0flab\uff0fsecret.txt"
    (out,) = project_lines([line], _redactor())
    assert "secret" not in out
    assert out == WITHHELD or "<path>" in out


def test_error_text_is_projected_line_by_line():
    """`error` holds a sentence plus up to 40 executor.log lines.

    Projected per line, so the 1000-character cap of one redacted string never
    cuts the tail short and the line structure survives.
    """
    tail = [f"line {i}: reading /home/labuser/wes/uploads/{SAMPLE}_R1.fastq.gz" for i in range(40)]
    error = "main.sh exited with code 2 before creating a run directory.\n" + "\n".join(tail)
    out = project_error(error, _redactor())
    assert out is not None
    assert _leaks(out, SAMPLE) == []
    assert out.count("\n") == error.count("\n")
    assert out.startswith("main.sh exited with code 2 before creating a run directory.")
    assert "line 39: reading <path>" in out


def test_error_none_stays_none():
    assert project_error(None, _redactor()) is None


# --- through the API: the whole response, not one field --------------------


@pytest.fixture
def failed_job(make_job, run):
    builder = run(RUN_ID).as_failing_precheck()
    builder.raw("logs/pipeline.log", "\n".join(FAILED_TAIL) + "\n")
    make_job(RUN_ID, sample_id=SAMPLE)
    return RUN_ID


def test_job_response_contains_no_path_or_identifier(client, failed_job):
    response = client.get(f"/api/jobs/{failed_job}")
    assert response.status_code == 200
    body = response.json()
    assert len(body["logTail"]) == len(FAILED_TAIL)

    # Every string in the response except the fields whose job is to BE the
    # identifier (jobId, runId). Those are the URL the browser already has.
    strings = []

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key not in ("jobId", "runId"):
            strings.append(node)

    walk(body)
    assert _leaks("\n".join(strings), SAMPLE, RUN_ID) == []


def test_job_response_log_keeps_the_causes(client, failed_job):
    joined = "\n".join(client.get(f"/api/jobs/{failed_job}").json()["logTail"])
    assert [n for n in MUST_KEEP if n not in joined] == []


def test_executor_failure_error_is_projected_in_detail_and_list(client, make_job):
    """EXEC_FAILED: no run directory, so `error` is the only text the user gets."""
    error = (
        "main.sh exited with code 2 before creating a run directory. "
        "This is a configuration or environment failure, not a pipeline result.\n"
        f"[ERROR] cannot read /home/labuser/wes/uploads/{SAMPLE}_R1.fastq.gz\n"
        "[ERROR] samplesheet rejected"
    )
    job_id = make_job(RUN_ID, sample_id=SAMPLE, status=worker.EXEC_FAILED, error=error)

    detail = client.get(f"/api/jobs/{job_id}").json()
    listed = next(j for j in client.get("/api/jobs").json()["jobs"] if j["jobId"] == job_id)

    for text in (detail["error"], listed["error"]):
        assert _leaks(text, SAMPLE) == []
        assert "before creating a run directory" in text
        assert "samplesheet rejected" in text
        assert text.count("\n") == 2


def test_step_failure_message_is_projected_in_error_and_step_messages(client, make_job, run):
    """A step failure message reaches the browser twice.

    run_status_reader joins the failed step's messages into `error`, and
    build_steps puts the same messages on steps[].messages. Both are free text
    written by main.sh, so both go through the same projection.
    """
    message = (
        f"cannot open /home/labuser/wes/uploads/{SAMPLE}_R1.fastq.gz: "
        "gzip integrity check failed (exit 1)"
    )
    builder = run(RUN_ID)
    builder.step(
        "00_input_validation",
        status="failed",
        checks=[{"name": "fastq_gzip", "status": "FAIL", "detail": message}],
        failures=[{"code": "fastq_gzip", "message": message}],
    )
    builder.run_status(
        "check_only",
        steps=[{"step_id": "00_input_validation", "status": "failed", "exit_code": 1}],
    )
    make_job(RUN_ID, sample_id=SAMPLE)

    body = client.get(f"/api/jobs/{RUN_ID}").json()
    assert body["error"] is not None
    texts = [body["error"], *body["steps"][0]["messages"]]
    assert body["steps"][0]["messages"], "the failure message must still be listed"
    for text in texts:
        assert _leaks(text, SAMPLE) == []
        assert "gzip integrity check failed (exit 1)" in text
