"""methods.md must be written completely, or the step must say it was not.

The bug this guards against: every metadata bullet in write_final_report was
written with `printf '- Pipeline: ...'`. The format string starts with a dash,
so bash's printf builtin parsed it as options and failed with

    printf: - : invalid option

Ten bullets vanished from methods.md - pipeline, sample, assay, reference
bundle, capture design, capture-kit profile, target BED, coverage BED, source
URL, core endpoint - and the document jumped straight from the title to
"## Steps executed". The analysis was unaffected, but the reproducibility record
was silently damaged and 99_finalization still reported completed / exit 0.

These tests run the real `write_final_report` extracted from script/main.sh, with
only the globals and two helpers it needs stubbed, and assert on the document it
actually produces - not on the source text.

`test_leading_dash_printf_without_dashdash_fails` is the control: it shows the
old form really does fail in this bash, so the rest is not passing by accident.
"""

from __future__ import annotations

import os
import sys
import re
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from .. import config

BASH = shutil.which(config.BASH_BIN) or shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not on PATH")

# Sections methods.md must always carry. The conditional "Target BED source URL"
# bullet is not here: it is only emitted when the registry supplies a URL.
REQUIRED_MARKERS = [
    "# Methods — run",
    "- Pipeline:",
    "- Sample:",
    "- Assay:",
    "- Reference bundle:",
    "- Capture design:",
    "- Capture-kit profile:",
    "- Target BED:",
    "- Coverage BED:",
    "- Core endpoint: raw VCF",
    "## Steps executed",
    "## Tool versions",
    "## Resource checksums",
    "## Limitations",
]


def extract_function(name: str) -> str:
    """Lift one shell function out of main.sh as it is on disk.

    Extracting rather than copying is the point: a copy would keep passing after
    main.sh changed.

    Heredocs are tracked while scanning for the closing brace. write_final_report
    embeds a Python block whose dict literal closes with `}` in column 0, and a
    naive search would cut the function in half there.
    """
    lines = config.PIPELINE_SH.read_text(encoding="utf-8").splitlines(keepends=True)

    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))

    heredoc: str | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
            continue
        opening = re.search(r"<<-?'([A-Za-z_][A-Za-z0-9_]*)'", line)
        if opening is not None:
            heredoc = opening.group(1)
            continue
        if index > start and line.rstrip("\n") == "}":
            return "".join(lines[start : index + 1])

    raise AssertionError(f"could not find the end of {name}() in main.sh")


def harness(tmp_path, *, run_dir_name: str = "run") -> str:
    """Everything write_final_report reads, and nothing else.

    json_get and resolve_python are stubbed because they are separate units with
    their own behaviour; the document generator is what is under test here.
    """
    run_dir = tmp_path / run_dir_name
    steps_dir = run_dir / "status" / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "versions.txt").write_text("bwa 0.7.17\nsamtools 1.19\n", encoding="utf-8")
    (run_dir / "resources.sha256").write_text("abc123  reference.fa\n", encoding="utf-8")

    posix = run_dir.as_posix()
    # The interpreter running the tests, so the embedded Python block does not
    # depend on whatever `python3` resolves to inside Git Bash.
    python = pathlib.Path(sys.executable).as_posix()
    return f"""
set -Eeuo pipefail

RUN_DIR='{posix}'
STEPS_DIR='{posix}/status/steps'
VERSIONS_TXT='{posix}/versions.txt'
RESOURCE_SHA256='{posix}/resources.sha256'

RUN_ID='wes-20260904-201711-97ea7b'
PIPELINE_NAME='wes-germline'
PIPELINE_VERSION='1.2.0'
SAMPLE_ID='SRR2962669.subset_5M'
BUNDLE_ID='grch38_wes_germline'
ASSEMBLY='GRCh38'
CONTIG_STYLE='chr'
TARGET_BED_MANUFACTURER='Integrated DNA Technologies'
TARGET_BED_CAPTURE_KIT_NAME='xGen Exome Hyb Panel'
TARGET_BED_CAPTURE_KIT_VERSION='v2'
TARGET_BED_DESIGN_ID='xgen-exome-hyb-panel-v2'
CAPTURE_KIT_ID='idt_xgen_exome_hyb_panel_v2'
CAPTURE_KIT_MODE='registry'
TARGET_BED_FILE_NAME='idt_xgen_exome_hyb_panel_v2.targets.hg38.bed'
TARGET_BED_GENOME_BUILD='GRCh38'
TARGET_BED_SOURCE='IDT official panel files'
TARGET_BED_SHA256='9b18f157033c49380e146ab370258976aa0eaf2a48e4f466c05a5e9f4e41df3a'
TARGET_BED_SOURCE_URL=''
COVERAGE_BED='{posix}/coverage.bed'
COVERAGE_BED_SHA256='3934ebff86cba64901f1441435feec75fe8fab21cf7b83d96a683552a3bcc66f'

log() {{ printf '%s\\n' "$*" >&2; }}
json_get() {{ printf '%s' "${{3:-}}"; }}
resolve_python() {{ printf '%s' '{python}'; }}
step_warning() {{ printf 'STEP_WARNING\\t%s\\n' "$1"; }}

{extract_function("write_final_report")}
"""


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    """Run a script from a file rather than `bash -c`.

    On Windows the script would otherwise go through MSVC argv quoting and then
    be re-parsed by MSYS bash. The document contains an em dash and backticks,
    and that round trip corrupts them into a syntax error. A file is read as
    UTF-8 bytes and avoids the whole problem.
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=".sh", encoding="utf-8", newline="\n", delete=False
    ) as handle:
        handle.write(script)
        path = handle.name
    try:
        return subprocess.run(
            [BASH, path],
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        os.unlink(path)


# --- the control -------------------------------------------------------------


def test_leading_dash_printf_without_dashdash_fails():
    """The reported failure, reproduced: printf treats '- ...' as options."""
    completed = run_bash("printf '- Pipeline: %s\\n' x")

    assert completed.returncode != 0, completed
    assert "invalid option" in completed.stderr, completed.stderr


def test_leading_dash_printf_with_dashdash_succeeds():
    """`printf --` is the form main.sh's Limitations section already used."""
    completed = run_bash("printf -- '- Pipeline: %s\\n' x")

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "- Pipeline: x\n", completed.stdout


