"""main.sh's BAM header checks must survive SIGPIPE.

The bug this guards against: `samtools view -H "$bam" | grep -q '^@HD.*SO:coordinate'`.
`grep -q` exits at the first match and closes the pipe; samtools is killed by
SIGPIPE and exits 141. main.sh runs under `set -o pipefail`, so the pipeline
reports 141 *even though grep matched*, and a correct, coordinate-sorted BAM is
recorded as a failed check. A real run produced `PIPESTATUS=141 0` on a BAM
whose header did contain `@HD VN:1.5 SO:coordinate`.

The helpers are extracted from script/main.sh as it is on disk and run in a real
bash under the same `set -Eeuo pipefail`, with `samtools` replaced by a shell
function. Extracting rather than copying is the point: a copy would keep passing
after main.sh changed.

`test_old_pipeline_pattern_still_reproduces_the_bug` is what makes the rest
meaningful. It runs the *old* pattern in the same harness and asserts it really
does produce 141; without it, the other tests could pass simply because the fake
header was too small to fill a pipe buffer.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from .. import config

BASH = shutil.which(config.BASH_BIN) or shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not on PATH")

HELPERS_START = "# --- BAM header reads ---"
HELPERS_END = "# 2b. Step lifecycle"

# A header big enough that samtools is still writing when grep -q exits.
# @HD is deliberately the first line, which is what makes the close immediate.
FAKE_HEADER_AWK = (
    'BEGIN {{ printf "@HD\\tVN:1.5\\tSO:{sort_order}\\n"; '
    'for (i = 1; i <= 5000; i++) printf "@SQ\\tSN:chr%d\\tLN:248956422\\n", i; '
    'printf "@RG\\tID:{sample}.L001\\tSM:{sample}\\tPL:ILLUMINA\\n" }}'
)


def helper_source() -> str:
    """The three helper functions, lifted out of main.sh."""
    text = config.PIPELINE_SH.read_text(encoding="utf-8")
    start = text.index(HELPERS_START)
    end = text.index(HELPERS_END, start)
    return text[start:end]


def fake_samtools(sort_order: str = "coordinate", sample: str = "DEMO_WES") -> str:
    """A `samtools` shell function. A function shadows the real command, so no
    PATH or executable-bit games are needed (this suite also runs on Windows)."""
    program = FAKE_HEADER_AWK.format(sort_order=sort_order, sample=sample)
    return f"samtools() {{ awk '{program}'; }}\n"


def fake_samtools_failing() -> str:
    """samtools that cannot read the file at all: no output, non-zero exit."""
    return "samtools() { return 1; }\n"


def run_bash(script: str) -> str:
    completed = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"harness script failed ({completed.returncode})\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    return completed.stdout


def check_script(samtools_def: str, sample: str = "DEMO_WES") -> str:
    """Read the header once, then run both checks — exactly as main.sh does."""
    return f"""
set -Eeuo pipefail
{samtools_def}
{helper_source()}

if header=$(read_bam_header fake.bam); then read_ok=1; else read_ok=0; fi
if bam_header_sorted_by_coordinate "${{header:-}}"; then sorted=1; else sorted=0; fi
if bam_header_has_sample "${{header:-}}" "{sample}"; then sm=1; else sm=0; fi
echo "read_ok=$read_ok sorted=$sorted sm=$sm bytes=${{#header}}"
"""


# --- the control -------------------------------------------------------------


def test_old_pipeline_pattern_still_reproduces_the_bug():
    """`samtools view -H | grep -q` returns 141 while grep reports a match.

    This is the reported failure, reproduced. If this test ever stops failing
    the way it does here, the tests below stop proving anything.
    """
    output = run_bash(
        f"""
set -Eeuo pipefail
{fake_samtools()}
set +e
samtools view -H fake.bam 2>/dev/null | grep -q '^@HD.*SO:coordinate'
pipe=("${{PIPESTATUS[@]}}")
set -e
echo "pipestatus=${{pipe[*]}}"
"""
    )

    # 141 = 128 + SIGPIPE(13) for samtools, 0 for grep: grep DID match.
    assert "pipestatus=141 0" in output, output


# --- the fix -----------------------------------------------------------------


def test_coordinate_sorted_header_passes_both_checks():
    """The exact case that used to fail: SO:coordinate present, big header."""
    output = run_bash(check_script(fake_samtools()))

    assert "read_ok=1" in output, output
    assert "sorted=1" in output, output
    assert "sm=1" in output, output
    # Proves the header really was larger than a pipe buffer.
    assert int(output.split("bytes=")[1]) > 65536, output


def test_helpers_do_not_run_under_a_pipe():
    """read_bam_header must not be spliced back into a pipeline.

    The whole fix is that nothing closes samtools' stdout early. A future edit
    that reintroduces `| grep` would restore the bug, so the source is checked.
    """
    source = config.PIPELINE_SH.read_text(encoding="utf-8")
    offending = [
        line.strip()
        for line in source.splitlines()
        if "samtools view -H" in line
        and "|" in line.split("samtools view -H", 1)[1]
        and not line.lstrip().startswith("#")
    ]
    assert offending == [], offending


# --- the validator still validates -------------------------------------------


def test_queryname_sorted_header_fails_the_sort_check():
    """The fix must not turn the check into a rubber stamp."""
    output = run_bash(check_script(fake_samtools(sort_order="queryname")))

    assert "read_ok=1" in output, output
    assert "sorted=0" in output, output


def test_wrong_sample_fails_the_read_group_check():
    output = run_bash(check_script(fake_samtools(sample="OTHER_SAMPLE")))

    assert "read_ok=1" in output, output
    assert "sm=0" in output, output


def test_unreadable_header_is_reported_as_a_read_failure():
    """A samtools failure is a different finding from a wrong header.

    main.sh reports it under its own check id (`bam_header_*`) so that "the BAM
    is bad" and "we could not look at the BAM" are never conflated.
    """
    output = run_bash(check_script(fake_samtools_failing()))

    assert "read_ok=0" in output, output
    assert "bytes=0" in output, output