# --- the real generator ------------------------------------------------------


def test_methods_document_is_generated_without_printf_errors(tmp_path):
    completed = run_bash(harness(tmp_path) + "\nwrite_final_report\n")

    assert completed.returncode == 0, completed.stderr
    assert "invalid option" not in completed.stderr, completed.stderr
    assert "usage: printf" not in completed.stderr, completed.stderr


@pytest.mark.parametrize("marker", REQUIRED_MARKERS)
def test_methods_document_contains_every_required_section(tmp_path, marker):
    """Asserted against the produced file, not against main.sh's source text."""
    completed = run_bash(harness(tmp_path) + "\nwrite_final_report\n")
    assert completed.returncode == 0, completed.stderr

    document = (tmp_path / "run" / "methods.md").read_text(encoding="utf-8")

    assert marker in document, f"{marker!r} missing from:\n{document}"


def test_metadata_bullets_carry_the_run_values(tmp_path):
    """The bullets that were lost must carry real values, not empty labels."""
    completed = run_bash(harness(tmp_path) + "\nwrite_final_report\n")
    assert completed.returncode == 0, completed.stderr

    document = (tmp_path / "run" / "methods.md").read_text(encoding="utf-8")

    assert "- Pipeline: wes-germline 1.2.0" in document, document
    assert "SRR2962669.subset_5M" in document, document
    assert "idt_xgen_exome_hyb_panel_v2" in document, document
    assert "GRCh38" in document, document
    # The core endpoint statement is the one claim a reader must not miss.
    assert "No variant filtering was applied" in document, document


def test_bullet_block_precedes_steps_executed(tmp_path):
    """The exact shape of the damage: title straight to '## Steps executed'."""
    completed = run_bash(harness(tmp_path) + "\nwrite_final_report\n")
    assert completed.returncode == 0, completed.stderr

    document = (tmp_path / "run" / "methods.md").read_text(encoding="utf-8")

    assert document.index("- Pipeline:") < document.index("## Steps executed"), document


# --- failure is reported, not swallowed --------------------------------------


def test_write_final_report_fails_when_the_bullets_are_dropped(tmp_path):
    """Reproduce the original damage against the real function.

    `printf` is shadowed by a function that refuses any format starting with a
    dash, which is exactly what the builtin did before the fix. Every metadata
    bullet therefore disappears from the document, and write_final_report's own
    verification must return non-zero instead of reporting success.
    """
    completed = run_bash(
        harness(tmp_path)
        + """
printf() {
    case "${1:-}" in
        -*) return 2 ;;
        *) builtin printf "$@" ;;
    esac
}
rc=0
write_final_report || rc=$?
printf_rc=$rc
builtin printf 'rc=%s\n' "$printf_rc"
"""
    )

    assert completed.returncode == 0, completed.stderr
    assert "rc=1" in completed.stdout, completed.stdout
    # The log line must name what went missing, so the operator can act on it.
    assert "methods.md is incomplete" in completed.stderr, completed.stderr
    assert "- Pipeline:" in completed.stderr, completed.stderr

    # The damage is the one that was actually observed: title, then straight to
    # the steps table.
    document = (tmp_path / "run" / "methods.md").read_text(encoding="utf-8")
    assert "- Pipeline:" not in document, document
    assert "## Steps executed" in document, document


def test_finalization_reports_a_warning_when_the_document_is_incomplete():
    """run_finalization must not call write_final_report bare.

    errexit is disabled inside dispatch_step (run_pipeline calls it on the left
    of `||`), so a bare call would discard the non-zero return exactly as the
    original bug did.
    """
    finalization = extract_function("run_finalization")

    assert "if ! write_final_report; then" in finalization, finalization
    assert "METHODS_DOCUMENT_INCOMPLETE" in finalization, finalization
    # A provenance document is not a core analysis artifact: run_final_validation
    # fails the run only for BAM/gVCF/raw VCF. This must stay a warning.
    assert "step_warning" in finalization, finalization
    assert not re.search(r"step_check_fail\s+\"METHODS", finalization), finalization
