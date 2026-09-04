#!/usr/bin/env bash
# =============================================================================
# main.sh — germline WES pipeline: FASTQ -> raw VCF (single-file orchestrator)
#
# All executable analysis code for this project lives in THIS file. There are
# no stage scripts, no helper library files and no separate runner program.
# Function boundaries below are deliberately explicit so that, once the
# pipeline has been validated end to end, they can later be split into stage
# files for a FastAPI backend without changing the analysis logic.
#
# -----------------------------------------------------------------------------
# CODE ORIGIN MAP
# (full record: docs/MAIN_SH_COMPLETE_GUIDE.md — "24. 조원 코드 통합 판단")
#
#   The previous revision of this file was a concatenation of five independent
#   scripts written by different team members. Line numbers below refer to that
#   previous revision (commit a0c9927, 2323 lines).
#
#   [A] lines 1-248, 405-1050  QC + Alignment block
#       samplesheet validation, reference indexing, lane FastQC, lane BWA-MEM,
#       lane merge, MultiQC.        -> validate_samplesheet, run_raw_qc,
#                                      run_alignment
#   [B] lines 253-399           fastp trimming block
#                               -> run_preprocessing
#   [C] lines 1053-1397         Processing + Variant Calling block.
#       Byte-identical to lines 622-966 of the author's complete standalone
#       script (run_wes_processing_variantcall_full_v5_1.sh). That complete
#       script is a READ-ONLY reference; its sections 0-6 supplied the
#       configuration, helpers and preflight that were cut when the block was
#       pasted here.               -> run_processing, run_variant_calling,
#                                      run_final_validation, helpers
#   [D] lines 1403-1565         Coverage QC block   -> merged into run_coverage_qc
#   [E] lines 1571-2153         Filtering + annotation block -> run_filtering,
#                                                              run_annotation
#   [F] lines 2161-2323         InterVar block      -> run_intervar
#
# CONFIRMED ERRORS REMOVED
# (evidence: docs/MAIN_SH_COMPLETE_GUIDE.md — "24. 조원 코드 통합 판단"):
#   - orphan backtick at line 2153 (whole file failed `bash -n`)
#   - three top-level `main "$@"` calls (399, 1565, 2323)
#   - top-level `exit 0` at 1397 which made lines 1398-2323 unreachable
#   - undefined symbols in block [C] (its configuration section was cut off)
#   - `find ... | head -1` auto-discovery of BAM/VCF inputs (1448, 2192) and
#     FASTQ glob discovery (301-314)
#   - breast-cancer 8-gene BED substituted for a WES target BED (1461-1479)
#   - `conda install` (371, 1519), `git clone` + `pip install` + reference DB
#     download (2213-2217) during analysis
#   - mixed assemblies: resources from different reference builds were combined,
#     and the reference build and the InterVar build were inconsistent (2295)
#   - trim decision recorded as "none" while fastp actually ran (375 vs 1063)
#   - shared `latest_v5` symlink (1386)
#
# ENGINE SCOPE vs CURRENT PROFILE — these are two different things.
#
#   Engine: a config-driven germline WES orchestrator. No assembly, reference
#   path, capture kit or resource location is hard-coded anywhere in this file.
#   Every build-specific value arrives through resource_bundle in the run
#   config, so another compatible bundle is adopted by editing config, not code.
#   The engine does not restrict runs to one assembly; what it refuses is an
#   UNDECLARED or STRUCTURALLY INCOMPATIBLE bundle (see normalize_config and
#   validate_reference_bundle).
#
#   Current documented/default profile: GRCh38. The example bundle in
#   docs/MAIN_SH_COMPLETE_GUIDE.md targets GRCh38, and the only assembly with an
#   InterVar build mapping today is GRCh38 -> hg38. This is the recommended
#   profile, not an engine limit.
#
# Analysis shape currently exercised (not a permanent restriction):
#   paired-end Illumina germline WES, one biological sample per run, multiple
#   lanes allowed, a whole-exome target BED and known-sites belonging to the
#   declared bundle, FASTQ through raw VCF.
#
# NOT YET VERIFIED: no run of this revision against real resources has been
#   performed. `bash -n`, `--help` and code/doc consistency are static checks
#   only; they say nothing about whether any particular bundle works.
# =============================================================================
set -Eeuo pipefail

# =============================================================================
# 0. Pipeline metadata and defaults
# =============================================================================
PIPELINE_NAME="variant-pipeline-lab-wes"
PIPELINE_VERSION="1.2.0"
SCRIPT_PATH="${BASH_SOURCE[0]}"

# Defaults applied when the run config omits an optional key.
DEFAULT_THREADS=4
DEFAULT_SORT_THREADS=4
DEFAULT_SORT_MEM="2G"
DEFAULT_FASTQC_THREADS=2
DEFAULT_PAIRHMM_THREADS=4
DEFAULT_JAVA_MEM_GB=8
DEFAULT_INTERVAL_PADDING=100
DEFAULT_MOSDEPTH_MAPQ=20
DEFAULT_LOW_COVERAGE_DEPTH=20
DEFAULT_MIN_RAM_GB=8
DEFAULT_TRIM_MODE="skip"

# ---------------------------------------------------------------------------
# Reference-bundle vocabulary.
#
# This pipeline is a config-driven germline WES engine: it does NOT hard-code an
# assembly, a reference path or a capture kit. Everything build-specific arrives
# through resource_bundle in the run config. The two tables below are the only
# build-related vocabulary the engine knows, and both are deliberately generic
# and extensible.
#
#   VALID_CONTIG_STYLES
#     Accepted values for resource_bundle.contig_style. This describes the
#     CHROMOSOME NAMING CONVENTION only, never the assembly:
#       plain | nochr | ensembl  ->  contigs are named 1, 2, ... MT
#       chr   | ucsc             ->  contigs are named chr1, chr2, ... chrM
#     Assembly or build names (GRCh38, hg38, ...) are rejected here on purpose;
#     they belong in resource_bundle.assembly.
#
#   INTERVAR_BUILD_FOR_ASSEMBLY
#     Optional-step mapping from a declared assembly to the build name the
#     InterVar/ANNOVAR command line expects. It is consulted ONLY when the
#     InterVar optional step runs, so an assembly missing from this table still
#     works for the whole core pipeline. To adopt another assembly later, add a
#     row here — no other code change is required.
# ---------------------------------------------------------------------------
VALID_CONTIG_STYLES=(plain nochr ensembl chr ucsc)

declare -A INTERVAR_BUILD_FOR_ASSEMBLY=(
    [grch38]=hg38
)

# ---------------------------------------------------------------------------
# Step metadata — declared ONCE here and used by build_step_plan, resume,
# finalization and status computation. Nothing else may infer core/optional
# status from a function name or an ID prefix.
#
#   STEP_KIND[id]    core | optional
#   STEP_DEPENDS[id] space-separated list of steps whose artifacts this step
#                    consumes. Used for downstream invalidation on resume: if a
#                    dependency is invalid, this step cannot be reused either.
# ---------------------------------------------------------------------------
declare -A STEP_KIND=(
    [00_input_validation]=core
    [01_raw_qc]=core
    [02_preprocessing]=core
    [03_alignment]=core
    [04_processing]=core
    [05_coverage_qc]=core
    [06_variant_calling]=core
    [08_filtering]=optional
    [10_annotation]=optional
    [11_intervar]=optional
    [99_finalization]=core
)

declare -A STEP_DEPENDS=(
    [00_input_validation]=""
    [01_raw_qc]="00_input_validation"
    [02_preprocessing]="00_input_validation"
    [03_alignment]="02_preprocessing"
    [04_processing]="03_alignment"
    [05_coverage_qc]="04_processing"
    [06_variant_calling]="04_processing"
    [08_filtering]="06_variant_calling"
    [10_annotation]="06_variant_calling"
    [11_intervar]="06_variant_calling"
    [99_finalization]="06_variant_calling"
)

# Core step order. Optional steps are appended by build_step_plan().
CORE_STEPS=(
    00_input_validation
    01_raw_qc
    02_preprocessing
    03_alignment
    04_processing
    05_coverage_qc
    06_variant_calling
)
OPTIONAL_STEPS=(08_filtering 10_annotation 11_intervar)
FINAL_STEP="99_finalization"

# Schema version for every backend-facing JSON document.
JSON_SCHEMA_VERSION="1.0"

step_kind() { printf '%s' "${STEP_KIND[$1]:-core}"; }
is_optional_step() { [[ "$(step_kind "$1")" == "optional" ]]; }
is_core_step()     { [[ "$(step_kind "$1")" == "core" ]]; }

# =============================================================================
# 1. Runtime state
#
# Every value a later function needs is passed through one of these variables
# or through an explicit manifest file. No function ever discovers its input by
# globbing the filesystem.
# =============================================================================
CONFIG_PATH=""
CHECK_ONLY=0
RESUME=0
FROM_STEP=""
TO_STEP=""

RUN_ID=""
OUTPUT_ROOT=""
RUN_DIR=""
SAMPLESHEET=""
TRIM_MODE="$DEFAULT_TRIM_MODE"
THREADS="$DEFAULT_THREADS"
SORT_THREADS="$DEFAULT_SORT_THREADS"
SORT_MEM="$DEFAULT_SORT_MEM"
FASTQC_THREADS="$DEFAULT_FASTQC_THREADS"
PAIRHMM_THREADS="$DEFAULT_PAIRHMM_THREADS"
JAVA_MEM_GB="$DEFAULT_JAVA_MEM_GB"
INTERVAL_PADDING="$DEFAULT_INTERVAL_PADDING"
MOSDEPTH_MAPQ="$DEFAULT_MOSDEPTH_MAPQ"
LOW_COVERAGE_DEPTH="$DEFAULT_LOW_COVERAGE_DEPTH"
MIN_RAM_GB="$DEFAULT_MIN_RAM_GB"
COVERAGE_MIN_MEAN_DEPTH=0
BQSR_TARGET_ONLY="false"
BQSR_DIAGNOSTICS="false"
RESUME_STRICT_CHECKSUMS="false"

BUNDLE_ID=""
ASSEMBLY=""
CONTIG_STYLE=""
REF_FASTA=""
CAPTURE_KIT_ID=""
CAPTURE_KIT_REGISTRY=""
CAPTURE_KIT_MODE="direct"
TARGET_BED=""
TARGET_BED_STATUS=""
TARGET_BED_MANUFACTURER=""
TARGET_BED_CAPTURE_KIT_NAME=""
TARGET_BED_CAPTURE_KIT_VERSION=""
TARGET_BED_DESIGN_ID=""
TARGET_BED_GENOME_BUILD=""
TARGET_BED_SOURCE=""
TARGET_BED_SOURCE_URL=""
TARGET_BED_FILE_NAME=""
TARGET_BED_SHA256=""
COVERAGE_BED=""
COVERAGE_BED_SHA256=""
DBSNP_VCF=""
CLINVAR_VCF=""
VEP_CACHE=""
TRUTH_VCF=""
TRUTH_BED=""
KNOWN_SITES=()

OPT_FILTERING="false"
OPT_ANNOTATION="false"
OPT_INTERVAR="false"

# Filled in by the pipeline functions and consumed by later ones.
SAMPLE_ID=""
LANE_COUNT=0
FASTQ_MANIFEST=""      # 02_preprocessing -> 03_alignment
SAMPLE_BAM=""          # 03_alignment     -> 04_processing
ANALYSIS_READY_BAM=""  # 04_processing    -> 05/06
RAW_VCF=""             # 06_variant_calling -> optional steps
GVCF=""

# Paths inside the run directory.
CONFIG_DIR="" STATUS_DIR="" STEPS_DIR="" LOG_DIR="" METRICS_DIR=""
ARTIFACT_DIR="" TMP_ROOT="" OPTIONAL_DIR=""
PIPELINE_LOG="" STATUS_TSV="" TRACE_TSV="" COMMANDS_SH="" VERSIONS_TXT=""
RESOURCE_SHA256="" FINAL_VALIDATION=""

PYTHON_BIN=""
RUN_LOCK_DIR=""
RUN_LOCK_HELD=0
CURRENT_STEP=""
STEP_WORK=""
STEP_START_EPOCH=0
STEP_START_ISO=""
STEP_FINALIZED=1
STEP_NEXT_READY=1
RUN_HAS_WARNINGS=0
RUN_TERMINAL_STATE=""
# Steps that will be re-executed; anything depending on them cannot be reused.
INVALIDATED_STEPS=()
# Optional steps that failed; recorded so finalization can report them
# without turning a completed core run into a failure.
OPTIONAL_FAILED_STEPS=()
RECORDED_IDENTITY=""
CONFIG_IDENTITY=""
STEP_PLAN=()

# =============================================================================
# 2. Common helpers
# =============================================================================

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }
iso_now()   { date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z'; }

log()  { printf '[%s] %s\n' "$(timestamp)" "$*"; }
warn() { printf '[%s] [WARN] %s\n' "$(timestamp)" "$*" >&2; }
die()  { printf '[%s] [ERROR] %s\n' "$(timestamp)" "$*" >&2; exit 1; }

have_command() { command -v "$1" >/dev/null 2>&1; }

require_command() {
    have_command "$1" || die "Required command not found in PATH: $1"
}

require_readable_file() {
    local path=$1 label=${2:-file}
    [[ -e "$path" ]] || die "$label does not exist: $path"
    [[ -f "$path" ]] || die "$label is not a regular file: $path"
    [[ -r "$path" ]] || die "$label is not readable: $path"
    [[ -s "$path" ]] || die "$label is empty: $path"
}

# ---------------------------------------------------------------------------
# Python interpreter
#
# JSON parsing/writing and the more complex FASTQ/BED validations use inline
# Python heredocs. These heredocs are part of this script; there is no separate
# Python program. Every heredoc uses a QUOTED delimiter and receives its values
# through argv, so no shell value is ever interpolated into Python source.
#
# python3 is preferred. Some machines only provide a working `python`, and
# Windows ships a `python3` stub that exits without running, so the interpreter
# is probed rather than assumed.
# ---------------------------------------------------------------------------
resolve_python() {
    if [[ -n "$PYTHON_BIN" ]]; then printf '%s' "$PYTHON_BIN"; return 0; fi
    local candidate
    for candidate in python3 python; do
        if have_command "$candidate" && "$candidate" -c 'import json,sys' >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            printf '%s' "$PYTHON_BIN"
            return 0
        fi
    done
    return 1
}

require_python() {
    resolve_python >/dev/null \
        || die "No working Python interpreter found (tried python3, python). Python is required for JSON handling."
}

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
# json_get <file> <dotted.key> [default]
json_get() {
    local file=$1 key=$2 has_default=0 default_value=""
    if [[ $# -ge 3 ]]; then has_default=1; default_value=$3; fi
    "$(resolve_python)" - "$file" "$key" "$has_default" "$default_value" <<'PYJSONGET' | tr -d '\r'
import json, sys
path, key, has_default, default_value = sys.argv[1:5]
try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
except Exception as exc:                                    # noqa: BLE001
    print(f"cannot read JSON {path}: {exc}", file=sys.stderr)
    sys.exit(2)
node = doc
for part in key.split("."):
    if isinstance(node, dict) and part in node:
        node = node[part]
    else:
        if has_default == "1":
            print(default_value); sys.exit(0)
        print(f"missing key '{key}' in {path}", file=sys.stderr)
        sys.exit(3)
if node is None:
    print(default_value if has_default == "1" else "")
elif isinstance(node, bool):
    print("true" if node else "false")
elif isinstance(node, (str, int, float)):
    print(node)
else:
    print(json.dumps(node, ensure_ascii=False))
PYJSONGET
}

# json_list <file> <dotted.key> -> one element per line
json_list() {
    local file=$1 key=$2
    "$(resolve_python)" - "$file" "$key" <<'PYJSONLIST' | tr -d '\r'
import json, sys
path, key = sys.argv[1:3]
with open(path, encoding="utf-8") as fh:
    doc = json.load(fh)
node = doc
for part in key.split("."):
    if isinstance(node, dict) and part in node:
        node = node[part]
    else:
        sys.exit(0)
if node is None:
    sys.exit(0)
if not isinstance(node, list):
    print("key is not a list", file=sys.stderr); sys.exit(2)
for item in node:
    if item is not None:
        print(item)
PYJSONLIST
}

# atomic_write_json <destination>   (document arrives on stdin)
atomic_write_json() {
    local dest=$1 tmp
    tmp="${dest}.part.$$"
    mkdir -p -- "$(dirname -- "$dest")"
    cat > "$tmp"
    if ! "$(resolve_python)" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$tmp" 2>/dev/null; then
        rm -f -- "$tmp"
        die "Refusing to publish invalid JSON: $dest"
    fi
    mv -f -- "$tmp" "$dest"
}

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
normalize_path() {
    "$(resolve_python)" - "$1" <<'PYNORM' | tr -d '\r'
import os, sys
print(os.path.realpath(os.path.abspath(os.path.expanduser(sys.argv[1]))))
PYNORM
}

# trim_ws <value> -> value without leading/trailing whitespace.
# A config value of "  " must not pass a plain -n test.
trim_ws() {
    local s=$1
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

# is_placeholder <value> -> 0 when the value is an unreplaced template token.
# Config templates ship with TODO_… markers so that a half-filled bundle fails
# loudly instead of silently disabling a downstream check.
is_placeholder() {
    local v; v=$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')
    [[ "$v" == TODO* || "$v" == "<"*">" || "$v" == "CHANGEME"* ]]
}

# in_list <needle> <haystack...> -> 0 on exact match
in_list() {
    local needle=$1; shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

# path_under <candidate> <root> -> 0 when candidate is inside (or equal to) root
path_under() {
    "$(resolve_python)" - "$1" "$2" <<'PYUNDER'
import os, sys
cand = os.path.realpath(os.path.abspath(os.path.expanduser(sys.argv[1])))
root = os.path.realpath(os.path.abspath(os.path.expanduser(sys.argv[2])))
try:
    common = os.path.commonpath([cand, root])
except ValueError:
    sys.exit(1)
sys.exit(0 if common == root else 1)
PYUNDER
}

sha256_file() {
    local path=$1
    [[ -f "$path" ]] || return 1
    if have_command sha256sum; then
        sha256sum "$path" | awk '{print $1}'
    elif have_command shasum; then
        shasum -a 256 "$path" | awk '{print $1}'
    else
        return 1
    fi
}

file_size() {
    stat -c %s "$1" 2>/dev/null || stat -f %z "$1" 2>/dev/null || echo 0
}

# ---------------------------------------------------------------------------
# Run lock
#
# The lock is a `mkdir`, which is atomic on POSIX filesystems. `flock` is NOT
# used: it would still need this fallback where it is unavailable or unreliable
# (some NFS setups), leaving two mechanisms to reason about instead of one.
#
# A `mkdir` lock cannot distinguish a live owner from one killed by SIGKILL, so
# the owner pid, host and start time are recorded. When the lock belongs to a
# pid on THIS host that no longer exists, that is reported as a probable stale
# lock - but it is never removed automatically, because a pid can be reused and
# a lock taken on another host cannot be checked from here.
# ---------------------------------------------------------------------------
acquire_run_lock() {
    RUN_LOCK_DIR="$RUN_DIR/.run.lock"
    if mkdir "$RUN_LOCK_DIR" 2>/dev/null; then
        printf 'pid=%s\nhost=%s\nstarted=%s\n' \
            "$$" "$(hostname 2>/dev/null || echo unknown)" "$(iso_now)" > "$RUN_LOCK_DIR/owner"
        RUN_LOCK_HELD=1
        return 0
    fi
    local holder="unknown" lock_pid="" lock_host="" hint="" this_host
    this_host=$(hostname 2>/dev/null || echo unknown)
    if [[ -f "$RUN_LOCK_DIR/owner" ]]; then
        holder=$(tr '
' ' ' < "$RUN_LOCK_DIR/owner")
        lock_pid=$(sed -n 's/^pid=//p' "$RUN_LOCK_DIR/owner" | head -n 1)
        lock_host=$(sed -n 's/^host=//p' "$RUN_LOCK_DIR/owner" | head -n 1)
    fi
    if [[ -n "$lock_pid" && "$lock_host" == "$this_host" ]]; then
        if kill -0 "$lock_pid" 2>/dev/null; then
            hint="The owning process (pid $lock_pid) is still running on this host. Wait for it to finish, or stop it deliberately."
        else
            hint="No process with pid $lock_pid is running on this host, so this is PROBABLY a stale lock left by a killed run. It is NOT removed automatically, because a pid can be reused. If you are certain nothing is running, remove the lock directory and retry."
        fi
    else
        hint="The lock was taken on host '"'"'${lock_host:-unknown}'"'"', which cannot be checked from here. Confirm no run is active there before removing the lock."
    fi
    die "This run is already locked ($holder).
Only one orchestrator may drive a run at a time.
$hint
Lock directory: $RUN_LOCK_DIR"
}

release_run_lock() {
    if (( RUN_LOCK_HELD == 1 )) && [[ -n "$RUN_LOCK_DIR" && -d "$RUN_LOCK_DIR" ]]; then
        rm -rf -- "$RUN_LOCK_DIR"
        RUN_LOCK_HELD=0
    fi
}

# ---------------------------------------------------------------------------
# Audit trail (append-only, human readable)
#
# These files are the reused output of the Processing source's section 4:
# stage_status.tsv, execution_trace.tsv, commands.sh, pipeline.log,
# software_versions.txt. The JSON documents under status/ are the machine
# contract; these TSV files are the human record. Both are written by the same
# helpers so they cannot disagree.
# ---------------------------------------------------------------------------
append_status_tsv() {
    local step=$1 status=$2 code=$3
    [[ -n "$STATUS_TSV" ]] || return 0
    [[ -f "$STATUS_TSV" ]] || printf 'timestamp\tstep\tstatus\texit_code\n' > "$STATUS_TSV"
    printf '%s\t%s\t%s\t%s\n' "$(iso_now)" "$step" "$status" "$code" >> "$STATUS_TSV"
}

append_trace_tsv() {
    local step=$1 seconds=$2
    [[ -n "$TRACE_TSV" ]] || return 0
    [[ -f "$TRACE_TSV" ]] || printf 'step\tseconds\tfinished_at\n' > "$TRACE_TSV"
    printf '%s\t%s\t%s\n' "$step" "$seconds" "$(iso_now)" >> "$TRACE_TSV"
}

# record_command <label> <argv...>
record_command() {
    local label=$1; shift
    [[ -n "$COMMANDS_SH" ]] || return 0
    if [[ ! -f "$COMMANDS_SH" ]]; then
        printf '#!/usr/bin/env bash\n# Exact commands executed by this run, in order.\nset -euo pipefail\n\n' > "$COMMANDS_SH"
        chmod +x "$COMMANDS_SH" 2>/dev/null || true
    fi
    { printf '# %s — %s\n' "$(iso_now)" "$label"; printf '%q ' "$@"; printf '\n\n'; } >> "$COMMANDS_SH"
}

# ---------------------------------------------------------------------------
# Tool execution
#
# Commands are always executed as an argument vector, never as an assembled
# shell string, so a value coming from the config or samplesheet can never be
# re-interpreted as shell syntax. The explicit if-condition keeps errexit and
# the ERR trap from masking the tool's real exit code (pattern taken from the
# Processing source's run_cmd).
# ---------------------------------------------------------------------------
run_cmd() {
    local label=$1; shift
    local stderr_log="$LOG_DIR/${CURRENT_STEP}.${label}.stderr.log"
    record_command "${CURRENT_STEP}/${label}" "$@"
    log "  run: $label"
    local rc=0
    if "$@" 2>> "$stderr_log"; then rc=0; else rc=$?; fi
    return "$rc"
}

# run_cmd_stdout <label> <stdout_file> <argv...>
run_cmd_stdout() {
    local label=$1 out_file=$2; shift 2
    local stderr_log="$LOG_DIR/${CURRENT_STEP}.${label}.stderr.log"
    record_command "${CURRENT_STEP}/${label}" "$@"
    log "  run: $label"
    local rc=0
    if "$@" > "$out_file" 2>> "$stderr_log"; then rc=0; else rc=$?; fi
    return "$rc"
}

# require_cmd_ok <label> <argv...> — a non-zero exit fails the whole step
require_cmd_ok() {
    local label=$1; shift
    local rc=0
    run_cmd "$label" "$@" || rc=$?
    if (( rc != 0 )); then
        step_check_fail "$label" "command failed with exit code $rc; see logs/${CURRENT_STEP}.${label}.stderr.log"
        return "$rc"
    fi
    return 0
}

# run_optional_cmd <label> <argv...>
# Never fails the step: a non-zero exit is recorded as a warning. Reused from
# the Processing source, where it protects core results from optional tooling.
run_optional_cmd() {
    local label=$1; shift
    local rc=0
    run_cmd "$label" "$@" || rc=$?
    if (( rc != 0 )); then
        step_warning "OPTIONAL_CMD_FAILED" "$label exited with code $rc" \
            "This command is optional; core results are unaffected" "true"
    fi
    return 0
}

# --- BAM header reads --------------------------------------------------------
#
# read_bam_header <bam>            header text on stdout, samtools' own status
# bam_header_sorted_by_coordinate <header>
# bam_header_has_sample <header> <sample>
#
# Why the header is read in full before it is examined, instead of the shorter
# `samtools view -H "$bam" | grep -q ...`:
#
#   `grep -q` exits at the first match and closes the pipe. samtools is then
#   killed by SIGPIPE and exits 141. This script runs under `set -o pipefail`,
#   so the pipeline reports 141 even though grep matched, and a perfectly good
#   BAM is recorded as a failed check.
#
#   It is not intermittent in the way it looks: @HD is the FIRST header line, so
#   the match - and the close - happen immediately, while samtools still has
#   thousands of @SQ lines to write. A real run produced PIPESTATUS=141 0 on a
#   BAM whose header did contain `@HD VN:1.5 SO:coordinate`.
#
#   Command substitution reads to EOF, so there is no early reader, samtools
#   always runs to completion, and the status returned is its real one. The
#   greps below read a here-string, where an early exit costs nothing.
#
# The read and the checks are separate on purpose: "samtools could not read the
# header" and "the header says the wrong thing" are different failures and must
# not be reported as the same check.
read_bam_header() { samtools view -H "$1" 2>/dev/null; }

bam_header_sorted_by_coordinate() { grep -q '^@HD.*SO:coordinate' <<< "$1"; }

bam_header_has_sample() { grep -q "SM:$2" <<< "$1"; }

# =============================================================================
# 2b. Step lifecycle
#
# A step accumulates its findings in tab-separated scratch files and emits
# three JSON documents when it ends. Values are sanitised so that a tab or a
# newline inside a path cannot corrupt the scratch format.
# =============================================================================
sanitize_field() { printf '%s' "${1//[$'\t\n\r']/ }"; }

start_step() {
    CURRENT_STEP=$1
    STEP_START_EPOCH=$(date +%s)
    STEP_START_ISO=$(iso_now)
    STEP_FINALIZED=0
    STEP_NEXT_READY=1
    STEP_WORK="$STEPS_DIR/.${CURRENT_STEP}.work"
    rm -rf -- "$STEP_WORK"
    mkdir -p -- "$STEP_WORK"
    local f
    for f in inputs outputs checks warnings failures metrics artifacts; do
        : > "$STEP_WORK/${f}.tsv"
    done
    append_status_tsv "$CURRENT_STEP" "STARTED" "0"
    write_run_status running
    log "============================================================"
    log "START $CURRENT_STEP"
}

step_input()  { printf '%s\t%s\n' "$(sanitize_field "$1")" "$(sanitize_field "$2")" >> "$STEP_WORK/inputs.tsv"; }
step_output() { printf '%s\t%s\n' "$(sanitize_field "$1")" "$(sanitize_field "$2")" >> "$STEP_WORK/outputs.tsv"; }

step_check_pass() {
    printf '%s\tPASS\t%s\n' "$(sanitize_field "$1")" "$(sanitize_field "$2")" >> "$STEP_WORK/checks.tsv"
}

step_check_fail() {
    printf '%s\tFAIL\t%s\n' "$(sanitize_field "$1")" "$(sanitize_field "$2")" >> "$STEP_WORK/checks.tsv"
    printf '%s\t%s\n' "$(sanitize_field "$1")" "$(sanitize_field "$2")" >> "$STEP_WORK/failures.tsv"
    STEP_NEXT_READY=0
    warn "[$CURRENT_STEP] FAIL $1: $2"
}

# step_warning <code> <message> <impact> <can_continue:true|false>
step_warning() {
    local code=$1 message=$2 impact=$3 can_continue=${4:-true}
    printf '%s\t%s\t%s\t%s\n' \
        "$(sanitize_field "$code")" "$(sanitize_field "$message")" \
        "$(sanitize_field "$impact")" "$(sanitize_field "$can_continue")" >> "$STEP_WORK/warnings.tsv"
    printf '%s\tWARN\t%s\n' "$(sanitize_field "$code")" "$(sanitize_field "$message")" >> "$STEP_WORK/checks.tsv"
    [[ "$can_continue" == "true" ]] || STEP_NEXT_READY=0
    RUN_HAS_WARNINGS=1
    warn "[$code] $message"
}

# step_metric <key> <value> [num|str]
step_metric() {
    local key=$1 value=$2 kind=${3:-auto}
    if [[ "$kind" == "auto" ]]; then
        if [[ "$value" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then kind=num; else kind=str; fi
    fi
    printf '%s\t%s\t%s\n' "$(sanitize_field "$key")" "$(sanitize_field "$value")" "$kind" >> "$STEP_WORK/metrics.tsv"
}

# add_artifact <kind> <display_name> <abs_path> <downloadable:0|1> <checksum:0|1> <description>
add_artifact() {
    local kind=$1 display=$2 path=$3 downloadable=${4:-1} checksum=${5:-0} description=${6:-}
    [[ -s "$path" ]] || return 0
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$(sanitize_field "$kind")" "$(sanitize_field "$display")" "$(sanitize_field "$path")" \
        "$(sanitize_field "$downloadable")" "$(sanitize_field "$checksum")" \
        "$(sanitize_field "$description")" >> "$STEP_WORK/artifacts.tsv"
}

# step_has_failures -> 0 when at least one failure was recorded
step_has_failures() { [[ -s "$STEP_WORK/failures.tsv" ]]; }
step_has_warnings() { [[ -s "$STEP_WORK/warnings.tsv" ]]; }

# finish_step <status> [exit_code]
finish_step() {
    local status=$1 exit_code=${2:-0}
    (( STEP_FINALIZED == 1 )) && return 0
    STEP_FINALIZED=1

    local end_epoch elapsed finished
    end_epoch=$(date +%s)
    elapsed=$(( end_epoch - STEP_START_EPOCH ))
    finished=$(iso_now)

    if [[ "$status" == "failed" || "$status" == "cancelled" ]]; then
        STEP_NEXT_READY=0
    fi

    "$(resolve_python)" - \
        "$STEP_WORK" "$RUN_DIR" "$RUN_ID" "$CURRENT_STEP" "$status" "$exit_code" \
        "$STEP_START_ISO" "$finished" "$elapsed" "$STEP_NEXT_READY"         "$JSON_SCHEMA_VERSION" <<'PYSTEP'
import hashlib, json, os, sys

(work, run_dir, run_id, step_id, status, exit_code,
 started, finished, elapsed, next_ready, schema_version) = sys.argv[1:12]


def rows(name, width):
    path = os.path.join(work, name)
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            parts += [""] * (width - len(parts))
            out.append(parts[:width])
    return out


def rel(p):
    try:
        return os.path.relpath(p, run_dir).replace(os.sep, "/")
    except ValueError:
        return p


inputs = [{"type": t, "path": rel(p)} for t, p in rows("inputs.tsv", 2)]
outputs = [{"type": t, "path": rel(p)} for t, p in rows("outputs.tsv", 2)]
checks = [{"name": n, "status": s, "detail": d} for n, s, d in rows("checks.tsv", 3)]
warnings = [{"code": c, "message": m, "impact": i, "can_continue": k == "true"}
            for c, m, i, k in rows("warnings.tsv", 4)]
failures = [{"code": c, "message": m} for c, m in rows("failures.tsv", 2)]

metrics = {}
for key, value, kind in rows("metrics.tsv", 3):
    if kind == "num":
        try:
            metrics[key] = int(value) if value.lstrip("-").isdigit() else float(value)
        except ValueError:
            metrics[key] = value
    else:
        metrics[key] = value

artifacts = []
for kind, display, path, downloadable, checksum, description in rows("artifacts.tsv", 6):
    if not os.path.isfile(path):
        continue
    entry = {
        "file_id": "",
        "step_id": step_id,
        "kind": kind,
        "display_name": display,
        "relative_path": rel(path),
        "size_bytes": os.path.getsize(path),
        "sha256": None,
        "downloadable": downloadable == "1",
        "description": description,
    }
    if checksum == "1":
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        entry["sha256"] = h.hexdigest()
    seed = f"{run_id}:{step_id}:{entry['relative_path']}".encode("utf-8")
    entry["file_id"] = "f_" + hashlib.sha256(seed).hexdigest()[:16]
    artifacts.append(entry)

validation = {
    "status": "fail" if failures else ("warn" if warnings else "pass"),
    "checks": len(checks),
    "warnings": len(warnings),
    "failures": len(failures),
    "results": checks,
}

ready = (next_ready == "1") and not failures and status in ("completed", "warning", "skipped")

doc = {
    "schema_version": schema_version,
    "run_id": run_id,
    "step_id": step_id,
    "status": status,
    "exit_code": int(exit_code),
    "started_at": started,
    "finished_at": finished,
    "elapsed_seconds": int(elapsed),
    "inputs": inputs,
    "outputs": outputs,
    "validation": validation,
    "warnings": warnings,
    "failures": failures,
    "metrics_file": f"metrics/{step_id}.json",
    "artifacts_file": f"artifacts/{step_id}.json",
    "next_step_ready": ready,
}


def write_atomic(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


write_atomic(os.path.join(run_dir, "status", "steps", step_id + ".json"), doc)
write_atomic(os.path.join(run_dir, "metrics", step_id + ".json"),
             {"schema_version": schema_version, "run_id": run_id,
              "step_id": step_id, "metrics": metrics})
write_atomic(os.path.join(run_dir, "artifacts", step_id + ".json"),
             {"schema_version": schema_version, "run_id": run_id,
              "step_id": step_id, "artifacts": artifacts})
PYSTEP

    append_status_tsv "$CURRENT_STEP" "$(printf '%s' "$status" | tr '[:lower:]' '[:upper:]')" "$exit_code"
    append_trace_tsv "$CURRENT_STEP" "$elapsed"
    log "DONE  $CURRENT_STEP status=$status exit=$exit_code (${elapsed}s)"
    rm -rf -- "$STEP_WORK"
}

# complete_step / warn_step / fail_step — convenience wrappers that pick the
# terminal status from what the step recorded.
complete_step() {
    if step_has_failures; then finish_step failed 1; return 1; fi
    if step_has_warnings; then finish_step warning 0; else finish_step completed 0; fi
    return 0
}

fail_step() {
    local code=$1 message=$2
    step_check_fail "$code" "$message"
    finish_step failed 1
    return 1
}

skip_step() {
    local reason=$1
    step_check_pass "skipped" "$reason"
    finish_step skipped 0
    return 0
}

# ---------------------------------------------------------------------------
# run_status.json — the single machine-readable view of the whole run
# ---------------------------------------------------------------------------
write_run_status() {
    local state=$1
    [[ -n "$STATUS_DIR" ]] || return 0
    "$(resolve_python)" - "$RUN_DIR" "$RUN_ID" "$state" "$CURRENT_STEP" "$PIPELINE_NAME" "$PIPELINE_VERSION" <<'PYRUNSTATUS'
import json, os, sys

run_dir, run_id, state, current_step, name, version = sys.argv[1:7]
steps_dir = os.path.join(run_dir, "status", "steps")
steps = []
if os.path.isdir(steps_dir):
    for fn in sorted(os.listdir(steps_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(steps_dir, fn), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        steps.append({
            "step_id": d.get("step_id"),
            "status": d.get("status"),
            "exit_code": d.get("exit_code"),
            "started_at": d.get("started_at"),
            "finished_at": d.get("finished_at"),
            "elapsed_seconds": d.get("elapsed_seconds"),
            "warnings": len(d.get("warnings") or []),
            "failures": len(d.get("failures") or []),
            "next_step_ready": d.get("next_step_ready"),
        })

doc = {
    "schema_version": "1.0",
    "pipeline_name": name,
    "pipeline_version": version,
    "run_id": run_id,
    "status": state,
    "current_step": current_step or None,
    "steps": steps,
    "completed_steps": [s["step_id"] for s in steps if s["status"] in ("completed", "warning", "skipped")],
    "failed_steps": [s["step_id"] for s in steps if s["status"] == "failed"],
    "updated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
}

path = os.path.join(run_dir, "status", "run_status.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
tmp = path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PYRUNSTATUS
}

# =============================================================================
# 3. CLI and configuration
# =============================================================================

usage() {
    cat <<'USAGE'
Usage:
  bash script/main.sh --config <run_config.json> [options]

Options:
  --config FILE        Run configuration (JSON). Required except with --help.
  --check-only         Run every preflight validation, then stop before any
                       analysis tool is executed.
  --resume             Re-enter an existing run directory and skip steps that
                       already completed and still validate.
  --from-step ID       Start at this step (its required inputs are still
                       validated).
  --to-step ID         Stop after this step.
  --help               Show this message.

Steps:
  00_input_validation 01_raw_qc 02_preprocessing 03_alignment
  04_processing 05_coverage_qc 06_variant_calling
  08_filtering 10_annotation 11_intervar          (optional, off by default)
  99_finalization

The core completion point is the raw VCF produced by 06_variant_calling.
설정(config)과 samplesheet 작성법은 docs/MAIN_SH_COMPLETE_GUIDE.md의
"6. 실행 방법과 CLI option", "7. config 전체 설명", "8. samplesheet 전체 설명" 장을 보세요.
USAGE
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --config)
                [[ $# -ge 2 ]] || die "--config requires a value"
                CONFIG_PATH=$2; shift 2 ;;
            --check-only) CHECK_ONLY=1; shift ;;
            --resume)     RESUME=1; shift ;;
            --from-step)
                [[ $# -ge 2 ]] || die "--from-step requires a value"
                FROM_STEP=$2; shift 2 ;;
            --to-step)
                [[ $# -ge 2 ]] || die "--to-step requires a value"
                TO_STEP=$2; shift 2 ;;
            -h|--help) usage; return 10 ;;
            *) usage >&2; die "Unknown option: $1" ;;
        esac
    done
    return 0
}

# ---------------------------------------------------------------------------
# resolve_capture_kit_profile
#
# The UI/backend submits a stable capture_kit.id, not an arbitrary server path.
# This function resolves that ID through an operator-managed registry and
# replaces the direct BED fields with the selected, versioned profile. Paths in
# the registry are resolved relative to the registry file itself. A run may use
# either registry mode or the legacy direct resource_bundle fields, never both.
# ---------------------------------------------------------------------------
resolve_capture_kit_profile() {
    CAPTURE_KIT_ID=$(trim_ws "$CAPTURE_KIT_ID")
    CAPTURE_KIT_REGISTRY=$(trim_ws "$CAPTURE_KIT_REGISTRY")

    if [[ -z "$CAPTURE_KIT_ID" && -z "$CAPTURE_KIT_REGISTRY" ]]; then
        CAPTURE_KIT_MODE="direct"
        [[ -n "$COVERAGE_BED" ]] || COVERAGE_BED="$TARGET_BED"
        [[ -n "$COVERAGE_BED_SHA256" ]] || COVERAGE_BED_SHA256="$TARGET_BED_SHA256"
        return 0
    fi

    [[ -n "$CAPTURE_KIT_ID" ]] \
        || die "capture_kit.id is required when capture_kit.registry is set"
    [[ -n "$CAPTURE_KIT_REGISTRY" ]] \
        || die "capture_kit.registry is required when capture_kit.id is set"
    [[ "$CAPTURE_KIT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
        || die "capture_kit.id contains unsupported characters: '$CAPTURE_KIT_ID'"
    is_placeholder "$CAPTURE_KIT_ID" \
        && die "capture_kit.id is still a template placeholder: '$CAPTURE_KIT_ID'"
    is_placeholder "$CAPTURE_KIT_REGISTRY" \
        && die "capture_kit.registry is still a template placeholder: '$CAPTURE_KIT_REGISTRY'"

    # Avoid two competing sources of truth. The backend should submit only the
    # kit ID/registry; the selected profile supplies every BED and metadata
    # field below.
    if [[ -n "$(trim_ws "$TARGET_BED")" || -n "$(trim_ws "$TARGET_BED_STATUS")" \
          || -n "$(trim_ws "$COVERAGE_BED")" ]]; then
        die "capture_kit registry mode cannot be combined with direct resource_bundle target/coverage BED fields"
    fi

    CAPTURE_KIT_REGISTRY=$(normalize_path "$CAPTURE_KIT_REGISTRY")
    require_readable_file "$CAPTURE_KIT_REGISTRY" "Capture-kit registry"

    local profile_tmp
    profile_tmp=$(mktemp "${TMPDIR:-/tmp}/capture-kit-profile.XXXXXX") \
        || die "Could not create a temporary file for capture-kit resolution"

    if ! "$(resolve_python)" - "$CAPTURE_KIT_REGISTRY" "$CAPTURE_KIT_ID" > "$profile_tmp" <<'PYKIT'
import json, os, re, sys

registry_path, kit_id = sys.argv[1:3]
try:
    with open(registry_path, encoding="utf-8") as fh:
        doc = json.load(fh)
except Exception as exc:  # noqa: BLE001
    print(f"cannot read capture-kit registry {registry_path}: {exc}", file=sys.stderr)
    sys.exit(2)

if str(doc.get("schema_version", "")) != "1.0":
    print("capture-kit registry schema_version must be '1.0'", file=sys.stderr)
    sys.exit(2)
kits = doc.get("kits")
if not isinstance(kits, dict):
    print("capture-kit registry must contain an object named 'kits'", file=sys.stderr)
    sys.exit(2)
profile = kits.get(kit_id)
if not isinstance(profile, dict):
    available = ", ".join(sorted(kits)) or "<none>"
    print(f"capture kit '{kit_id}' is not registered; available: {available}", file=sys.stderr)
    sys.exit(3)

required = (
    "status", "manufacturer", "capture_kit_name", "capture_kit_version",
    "design_id", "genome_build", "source", "target_bed",
    "target_bed_sha256",
)
missing = [key for key in required if not str(profile.get(key, "")).strip()]
if missing:
    print(f"capture-kit profile '{kit_id}' is missing: {', '.join(missing)}", file=sys.stderr)
    sys.exit(4)

base = os.path.dirname(os.path.realpath(registry_path))


def path_value(key, fallback=""):
    raw = str(profile.get(key, fallback) or "").strip()
    if not raw:
        return ""
    raw = os.path.expanduser(raw)
    return os.path.realpath(raw if os.path.isabs(raw) else os.path.join(base, raw))


target_bed = path_value("target_bed")
coverage_bed = path_value("coverage_bed", profile["target_bed"])
target_sha = str(profile["target_bed_sha256"]).strip().lower()
coverage_sha = str(profile.get("coverage_bed_sha256", target_sha)).strip().lower()
for label, value in (("target_bed_sha256", target_sha),
                     ("coverage_bed_sha256", coverage_sha)):
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        print(f"capture-kit profile '{kit_id}' has an invalid {label}", file=sys.stderr)
        sys.exit(4)

values = (
    str(profile["status"]).strip(),
    str(profile["manufacturer"]).strip(),
    str(profile["capture_kit_name"]).strip(),
    str(profile["capture_kit_version"]).strip(),
    str(profile["design_id"]).strip(),
    str(profile["genome_build"]).strip(),
    str(profile["source"]).strip(),
    str(profile.get("source_url", "") or "").strip(),
    target_bed,
    os.path.basename(target_bed),
    target_sha,
    coverage_bed,
    coverage_sha,
)
for value in values:
    sys.stdout.buffer.write(value.encode("utf-8") + b"\0")
PYKIT
    then
        rm -f -- "$profile_tmp"
        die "Could not resolve capture-kit profile '$CAPTURE_KIT_ID'"
    fi

    local -a profile=()
    mapfile -d '' -t profile < "$profile_tmp"
    rm -f -- "$profile_tmp"
    [[ ${#profile[@]} -eq 13 ]] \
        || die "Capture-kit registry returned an incomplete profile for '$CAPTURE_KIT_ID'"

    TARGET_BED_STATUS=${profile[0]}
    TARGET_BED_MANUFACTURER=${profile[1]}
    TARGET_BED_CAPTURE_KIT_NAME=${profile[2]}
    TARGET_BED_CAPTURE_KIT_VERSION=${profile[3]}
    TARGET_BED_DESIGN_ID=${profile[4]}
    TARGET_BED_GENOME_BUILD=${profile[5]}
    TARGET_BED_SOURCE=${profile[6]}
    TARGET_BED_SOURCE_URL=${profile[7]}
    TARGET_BED=${profile[8]}
    TARGET_BED_FILE_NAME=${profile[9]}
    TARGET_BED_SHA256=${profile[10]}
    COVERAGE_BED=${profile[11]}
    COVERAGE_BED_SHA256=${profile[12]}
    CAPTURE_KIT_MODE="registry"
}

# ---------------------------------------------------------------------------
# load_config — read every value from the run config.
#
# Nothing here is hard-coded to a sample, a reference or a directory: changing
# the sample, the FASTQ files, the output location or the whole resource
# bundle is a configuration change, never a code change.
# ---------------------------------------------------------------------------
load_config() {
    require_readable_file "$CONFIG_PATH" "Run config"

    RUN_ID=$(json_get "$CONFIG_PATH" run_id)
    SAMPLESHEET=$(json_get "$CONFIG_PATH" samplesheet)
    OUTPUT_ROOT=$(json_get "$CONFIG_PATH" output_root)

    THREADS=$(json_get "$CONFIG_PATH" threads "$DEFAULT_THREADS")
    SORT_THREADS=$(json_get "$CONFIG_PATH" sort_threads "$THREADS")
    SORT_MEM=$(json_get "$CONFIG_PATH" sort_mem "$DEFAULT_SORT_MEM")
    FASTQC_THREADS=$(json_get "$CONFIG_PATH" fastqc_threads "$DEFAULT_FASTQC_THREADS")
    PAIRHMM_THREADS=$(json_get "$CONFIG_PATH" pairhmm_threads "$DEFAULT_PAIRHMM_THREADS")
    JAVA_MEM_GB=$(json_get "$CONFIG_PATH" java_mem_gb "$DEFAULT_JAVA_MEM_GB")
    INTERVAL_PADDING=$(json_get "$CONFIG_PATH" interval_padding "$DEFAULT_INTERVAL_PADDING")
    MOSDEPTH_MAPQ=$(json_get "$CONFIG_PATH" mosdepth_mapq "$DEFAULT_MOSDEPTH_MAPQ")
    LOW_COVERAGE_DEPTH=$(json_get "$CONFIG_PATH" low_coverage_depth "$DEFAULT_LOW_COVERAGE_DEPTH")
    MIN_RAM_GB=$(json_get "$CONFIG_PATH" min_available_ram_gb "$DEFAULT_MIN_RAM_GB")
    COVERAGE_MIN_MEAN_DEPTH=$(json_get "$CONFIG_PATH" coverage_min_mean_depth 0)
    TRIM_MODE=$(json_get "$CONFIG_PATH" trim_mode "$DEFAULT_TRIM_MODE")
    BQSR_TARGET_ONLY=$(json_get "$CONFIG_PATH" bqsr_target_only false)
    BQSR_DIAGNOSTICS=$(json_get "$CONFIG_PATH" bqsr_diagnostics false)
    RESUME_STRICT_CHECKSUMS=$(json_get "$CONFIG_PATH" resume_strict_checksums false)

    BUNDLE_ID=$(json_get "$CONFIG_PATH" resource_bundle.bundle_id "")
    CAPTURE_KIT_ID=$(json_get "$CONFIG_PATH" capture_kit.id "")
    CAPTURE_KIT_REGISTRY=$(json_get "$CONFIG_PATH" capture_kit.registry "")
    ASSEMBLY=$(json_get "$CONFIG_PATH" resource_bundle.assembly "")
    CONTIG_STYLE=$(json_get "$CONFIG_PATH" resource_bundle.contig_style "")
    REF_FASTA=$(json_get "$CONFIG_PATH" resource_bundle.reference_fasta "")
    TARGET_BED=$(json_get "$CONFIG_PATH" resource_bundle.target_bed "")
    TARGET_BED_STATUS=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.status "")
    TARGET_BED_MANUFACTURER=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.manufacturer "")
    TARGET_BED_CAPTURE_KIT_NAME=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.capture_kit_name "")
    TARGET_BED_CAPTURE_KIT_VERSION=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.capture_kit_version "")
    TARGET_BED_DESIGN_ID=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.design_id "")
    TARGET_BED_GENOME_BUILD=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.genome_build "")
    TARGET_BED_SOURCE=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.source "")
    TARGET_BED_SOURCE_URL=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.source_url "")
    TARGET_BED_FILE_NAME=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.file_name "")
    TARGET_BED_SHA256=$(json_get "$CONFIG_PATH" resource_bundle.target_bed_metadata.sha256 "")
    COVERAGE_BED=$(json_get "$CONFIG_PATH" resource_bundle.coverage_bed "")
    COVERAGE_BED_SHA256=$(json_get "$CONFIG_PATH" resource_bundle.coverage_bed_sha256 "")
    DBSNP_VCF=$(json_get "$CONFIG_PATH" resource_bundle.dbsnp_vcf "")
    CLINVAR_VCF=$(json_get "$CONFIG_PATH" resource_bundle.clinvar_vcf "")
    VEP_CACHE=$(json_get "$CONFIG_PATH" resource_bundle.vep_cache "")
    TRUTH_VCF=$(json_get "$CONFIG_PATH" resource_bundle.truth_vcf "")
    TRUTH_BED=$(json_get "$CONFIG_PATH" resource_bundle.truth_bed "")

    KNOWN_SITES=()
    local line
    while IFS= read -r line; do
        [[ -n "$line" ]] && KNOWN_SITES+=("$line")
    done < <(json_list "$CONFIG_PATH" resource_bundle.known_sites)

    OPT_FILTERING=$(json_get "$CONFIG_PATH" optional_steps.filtering false)
    OPT_ANNOTATION=$(json_get "$CONFIG_PATH" optional_steps.annotation false)
    OPT_INTERVAR=$(json_get "$CONFIG_PATH" optional_steps.intervar false)

    resolve_capture_kit_profile
}

normalize_config() {
    [[ -n "$RUN_ID" ]] || die "run_id is required in the run config"
    [[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
        || die "run_id must start with a letter or digit and contain only letters, digits, dot, underscore and hyphen: '$RUN_ID'"
    [[ -n "$SAMPLESHEET" ]] || die "samplesheet is required in the run config"
    [[ -n "$OUTPUT_ROOT" ]] || die "output_root is required in the run config"

    REF_FASTA=$(trim_ws "$REF_FASTA")
    TARGET_BED=$(trim_ws "$TARGET_BED")
    COVERAGE_BED=$(trim_ws "$COVERAGE_BED")
    [[ -n "$REF_FASTA" ]] || die "resource_bundle.reference_fasta is required"
    [[ -n "$TARGET_BED" ]] || die "resource_bundle.target_bed is required"
    [[ -n "$COVERAGE_BED" ]] || COVERAGE_BED="$TARGET_BED"
    is_placeholder "$REF_FASTA" \
        && die "resource_bundle.reference_fasta is still a template placeholder: '$REF_FASTA'"
    is_placeholder "$TARGET_BED" \
        && die "resource_bundle.target_bed is still a template placeholder: '$TARGET_BED'. Do not guess a GRCh38 BED path; confirm the exact assay design first."
    is_placeholder "$COVERAGE_BED" \
        && die "resource_bundle.coverage_bed is still a template placeholder: '$COVERAGE_BED'"

    SAMPLESHEET=$(normalize_path "$SAMPLESHEET")
    OUTPUT_ROOT=$(normalize_path "$OUTPUT_ROOT")
    [[ -n "$REF_FASTA" ]] && REF_FASTA=$(normalize_path "$REF_FASTA")
    [[ -n "$TARGET_BED" ]] && TARGET_BED=$(normalize_path "$TARGET_BED")
    [[ -n "$COVERAGE_BED" ]] && COVERAGE_BED=$(normalize_path "$COVERAGE_BED")
    [[ -n "$DBSNP_VCF" && "$DBSNP_VCF" != "null" ]] && DBSNP_VCF=$(normalize_path "$DBSNP_VCF") || DBSNP_VCF=""
    [[ -n "$CLINVAR_VCF" && "$CLINVAR_VCF" != "null" ]] && CLINVAR_VCF=$(normalize_path "$CLINVAR_VCF") || CLINVAR_VCF=""
    [[ -n "$VEP_CACHE" && "$VEP_CACHE" != "null" ]] && VEP_CACHE=$(normalize_path "$VEP_CACHE") || VEP_CACHE=""
    [[ -n "$TRUTH_VCF" && "$TRUTH_VCF" != "null" ]] && TRUTH_VCF=$(normalize_path "$TRUTH_VCF") || TRUTH_VCF=""
    [[ -n "$TRUTH_BED" && "$TRUTH_BED" != "null" ]] && TRUTH_BED=$(normalize_path "$TRUTH_BED") || TRUTH_BED=""

    local i
    for i in "${!KNOWN_SITES[@]}"; do
        KNOWN_SITES[$i]=$(normalize_path "${KNOWN_SITES[$i]}")
    done

    local n
    for n in THREADS SORT_THREADS FASTQC_THREADS PAIRHMM_THREADS JAVA_MEM_GB \
             INTERVAL_PADDING MOSDEPTH_MAPQ LOW_COVERAGE_DEPTH MIN_RAM_GB; do
        [[ "${!n}" =~ ^[0-9]+$ ]] || die "$n must be a non-negative integer (got '${!n}')"
    done
    (( THREADS >= 1 )) || die "threads must be at least 1"
    (( JAVA_MEM_GB >= 4 )) || die "java_mem_gb should be at least 4"
    [[ "$SORT_MEM" =~ ^[0-9]+[KMG]?$ ]] || die "sort_mem must look like '2G' or '768M' (got '$SORT_MEM')"

    case "$TRIM_MODE" in
        skip|force) : ;;
        *) die "trim_mode must be 'skip' or 'force' (got '$TRIM_MODE'). An automatic threshold mode is not implemented." ;;
    esac

    # ---- resource_bundle contract ------------------------------------------
    # The engine accepts any explicitly declared assembly; it does not restrict
    # runs to one reference build. What it refuses is an UNDECLARED one: an
    # empty value, a null, a whitespace-only value or an unresolved template
    # placeholder. Those silently disable the assembly-dependent checks
    # downstream, which is exactly the failure mode this contract exists to
    # prevent.
    ASSEMBLY=$(trim_ws "$ASSEMBLY")
    CONTIG_STYLE=$(trim_ws "$CONTIG_STYLE")

    [[ -n "$ASSEMBLY" ]] || die "resource_bundle.assembly is required and must name the reference assembly of this bundle (for example 'GRCh38'). It is recorded in provenance, reported in methods.md and used to check the InterVar build, so it is never inferred from a file name."
    is_placeholder "$ASSEMBLY" \
        && die "resource_bundle.assembly is still a template placeholder: '$ASSEMBLY'. Replace it with the assembly this bundle actually provides."

    # contig_style is a chromosome NAMING CONVENTION, not an assembly name.
    # Accepting an assembly name here is what previously let 'assembly' and
    # 'contig style' blur into one field.
    [[ -n "$CONTIG_STYLE" ]] || die "resource_bundle.contig_style is required. It declares the chromosome naming convention of the reference, not the assembly: use ${VALID_CONTIG_STYLES[*]} (plain/nochr/ensembl = contigs named '1', chr/ucsc = contigs named 'chr1'). The declared value is checked against the actual FASTA in preflight."
    is_placeholder "$CONTIG_STYLE" \
        && die "resource_bundle.contig_style is still a template placeholder: '$CONTIG_STYLE'. Inspect the first column of the reference .fai and declare one of: ${VALID_CONTIG_STYLES[*]}"
    CONTIG_STYLE=$(printf '%s' "$CONTIG_STYLE" | tr '[:upper:]' '[:lower:]')
    if ! in_list "$CONTIG_STYLE" "${VALID_CONTIG_STYLES[@]}"; then
        die "resource_bundle.contig_style must be one of: ${VALID_CONTIG_STYLES[*]} (got '$CONTIG_STYLE').
contig_style describes the chromosome naming convention only:
  plain | nochr | ensembl   contigs are named 1, 2, ... MT
  chr   | ucsc              contigs are named chr1, chr2, ... chrM
An assembly or build name (GRCh38, hg38, ...) is not a contig style; declare that in resource_bundle.assembly instead."
    fi

    # ---- target BED provenance contract ------------------------------------
    # Coordinate checks can reject malformed or structurally incompatible BEDs,
    # but they cannot prove that a BED belongs to the capture design used for
    # this sample. That provenance is therefore explicit, fail-closed metadata.
    # The field names are vendor-neutral: Agilent, Twist, IDT or a custom design
    # can be selected by changing config only.
    local metadata_var metadata_key
    for metadata_var in TARGET_BED_STATUS TARGET_BED_MANUFACTURER TARGET_BED_CAPTURE_KIT_NAME \
                        TARGET_BED_CAPTURE_KIT_VERSION TARGET_BED_DESIGN_ID \
                        TARGET_BED_GENOME_BUILD TARGET_BED_SOURCE \
                        TARGET_BED_FILE_NAME TARGET_BED_SHA256; do
        printf -v "$metadata_var" '%s' "$(trim_ws "${!metadata_var}")"
        metadata_key=${metadata_var#TARGET_BED_}
        metadata_key=$(printf '%s' "$metadata_key" | tr '[:upper:]' '[:lower:]')
        [[ -n "${!metadata_var}" ]] \
            || die "resource_bundle.target_bed_metadata.${metadata_key} is required"
        is_placeholder "${!metadata_var}" \
            && die "resource_bundle.target_bed_metadata.${metadata_key} is unresolved: '${!metadata_var}'"
    done
    TARGET_BED_SOURCE_URL=$(trim_ws "$TARGET_BED_SOURCE_URL")
    if [[ -n "$TARGET_BED_SOURCE_URL" ]] && is_placeholder "$TARGET_BED_SOURCE_URL"; then
        die "resource_bundle.target_bed_metadata.source_url is unresolved: '$TARGET_BED_SOURCE_URL'"
    fi

    TARGET_BED_STATUS=$(printf '%s' "$TARGET_BED_STATUS" | tr '[:upper:]' '[:lower:]')
    [[ "$TARGET_BED_STATUS" == "confirmed" ]] \
        || die "resource_bundle.target_bed_metadata.status must be 'confirmed' before analysis (got '$TARGET_BED_STATUS'). Keep it 'unconfirmed' while the exact kit/design/BED is unresolved."
    [[ "${TARGET_BED_GENOME_BUILD,,}" == "${ASSEMBLY,,}" ]] \
        || die "target BED genome_build '$TARGET_BED_GENOME_BUILD' does not match resource_bundle.assembly '$ASSEMBLY'"
    [[ "$TARGET_BED_FILE_NAME" == "$(basename -- "$TARGET_BED")" ]] \
        || die "target BED metadata file_name '$TARGET_BED_FILE_NAME' does not match the configured path basename '$(basename -- "$TARGET_BED")'"
    TARGET_BED_SHA256=$(printf '%s' "$TARGET_BED_SHA256" | tr '[:upper:]' '[:lower:]')
    [[ "$TARGET_BED_SHA256" =~ ^[0-9a-f]{64}$ ]] \
        || die "resource_bundle.target_bed_metadata.sha256 must be a 64-character SHA-256 digest"
    COVERAGE_BED_SHA256=$(trim_ws "$COVERAGE_BED_SHA256")
    [[ -n "$COVERAGE_BED_SHA256" ]] || COVERAGE_BED_SHA256="$TARGET_BED_SHA256"
    COVERAGE_BED_SHA256=$(printf '%s' "$COVERAGE_BED_SHA256" | tr '[:upper:]' '[:lower:]')
    [[ "$COVERAGE_BED_SHA256" =~ ^[0-9a-f]{64}$ ]] \
        || die "coverage BED SHA-256 must be a 64-character digest"
    [[ -n "$CAPTURE_KIT_ID" ]] || CAPTURE_KIT_ID="$TARGET_BED_DESIGN_ID"

    RUN_DIR="$OUTPUT_ROOT/$RUN_ID"
    CONFIG_DIR="$RUN_DIR/config"
    STATUS_DIR="$RUN_DIR/status"
    STEPS_DIR="$STATUS_DIR/steps"
    LOG_DIR="$RUN_DIR/logs"
    METRICS_DIR="$RUN_DIR/metrics"
    ARTIFACT_DIR="$RUN_DIR/artifacts"
    TMP_ROOT="$RUN_DIR/tmp"
    OPTIONAL_DIR="$RUN_DIR/optional"
    PIPELINE_LOG="$LOG_DIR/pipeline.log"
    STATUS_TSV="$LOG_DIR/stage_status.tsv"
    TRACE_TSV="$LOG_DIR/execution_trace.tsv"
    COMMANDS_SH="$LOG_DIR/commands.sh"
    VERSIONS_TXT="$LOG_DIR/software_versions.txt"
    RESOURCE_SHA256="$LOG_DIR/resource_sha256.txt"
    FINAL_VALIDATION="$RUN_DIR/final_validation.tsv"
}

# =============================================================================
# 4. Run initialisation
# =============================================================================

initialize_run() {
    [[ -d "$OUTPUT_ROOT" ]] || die "output_root does not exist: $OUTPUT_ROOT"
    [[ -w "$OUTPUT_ROOT" ]] || die "output_root is not writable: $OUTPUT_ROOT"

    # A previous --check-only run leaves a directory but no analysis output.
    # It must not force the user into --resume for the real run.  (AUD-HIGH-004)
    local prior_check_only=0
    if [[ -e "$RUN_DIR" && -s "$STATUS_DIR/run_status.json" ]]; then
        if [[ "$(json_get "$STATUS_DIR/run_status.json" status "" 2>/dev/null || echo "")" == "check_only" ]]; then
            prior_check_only=1
        fi
    fi

    if [[ -e "$RUN_DIR" ]] && (( prior_check_only == 1 )) && (( CHECK_ONLY == 0 )) && (( RESUME == 0 )); then
        log "The existing run directory holds only a previous --check-only result; starting the real run in place."
        rm -f -- "$RUN_DIR"/RUN_COMPLETED "$RUN_DIR"/RUN_COMPLETED_WITH_WARNINGS                  "$RUN_DIR"/RUN_FAILED "$RUN_DIR"/RUN_CANCELLED
    elif [[ -e "$RUN_DIR" ]]; then
        if (( RESUME == 0 )); then
            die "Run directory already exists: $RUN_DIR
Refusing to overwrite a previous run. Use --resume to continue it, or choose a different run_id.
Results of different run_id values are always kept separate, even for the same sample."
        fi
        [[ -d "$RUN_DIR" ]] || die "Run path exists but is not a directory: $RUN_DIR"
        log "Resuming existing run directory: $RUN_DIR"
    fi

    mkdir -p -- "$CONFIG_DIR" "$STEPS_DIR" "$LOG_DIR" "$METRICS_DIR" \
                "$ARTIFACT_DIR" "$TMP_ROOT" "$OPTIONAL_DIR"

    acquire_run_lock

    # Everything printed from here on is also captured in pipeline.log.
    exec > >(tee -a "$PIPELINE_LOG") 2>&1

    log "============================================================"
    log "$PIPELINE_NAME $PIPELINE_VERSION"
    log "run_id     : $RUN_ID"
    log "run_dir    : $RUN_DIR"
    log "samplesheet: $SAMPLESHEET"
    log "bundle     : ${BUNDLE_ID:-<unnamed>} (assembly=${ASSEMBLY:-?}, contig_style=${CONTIG_STYLE:-?})"
    log "capture kit: ${CAPTURE_KIT_ID:-<direct>} (mode=$CAPTURE_KIT_MODE)"
    log "threads    : $THREADS   java_mem_gb: $JAVA_MEM_GB   trim_mode: $TRIM_MODE"
    log "============================================================"
}

# ---------------------------------------------------------------------------
# Configuration snapshot and resume identity
#
# AUD-BLOCKER-001 fix. The previous version wrote the snapshot before any
# reuse check, and then compared that just-written snapshot against the
# identity it had itself produced — a tautology that could never detect a
# changed configuration.
#
# The write and the comparison are now separate operations:
#
#   render_config_snapshot <destination>
#       Renders the effective configuration to an arbitrary path and prints its
#       identity hash. It never touches the canonical snapshot unless that is
#       the destination it was given.
#
#   main()
#       fresh run  -> render directly to config/run_config.snapshot.json
#       resume     -> render to a temporary path, compare identities against
#                     the PRESERVED snapshot, and only then decide. The
#                     canonical snapshot is never overwritten on resume; the
#                     incoming request is kept as an audit copy instead.
#
# AUD-HIGH-001 fix. The identity now includes content checksums of the
# samplesheet, every input FASTQ, the reference FASTA, the target BED and every
# known-sites file, so replacing a file in place without changing its path is
# detected. Hashing large FASTQ files is expensive, so the FASTQ contribution
# uses size+mtime by default and switches to a full content hash when
# `resume_strict_checksums` is true in the run config.
# ---------------------------------------------------------------------------
render_config_snapshot() {
    local snapshot=$1
    local known_sites_json
    known_sites_json=$(printf '%s\n' ${KNOWN_SITES[@]+"${KNOWN_SITES[@]}"} \
        | "$(resolve_python)" -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')

    "$(resolve_python)" - "$snapshot" \
        "$PIPELINE_NAME" "$PIPELINE_VERSION" "$RUN_ID" "$SAMPLESHEET" "$OUTPUT_ROOT" "$RUN_DIR" \
        "$THREADS" "$SORT_THREADS" "$SORT_MEM" "$FASTQC_THREADS" "$PAIRHMM_THREADS" \
        "$JAVA_MEM_GB" "$INTERVAL_PADDING" "$MOSDEPTH_MAPQ" "$LOW_COVERAGE_DEPTH" \
        "$MIN_RAM_GB" "$COVERAGE_MIN_MEAN_DEPTH" "$TRIM_MODE" \
        "$BQSR_TARGET_ONLY" "$BQSR_DIAGNOSTICS" \
        "$CAPTURE_KIT_ID" "$CAPTURE_KIT_REGISTRY" "$CAPTURE_KIT_MODE" \
        "$BUNDLE_ID" "$ASSEMBLY" "$CONTIG_STYLE" "$REF_FASTA" "$TARGET_BED" \
        "$TARGET_BED_STATUS" "$TARGET_BED_MANUFACTURER" \
        "$TARGET_BED_CAPTURE_KIT_NAME" "$TARGET_BED_CAPTURE_KIT_VERSION" \
        "$TARGET_BED_DESIGN_ID" "$TARGET_BED_GENOME_BUILD" \
        "$TARGET_BED_SOURCE" "$TARGET_BED_SOURCE_URL" \
        "$TARGET_BED_FILE_NAME" "$TARGET_BED_SHA256" \
        "$COVERAGE_BED" "$COVERAGE_BED_SHA256" \
        "$DBSNP_VCF" "$CLINVAR_VCF" "$VEP_CACHE" "$TRUTH_VCF" "$TRUTH_BED" \
        "$known_sites_json" "$OPT_FILTERING" "$OPT_ANNOTATION" "$OPT_INTERVAR" \
        "$RESUME_STRICT_CHECKSUMS" "$JSON_SCHEMA_VERSION" <<'PYSNAP' | tr -d '\r'
import hashlib, json, os, sys

(out, name, version, run_id, samplesheet, output_root, run_dir,
 threads, sort_threads, sort_mem, fastqc_threads, pairhmm_threads,
 java_mem_gb, interval_padding, mosdepth_mapq, low_coverage_depth,
 min_ram_gb, coverage_min_mean_depth, trim_mode,
 bqsr_target_only, bqsr_diagnostics,
 capture_kit_id, capture_kit_registry, capture_kit_mode,
 bundle_id, assembly, contig_style, ref_fasta, target_bed,
 target_bed_status, target_bed_manufacturer,
 target_bed_capture_kit_name, target_bed_capture_kit_version,
 target_bed_design_id, target_bed_genome_build,
 target_bed_source, target_bed_source_url,
 target_bed_file_name, target_bed_sha256,
 coverage_bed, coverage_bed_sha256,
 dbsnp, clinvar, vep_cache, truth_vcf, truth_bed,
 known_sites_json, opt_filtering, opt_annotation, opt_intervar,
 strict_checksums, schema_version) = sys.argv[1:53]


def nn(v):
    return v if v else None


doc = {
    "pipeline_name": name,
    "pipeline_version": version,
    "run_id": run_id,
    "samplesheet": samplesheet,
    "output_root": output_root,
    "run_dir": run_dir,
    "threads": int(threads),
    "sort_threads": int(sort_threads),
    "sort_mem": sort_mem,
    "fastqc_threads": int(fastqc_threads),
    "pairhmm_threads": int(pairhmm_threads),
    "java_mem_gb": int(java_mem_gb),
    "interval_padding": int(interval_padding),
    "mosdepth_mapq": int(mosdepth_mapq),
    "low_coverage_depth": int(low_coverage_depth),
    "min_available_ram_gb": int(min_ram_gb),
    "coverage_min_mean_depth": float(coverage_min_mean_depth),
    "trim_mode": trim_mode,
    "bqsr_target_only": bqsr_target_only == "true",
    "bqsr_diagnostics": bqsr_diagnostics == "true",
    "assay": "WES",
    "library_layout": "paired-end",
    "capture_kit": {
        "id": capture_kit_id,
        "mode": capture_kit_mode,
        "registry": nn(capture_kit_registry),
    },
    "resource_bundle": {
        "bundle_id": nn(bundle_id),
        "assembly": nn(assembly),
        "contig_style": nn(contig_style),
        "reference_fasta": nn(ref_fasta),
        "target_bed": nn(target_bed),
        "target_bed_metadata": {
            "status": target_bed_status,
            "manufacturer": target_bed_manufacturer,
            "capture_kit_name": target_bed_capture_kit_name,
            "capture_kit_version": target_bed_capture_kit_version,
            "design_id": target_bed_design_id,
            "genome_build": target_bed_genome_build,
            "source": target_bed_source,
            "source_url": nn(target_bed_source_url),
            "file_name": target_bed_file_name,
            "sha256": target_bed_sha256,
        },
        "coverage_bed": nn(coverage_bed),
        "coverage_bed_sha256": coverage_bed_sha256,
        "known_sites": json.loads(known_sites_json),
        "dbsnp_vcf": nn(dbsnp),
        "clinvar_vcf": nn(clinvar),
        "vep_cache": nn(vep_cache),
        "truth_vcf": nn(truth_vcf),
        "truth_bed": nn(truth_bed),
    },
    "optional_steps": {
        "filtering": opt_filtering == "true",
        "annotation": opt_annotation == "true",
        "intervar": opt_intervar == "true",
    },
}

# Identity of the analysis-affecting settings. resume compares this value.
# ---------------------------------------------------------------------------
# Resume identity
#
# Covers the settings that change what the analysis produces, PLUS the content
# of every input and resource file. Replacing a file in place without changing
# its path therefore invalidates resume.
#
# FASTQ files are fingerprinted by size+mtime by default because hashing a full
# WES input costs minutes; set resume_strict_checksums=true to hash contents.
# Reference/BED/known-sites/samplesheet are always content-hashed: they are
# small relative to the FASTQ and they silently change results if swapped.
# ---------------------------------------------------------------------------
def sha256_of(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def stat_fingerprint(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return f"{st.st_size}:{int(st.st_mtime)}"


resource_identity = {}
for label, path in [("samplesheet", samplesheet),
                    ("reference_fasta", ref_fasta),
                    ("target_bed", target_bed),
                    ("coverage_bed", coverage_bed),
                    ("capture_kit_registry", capture_kit_registry)]:
    if path:
        resource_identity[label] = sha256_of(path)
for i, ks in enumerate(doc["resource_bundle"]["known_sites"]):
    resource_identity[f"known_sites[{i}]"] = sha256_of(ks)
if dbsnp:
    resource_identity["dbsnp_vcf"] = sha256_of(dbsnp)

# Per-lane FASTQ fingerprints, taken from the samplesheet itself so that a
# changed FASTQ path *or* a changed FASTQ file both alter the identity.
fastq_identity = {}
try:
    import csv as _csv
    with open(samplesheet, encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            for col in ("fastq_1", "fastq_2"):
                raw = (row.get(col) or "").strip()
                if not raw:
                    continue
                p = raw if os.path.isabs(raw) else os.path.join(
                    os.path.dirname(os.path.abspath(samplesheet)), raw)
                p = os.path.realpath(p)
                key = f"{(row.get('sample') or '').strip()}/{(row.get('lane') or '').strip()}/{col}"
                fastq_identity[key] = (sha256_of(p) if strict_checksums == "true"
                                       else stat_fingerprint(p))
except (OSError, ValueError, KeyError):
    fastq_identity["__unreadable__"] = True

identity_keys = {
    "run_id": doc["run_id"],
    "settings": {k: doc[k] for k in (
        "samplesheet", "trim_mode", "interval_padding", "mosdepth_mapq",
        "pairhmm_threads", "bqsr_target_only", "resource_bundle")},
    "resource_content": resource_identity,
    "fastq_content": fastq_identity,
    "fastq_identity_mode": "sha256" if strict_checksums == "true" else "size_mtime",
}
doc["resume_identity_detail"] = identity_keys
doc["config_identity_sha256"] = hashlib.sha256(
    json.dumps(identity_keys, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()
doc["schema_version"] = schema_version

tmp = out + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, out)
print(doc["config_identity_sha256"])
PYSNAP
}

# =============================================================================
# 5. Preflight
# =============================================================================

# ---------------------------------------------------------------------------
# validate_samplesheet
#
# [ORIGIN] previous main.sh lines 432-669 (QC + Alignment block).
# [KEEP_WITH_INTERFACE_PATCH] The validation logic is preserved: required
#   columns, ID character rules, blank/extra field detection, per-row FASTQ
#   existence / readability / size checks, gzip magic-number check, R1 == R2
#   rejection, duplicate sample+lane rejection, FASTQ re-use rejection,
#   per-sample metadata consistency and normalized manifest emission.
# [ADDED] read-group columns (rg_id, library, platform, platform_unit) with
#   safe defaults, and the "exactly one biological sample" rule.
# [SCHEMA] The original columns are kept. patient/sex/status are still accepted
#   so existing samplesheets continue to load; they are not used by the current
#   germline single-sample profile.
# ---------------------------------------------------------------------------
validate_samplesheet() {
    local out_tsv="$RUN_DIR/00_input_validation/manifest.tsv"
    local out_json="$CONFIG_DIR/normalized_manifest.json"
    local report="$RUN_DIR/00_input_validation/samplesheet_validation.txt"
    mkdir -p -- "$RUN_DIR/00_input_validation"

    local rc=0
    set +e
    "$(resolve_python)" - "$SAMPLESHEET" "$out_tsv" "$out_json" > "$report" 2>&1 <<'PYSHEET'
import csv, json, os, re, sys
from collections import OrderedDict
from pathlib import Path

sheet_path = Path(sys.argv[1])
manifest_tsv = Path(sys.argv[2])
manifest_json = Path(sys.argv[3])

REQUIRED = ["sample", "lane", "fastq_1", "fastq_2"]
KNOWN = {"sample", "lane", "fastq_1", "fastq_2",
         "rg_id", "library", "platform", "platform_unit",
         "patient", "sex", "status"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FASTQ_RE = re.compile(r"\.(fastq|fq)\.gz$", re.IGNORECASE)

errors, warnings, rows = [], [], []
seen_keys, seen_fastq, sample_meta = set(), {}, OrderedDict()
base_dir = sheet_path.parent.resolve()

try:
    handle = sheet_path.open("r", encoding="utf-8-sig", newline="")
except UnicodeDecodeError as exc:
    print(f"[ERROR] Samplesheet is not valid UTF-8: {exc}"); sys.exit(2)
except OSError as exc:
    print(f"[ERROR] Cannot open samplesheet: {exc}"); sys.exit(2)

with handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        errors.append("Header row is missing.")
    else:
        original = reader.fieldnames
        headers = [h.strip() if h is not None else "" for h in original]
        if len(headers) != len(set(headers)):
            errors.append(f"Duplicate column names: {headers}")
        if any(not h for h in headers):
            errors.append("One or more column names are blank.")
        missing = [c for c in REQUIRED if c not in headers]
        if missing:
            errors.append("Missing required columns: " + ", ".join(missing))
        unknown = [c for c in headers if c not in KNOWN]
        if unknown:
            warnings.append("Unknown columns are ignored: " + ", ".join(unknown))
        header_map = dict(zip(original, headers))

        for line_no, raw in enumerate(reader, start=2):
            if None in raw:
                errors.append(f"Line {line_no}: too many comma-separated fields."); continue
            row = {header_map.get(k, k): (v or "").strip() for k, v in raw.items()}
            if not any(row.values()):
                warnings.append(f"Line {line_no}: blank row skipped."); continue

            sample = row.get("sample", "")
            lane = row.get("lane", "")
            fq1_raw = row.get("fastq_1", "")
            fq2_raw = row.get("fastq_2", "")

            for field in ("sample", "lane"):
                value = row.get(field, "")
                if not value:
                    errors.append(f"Line {line_no}: '{field}' is empty.")
                elif not ID_RE.fullmatch(value):
                    errors.append(
                        f"Line {line_no}: invalid {field} '{value}'. Use letters, digits, dot, "
                        "underscore and hyphen only; the first character must be alphanumeric.")

            rg_id = row.get("rg_id", "") or f"{sample}.{lane}"
            library = row.get("library", "") or sample
            platform = row.get("platform", "") or "ILLUMINA"
            platform_unit = row.get("platform_unit", "") or lane
            for field, value in (("rg_id", rg_id), ("library", library),
                                 ("platform", platform), ("platform_unit", platform_unit)):
                if not ID_RE.fullmatch(value):
                    errors.append(f"Line {line_no}: invalid {field} '{value}'.")

            if not fq1_raw:
                errors.append(f"Line {line_no}: fastq_1 is empty.")
            if not fq2_raw:
                errors.append(f"Line {line_no}: fastq_2 is empty (paired-end input is required).")
            if not fq1_raw or not fq2_raw:
                continue

            def resolve(raw_path):
                p = Path(os.path.expanduser(raw_path))
                if not p.is_absolute():
                    p = base_dir / p
                return p.resolve()

            fq1, fq2 = resolve(fq1_raw), resolve(fq2_raw)

            for label, path in (("fastq_1", fq1), ("fastq_2", fq2)):
                if not FASTQ_RE.search(path.name):
                    errors.append(f"Line {line_no}: {label} must end in .fastq.gz or .fq.gz: {path}")
                if not path.exists():
                    errors.append(f"Line {line_no}: {label} does not exist: {path}")
                elif not path.is_file():
                    errors.append(f"Line {line_no}: {label} is not a regular file: {path}")
                elif not os.access(path, os.R_OK):
                    errors.append(f"Line {line_no}: {label} is not readable: {path}")
                elif path.stat().st_size == 0:
                    errors.append(f"Line {line_no}: {label} is empty: {path}")
                else:
                    try:
                        with path.open("rb") as fh:
                            magic = fh.read(2)
                        if magic != b"\x1f\x8b":
                            errors.append(f"Line {line_no}: {label} is not gzip-compressed: {path}")
                    except OSError as exc:
                        errors.append(f"Line {line_no}: cannot inspect {label}: {path}: {exc}")

            if fq1 == fq2:
                errors.append(f"Line {line_no}: fastq_1 and fastq_2 are the same file: {fq1}")

            key = (sample, lane)
            if key in seen_keys:
                errors.append(f"Line {line_no}: duplicate sample/lane combination: {sample}/{lane}")
            seen_keys.add(key)

            for label, path in (("fastq_1", fq1), ("fastq_2", fq2)):
                prev = seen_fastq.get(str(path))
                if prev is not None:
                    errors.append(f"Line {line_no}: FASTQ re-used. {path} was already used as {prev}.")
                else:
                    seen_fastq[str(path)] = f"{sample}/{lane}/{label}"

            meta = (library, platform)
            prev_meta = sample_meta.get(sample)
            if prev_meta is not None and prev_meta != meta:
                errors.append(f"Line {line_no}: library/platform differ between lanes of sample "
                              f"'{sample}': {prev_meta} vs {meta}")
            else:
                sample_meta.setdefault(sample, meta)

            rows.append({"sample": sample, "lane": lane, "rg_id": rg_id,
                         "library": library, "platform": platform,
                         "platform_unit": platform_unit,
                         "fastq_1": str(fq1), "fastq_2": str(fq2)})

if not rows:
    errors.append("No usable data rows were found.")

samples = sorted({r["sample"] for r in rows})
if len(samples) > 1:
    errors.append(
        "The current verification profile supports exactly one biological sample per run. "
        f"Found {len(samples)}: {', '.join(samples)}. Multi-sample joint calling is out of scope.")

for w in warnings:
    print(f"[WARN] {w}")
if errors:
    print("[ERROR] Samplesheet validation failed:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(2)

for r in rows:
    values = [r[k] for k in ("sample", "lane", "rg_id", "library", "platform",
                             "platform_unit", "fastq_1", "fastq_2")]
    if any("\t" in v or "\n" in v or "\r" in v for v in values):
        print("[ERROR] Tabs or newlines are not allowed in samplesheet values."); sys.exit(2)

manifest_tsv.parent.mkdir(parents=True, exist_ok=True)
with manifest_tsv.open("w", encoding="utf-8", newline="") as fh:
    for r in rows:
        fh.write("\t".join([r["sample"], r["lane"], r["rg_id"], r["library"],
                            r["platform"], r["platform_unit"],
                            r["fastq_1"], r["fastq_2"]]) + "\n")

sample = samples[0]
manifest_json.parent.mkdir(parents=True, exist_ok=True)
with manifest_json.open("w", encoding="utf-8") as fh:
    json.dump({"sample": sample,
               "library": sample_meta[sample][0],
               "platform": sample_meta[sample][1],
               "lane_count": len(rows),
               "lanes": rows}, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

print(f"[OK] Validated {len(rows)} lane row(s) for sample '{sample}'.")
PYSHEET
    rc=$?
    set -e

    cat "$report" || true
    if (( rc != 0 )); then
        step_check_fail "samplesheet" "validation failed; see 00_input_validation/samplesheet_validation.txt"
        return 1
    fi

    SAMPLE_ID=$(json_get "$out_json" sample)
    LANE_COUNT=$(json_get "$out_json" lane_count)
    step_check_pass "samplesheet" "columns, IDs, FASTQ pairs and metadata are consistent"
    step_metric sample "$SAMPLE_ID" str
    step_metric lane_count "$LANE_COUNT" num
    step_output manifest_tsv "$out_tsv"
    step_output normalized_manifest "$out_json"
    add_artifact manifest "Normalized run manifest" "$out_json" 1 1 "Validated sample/lane/FASTQ manifest"
    add_artifact validation_report "Samplesheet validation report" "$report" 1 0 "Samplesheet preflight output"
    return 0
}

# ---------------------------------------------------------------------------
# validate_reference_bundle
#
# [ORIGIN] Processing source section 3 (PRECHECK), read-only reference file
#   run_wes_processing_variantcall_full_v5_1.sh.
# [KEEP_WITH_INTERFACE_PATCH] Preserved checks: reference .fai and .dict
#   agreement on contig order and length, BWA index presence, known-sites
#   tabix index + header parse + contig-subset check, target BED structural and
#   range validation with a non-overlapping base count.
# [REMOVED] the `$HOME/sideprojects/` personal-area restriction and the
#   project-specific subset-path guard: both blocked any other user or server.
# [ADDED] a declared-contig-style consistency check so a bundle declaring
#   unprefixed contigs cannot be paired with a chr-prefixed reference, and vice
#   versa. contig_style describes chromosome naming only; the assembly itself is
#   recorded separately in resource_bundle.assembly.
# [ADDED] dbsnp_vcf gets the same structural checks as known-sites when it is
#   declared, because it is passed to GenotypeGVCFs in a core step.
#
# [WHAT THIS PROVES — AND WHAT IT DOES NOT]
#   These checks establish STRUCTURAL COMPATIBILITY: the files agree on contig
#   names, contig lengths and coordinate ranges, so the tools will not silently
#   mis-map coordinates.
#   They do NOT prove shared build provenance. Two files can agree on every
#   contig name and length and still come from different releases or different
#   patch levels of the same assembly. Provenance comes from the declared
#   resource_bundle (assembly, bundle_id) and from how the operator obtained the
#   files — never from these checks alone. Report wording must stay at
#   "structurally compatible" and must not claim a verified build.
# ---------------------------------------------------------------------------
validate_reference_bundle() {
    local report="$RUN_DIR/00_input_validation/resource_validation.txt"
    local rc=0

    set +e
    "$(resolve_python)" - "$REF_FASTA" "$TARGET_BED" "$COVERAGE_BED" \
        "$CONTIG_STYLE" "$DBSNP_VCF" "$TARGET_BED_SHA256" "$COVERAGE_BED_SHA256" \
        ${KNOWN_SITES[@]+"${KNOWN_SITES[@]}"} > "$report" 2>&1 <<'PYBUNDLE'
import hashlib, os, re, subprocess, sys
from collections import defaultdict

ref, bed, coverage_bed, contig_style, dbsnp, expected_bed_sha256, expected_coverage_sha256, *known_sites = sys.argv[1:]
errors, notes = [], []


def need(path, label):
    if not path:
        errors.append(f"{label} is not set in the resource bundle"); return False
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        errors.append(f"{label} missing or empty: {path}"); return False
    return True


# The five files bwa loads for an index, in no particular order.
BWA_INDEX_EXTS = ("amb", "ann", "bwt", "pac", "sa")


def check_bwa_index(ref):
    """Resolve the index prefix the way bwa does, then require THAT one complete.

    bwa.c bwa_idx_infer_prefix() probes "<hint>.64.bwt" first; if that file
    opens it returns "<hint>.64" as the prefix without looking at anything else.
    Only when that probe fails does it try "<hint>.bwt" -> "<hint>".
    bwa_idx_load_from_disk() then loads .amb/.ann/.pac/.sa at the prefix it was
    handed and fails if one is missing -- it never falls back to the other
    prefix. run_alignment() passes the FASTA path as that hint, so the same
    resolution decides what an actual `bwa mem` here would use.

    Two consequences this check reproduces:
      * a ".64" set (how the Broad GRCh38 bundle ships) is a normal, usable
        index. Requiring the unsuffixed names failed a perfectly good bundle.
      * "some complete set exists somewhere" is the wrong question. A stray
        <ref>.64.bwt hides a complete unsuffixed set from bwa, so it has to fail
        here rather than hours later in 03_alignment.
    """
    for suffix in (".64", ""):
        prefix = ref + suffix
        # Existence only, matching the fopen() probe bwa makes. A zero-byte
        # .bwt still selects the prefix; it is reported as incomplete below,
        # which is what bwa would do too.
        if not os.path.isfile(prefix + ".bwt"):
            continue
        missing = [ext for ext in BWA_INDEX_EXTS
                   if not (os.path.isfile(f"{prefix}.{ext}")
                           and os.path.getsize(f"{prefix}.{ext}") > 0)]
        if missing:
            errors.append(
                f"BWA index at '{prefix}.*' is incomplete: missing or empty "
                f"{', '.join('.' + e for e in missing)}. bwa resolves the reference "
                f"to this prefix because '{prefix}.bwt' exists, and it never falls "
                "back to another naming variant, so an index at the other prefix "
                "would not be used. Rebuild it with `bwa index`.")
        else:
            notes.append(
                f"BWA index: '{prefix}.*' complete "
                f"({'64-bit .64 naming' if suffix else 'standard naming'}; "
                "this is the prefix bwa resolves the reference to)")
        return

    errors.append(
        f"BWA index not found: neither '{ref}.64.bwt' nor '{ref}.bwt' exists. "
        "Run `bwa index` on the reference; the pipeline never builds it.")


ref_ok = need(ref, "reference_fasta")
bed_ok = need(bed, "target_bed")
coverage_bed_ok = need(coverage_bed, "coverage_bed")

fai = ref + ".fai"
dict_path = os.path.splitext(ref)[0] + ".dict"

if ref_ok:
    need(fai, "reference FASTA index (.fai)")
    need(dict_path, "reference sequence dictionary (.dict)")
    check_bwa_index(ref)

if os.path.isfile(fai) and os.path.isfile(dict_path):
    fai_rows = []
    with open(fai, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                f = line.split("\t")
                fai_rows.append((f[0], int(f[1])))
    dict_rows = []
    with open(dict_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("@SQ"):
                continue
            fields = dict(x.split(":", 1) for x in line.rstrip().split("\t")[1:] if ":" in x)
            dict_rows.append((fields.get("SN"), int(fields.get("LN", "-1"))))
    if fai_rows != dict_rows:
        errors.append("reference .fai and .dict disagree on contig order or lengths")
    else:
        notes.append(f"reference contigs: {len(fai_rows)}")

ref_contigs = set()
ref_lengths = {}
if os.path.isfile(fai):
    with open(fai, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                f = line.rstrip().split("\t")
                ref_contigs.add(f[0])
                ref_lengths[f[0]] = int(f[1])

# contig_style is a chromosome NAMING CONVENTION, never an assembly name.
# normalize_config() already restricted the value to this vocabulary; the
# explicit else keeps the check exhaustive here too, so an unrecognised style
# can never silently skip the comparison against the real FASTA.
NOCHR_STYLES = ("plain", "nochr", "ensembl")
CHR_STYLES = ("chr", "ucsc")

if ref_contigs:
    chr_prefixed = sum(1 for c in ref_contigs if c.startswith("chr"))
    looks_chr = chr_prefixed > len(ref_contigs) / 2
    style = (contig_style or "").lower()
    if style in NOCHR_STYLES:
        if looks_chr:
            errors.append(f"contig_style='{contig_style}' declares no 'chr' prefix but the reference uses 'chr'")
    elif style in CHR_STYLES:
        if not looks_chr:
            errors.append(f"contig_style='{contig_style}' declares a 'chr' prefix but the reference does not use it")
    else:
        errors.append(
            f"contig_style='{contig_style}' is not a recognised chromosome naming convention; "
            f"expected one of {', '.join(NOCHR_STYLES + CHR_STYLES)}. "
            "An assembly or build name is not a contig style.")
    notes.append(f"contig style: declared='{contig_style}', chr-prefixed={chr_prefixed}/{len(ref_contigs)}")

def check_bed(path, label, expected_sha256):
    rows = merged_rows = raw_bases = merged_bases = 0
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256.lower() != expected_sha256.lower():
        errors.append(
            f"{label} SHA-256 mismatch: "
            f"metadata={expected_sha256.lower()} actual={actual_sha256.lower()}")
    else:
        notes.append(f"{label} SHA-256 verified: {actual_sha256}")

    lengths, order = {}, {}
    with open(fai, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if line.strip():
                f = line.rstrip().split("\t")
                lengths[f[0]] = int(f[1]); order[f[0]] = i
    ivs = defaultdict(list)
    try:
        with open(path, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip() or line.startswith(("#", "track", "browser")):
                    continue
                f = line.rstrip().split("\t")
                if len(f) < 3:
                    raise ValueError(f"{label} line {line_no}: fewer than 3 columns")
                try:
                    start, end = int(f[1]), int(f[2])
                except ValueError:
                    raise ValueError(f"{label} line {line_no}: start/end are not integers")
                chrom = f[0]
                if chrom not in lengths:
                    raise ValueError(f"{label} line {line_no}: contig absent from reference: {chrom}")
                if start < 0 or end <= start or end > lengths[chrom]:
                    raise ValueError(f"{label} line {line_no}: interval out of range {chrom}:{start}-{end}")
                rows += 1
                raw_bases += end - start
                ivs[chrom].append((start, end))
        if rows == 0:
            raise ValueError(f"{label} contains no usable intervals")
        for chrom in sorted(ivs, key=lambda c: (order[c], c)):
            merged = []
            for s, e in sorted(ivs[chrom]):
                if not merged or s > merged[-1][1]:
                    merged.append([s, e])
                elif e > merged[-1][1]:
                    merged[-1][1] = e
            merged_rows += len(merged)
            merged_bases += sum(e - s for s, e in merged)
        notes.append(f"{label}: rows={rows}, non-overlap rows={merged_rows}, "
                     f"non-overlap bases={merged_bases}")
    except ValueError as exc:
        errors.append(str(exc))
    return rows, merged_rows, raw_bases, merged_bases


bed_rows = bed_merged_rows = bed_raw_bases = bed_merged_bases = 0
coverage_rows = coverage_merged_rows = coverage_raw_bases = coverage_merged_bases = 0
if bed_ok and ref_contigs:
    bed_rows, bed_merged_rows, bed_raw_bases, bed_merged_bases = check_bed(
        bed, "target BED", expected_bed_sha256)
if coverage_bed_ok and ref_contigs:
    coverage_rows, coverage_merged_rows, coverage_raw_bases, coverage_merged_bases = check_bed(
        coverage_bed, "coverage BED", expected_coverage_sha256)

CONTIG_LEN_RE = re.compile(r"##contig=<([^>]*)>")


def check_vcf_resource(vcf, label):
    """Structural checks shared by every indexed VCF resource in the bundle.

    Verifies: file present and non-empty, tabix/CSI index present, header
    parses, indexed contigs are a subset of the reference, and any contig
    lengths declared in the header agree with the reference .fai.

    This establishes structural compatibility only. It cannot establish that
    the file was built from the same assembly release as the reference; that
    remains a property of the declared resource_bundle.
    """
    errors_before = len(errors)
    if not need(vcf, label):
        return
    if not (os.path.isfile(vcf + ".tbi") or os.path.isfile(vcf + ".csi")):
        errors.append(f"{label} index missing (.tbi or .csi): {vcf}"); return
    try:
        p = subprocess.run(["bcftools", "view", "-h", vcf], capture_output=True, text=True, timeout=180)
        if p.returncode != 0:
            errors.append(f"cannot parse VCF header: {vcf}"); return
        header = p.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"bcftools unavailable for {vcf}: {exc}"); return

    # Header-declared contig lengths, when present, are a cheap and decisive
    # way to catch a resource built against a different assembly.
    mismatched = []
    for line in header.splitlines():
        m = CONTIG_LEN_RE.match(line.strip())
        if not m:
            continue
        fields = dict(kv.split("=", 1) for kv in m.group(1).split(",") if "=" in kv)
        name, ln = fields.get("ID"), fields.get("length")
        if not name or not ln or name not in ref_lengths:
            continue
        try:
            ln = int(ln)
        except ValueError:
            continue
        if ln != ref_lengths[name]:
            mismatched.append(f"{name}: header={ln} reference={ref_lengths[name]}")
    if mismatched:
        errors.append(f"{label} declares contig lengths that differ from the reference: "
                      f"{vcf}: {mismatched[:5]}")

    try:
        p = subprocess.run(["tabix", "-l", vcf], capture_output=True, text=True, timeout=180)
        if p.returncode != 0:
            errors.append(f"cannot read tabix contig list: {vcf}"); return
        listed = {x for x in p.stdout.splitlines() if x}
        unknown = sorted(listed - ref_contigs)
        if ref_contigs and unknown:
            errors.append(f"{label} contigs absent from the reference: {vcf}: {unknown[:10]}")
        elif listed and len(errors) == errors_before:
            notes.append(f"{label} structurally compatible: {os.path.basename(vcf)} "
                         f"({len(listed)} indexed contigs)")
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"tabix unavailable for {vcf}: {exc}")


if not known_sites:
    errors.append("known_sites is empty; BQSR is a core step and requires known sites")
for vcf in known_sites:
    check_vcf_resource(vcf, "known_sites entry")

# dbsnp_vcf is optional, but once declared it is handed to GenotypeGVCFs in a
# CORE step. A declared-but-broken dbSNP must therefore fail here rather than
# surface mid-run. Leaving it unset stays a warning at variant-calling time.
if dbsnp:
    check_vcf_resource(dbsnp, "dbsnp_vcf")
else:
    notes.append("dbsnp_vcf: not declared (rsIDs will not be added; variants are unaffected)")

for n in notes:
    print(f"[NOTE] {n}")
if errors:
    print("[ERROR] Resource bundle validation failed:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(2)
print("[OK] Resource bundle is structurally compatible "
      "(contig names, lengths and coordinate ranges agree).")
print("[NOTE] Structural compatibility is not proof of shared build provenance; "
      "that is asserted by the declared resource_bundle, not by these checks.")
print(f"METRIC target_rows={bed_rows}")
print(f"METRIC target_merged_rows={bed_merged_rows}")
print(f"METRIC target_merged_bases={bed_merged_bases}")
print(f"METRIC coverage_rows={coverage_rows}")
print(f"METRIC coverage_merged_rows={coverage_merged_rows}")
print(f"METRIC coverage_merged_bases={coverage_merged_bases}")
PYBUNDLE
    rc=$?
    set -e

    cat "$report" || true
    if (( rc != 0 )); then
        step_check_fail "resource_bundle" "validation failed; see 00_input_validation/resource_validation.txt"
        return 1
    fi
    # Wording is deliberate: the checks above compare contig names, contig
    # lengths and coordinate ranges. They do not establish that every file came
    # from the same assembly release, so this must not read as "build verified".
    step_check_pass "resource_bundle" "reference, indexes, target/coverage BEDs, known-sites and dbSNP are structurally compatible (declared assembly=${ASSEMBLY}, contig_style=${CONTIG_STYLE}); build provenance is asserted by the bundle, not proven here"

    local key value
    while IFS='=' read -r key value; do
        [[ -n "$key" ]] && step_metric "$key" "$value" num
    done < <(grep '^METRIC ' "$report" | sed 's/^METRIC //')

    step_metric assembly "$ASSEMBLY" str
    step_metric contig_style "$CONTIG_STYLE" str
    step_metric bundle_id "${BUNDLE_ID:-unset}" str
    step_metric capture_kit_id "$CAPTURE_KIT_ID" str
    step_metric capture_kit_mode "$CAPTURE_KIT_MODE" str
    step_metric target_bed_status "$TARGET_BED_STATUS" str
    step_metric target_bed_manufacturer "$TARGET_BED_MANUFACTURER" str
    step_metric target_bed_capture_kit_name "$TARGET_BED_CAPTURE_KIT_NAME" str
    step_metric target_bed_capture_kit_version "$TARGET_BED_CAPTURE_KIT_VERSION" str
    step_metric target_bed_design_id "$TARGET_BED_DESIGN_ID" str
    step_metric target_bed_genome_build "$TARGET_BED_GENOME_BUILD" str
    step_metric target_bed_source "$TARGET_BED_SOURCE" str
    step_metric target_bed_sha256 "$TARGET_BED_SHA256" str
    step_metric coverage_bed_sha256 "$COVERAGE_BED_SHA256" str
    step_input reference_fasta "$REF_FASTA"
    step_input target_bed "$TARGET_BED"
    step_input coverage_bed "$COVERAGE_BED"
    [[ -n "$CAPTURE_KIT_REGISTRY" ]] && step_input capture_kit_registry "$CAPTURE_KIT_REGISTRY"
    local ks
    for ks in ${KNOWN_SITES[@]+"${KNOWN_SITES[@]}"}; do step_input known_sites "$ks"; done
    if [[ -n "$DBSNP_VCF" ]]; then step_input dbsnp_vcf "$DBSNP_VCF"; fi

    # Resource checksums (reused from the Processing source section 5).
    : > "$RESOURCE_SHA256"
    local res
    for res in "$REF_FASTA" "$TARGET_BED" "$COVERAGE_BED" ${KNOWN_SITES[@]+"${KNOWN_SITES[@]}"}; do
        [[ -f "$res" ]] && printf '%s  %s\n' "$(sha256_file "$res")" "$res" >> "$RESOURCE_SHA256"
    done
    add_artifact resource_checksums "Resource checksums" "$RESOURCE_SHA256" 1 0 \
        "sha256 of reference, target/coverage BEDs and known-sites"
    add_artifact validation_report "Resource validation report" "$report" 1 0 "Resource bundle preflight output"
    return 0
}

# ---------------------------------------------------------------------------
# check_vcf_against_reference <vcf> [label]
#
# Structural compatibility check for an OPTIONAL annotation VCF, applying the
# same rules validate_reference_bundle() applies to known-sites and dbSNP:
# file present, index present, header parses, contig naming convention matches
# the reference, indexed contigs are a subset of the reference, and any
# header-declared contig lengths agree with the reference .fai.
#
# Returns 0 when structurally compatible, non-zero otherwise, and prints a
# one-line reason on failure. Callers in optional steps turn a non-zero result
# into a skip + warning so that core results are never affected.
#
# [SCOPE] Like the preflight checks, this proves coordinate-structure
# compatibility only. It does not prove that the resource was built from the
# same assembly release as the reference. The resource_bundle contract — every
# resource in the bundle belongs to the declared assembly — is what asserts
# that, and the exact release belongs in the bundle's own provenance.
# ---------------------------------------------------------------------------
check_vcf_against_reference() {
    local vcf=$1 label=${2:-resource}
    "$(resolve_python)" - "$vcf" "$REF_FASTA" "$CONTIG_STYLE" "$label" <<'PYVCFCOMPAT'
import os, re, subprocess, sys

vcf, ref, contig_style, label = sys.argv[1:5]


def fail(msg):
    print(f"{label}: {msg}")
    sys.exit(1)


if not vcf or not os.path.isfile(vcf) or os.path.getsize(vcf) == 0:
    fail(f"missing or empty: {vcf}")
if not (os.path.isfile(vcf + ".tbi") or os.path.isfile(vcf + ".csi")):
    fail(f"index missing (.tbi or .csi): {vcf}")

fai = ref + ".fai"
ref_lengths = {}
if os.path.isfile(fai):
    with open(fai, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                f = line.rstrip().split("\t")
                ref_lengths[f[0]] = int(f[1])
if not ref_lengths:
    fail(f"cannot read reference index: {fai}")

try:
    p = subprocess.run(["bcftools", "view", "-h", vcf], capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        fail(f"cannot parse VCF header: {vcf}")
    header = p.stdout
except (OSError, subprocess.SubprocessError) as exc:
    fail(f"bcftools unavailable: {exc}")

hdr_contigs, mismatched = [], []
for line in header.splitlines():
    m = re.match(r"##contig=<([^>]*)>", line.strip())
    if not m:
        continue
    fields = dict(kv.split("=", 1) for kv in m.group(1).split(",") if "=" in kv)
    name = fields.get("ID")
    if not name:
        continue
    hdr_contigs.append(name)
    ln = fields.get("length")
    if ln and name in ref_lengths:
        try:
            if int(ln) != ref_lengths[name]:
                mismatched.append(f"{name}(header={ln},ref={ref_lengths[name]})")
        except ValueError:
            pass
if mismatched:
    fail(f"contig lengths differ from the reference: {mismatched[:5]}")

# Naming convention: compare against the reference rather than assuming a
# convention from the assembly name.
ref_chr = sum(1 for c in ref_lengths if c.startswith("chr")) > len(ref_lengths) / 2
if hdr_contigs:
    vcf_chr = sum(1 for c in hdr_contigs if c.startswith("chr")) > len(hdr_contigs) / 2
    if vcf_chr != ref_chr:
        fail("chromosome naming convention differs from the reference "
             f"(reference uses {'chr-prefixed' if ref_chr else 'unprefixed'} names, "
             f"this file uses {'chr-prefixed' if vcf_chr else 'unprefixed'} names)")

try:
    p = subprocess.run(["tabix", "-l", vcf], capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        fail(f"cannot read tabix contig list: {vcf}")
    listed = {x for x in p.stdout.splitlines() if x}
except (OSError, subprocess.SubprocessError) as exc:
    fail(f"tabix unavailable: {exc}")

unknown = sorted(listed - set(ref_lengths))
if unknown:
    fail(f"contigs absent from the reference: {unknown[:10]}")

print(f"{label}: structurally compatible with the reference "
      f"({len(listed)} indexed contigs; build provenance not proven by this check)")
PYVCFCOMPAT
}

# ---------------------------------------------------------------------------
# validate_tools — presence and version only. Nothing is installed here.
# [ORIGIN] previous main.sh lines 232-248 and Processing source section 3.
# ---------------------------------------------------------------------------
validate_tools() {
    local required=(bwa samtools gatk bcftools tabix bgzip mosdepth fastqc awk sed grep sort cut wc)
    [[ "$TRIM_MODE" == "force" ]] && required+=(fastp)
    if [[ "$OPT_ANNOTATION" == "true" ]]; then required+=(bcftools); fi

    local missing=() tool
    for tool in "${required[@]}"; do
        have_command "$tool" || missing+=("$tool")
    done
    if (( ${#missing[@]} > 0 )); then
        step_check_fail "required_tools" "missing from PATH: ${missing[*]}. 실행 전에 직접 설치하세요. 준비 방법은 docs/MAIN_SH_COMPLETE_GUIDE.md의 \"6. 실행 방법과 CLI option\"(실행 전 준비물)과 \"29. Linux smoke test 절차\" 장에 있습니다. 이 파이프라인은 도구를 스스로 설치하지 않습니다."
    else
        step_check_pass "required_tools" "all ${#required[@]} required tools found"
    fi

    if have_command multiqc; then
        step_check_pass "multiqc_present" "MultiQC available"
    else
        step_warning "MULTIQC_MISSING" "MultiQC is not installed" \
            "Per-lane FastQC still runs; only the aggregated report is unavailable" "true"
    fi

    {
        echo "pipeline_name=$PIPELINE_NAME"
        echo "pipeline_version=$PIPELINE_VERSION"
        echo "run_id=$RUN_ID"
        echo "host=$(hostname 2>/dev/null || echo unknown)"
        echo "user=$(whoami 2>/dev/null || echo unknown)"
        echo "conda_env=${CONDA_DEFAULT_ENV:-none}"
        have_command bwa      && echo "bwa=$(bwa 2>&1 | awk '/Version/ {print $2; exit}')"
        have_command samtools && echo "samtools=$(samtools --version 2>/dev/null | sed -n 1p)"
        have_command gatk     && echo "gatk=$(gatk --version 2>&1 | sed -n 1p)"
        have_command bcftools && echo "bcftools=$(bcftools --version 2>/dev/null | sed -n 1p)"
        have_command mosdepth && echo "mosdepth=$(mosdepth --version 2>&1 | sed -n 1p)"
        have_command fastqc   && echo "fastqc=$(fastqc --version 2>&1 | sed -n 1p)"
        have_command fastp    && echo "fastp=$(fastp --version 2>&1 | sed -n 1p)"
        have_command multiqc  && echo "multiqc=$(multiqc --version 2>&1 | sed -n 1p)"
        have_command java     && echo "java=$(java -version 2>&1 | sed -n 1p)"
        echo "python=$(resolve_python)"
    } > "$VERSIONS_TXT" 2>/dev/null || true
    add_artifact software_versions "Software versions" "$VERSIONS_TXT" 1 0 "Tool versions captured at preflight"
}

# ---------------------------------------------------------------------------
# validate_fastq_integrity — optional full gzip stream test  (AUD-MEDIUM-003)
#
# The samplesheet validator checks the two-byte gzip magic number, which is
# cheap but cannot detect a truncated file. A truncated FASTQ would otherwise
# surface much later, during alignment.
#
# `gzip -t` reads the whole stream, which costs minutes on a full WES input, so
# it is opt-in: set `verify_fastq_gzip: true` in the run config. When it is off,
# a note is recorded so the report says which level of checking was applied.
# ---------------------------------------------------------------------------
validate_fastq_integrity() {
    local verify
    verify=$(json_get "$CONFIG_PATH" verify_fastq_gzip false)
    local manifest="$RUN_DIR/00_input_validation/manifest.tsv"
    [[ -s "$manifest" ]] || return 0

    if [[ "$verify" != "true" ]]; then
        step_metric fastq_gzip_verification "magic_only" str
        step_check_pass "fastq_gzip" \
            "gzip magic number checked for every FASTQ. Full stream test skipped (set verify_fastq_gzip=true to enable); a truncated FASTQ would surface during alignment."
        return 0
    fi

    if ! have_command gzip; then
        step_warning "GZIP_MISSING" "verify_fastq_gzip=true but gzip is not installed" \
            "Only the gzip magic number was checked" "true"
        return 0
    fi

    log "  verify_fastq_gzip=true: testing every FASTQ stream end to end (this reads the full files)."
    local s l r lb pl pu f1 f2 f bad=0
    while IFS=$'\t' read -r s l r lb pl pu f1 f2; do
        [[ -n "$s" ]] || continue
        for f in "$f1" "$f2"; do
            if ! gzip -t -- "$f" 2>/dev/null; then
                step_check_fail "fastq_gzip" "gzip integrity test failed (truncated or corrupt): $f"
                bad=1
            fi
        done
    done < "$manifest"

    if (( bad == 0 )); then
        step_metric fastq_gzip_verification "full_stream" str
        step_check_pass "fastq_gzip" "every FASTQ passed a full gzip stream test"
    fi
}

# ---------------------------------------------------------------------------
# validate_compute_resources — disk, RAM and CPU.
# [ORIGIN] Processing source section 3. The disk estimate is its conservative
#   heuristic: (compressed FASTQ bytes x 7) + 20 GB headroom.
# ---------------------------------------------------------------------------
validate_compute_resources() {
    local manifest="$RUN_DIR/00_input_validation/manifest.tsv"
    local fq_bytes=0 size
    if [[ -s "$manifest" ]]; then
        local s l r lb p pu fq1 fq2 f
        while IFS=$'\t' read -r s l r lb p pu fq1 fq2; do
            for f in "$fq1" "$fq2"; do
                [[ -f "$f" ]] && { size=$(file_size "$f"); fq_bytes=$(( fq_bytes + size )); }
            done
        done < "$manifest"
    fi

    local required_gb available_gb
    required_gb=$(( (fq_bytes * 7 + 20 * 1024 * 1024 * 1024 + 1024 * 1024 * 1024 - 1) / 1024 / 1024 / 1024 ))
    available_gb=$(df -Pk "$RUN_DIR" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}')
    available_gb=${available_gb:-0}
    step_metric input_fastq_bytes "$fq_bytes" num
    step_metric required_disk_gb "$required_gb" num
    step_metric available_disk_gb "$available_gb" num
    if (( available_gb > 0 && available_gb < required_gb )); then
        step_check_fail "disk_space" "need about ${required_gb} GB, available ${available_gb} GB"
    elif (( available_gb == 0 )); then
        step_warning "DISK_UNKNOWN" "Could not determine free disk space" \
            "A long run may fail late if the filesystem fills up" "true"
    else
        step_check_pass "disk_space" "required ~${required_gb} GB, available ${available_gb} GB"
    fi

    if [[ -r /proc/meminfo ]]; then
        local ram_gb
        ram_gb=$(awk '/MemAvailable:/ {printf "%d", $2/1024/1024}' /proc/meminfo)
        step_metric available_ram_gb "$ram_gb" num
        if (( ram_gb < MIN_RAM_GB )); then
            step_check_fail "memory" "available RAM ${ram_gb} GB is below the configured minimum ${MIN_RAM_GB} GB"
        else
            step_check_pass "memory" "available ${ram_gb} GB (minimum ${MIN_RAM_GB} GB)"
        fi
    else
        step_warning "RAM_UNKNOWN" "/proc/meminfo is unavailable; RAM preflight skipped" \
            "GATK steps may fail if the host has less memory than java_mem_gb" "true"
    fi

    if have_command nproc; then
        local cores
        cores=$(nproc)
        step_metric logical_cores "$cores" num
        if (( THREADS > cores )); then
            step_check_fail "cpu" "threads=$THREADS exceeds logical cores=$cores"
        else
            step_check_pass "cpu" "threads=$THREADS, logical cores=$cores"
        fi
    fi
}

# ---------------------------------------------------------------------------
# validate_output_root — the run directory must live inside output_root.
# ---------------------------------------------------------------------------
validate_output_root() {
    if path_under "$RUN_DIR" "$OUTPUT_ROOT"; then
        step_check_pass "output_root" "run directory is contained in output_root"
    else
        step_check_fail "output_root" "run directory escapes output_root: $RUN_DIR"
    fi
    if path_under "$SAMPLESHEET" "$RUN_DIR"; then
        step_warning "SAMPLESHEET_INSIDE_RUN" "The samplesheet lives inside the run directory" \
            "Resuming after deleting the run directory will also delete the samplesheet" "true"
    fi
}

# =============================================================================
# 6. Core pipeline functions
#
# Every function reads only what it was explicitly given and publishes its
# outputs both as artifacts and as runtime variables for the next function.
# No function discovers its input by globbing the filesystem.
# =============================================================================

# ---------------------------------------------------------------------------
# 00_input_validation
# ---------------------------------------------------------------------------
run_input_validation() {
    start_step 00_input_validation
    mkdir -p -- "$RUN_DIR/00_input_validation"

    step_input run_config "$CONFIG_PATH"
    step_input samplesheet "$SAMPLESHEET"

    validate_tools
    validate_samplesheet || { finish_step failed 1; return 1; }
    validate_reference_bundle || { finish_step failed 1; return 1; }
    validate_output_root
    validate_fastq_integrity
    validate_compute_resources

    complete_step
}

# ---------------------------------------------------------------------------
# 01_raw_qc
#
# [ORIGIN] previous main.sh lines 776-810 (per-lane FastQC) and 1013-1027
#   (MultiQC), both from the QC + Alignment block.
# [KEEP_WITH_INTERFACE_PATCH] Preserved: per-lane output directory, FastQC
#   thread cap, verification that all four expected outputs exist, and the
#   "[SKIP] outputs already present" re-entrancy behaviour.
# [MERGE_BEST_PARTS] The previous file also invoked FastQC a second time at
#   line 1061 ("00_fastqc_raw", from the Processing source) using variables
#   that did not exist here. That duplicate is removed; the lane-aware
#   implementation is kept because it matches the samplesheet contract.
# [POLICY] MultiQC is report-only. No analysis step reads it, so a missing or
#   failing MultiQC is a warning, not a failure. A FastQC failure IS a failure
#   because per-lane QC evidence is part of the core report.
# ---------------------------------------------------------------------------
fastqc_stem() {
    local base stem
    base=$(basename -- "$1")
    stem=${base%.gz}; stem=${stem%.fastq}; stem=${stem%.fq}
    printf '%s' "$stem"
}

run_raw_qc() {
    start_step 01_raw_qc
    local stage_dir="$RUN_DIR/01_raw_qc"
    local fastqc_dir="$stage_dir/fastqc"
    local multiqc_dir="$stage_dir/multiqc"
    mkdir -p -- "$fastqc_dir" "$multiqc_dir"

    local manifest="$RUN_DIR/00_input_validation/manifest.tsv"
    [[ -s "$manifest" ]] || { fail_step "missing_manifest" "manifest not found: $manifest"; return 1; }
    step_input manifest_tsv "$manifest"

    local qc_threads=$(( FASTQC_THREADS < THREADS ? FASTQC_THREADS : THREADS ))
    (( qc_threads >= 1 )) || qc_threads=1

    local sample lane rg lib plat pu fq1 fq2 unit unit_dir
    local stem1 stem2 html1 zip1 html2 zip2 f
    local total=0 done_count=0

    while IFS=$'\t' read -r sample lane rg lib plat pu fq1 fq2; do
        [[ -n "$sample" ]] || continue
        total=$(( total + 1 ))
        unit="${sample}.${lane}"
        unit_dir="$fastqc_dir/$unit"
        mkdir -p -- "$unit_dir"
        step_input fastq_r1 "$fq1"
        step_input fastq_r2 "$fq2"

        stem1=$(fastqc_stem "$fq1"); stem2=$(fastqc_stem "$fq2")
        html1="$unit_dir/${stem1}_fastqc.html"; zip1="$unit_dir/${stem1}_fastqc.zip"
        html2="$unit_dir/${stem2}_fastqc.html"; zip2="$unit_dir/${stem2}_fastqc.zip"

        if [[ -s "$html1" && -s "$zip1" && -s "$html2" && -s "$zip2" ]]; then
            log "  [SKIP] FastQC outputs already present for $unit"
        else
            rm -f -- "$html1" "$zip1" "$html2" "$zip2"
            require_cmd_ok "fastqc_${unit}" \
                fastqc --threads "$qc_threads" --outdir "$unit_dir" "$fq1" "$fq2" \
                || { finish_step failed 1; return 1; }
        fi

        local missing=()
        for f in "$html1" "$zip1" "$html2" "$zip2"; do
            [[ -s "$f" ]] || missing+=("$(basename -- "$f")")
        done
        if (( ${#missing[@]} > 0 )); then
            step_check_fail "fastqc_outputs_${unit}" "FastQC did not produce: ${missing[*]}"
        else
            step_check_pass "fastqc_outputs_${unit}" "4 expected FastQC outputs present"
            done_count=$(( done_count + 1 ))
            step_output fastqc_html "$html1"
            step_output fastqc_html "$html2"
            add_artifact fastqc_html "FastQC ${unit} R1" "$html1" 1 0 "Per-lane FastQC report (R1)"
            add_artifact fastqc_html "FastQC ${unit} R2" "$html2" 1 0 "Per-lane FastQC report (R2)"
            add_artifact fastqc_zip "FastQC ${unit} R1 data" "$zip1" 1 0 "FastQC raw data (R1)"
            add_artifact fastqc_zip "FastQC ${unit} R2 data" "$zip2" 1 0 "FastQC raw data (R2)"
        fi
    done < "$manifest"

    step_metric lanes_total "$total" num
    step_metric lanes_with_fastqc "$done_count" num
    step_has_failures && { finish_step failed 1; return 1; }

    local multiqc_report="$multiqc_dir/multiqc_report.html"
    if have_command multiqc; then
        local rc=0
        run_cmd "multiqc" multiqc --force --outdir "$multiqc_dir" "$fastqc_dir" || rc=$?
        if (( rc != 0 )); then
            step_warning "MULTIQC_FAILED" "MultiQC exited with code $rc" \
                "Per-lane FastQC results remain; only the aggregated report is missing" "true"
        elif [[ ! -s "$multiqc_report" ]]; then
            step_warning "MULTIQC_NO_REPORT" "MultiQC ran but produced no multiqc_report.html" \
                "Aggregated QC report unavailable; per-lane FastQC is unaffected" "true"
        else
            step_check_pass "multiqc" "aggregated report created"
            step_output multiqc_html "$multiqc_report"
            add_artifact multiqc_html "MultiQC report" "$multiqc_report" 1 0 "Aggregated QC report"
        fi
    else
        step_warning "MULTIQC_MISSING" "MultiQC is not installed" \
            "Aggregated QC report is not produced; per-lane FastQC is unaffected" "true"
    fi

    complete_step
}

# ---------------------------------------------------------------------------
# 02_preprocessing
#
# [ORIGIN] previous main.sh lines 253-399 (fastp block) and line 1063
#   (trim-decision record from the Processing block).
# [KEEP_WITH_INTERFACE_PATCH] The fastp invocation and its option set are kept
#   verbatim: --detect_adapter_for_pe, --qualified_quality_phred 20,
#   --unqualified_percent_limit 40, --length_required 50, --thread, --json, --html.
# [REMOVED confirmed errors]
#   - `main "$@"` at line 399 ran this block in the middle of another block,
#     before the samplesheet had been validated
#   - detect_inputs() glob discovery (lines 283-323) which could pick up
#     another run's or another user's FASTQ
#   - extract_sample_id() (lines 326-344) which derived the sample ID from a
#     filename; the sample ID now comes from the validated manifest
#   - `conda install -c bioconda fastp -y` (line 371)
#   - the contradiction between running fastp and recording "trim_mode=none"
# [POLICY] trim_mode is explicit: skip or force. No automatic threshold mode is
#   implemented. The decision and the exact FASTQ list are always recorded.
# ---------------------------------------------------------------------------
run_preprocessing() {
    start_step 02_preprocessing
    local stage_dir="$RUN_DIR/02_preprocessing"
    local clean_dir="$stage_dir/fastq_clean"
    local qc_dir="$stage_dir/fastp"
    mkdir -p -- "$stage_dir"

    local manifest="$RUN_DIR/00_input_validation/manifest.tsv"
    [[ -s "$manifest" ]] || { fail_step "missing_manifest" "manifest not found: $manifest"; return 1; }
    step_input manifest_tsv "$manifest"

    FASTQ_MANIFEST="$stage_dir/fastq_manifest.tsv"
    local decision_json="$stage_dir/preprocessing_decision.json"
    local decision_rows="$STEP_WORK/decision_rows.tsv"
    : > "$FASTQ_MANIFEST"
    : > "$decision_rows"

    local reason lanes=0
    local sample lane rg lib plat pu fq1 fq2 unit
    local r1_clean r2_clean r1_part r2_part fastp_json fastp_html before after

    if [[ "$TRIM_MODE" == "skip" ]]; then
        reason="trim_mode=skip in the run config; the raw FASTQ is passed to alignment unchanged."
        while IFS=$'\t' read -r sample lane rg lib plat pu fq1 fq2; do
            [[ -n "$sample" ]] || continue
            lanes=$(( lanes + 1 ))
            step_input fastq_r1 "$fq1"; step_input fastq_r2 "$fq2"
            printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
                "$sample" "$lane" "$rg" "$lib" "$plat" "$pu" "$fq1" "$fq2" >> "$FASTQ_MANIFEST"
            printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$sample" "$lane" "$fq1" "$fq2" "$fq1" "$fq2" >> "$decision_rows"
        done < "$manifest"
        step_check_pass "trim_decision" "skip — the raw FASTQ is declared as the alignment input"
    else
        reason="trim_mode=force in the run config; fastp adapter/quality trimming was applied to every lane."
        have_command fastp || { fail_step "fastp_missing" "trim_mode=force but fastp is not installed. Install it before running; the pipeline never installs software."; return 1; }
        mkdir -p -- "$clean_dir" "$qc_dir"

        while IFS=$'\t' read -r sample lane rg lib plat pu fq1 fq2; do
            [[ -n "$sample" ]] || continue
            lanes=$(( lanes + 1 ))
            unit="${sample}.${lane}"
            step_input fastq_r1 "$fq1"; step_input fastq_r2 "$fq2"

            r1_clean="$clean_dir/${unit}_R1.clean.fastq.gz"
            r2_clean="$clean_dir/${unit}_R2.clean.fastq.gz"
            r1_part="${r1_clean}.part"; r2_part="${r2_clean}.part"
            fastp_json="$qc_dir/${unit}.fastp.json"; fastp_html="$qc_dir/${unit}.fastp.html"
            rm -f -- "$r1_part" "$r2_part"

            require_cmd_ok "fastp_${unit}" \
                fastp -i "$fq1" -I "$fq2" -o "$r1_part" -O "$r2_part" \
                      --detect_adapter_for_pe \
                      --qualified_quality_phred 20 \
                      --unqualified_percent_limit 40 \
                      --length_required 50 \
                      --thread "$THREADS" \
                      --json "$fastp_json" --html "$fastp_html" \
                || { finish_step failed 1; return 1; }

            if [[ ! -s "$r1_part" || ! -s "$r2_part" ]]; then
                rm -f -- "$r1_part" "$r2_part"
                fail_step "fastp_empty_output" "fastp produced an empty trimmed FASTQ for $unit"
                return 1
            fi
            mv -f -- "$r1_part" "$r1_clean"
            mv -f -- "$r2_part" "$r2_clean"

            step_check_pass "fastp_output_${unit}" "trimmed FASTQ pair created"
            step_output fastq_clean_r1 "$r1_clean"; step_output fastq_clean_r2 "$r2_clean"
            add_artifact fastp_json "fastp ${unit} metrics" "$fastp_json" 1 0 "fastp JSON report"
            add_artifact fastp_html "fastp ${unit} report" "$fastp_html" 1 0 "fastp HTML report"

            printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
                "$sample" "$lane" "$rg" "$lib" "$plat" "$pu" "$r1_clean" "$r2_clean" >> "$FASTQ_MANIFEST"
            printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$sample" "$lane" "$fq1" "$fq2" "$r1_clean" "$r2_clean" >> "$decision_rows"

            if [[ -s "$fastp_json" ]]; then
                before=$(json_get "$fastp_json" summary.before_filtering.total_reads 0 2>/dev/null || echo 0)
                after=$(json_get "$fastp_json" summary.after_filtering.total_reads 0 2>/dev/null || echo 0)
                step_metric "reads_before_${unit}" "$before" num
                step_metric "reads_after_${unit}" "$after" num
            fi
        done < "$manifest"
        step_check_pass "trim_decision" "force — fastp applied to $lanes lane(s)"
    fi

    (( lanes > 0 )) || { fail_step "no_lanes" "The manifest contained no lane rows"; return 1; }

    step_metric trim_mode "$TRIM_MODE" str
    step_metric lanes "$lanes" num
    step_output fastq_manifest "$FASTQ_MANIFEST"

    "$(resolve_python)" - "$decision_rows" "$decision_json" "$RUN_DIR" "$TRIM_MODE" \
        "$reason" "$FASTQ_MANIFEST" "$qc_dir" <<'PYDECISION'
import json, os, sys
rows_path, out_path, run_dir, mode, reason, fastq_manifest, qc_dir = sys.argv[1:8]


def rel(p):
    try:
        return os.path.relpath(p, run_dir).replace(os.sep, "/")
    except ValueError:
        return p


lanes = []
with open(rows_path, encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        sample, lane, in1, in2, out1, out2 = line.split("\t")
        lanes.append({"sample": sample, "lane": lane,
                      "input_fastq": {"r1": in1, "r2": in2},
                      "output_fastq": {"r1": out1, "r2": out2},
                      "trimmed": out1 != in1})

doc = {
    "mode": mode,
    "decision": "trimmed" if mode == "force" else "not_trimmed",
    "reason": reason,
    "automatic_threshold_decision": False,
    "lanes": lanes,
    "input_fastq": [l["input_fastq"] for l in lanes],
    "output_fastq": [l["output_fastq"] for l in lanes],
    "fastq_manifest": rel(fastq_manifest),
    "fastp_output_dir": rel(qc_dir) if mode == "force" else None,
    "next_step_ready": True,
}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
PYDECISION

    step_output preprocessing_decision "$decision_json"
    add_artifact preprocessing_decision "Preprocessing decision" "$decision_json" 1 1 \
        "Whether trimming was applied, why, and the exact FASTQ list alignment will use"

    complete_step
}

# ---------------------------------------------------------------------------
# 03_alignment
#
# [ORIGIN — two implementations merged]
#   A) previous main.sh lines 812-967 (QC + Alignment block) — BASE.
#      Kept: lane-level BWA-MEM with -K 100000000 and -Y, read group assembled
#      from sample metadata, coordinate sort, temporary output then atomic
#      rename, samtools quickcheck, index/flagstat/idxstats/stats, sample-level
#      merge with a hard-link fast path for the single-lane case, and the
#      completion-marker re-entrancy check.
#   B) Processing source section 7 "01_alignment" — SAFETY LOGIC ONLY.
#      Merged in: PIPESTATUS inspected per pipe element, samtools sort -T and
#      -m, `@HD ... SO:coordinate` verification, read-group SM verification,
#      per-command stderr logs, exact command recorded.
#      Its BWA-MEM call itself is NOT executed here: that copy exists so the
#      Processing part can be tested standalone, and running it would align the
#      same reads a second time.
# ---------------------------------------------------------------------------
run_alignment() {
    start_step 03_alignment
    local stage_dir="$RUN_DIR/03_alignment"
    local lane_dir="$stage_dir/lane_bam"
    local sample_dir="$stage_dir/sample_bam"
    local tmp_dir="$TMP_ROOT/03_alignment"
    mkdir -p -- "$lane_dir" "$sample_dir" "$tmp_dir"

    local fastq_manifest="$RUN_DIR/02_preprocessing/fastq_manifest.tsv"
    [[ -s "$fastq_manifest" ]] || { fail_step "missing_fastq_manifest" "02_preprocessing did not publish a FASTQ manifest: $fastq_manifest"; return 1; }
    step_input fastq_manifest "$fastq_manifest"
    step_input reference_fasta "$REF_FASTA"

    local sample lane rg lib plat pu fq1 fq2 unit
    local lane_bam lane_bai lane_part lane_done rg_string bwa_log sort_log
    local lane_bams=() lanes=0 sample_name=""

    while IFS=$'\t' read -r sample lane rg lib plat pu fq1 fq2; do
        [[ -n "$sample" ]] || continue
        if [[ -z "$sample_name" ]]; then
            sample_name="$sample"
        elif [[ "$sample_name" != "$sample" ]]; then
            fail_step "multiple_samples" "More than one sample in the FASTQ manifest: $sample_name and $sample"
            return 1
        fi
        lanes=$(( lanes + 1 ))
        unit="${sample}.${lane}"
        lane_bam="$lane_dir/${unit}.sorted.bam"
        lane_bai="${lane_bam}.bai"
        lane_part="$lane_dir/${unit}.sorted.part.bam"
        lane_done="$lane_dir/${unit}.done"
        lane_bams+=("$lane_bam")
        step_input fastq_r1 "$fq1"; step_input fastq_r2 "$fq2"

        local lane_valid=false
        if [[ -s "$lane_bam" && -s "$lane_bai" && -f "$lane_done" ]]; then
            if samtools quickcheck -q "$lane_bam"; then
                lane_valid=true
            else
                warn "Existing lane BAM failed quickcheck and will be rebuilt: $lane_bam"
            fi
        fi

        if [[ "$lane_valid" == true ]]; then
            log "  [SKIP] valid lane BAM already present: $unit"
        else
            rm -f -- "$lane_bam" "$lane_bai" "$lane_done" "$lane_part"
            rg_string="@RG\tID:${rg}\tSM:${sample}\tLB:${lib}\tPL:${plat}\tPU:${pu}"
            bwa_log="$LOG_DIR/${CURRENT_STEP}.bwa_${unit}.stderr.log"
            sort_log="$LOG_DIR/${CURRENT_STEP}.sort_${unit}.stderr.log"

            {
                printf '# %s — %s/align_%s\n' "$(iso_now)" "$CURRENT_STEP" "$unit"
                printf '%q ' bwa mem -K 100000000 -Y -t "$THREADS" -R "$rg_string" "$REF_FASTA" "$fq1" "$fq2"
                printf '| '
                printf '%q ' samtools sort -@ "$SORT_THREADS" -m "$SORT_MEM" \
                    -T "$tmp_dir/sort_${unit}" -O bam -o "$lane_part" -
                printf '\n\n'
            } >> "$COMMANDS_SH"

            log "  run: bwa mem | samtools sort ($unit)"
            local pipe_rc=()
            set +e
            bwa mem -K 100000000 -Y -t "$THREADS" -R "$rg_string" "$REF_FASTA" "$fq1" "$fq2" 2> "$bwa_log" \
              | samtools sort -@ "$SORT_THREADS" -m "$SORT_MEM" \
                    -T "$tmp_dir/sort_${unit}" -O bam -o "$lane_part" - 2> "$sort_log"
            pipe_rc=("${PIPESTATUS[@]}")
            set -e

            if (( pipe_rc[0] != 0 || pipe_rc[1] != 0 )); then
                rm -f -- "$lane_part"
                fail_step "alignment_${unit}" \
                    "bwa exit=${pipe_rc[0]}, samtools sort exit=${pipe_rc[1]}; see logs/${CURRENT_STEP}.bwa_${unit}.stderr.log"
                return 1
            fi
            if ! samtools quickcheck -v "$lane_part" >> "$sort_log" 2>&1; then
                rm -f -- "$lane_part"
                fail_step "alignment_${unit}" "samtools quickcheck failed on the temporary lane BAM"
                return 1
            fi
            mv -f -- "$lane_part" "$lane_bam"
            require_cmd_ok "index_${unit}" samtools index -@ "$THREADS" "$lane_bam" "$lane_bai" \
                || { finish_step failed 1; return 1; }
            touch -- "$lane_done"
        fi

        # `local` on its own line: `local h=$(cmd)` returns local's status, not
        # the command's, and the read failure would go unnoticed.
        local lane_header
        if lane_header=$(read_bam_header "$lane_bam"); then
            if bam_header_sorted_by_coordinate "$lane_header"; then
                step_check_pass "sort_order_${unit}" "@HD reports SO:coordinate"
            else
                step_check_fail "sort_order_${unit}" "@HD does not report SO:coordinate"
            fi
            if bam_header_has_sample "$lane_header" "$sample"; then
                step_check_pass "read_group_${unit}" "SM:${sample} present in @RG"
            else
                step_check_fail "read_group_${unit}" "SM:${sample} missing from the lane BAM @RG"
            fi
        else
            step_check_fail "bam_header_${unit}" \
                "samtools view -H could not read the lane BAM header"
        fi

        run_cmd_stdout "flagstat_${unit}" "$lane_dir/${unit}.flagstat.txt" samtools flagstat -@ "$THREADS" "$lane_bam" || true
        run_cmd_stdout "idxstats_${unit}" "$lane_dir/${unit}.idxstats.txt" samtools idxstats "$lane_bam" || true
        run_cmd_stdout "stats_${unit}" "$lane_dir/${unit}.stats.txt" samtools stats -@ "$THREADS" "$lane_bam" || true
    done < "$fastq_manifest"

    (( lanes > 0 )) || { fail_step "no_lanes" "The FASTQ manifest contained no rows"; return 1; }
    step_has_failures && { finish_step failed 1; return 1; }

    SAMPLE_ID="$sample_name"
    LANE_COUNT="$lanes"
    step_metric lane_count "$lanes" num
    step_metric sample "$SAMPLE_ID" str

    # ---- sample-level merge -------------------------------------------------
    SAMPLE_BAM="$sample_dir/${SAMPLE_ID}.sorted.bam"
    local sample_bai="${SAMPLE_BAM}.bai"
    local sample_part="$sample_dir/${SAMPLE_ID}.sorted.part.bam"
    local sample_done="$sample_dir/${SAMPLE_ID}.done"

    local sample_valid=false
    if [[ -s "$SAMPLE_BAM" && -s "$sample_bai" && -f "$sample_done" ]]; then
        if samtools quickcheck -q "$SAMPLE_BAM"; then
            sample_valid=true
        else
            warn "Existing sample BAM failed quickcheck and will be rebuilt: $SAMPLE_BAM"
        fi
    fi

    if [[ "$sample_valid" == true ]]; then
        log "  [SKIP] valid sample BAM already present: $SAMPLE_BAM"
    else
        rm -f -- "$SAMPLE_BAM" "$sample_bai" "$sample_done" "$sample_part"
        local bam
        for bam in "${lane_bams[@]}"; do
            [[ -s "$bam" ]] || { fail_step "missing_lane_bam" "Lane BAM required for merge is missing: $bam"; return 1; }
            samtools quickcheck -q "$bam" || { fail_step "invalid_lane_bam" "Lane BAM failed quickcheck: $bam"; return 1; }
        done

        if (( ${#lane_bams[@]} == 1 )); then
            # The single lane BAM already carries sample-level read groups; a
            # hard link avoids duplicating a large BAM (kept from main.sh 924-929).
            record_command "${CURRENT_STEP}/merge_single_lane" ln "${lane_bams[0]}" "$sample_part"
            ln "${lane_bams[0]}" "$sample_part" 2>/dev/null || cp -- "${lane_bams[0]}" "$sample_part"
        else
            require_cmd_ok "merge" samtools merge -@ "$THREADS" -f -o "$sample_part" "${lane_bams[@]}" \
                || { finish_step failed 1; return 1; }
        fi

        if ! samtools quickcheck -v "$sample_part" >> "$LOG_DIR/${CURRENT_STEP}.merge.stderr.log" 2>&1; then
            rm -f -- "$sample_part"
            fail_step "merge_quickcheck" "samtools quickcheck failed on the merged sample BAM"
            return 1
        fi
        mv -f -- "$sample_part" "$SAMPLE_BAM"
        require_cmd_ok "index_sample" samtools index -@ "$THREADS" "$SAMPLE_BAM" "$sample_bai" \
            || { finish_step failed 1; return 1; }
        touch -- "$sample_done"
    fi

    # One read, then both checks. The sort-order check and the SM survey used to
    # invoke samtools separately; a single header keeps them from disagreeing.
    local sample_header
    if sample_header=$(read_bam_header "$SAMPLE_BAM"); then
        if bam_header_sorted_by_coordinate "$sample_header"; then
            step_check_pass "sample_sort_order" "@HD reports SO:coordinate"
        else
            step_check_fail "sample_sort_order" "sample BAM @HD does not report SO:coordinate"
        fi

        local sm_values sm_count
        # awk and sort both read to EOF, so this pipeline was never exposed to
        # the SIGPIPE problem; it reads the saved header only to avoid a second
        # samtools invocation.
        sm_values=$(awk '/^@RG/ {for (i=1;i<=NF;i++) if ($i ~ /^SM:/) print substr($i,4)}' \
            <<< "$sample_header" | sort -u)
        sm_count=$(printf '%s\n' "$sm_values" | grep -c . || true)
        if [[ "$sm_count" == "1" && "$sm_values" == "$SAMPLE_ID" ]]; then
            step_check_pass "sample_read_group" "all read groups carry SM:${SAMPLE_ID}"
        else
            step_check_fail "sample_read_group" \
                "the merged BAM must carry exactly one SM equal to '${SAMPLE_ID}' (found: $(printf '%s' "$sm_values" | tr '\n' ' '))"
        fi
    else
        step_check_fail "sample_bam_header" \
            "samtools view -H could not read the merged sample BAM header"
    fi

    if samtools idxstats "$SAMPLE_BAM" >/dev/null 2>&1; then
        step_check_pass "sample_index" "BAM index is readable"
    else
        step_check_fail "sample_index" "BAM index missing or unreadable"
    fi

    local sample_flagstat="$sample_dir/${SAMPLE_ID}.flagstat.txt"
    run_cmd_stdout "flagstat_sample" "$sample_flagstat" samtools flagstat -@ "$THREADS" "$SAMPLE_BAM" || true
    run_cmd_stdout "stats_sample" "$sample_dir/${SAMPLE_ID}.stats.txt" samtools stats -@ "$THREADS" "$SAMPLE_BAM" || true

    if [[ -s "$sample_flagstat" ]]; then
        local total mapped_pct pp_pct
        total=$(awk 'NR==1 {print $1}' "$sample_flagstat")
        mapped_pct=$(grep -m1 ' mapped (' "$sample_flagstat" | sed -n 's/.*(\([0-9.]*\)%.*/\1/p') || true
        pp_pct=$(grep -m1 'properly paired (' "$sample_flagstat" | sed -n 's/.*(\([0-9.]*\)%.*/\1/p') || true
        [[ -n "$total" ]] && step_metric total_alignment_records "$total" num
        [[ -n "$mapped_pct" ]] && step_metric mapped_pct "$mapped_pct" num
        [[ -n "$pp_pct" ]] && step_metric properly_paired_pct "$pp_pct" num
    fi

    step_has_failures && { finish_step failed 1; return 1; }

    step_output sample_bam "$SAMPLE_BAM"
    step_output sample_bai "$sample_bai"
    add_artifact aligned_bam "Coordinate-sorted sample BAM" "$SAMPLE_BAM" 1 0 "Merged, coordinate-sorted alignment"
    add_artifact aligned_bai "Sample BAM index" "$sample_bai" 1 0 "BAI index"
    add_artifact sample_qc "Sample flagstat" "$sample_flagstat" 1 0 "samtools flagstat for the merged BAM"

    # Explicit hand-off so 04_processing never guesses a path.
    local align_json="$stage_dir/alignment_output.json"
    "$(resolve_python)" - "$align_json" "$RUN_DIR" "$SAMPLE_ID" "$SAMPLE_BAM" "$sample_bai" "$LANE_COUNT" <<'PYALIGN'
import json, os, sys
out_path, run_dir, sample, bam, bai, lane_count = sys.argv[1:7]


def rel(p):
    try:
        return os.path.relpath(p, run_dir).replace(os.sep, "/")
    except ValueError:
        return p


doc = {"sample": sample, "lane_count": int(lane_count),
       "sample_bam": bam, "sample_bai": bai,
       "sample_bam_relative": rel(bam), "sample_bai_relative": rel(bai),
       "sort_order": "coordinate", "next_step_ready": True}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
PYALIGN
    step_output alignment_output "$align_json"

    complete_step
}

# ---------------------------------------------------------------------------
# classify_validation — read a Picard ValidateSamFile SUMMARY report and return
# one of: CLEAN | ONLY_NM | OTHER:<types> | UNPARSEABLE
#
# Used by the NM/MD policy in run_processing. It never guesses: an output it
# cannot classify is reported as UNPARSEABLE so the caller can fail loudly
# instead of applying a silent repair.
# ---------------------------------------------------------------------------
classify_validation() {
    "$(resolve_python)" - "$1" <<'PYCLASS' | tr -d '\r'
import os, re, sys
path = sys.argv[1]
if not os.path.isfile(path) or os.path.getsize(path) == 0:
    print("UNPARSEABLE"); sys.exit(0)
text = open(path, encoding="utf-8", errors="replace").read()
if re.search(r"No errors found", text):
    print("CLEAN"); sys.exit(0)
error_types = set(re.findall(r"^ERROR:(\w+)", text, re.MULTILINE))
warn_types = set(re.findall(r"^WARNING:(\w+)", text, re.MULTILINE))
if not error_types and not warn_types:
    print("UNPARSEABLE"); sys.exit(0)
if not error_types:
    print("CLEAN"); sys.exit(0)
if error_types == {"INVALID_TAG_NM"}:
    print("ONLY_NM"); sys.exit(0)
print("OTHER:" + ",".join(sorted(error_types)))
PYCLASS
}

# ---------------------------------------------------------------------------
# 04_processing
#
# [ORIGIN] Processing source section 7 steps 02-06 — the same code is present
#   verbatim in the previous main.sh lines 1097-1193.
# [KEEP_WITH_INTERFACE_PATCH] Preserved: MarkDuplicates with
#   --REMOVE_DUPLICATES false --CREATE_INDEX false and the optional
#   --READ_NAME_REGEX null switch; duplicate metrics; samtools calmd for NM/MD;
#   ValidateSamFile -MODE SUMMARY; BaseRecalibrator with the bundle's
#   known-sites; ApplyBQSR deliberately WITHOUT -L so reads outside the target
#   intervals are preserved; optional before/after BQSR diagnostics; flagstat
#   and stats on both BAMs; the ApplyBQSR record-count preservation check;
#   `.part` output then atomic rename; samtools quickcheck.
# [NOT taken from the source] raw FastQC, BWA-MEM, coordinate sort (already
#   done by run_alignment), the HG002/SRR2962669 defaults, the personal project
#   root and the `latest_v5` symlink.
#
# NM/MD policy:
#   1. ValidateSamFile the MarkDuplicates BAM.
#   2. No ERROR                       -> continue to BQSR, no calmd.
#   3. ERRORs are only INVALID_TAG_NM -> run calmd, re-validate, continue only
#                                        if the re-validation is clean.
#   4. Any other ERROR type           -> fail.
#   5. Report cannot be classified    -> fail. Never repair silently.
# ---------------------------------------------------------------------------
run_processing() {
    start_step 04_processing
    local stage_dir="$RUN_DIR/04_processing"
    local qc_dir="$stage_dir/qc"
    local tmp_dir="$TMP_ROOT/04_processing"
    mkdir -p -- "$stage_dir" "$qc_dir" "$tmp_dir"

    local align_json="$RUN_DIR/03_alignment/alignment_output.json"
    [[ -s "$align_json" ]] || { fail_step "missing_alignment_output" "03_alignment did not publish alignment_output.json"; return 1; }
    step_input alignment_output "$align_json"

    SAMPLE_ID=$(json_get "$align_json" sample)
    SAMPLE_BAM=$(json_get "$align_json" sample_bam)
    [[ -s "$SAMPLE_BAM" ]] || { fail_step "missing_input_bam" "Sample BAM from 03_alignment is missing: $SAMPLE_BAM"; return 1; }
    step_input sample_bam "$SAMPLE_BAM"
    step_input reference_fasta "$REF_FASTA"

    if (( ${#KNOWN_SITES[@]} == 0 )); then
        fail_step "missing_known_sites" "BQSR is a core step and the resource bundle declares no known_sites."
        return 1
    fi
    local ks known_site_args=()
    for ks in "${KNOWN_SITES[@]}"; do
        [[ -s "$ks" ]] || { fail_step "missing_known_sites" "known_sites entry not found: $ks"; return 1; }
        step_input known_sites "$ks"
        known_site_args+=(--known-sites "$ks")
    done

    local java_opts="-Xmx${JAVA_MEM_GB}g -Djava.io.tmpdir=${tmp_dir}"
    local markdup_bam="$stage_dir/${SAMPLE_ID}.markdup.bam"
    local markdup_part="$stage_dir/${SAMPLE_ID}.markdup.part.bam"
    local markdup_nm_part="$stage_dir/${SAMPLE_ID}.markdup.nmfix.part.bam"
    local markdup_metrics="$stage_dir/${SAMPLE_ID}.markdup.metrics.txt"
    local recal_table="$stage_dir/${SAMPLE_ID}.recal_data.table"
    local recal_part="$stage_dir/${SAMPLE_ID}.recal_data.part.table"
    local recal_after="$stage_dir/${SAMPLE_ID}.recal_data.after.table"
    ANALYSIS_READY_BAM="$stage_dir/${SAMPLE_ID}.analysis_ready.bam"
    local final_part="$stage_dir/${SAMPLE_ID}.analysis_ready.part.bam"

    # ---- optical-duplicate mode from the first query name -------------------
    local read_name_regex_args=() first_qname="" read_name_mode
    set +o pipefail
    first_qname=$(samtools view "$SAMPLE_BAM" 2>/dev/null | head -n 1 | cut -f1 || true)
    set -o pipefail
    if [[ -n "$first_qname" ]]; then
        if [[ "$first_qname" =~ ^[^:]+:[0-9]+:[^:]+:[0-9]+:[0-9]+:[0-9]+:[0-9]+ ]]; then
            read_name_mode="illumina_coordinates"
        else
            read_name_mode="no_coordinates"
            read_name_regex_args=(--READ_NAME_REGEX null)
        fi
    else
        read_name_mode="unknown"
        step_warning "READ_NAME_MODE_UNKNOWN" "Could not read the first query name from the BAM" \
            "MarkDuplicates uses the Picard default optical-duplicate regex" "true"
    fi
    step_metric read_name_mode "$read_name_mode" str

    # ---- MarkDuplicates -----------------------------------------------------
    rm -f -- "$markdup_part"
    require_cmd_ok "markduplicates" \
        gatk --java-options "$java_opts" MarkDuplicates \
            -I "$SAMPLE_BAM" -O "$markdup_part" -M "$markdup_metrics" \
            --REMOVE_DUPLICATES false --CREATE_INDEX false \
            ${read_name_regex_args[@]+"${read_name_regex_args[@]}"} \
            --TMP_DIR "$tmp_dir" \
        || { finish_step failed 1; return 1; }

    if ! samtools quickcheck -v "$markdup_part" >> "$LOG_DIR/${CURRENT_STEP}.markduplicates.stderr.log" 2>&1; then
        rm -f -- "$markdup_part"
        fail_step "markdup_quickcheck" "samtools quickcheck failed on the MarkDuplicates output"
        return 1
    fi
    mv -f -- "$markdup_part" "$markdup_bam"
    step_check_pass "markduplicates" "duplicates flagged, not removed (--REMOVE_DUPLICATES false)"

    if [[ -s "$markdup_metrics" ]]; then
        local dup_pct
        dup_pct=$("$(resolve_python)" - "$markdup_metrics" <<'PYDUP'
import sys
lines = [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8") if l.strip() and not l.startswith("#")]
for i, line in enumerate(lines):
    if line.startswith("LIBRARY") and i + 1 < len(lines):
        row = dict(zip(line.split("\t"), lines[i + 1].split("\t")))
        print(row.get("PERCENT_DUPLICATION", ""))
        break
PYDUP
)
        [[ -n "$dup_pct" ]] && step_metric percent_duplication "$dup_pct" num
    fi
    add_artifact markdup_metrics "MarkDuplicates metrics" "$markdup_metrics" 1 0 "Picard duplicate metrics"

    # ---- ValidateSamFile and conditional NM/MD repair -----------------------
    local validate_1="$qc_dir/${SAMPLE_ID}.markdup.validation.txt"
    run_cmd "validate_markdup" gatk --java-options "-Xmx4g" ValidateSamFile \
        -I "$markdup_bam" -R "$REF_FASTA" -MODE SUMMARY -O "$validate_1" || true
    local class_1
    class_1=$(classify_validation "$validate_1")
    step_metric markdup_validation "$class_1" str
    add_artifact validation_report "MarkDuplicates BAM validation" "$validate_1" 1 0 \
        "Picard ValidateSamFile SUMMARY (before any NM/MD repair)"

    local nm_repaired=false
    case "$class_1" in
        CLEAN)
            step_check_pass "bam_validation" "ValidateSamFile reported no errors; NM/MD repair not required"
            ;;
        ONLY_NM)
            log "  ValidateSamFile reported only INVALID_TAG_NM; running samtools calmd against the same reference."
            rm -f -- "$markdup_nm_part"
            local calmd_log="$LOG_DIR/${CURRENT_STEP}.calmd.stderr.log" rc=0
            record_command "${CURRENT_STEP}/calmd" samtools calmd -@ "$THREADS" -b "$markdup_bam" "$REF_FASTA"
            if samtools calmd -@ "$THREADS" -b "$markdup_bam" "$REF_FASTA" > "$markdup_nm_part" 2> "$calmd_log"; then
                rc=0
            else
                rc=$?
            fi
            if (( rc != 0 )); then
                rm -f -- "$markdup_nm_part"
                fail_step "calmd_failed" "samtools calmd exited with code $rc; see logs/${CURRENT_STEP}.calmd.stderr.log"
                return 1
            fi
            if ! samtools quickcheck -v "$markdup_nm_part" >> "$calmd_log" 2>&1; then
                rm -f -- "$markdup_nm_part"
                fail_step "calmd_quickcheck" "samtools quickcheck failed on the calmd output"
                return 1
            fi
            mv -f -- "$markdup_nm_part" "$markdup_bam"
            nm_repaired=true

            local validate_2="$qc_dir/${SAMPLE_ID}.markdup.validation.after_calmd.txt" class_2
            run_cmd "validate_markdup_after_calmd" gatk --java-options "-Xmx4g" ValidateSamFile \
                -I "$markdup_bam" -R "$REF_FASTA" -MODE SUMMARY -O "$validate_2" || true
            class_2=$(classify_validation "$validate_2")
            step_metric markdup_validation_after_calmd "$class_2" str
            add_artifact validation_report "BAM validation after NM/MD repair" "$validate_2" 1 0 \
                "Picard ValidateSamFile SUMMARY (after samtools calmd)"
            if [[ "$class_2" == "CLEAN" ]]; then
                step_check_pass "bam_validation" "INVALID_TAG_NM resolved by samtools calmd; re-validation is clean"
                step_warning "NM_MD_REPAIRED" "NM and MD tags were recalculated with samtools calmd" \
                    "Only the NM and MD tags changed; read sequence, CIGAR, coordinates and duplicate flags are preserved" "true"
            else
                fail_step "bam_validation" \
                    "ValidateSamFile still reports problems after calmd (classification: $class_2). Refusing to continue."
                return 1
            fi
            ;;
        UNPARSEABLE)
            fail_step "bam_validation" \
                "Could not classify the ValidateSamFile output. Refusing to apply a silent NM/MD repair; inspect $validate_1."
            return 1
            ;;
        OTHER:*)
            fail_step "bam_validation" \
                "ValidateSamFile reported error types that NM/MD repair cannot fix: ${class_1#OTHER:}. Inspect $validate_1."
            return 1
            ;;
        *)
            fail_step "bam_validation" "Unexpected validation classification: $class_1"
            return 1
            ;;
    esac
    step_metric nm_md_repaired "$nm_repaired" str

    require_cmd_ok "index_markdup" samtools index -@ "$THREADS" "$markdup_bam" \
        || { finish_step failed 1; return 1; }

    local markdup_flagstat="$qc_dir/${SAMPLE_ID}.markdup.flagstat.txt"
    run_cmd_stdout "flagstat_markdup" "$markdup_flagstat" samtools flagstat -@ "$THREADS" "$markdup_bam" || true
    run_cmd_stdout "stats_markdup" "$qc_dir/${SAMPLE_ID}.markdup.stats.txt" samtools stats -@ "$THREADS" "$markdup_bam" || true

    # ---- BQSR ---------------------------------------------------------------
    local bqsr_interval_args=()
    if [[ "$BQSR_TARGET_ONLY" == "true" ]]; then
        [[ -s "$TARGET_BED" ]] || { fail_step "missing_target_bed" "bqsr_target_only=true but target_bed is missing"; return 1; }
        bqsr_interval_args=(-L "$TARGET_BED" -ip "$INTERVAL_PADDING")
    fi

    rm -f -- "$recal_part"
    require_cmd_ok "base_recalibrator" \
        gatk --java-options "$java_opts" BaseRecalibrator \
            -R "$REF_FASTA" -I "$markdup_bam" \
            "${known_site_args[@]}" \
            ${bqsr_interval_args[@]+"${bqsr_interval_args[@]}"} \
            -O "$recal_part" --tmp-dir "$tmp_dir" \
        || { finish_step failed 1; return 1; }

    if ! grep -q 'RecalTable0' "$recal_part" 2>/dev/null; then
        rm -f -- "$recal_part"
        fail_step "recal_table" "BaseRecalibrator output does not contain RecalTable0"
        return 1
    fi
    mv -f -- "$recal_part" "$recal_table"
    step_check_pass "base_recalibrator" "recalibration table contains RecalTable0"
    add_artifact recal_table "BQSR recalibration table" "$recal_table" 1 0 "BaseRecalibrator model"

    # No -L here: ApplyBQSR must preserve the complete BAM rather than emit only
    # interval-overlapping reads. (Intent kept from the Processing source.)
    rm -f -- "$final_part"
    require_cmd_ok "apply_bqsr" \
        gatk --java-options "$java_opts" ApplyBQSR \
            -R "$REF_FASTA" -I "$markdup_bam" --bqsr-recal-file "$recal_table" \
            -O "$final_part" --create-output-bam-index false --tmp-dir "$tmp_dir" \
        || { finish_step failed 1; return 1; }

    if ! samtools quickcheck -v "$final_part" >> "$LOG_DIR/${CURRENT_STEP}.apply_bqsr.stderr.log" 2>&1; then
        rm -f -- "$final_part"
        fail_step "apply_bqsr_quickcheck" "samtools quickcheck failed on the ApplyBQSR output"
        return 1
    fi
    # ---- index and validate BEFORE publishing the final name  (AUD-HIGH-002)
    #
    # The BAM keeps its `.part` name until its index exists and every check has
    # passed. A failed step therefore never leaves a file that looks like a
    # finished analysis-ready BAM.
    require_cmd_ok "index_analysis_ready" samtools index -@ "$THREADS" "$final_part" \
        || { finish_step failed 1; return 1; }

    local final_flagstat="$qc_dir/${SAMPLE_ID}.analysis_ready.flagstat.txt"
    run_cmd_stdout "flagstat_final" "$final_flagstat" samtools flagstat -@ "$THREADS" "$final_part" || true
    run_cmd_stdout "stats_final" "$qc_dir/${SAMPLE_ID}.analysis_ready.stats.txt" samtools stats -@ "$THREADS" "$final_part" || true

    local validate_final="$qc_dir/${SAMPLE_ID}.analysis_ready.validation.txt" class_final
    run_cmd "validate_analysis_ready" gatk --java-options "-Xmx4g" ValidateSamFile \
        -I "$final_part" -R "$REF_FASTA" -MODE SUMMARY -O "$validate_final" || true
    class_final=$(classify_validation "$validate_final")
    add_artifact validation_report "Analysis-ready BAM validation" "$validate_final" 1 0 "Picard ValidateSamFile SUMMARY"
    if [[ "$class_final" == "CLEAN" ]]; then
        step_check_pass "analysis_ready_validation" "ValidateSamFile reported no errors"
    else
        step_check_fail "analysis_ready_validation" "analysis-ready BAM failed validation: $class_final"
    fi

    # ---- ApplyBQSR record-count preservation -------------------------------
    local markdup_total final_total
    markdup_total=$(awk 'NR==1 {print $1}' "$markdup_flagstat" 2>/dev/null || echo "")
    final_total=$(awk 'NR==1 {print $1}' "$final_flagstat" 2>/dev/null || echo "")
    if [[ -n "$markdup_total" && "$markdup_total" == "$final_total" ]]; then
        step_check_pass "applybqsr_record_preservation" "before=$markdup_total after=$final_total"
    else
        step_check_fail "applybqsr_record_preservation" \
            "record count changed across ApplyBQSR: before=${markdup_total:-NA} after=${final_total:-NA}"
    fi
    [[ -n "$final_total" ]] && step_metric analysis_ready_records "$final_total" num

    local final_header
    if final_header=$(read_bam_header "$final_part"); then
        if bam_header_has_sample "$final_header" "$SAMPLE_ID"; then
            step_check_pass "read_group_sample" "SM:${SAMPLE_ID} present"
        else
            step_check_fail "read_group_sample" "SM:${SAMPLE_ID} missing from the analysis-ready BAM"
        fi
    else
        step_check_fail "analysis_ready_bam_header" \
            "samtools view -H could not read the analysis-ready BAM header"
    fi

    # Publish only now: body and index together, and only if nothing failed.
    if step_has_failures; then
        warn "Analysis-ready BAM was not published; failed output is quarantined at $final_part"
        finish_step failed 1
        return 1
    fi
    mv -f -- "${final_part}.bai" "${ANALYSIS_READY_BAM}.bai"
    mv -f -- "$final_part" "$ANALYSIS_READY_BAM"

    # ---- optional BQSR diagnostics — never fails the step -------------------
    if [[ "$BQSR_DIAGNOSTICS" == "true" ]]; then
        if have_command Rscript; then
            local rc2=0
            run_cmd "recal_after" \
                gatk --java-options "$java_opts" BaseRecalibrator \
                    -R "$REF_FASTA" -I "$ANALYSIS_READY_BAM" \
                    "${known_site_args[@]}" ${bqsr_interval_args[@]+"${bqsr_interval_args[@]}"} \
                    -O "$recal_after" --tmp-dir "$tmp_dir" || rc2=$?
            if (( rc2 == 0 )) && [[ -s "$recal_after" ]]; then
                run_optional_cmd "analyze_covariates" \
                    gatk --java-options "$java_opts" AnalyzeCovariates \
                        -before "$recal_table" -after "$recal_after" \
                        -csv "$qc_dir/${SAMPLE_ID}.bqsr_covariates.csv" \
                        -plots "$qc_dir/${SAMPLE_ID}.bqsr_covariates.pdf"
                add_artifact bqsr_diagnostics "BQSR covariates plot" \
                    "$qc_dir/${SAMPLE_ID}.bqsr_covariates.pdf" 1 0 "Optional before/after BQSR diagnostic plot"
            else
                step_warning "BQSR_DIAG_FAILED" "Post-recalibration BaseRecalibrator exited with code $rc2" \
                    "The diagnostic plot is missing; recalibration itself is unaffected" "true"
            fi
        else
            step_warning "RSCRIPT_MISSING" "Rscript is not installed; the BQSR diagnostic plot is skipped" \
                "Core recalibration is unaffected" "true"
        fi
    fi

    step_has_failures && { finish_step failed 1; return 1; }

    step_output analysis_ready_bam "$ANALYSIS_READY_BAM"
    step_output analysis_ready_bai "${ANALYSIS_READY_BAM}.bai"
    add_artifact analysis_ready_bam "Analysis-ready BAM" "$ANALYSIS_READY_BAM" 1 1 \
        "Duplicate-flagged, base-recalibrated alignment"
    add_artifact analysis_ready_bai "Analysis-ready BAM index" "${ANALYSIS_READY_BAM}.bai" 1 1 "BAI index"
    add_artifact markdup_bam "MarkDuplicates BAM" "$markdup_bam" 0 0 "Intermediate duplicate-flagged BAM"
    add_artifact bam_qc "Analysis-ready flagstat" "$final_flagstat" 1 0 "samtools flagstat"

    local proc_json="$stage_dir/processing_output.json"
    "$(resolve_python)" - "$proc_json" "$RUN_DIR" "$SAMPLE_ID" "$ANALYSIS_READY_BAM" \
        "${ANALYSIS_READY_BAM}.bai" "$nm_repaired" <<'PYPROC'
import json, os, sys
out_path, run_dir, sample, bam, bai, nm_repaired = sys.argv[1:7]


def rel(p):
    try:
        return os.path.relpath(p, run_dir).replace(os.sep, "/")
    except ValueError:
        return p


doc = {"sample": sample, "analysis_ready_bam": bam, "analysis_ready_bai": bai,
       "analysis_ready_bam_relative": rel(bam),
       "nm_md_repaired": nm_repaired == "true",
       "duplicates_removed": False, "next_step_ready": True}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
PYPROC
    step_output processing_output "$proc_json"

    complete_step
}

# ---------------------------------------------------------------------------
# 05_coverage_qc
#
# [ORIGIN] Processing source (mosdepth call and metric derivation; also present
#   in the previous main.sh lines 1191-1193 and 1311-1333).
# [MERGE_BEST_PARTS] A second coverage implementation existed at lines
#   1403-1565. Its mosdepth call used --quantize; the --thresholds form is kept
#   because the >=Nx percentages feed the metrics contract directly and only
#   this form applies a MAPQ filter.
# [REMOVED confirmed errors from that second implementation]
#   - the breast-cancer 8-gene BED fallback (lines 1461-1479), which silently
#     replaced a whole-exome target with ~0.4 Mb of gene intervals and then
#     reported the result as exome coverage
#   - `find ... | head -1` discovery of a *.recal.bam (line 1448)
#   - `conda install -c bioconda mosdepth -y` (line 1519)
#   - `exit 2` on low mean depth (line 1562), which turned a QC observation
#     into a pipeline failure
# [POLICY] Low coverage is a WARNING and never fails the step. Mean depth alone
#   is not a pass/fail gate; breadth at several depths is reported beside it.
# [METRIC HONESTY] mosdepth runs with --no-per-base, so a true per-base MEDIAN
#   depth is not available and is therefore not reported.
# ---------------------------------------------------------------------------
run_coverage_qc() {
    start_step 05_coverage_qc
    local stage_dir="$RUN_DIR/05_coverage_qc"
    mkdir -p -- "$stage_dir"

    local proc_json="$RUN_DIR/04_processing/processing_output.json"
    [[ -s "$proc_json" ]] || { fail_step "missing_processing_output" "04_processing did not publish processing_output.json"; return 1; }
    step_input processing_output "$proc_json"

    SAMPLE_ID=$(json_get "$proc_json" sample)
    ANALYSIS_READY_BAM=$(json_get "$proc_json" analysis_ready_bam)
    [[ -s "$ANALYSIS_READY_BAM" ]] || { fail_step "missing_bam" "Analysis-ready BAM is missing: $ANALYSIS_READY_BAM"; return 1; }
    step_input analysis_ready_bam "$ANALYSIS_READY_BAM"

    samtools quickcheck -q "$ANALYSIS_READY_BAM" \
        || { fail_step "bam_invalid" "samtools quickcheck failed on the analysis-ready BAM"; return 1; }

    [[ -s "$COVERAGE_BED" ]] || { fail_step "missing_coverage_bed" "coverage_bed is required for WES coverage QC and is missing: $COVERAGE_BED"; return 1; }
    step_input coverage_bed "$COVERAGE_BED"

    local merged_bed="$stage_dir/coverage.nonoverlap.bed"
    local prefix="$stage_dir/${SAMPLE_ID}.mosdepth"
    local bam_contigs="$STEP_WORK/bam_contigs.txt"
    local bed_check="$stage_dir/coverage_bed_check.txt"

    samtools view -H "$ANALYSIS_READY_BAM" \
        | awk '/^@SQ/ {for (i=1;i<=NF;i++) if ($i ~ /^SN:/) print substr($i,4)}' > "$bam_contigs"

    local rc=0
    set +e
    "$(resolve_python)" - "$COVERAGE_BED" "${REF_FASTA}.fai" "$merged_bed" "$bam_contigs" > "$bed_check" 2>&1 <<'PYMERGE'
import sys
from collections import defaultdict
coverage_bed, fai, out, bam_contigs_path = sys.argv[1:5]

order = {}
with open(fai, encoding="utf-8") as fh:
    for i, line in enumerate(fh):
        if line.strip():
            order[line.split("\t")[0]] = i

bam_contigs = {l.strip() for l in open(bam_contigs_path, encoding="utf-8") if l.strip()}

ivs = defaultdict(list)
bed_contigs = set()
with open(coverage_bed, encoding="utf-8") as fh:
    for line_no, line in enumerate(fh, 1):
        if not line.strip() or line.startswith(("#", "track", "browser")):
            continue
        f = line.rstrip().split("\t")
        if len(f) < 3:
            print(f"[ERROR] BED line {line_no}: fewer than 3 columns"); sys.exit(2)
        try:
            s, e = int(f[1]), int(f[2])
        except ValueError:
            print(f"[ERROR] BED line {line_no}: start/end are not integers"); sys.exit(2)
        bed_contigs.add(f[0]); ivs[f[0]].append((s, e))

if not ivs:
    print("[ERROR] coverage BED contains no usable intervals"); sys.exit(2)

missing = sorted(bed_contigs - bam_contigs)
if bam_contigs and missing:
    print(f"[ERROR] coverage BED contigs absent from the BAM header: {missing[:10]}"); sys.exit(2)

merged_rows = merged_bases = 0
with open(out, "w", encoding="utf-8") as w:
    for chrom in sorted(ivs, key=lambda c: (order.get(c, 10 ** 9), c)):
        merged = []
        for s, e in sorted(ivs[chrom]):
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            elif e > merged[-1][1]:
                merged[-1][1] = e
        for s, e in merged:
            w.write(f"{chrom}\t{s}\t{e}\n")
            merged_rows += 1; merged_bases += e - s

print("[OK] non-overlapping coverage BED created")
print(f"METRIC coverage_intervals={merged_rows}")
print(f"METRIC coverage_nonoverlap_bases={merged_bases}")
PYMERGE
    rc=$?
    set -e
    cat "$bed_check" || true
    if (( rc != 0 )); then
        fail_step "coverage_bed_invalid" "Coverage BED / BAM contig validation failed; see 05_coverage_qc/coverage_bed_check.txt"
        return 1
    fi
    step_check_pass "coverage_bed" "coverage BED intervals are valid and its contigs exist in the BAM header"

    local key value
    while IFS='=' read -r key value; do
        [[ -n "$key" ]] && step_metric "$key" "$value" num
    done < <(grep '^METRIC ' "$bed_check" | sed 's/^METRIC //')

    require_cmd_ok "mosdepth" \
        mosdepth --threads "$THREADS" --no-per-base --mapq "$MOSDEPTH_MAPQ" \
            --by "$merged_bed" --thresholds 1,10,20,30,50,100 \
            "$prefix" "$ANALYSIS_READY_BAM" \
        || { finish_step failed 1; return 1; }

    local regions_gz="${prefix}.regions.bed.gz"
    local thresh_gz="${prefix}.thresholds.bed.gz"
    local summary_txt="${prefix}.mosdepth.summary.txt"
    local required
    for required in "$regions_gz" "$thresh_gz"; do
        [[ -s "$required" ]] || { fail_step "missing_mosdepth_output" "mosdepth did not produce: $required"; return 1; }
    done
    step_check_pass "mosdepth_outputs" "regions and thresholds output present"

    local coverage_json="$stage_dir/coverage_metrics.json"
    local low_cov_bed="$stage_dir/low_coverage_intervals.bed"

    set +e
    "$(resolve_python)" - "$regions_gz" "$thresh_gz" "$coverage_json" "$low_cov_bed" "$LOW_COVERAGE_DEPTH" <<'PYCOV'
import gzip, json, os, re, sys
regions, thresholds, out_json, low_bed, low_depth = sys.argv[1:6]
low_depth = float(low_depth)
metrics = {}

bases = 0
depth_bases = 0.0
low_intervals = low_bases = uncovered_intervals = uncovered_bases = 0

with gzip.open(regions, "rt") as fh, open(low_bed, "w", encoding="utf-8") as lw:
    for line in fh:
        if not line.strip() or line.startswith("#"):
            continue
        f = line.rstrip().split("\t")
        length = int(f[2]) - int(f[1])
        depth = float(f[-1])
        bases += length
        depth_bases += length * depth
        if depth == 0.0:
            uncovered_intervals += 1; uncovered_bases += length
        if depth < low_depth:
            low_intervals += 1; low_bases += length
            lw.write(f"{f[0]}\t{f[1]}\t{f[2]}\t{depth}\n")

if bases:
    metrics["target_nonoverlap_bases"] = bases
    metrics["mean_target_depth"] = round(depth_bases / bases, 4)
    metrics["low_coverage_bases_pct"] = round(100.0 * low_bases / bases, 4)
    metrics["uncovered_bases_pct"] = round(100.0 * uncovered_bases / bases, 4)
metrics["low_coverage_threshold_x"] = low_depth
metrics["low_coverage_intervals"] = low_intervals
metrics["low_coverage_bases"] = low_bases
metrics["uncovered_intervals"] = uncovered_intervals
metrics["uncovered_bases"] = uncovered_bases

names, idx, sums, total = [], [], [], 0
with gzip.open(thresholds, "rt") as fh:
    for line in fh:
        f = line.rstrip().split("\t")
        if line.startswith("#"):
            for i, c in enumerate(f):
                if re.fullmatch(r"\d+X", c.strip()):
                    idx.append(i); names.append(c.strip())
            sums = [0] * len(idx)
            continue
        if not idx:
            continue
        total += int(f[2]) - int(f[1])
        for j, i in enumerate(idx):
            sums[j] += int(f[i])
if total:
    for name, n in zip(names, sums):
        metrics[f"target_bases_ge_{name}_pct"] = round(100.0 * n / total, 4)

# A per-base median is intentionally absent: mosdepth ran with --no-per-base,
# so per-base depths were never materialised. Reporting one would be invented.
metrics["median_target_depth"] = None
metrics["median_note"] = ("not computed: mosdepth runs with --no-per-base, "
                          "so per-base depths are unavailable")

tmp = out_json + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(metrics, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_json)
PYCOV
    rc=$?
    set -e
    if (( rc != 0 )) || [[ ! -s "$coverage_json" ]]; then
        fail_step "coverage_metrics" "Could not derive coverage metrics from the mosdepth output"
        return 1
    fi

    while IFS='=' read -r key value; do
        [[ -n "$key" ]] && step_metric "$key" "$value" num
    done < <("$(resolve_python)" - "$coverage_json" <<'PYEMIT'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
for k, v in doc.items():
    if isinstance(v, (int, float)):
        print(f"{k}={v}")
PYEMIT
)

    local mean_depth ge20 ge30 uncovered_pct
    mean_depth=$(json_get "$coverage_json" mean_target_depth 0)
    ge20=$(json_get "$coverage_json" target_bases_ge_20X_pct 0)
    ge30=$(json_get "$coverage_json" target_bases_ge_30X_pct 0)
    uncovered_pct=$(json_get "$coverage_json" uncovered_bases_pct 0)
    log "  mean target depth ${mean_depth}x | >=20x ${ge20}% | >=30x ${ge30}% | uncovered ${uncovered_pct}%"

    if [[ "$COVERAGE_MIN_MEAN_DEPTH" != "0" ]]; then
        if awk -v a="$mean_depth" -v b="$COVERAGE_MIN_MEAN_DEPTH" 'BEGIN {exit !(a < b)}'; then
            step_warning "LOW_MEAN_COVERAGE" \
                "mean target depth ${mean_depth}x is below the configured reference value ${COVERAGE_MIN_MEAN_DEPTH}x" \
                "Variant sensitivity may be reduced in low-coverage targets; the run continues and variant calling proceeds" \
                "true"
        else
            step_check_pass "mean_coverage" "mean target depth ${mean_depth}x (configured reference ${COVERAGE_MIN_MEAN_DEPTH}x)"
        fi
    else
        step_check_pass "mean_coverage" "mean target depth ${mean_depth}x (no configured pass/fail threshold)"
    fi

    if awk -v v="$uncovered_pct" 'BEGIN {exit !(v > 0)}'; then
        step_warning "UNCOVERED_TARGETS" "${uncovered_pct}% of non-overlapping target bases have zero coverage" \
            "Variants cannot be called in uncovered intervals; see 05_coverage_qc/low_coverage_intervals.bed" "true"
    fi

    step_output coverage_metrics "$coverage_json"
    step_output merged_coverage_bed "$merged_bed"
    add_artifact coverage_metrics "Coverage metrics" "$coverage_json" 1 0 \
        "Mean target depth and breadth at 1/10/20/30/50/100x"
    add_artifact coverage_regions "mosdepth regions" "$regions_gz" 1 0 "Per-target mean depth"
    add_artifact coverage_thresholds "mosdepth thresholds" "$thresh_gz" 1 0 "Bases at or above each depth threshold"
    add_artifact low_coverage_bed "Low-coverage intervals" "$low_cov_bed" 1 0 \
        "Target intervals whose mean depth is below the configured low-coverage depth"
    [[ -s "$summary_txt" ]] && add_artifact coverage_summary "mosdepth summary" "$summary_txt" 1 0 "mosdepth summary table"

    complete_step
}

# ---------------------------------------------------------------------------
# 06_variant_calling
#
# [ORIGIN] Processing source section 7 steps 08-09 and section 8 (also in the
#   previous main.sh lines 1195-1212 and 1262-1285).
# [KEEP_WITH_INTERFACE_PATCH] Preserved: HaplotypeCaller with -ERC GVCF, -L and
#   -ip, --native-pair-hmm-threads; `.part` output then atomic rename including
#   the .tbi companion; tabix fallback when no index was emitted; GenotypeGVCFs
#   over the same intervals; VCF header parse validation; index readability;
#   VCF sample-column identity against the read-group SM; non-zero record
#   count; REF-allele agreement via `bcftools norm -c e`; `bcftools stats`.
# [INTERFACE] The message that used to name one hard-coded reference in "all REF
#   alleles match <reference>" now names the assembly declared in the bundle, so
#   another bundle needs no code change.
# [SCOPE] raw VCF is the core completion point. Hard filtering is deliberately
#   not performed here; see run_filtering and the preservation document.
# ---------------------------------------------------------------------------
run_variant_calling() {
    start_step 06_variant_calling
    local stage_dir="$RUN_DIR/06_variant_calling"
    local tmp_dir="$TMP_ROOT/06_variant_calling"
    mkdir -p -- "$stage_dir" "$tmp_dir"

    local proc_json="$RUN_DIR/04_processing/processing_output.json"
    [[ -s "$proc_json" ]] || { fail_step "missing_processing_output" "04_processing did not publish processing_output.json"; return 1; }
    step_input processing_output "$proc_json"

    SAMPLE_ID=$(json_get "$proc_json" sample)
    ANALYSIS_READY_BAM=$(json_get "$proc_json" analysis_ready_bam)
    [[ -s "$ANALYSIS_READY_BAM" ]] || { fail_step "missing_bam" "Analysis-ready BAM is missing: $ANALYSIS_READY_BAM"; return 1; }
    samtools quickcheck -q "$ANALYSIS_READY_BAM" \
        || { fail_step "bam_invalid" "samtools quickcheck failed on the analysis-ready BAM; variant calling will not run"; return 1; }
    step_input analysis_ready_bam "$ANALYSIS_READY_BAM"
    step_input reference_fasta "$REF_FASTA"
    step_input target_bed "$TARGET_BED"

    local java_opts="-Xmx${JAVA_MEM_GB}g -Djava.io.tmpdir=${tmp_dir}"
    GVCF="$stage_dir/${SAMPLE_ID}.g.vcf.gz"
    local gvcf_part="$stage_dir/${SAMPLE_ID}.part.g.vcf.gz"
    RAW_VCF="$stage_dir/${SAMPLE_ID}.raw.vcf.gz"
    local raw_part="$stage_dir/${SAMPLE_ID}.raw.part.vcf.gz"

    rm -f -- "$gvcf_part" "${gvcf_part}.tbi"
    require_cmd_ok "haplotypecaller" \
        gatk --java-options "$java_opts" HaplotypeCaller \
            -R "$REF_FASTA" -I "$ANALYSIS_READY_BAM" -ERC GVCF \
            -L "$TARGET_BED" -ip "$INTERVAL_PADDING" \
            --native-pair-hmm-threads "$PAIRHMM_THREADS" \
            -O "$gvcf_part" --tmp-dir "$tmp_dir" \
        || { finish_step failed 1; return 1; }

    [[ -s "$gvcf_part" ]] || { fail_step "gvcf_missing" "HaplotypeCaller produced no gVCF"; return 1; }

    # AUD-HIGH-002: index while still named `.part`, then publish body+index
    # together, so a failure never leaves a final-looking gVCF without an index.
    if [[ ! -s "${gvcf_part}.tbi" ]]; then
        require_cmd_ok "index_gvcf" tabix -p vcf "$gvcf_part" || { finish_step failed 1; return 1; }
    fi
    if ! bcftools view -h "$gvcf_part" >/dev/null 2>&1; then
        fail_step "gvcf_parse" "the produced gVCF cannot be parsed; it was not published"
        return 1
    fi
    mv -f -- "${gvcf_part}.tbi" "${GVCF}.tbi"
    mv -f -- "$gvcf_part" "$GVCF"
    step_check_pass "haplotypecaller" "gVCF and index created and validated before publication"

    # --dbsnp only adds rsIDs. It is applied when the bundle declares a dbSNP
    # resource and skipped otherwise, rather than guessing one from known_sites.
    local dbsnp_args=()
    if [[ -n "$DBSNP_VCF" ]]; then
        if [[ -s "$DBSNP_VCF" ]]; then
            dbsnp_args=(--dbsnp "$DBSNP_VCF")
            step_input dbsnp "$DBSNP_VCF"
        else
            step_warning "DBSNP_MISSING" "dbsnp_vcf is declared in the bundle but not readable: $DBSNP_VCF" \
                "Variant records will carry no rsID; the calls themselves are unaffected" "true"
        fi
    else
        step_warning "DBSNP_NOT_CONFIGURED" "The resource bundle declares no dbsnp_vcf" \
            "Variant records will carry no rsID; the calls themselves are unaffected" "true"
    fi

    rm -f -- "$raw_part" "${raw_part}.tbi"
    require_cmd_ok "genotype_gvcfs" \
        gatk --java-options "$java_opts" GenotypeGVCFs \
            -R "$REF_FASTA" -V "$GVCF" \
            ${dbsnp_args[@]+"${dbsnp_args[@]}"} \
            -L "$TARGET_BED" -ip "$INTERVAL_PADDING" \
            -O "$raw_part" --tmp-dir "$tmp_dir" \
        || { finish_step failed 1; return 1; }

    [[ -s "$raw_part" ]] || { fail_step "raw_vcf_missing" "GenotypeGVCFs produced no VCF"; return 1; }

    # AUD-HIGH-002: the raw VCF is the core completion artifact, so it is
    # indexed and parse-checked while still named `.part`. It receives its
    # final name only once body and index are both good.
    if [[ ! -s "${raw_part}.tbi" ]]; then
        require_cmd_ok "index_raw_vcf" tabix -p vcf "$raw_part" || { finish_step failed 1; return 1; }
    fi
    if ! bcftools view -h "$raw_part" >/dev/null 2>&1; then
        fail_step "raw_vcf_parse" "the produced raw VCF cannot be parsed; it was not published"
        return 1
    fi
    mv -f -- "${raw_part}.tbi" "${RAW_VCF}.tbi"
    mv -f -- "$raw_part" "$RAW_VCF"
    step_check_pass "genotype_gvcfs" "raw VCF and index created and validated before publication"

    local vcf label
    for vcf in "$GVCF" "$RAW_VCF"; do
        label=$(basename -- "$vcf")
        if bcftools view -h "$vcf" >/dev/null 2>&1; then
            step_check_pass "vcf_parse_${label}" "header parses"
        else
            step_check_fail "vcf_parse_${label}" "bcftools cannot parse the VCF header"
        fi
        if tabix -l "$vcf" >/dev/null 2>&1; then
            step_check_pass "vcf_index_${label}" "index is readable"
        else
            step_check_fail "vcf_index_${label}" "tabix index missing or unreadable"
        fi
    done

    local vcf_sample vcf_sample_count
    vcf_sample=$(bcftools query -l "$RAW_VCF" 2>/dev/null | head -n 1 || true)
    vcf_sample_count=$(bcftools query -l "$RAW_VCF" 2>/dev/null | grep -c . || true)
    if [[ "$vcf_sample_count" == "1" && "$vcf_sample" == "$SAMPLE_ID" ]]; then
        step_check_pass "vcf_sample" "single sample column '$vcf_sample' matches the read-group SM"
    else
        step_check_fail "vcf_sample" \
            "expected exactly one sample column named '$SAMPLE_ID'; found $vcf_sample_count ('${vcf_sample:-none}')"
    fi

    local raw_records
    raw_records=$(bcftools view -H "$RAW_VCF" 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$raw_records" =~ ^[0-9]+$ ]] && (( raw_records > 0 )); then
        step_check_pass "raw_vcf_records" "$raw_records variant records"
        step_metric raw_variant_records "$raw_records" num
    else
        step_check_fail "raw_vcf_records" "the raw VCF contains no variant records"
    fi

    local ref_check_log="$LOG_DIR/${CURRENT_STEP}.ref_allele_check.log"
    if bcftools norm -f "$REF_FASTA" -c e -Ou -o /dev/null "$RAW_VCF" > "$ref_check_log" 2>&1; then
        step_check_pass "raw_vcf_ref_match" "all REF alleles agree with the ${ASSEMBLY:-configured} reference"
    else
        step_check_fail "raw_vcf_ref_match" \
            "REF allele mismatch against the ${ASSEMBLY:-configured} reference; see logs/${CURRENT_STEP}.ref_allele_check.log"
    fi

    local bcf_stats="$stage_dir/${SAMPLE_ID}.raw.bcftools.stats.txt"
    if run_cmd_stdout "bcftools_stats" "$bcf_stats" bcftools stats "$RAW_VCF"; then
        step_check_pass "bcftools_stats" "variant statistics created"
        local key value
        while IFS='=' read -r key value; do
            [[ -n "$key" ]] && step_metric "$key" "$value" num
        done < <("$(resolve_python)" - "$bcf_stats" <<'PYSTATS'
import sys
wanted = {"number of records": "raw_records", "number of SNPs": "raw_snps",
          "number of indels": "raw_indels",
          "number of multiallelic sites": "raw_multiallelic_sites"}
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    f = line.rstrip("\n").split("\t")
    if f[0] == "SN" and len(f) >= 4:
        key = wanted.get(f[2].rstrip(":"))
        if key:
            print(f"{key}={f[3]}")
    elif f[0] == "TSTV" and len(f) >= 5:
        print(f"raw_ts_tv={f[4]}")
PYSTATS
)
    else
        step_warning "BCFTOOLS_STATS_FAILED" "bcftools stats did not complete" \
            "Summary counts are unavailable; the raw VCF itself is unaffected" "true"
    fi

    step_has_failures && { finish_step failed 1; return 1; }

    step_output gvcf "$GVCF"
    step_output raw_vcf "$RAW_VCF"
    add_artifact gvcf "Sample gVCF" "$GVCF" 1 1 "HaplotypeCaller reference-confidence gVCF"
    add_artifact gvcf_index "gVCF index" "${GVCF}.tbi" 1 1 "Tabix index for the gVCF"
    add_artifact raw_vcf "Raw VCF" "$RAW_VCF" 1 1 \
        "GenotypeGVCFs output — the core completion artifact. No filtering has been applied."
    add_artifact raw_vcf_index "Raw VCF index" "${RAW_VCF}.tbi" 1 1 "Tabix index for the raw VCF"
    add_artifact vcf_stats "bcftools stats" "$bcf_stats" 1 0 "Variant summary statistics"

    local vc_json="$stage_dir/variant_calling_output.json"
    "$(resolve_python)" - "$vc_json" "$RUN_DIR" "$SAMPLE_ID" "$GVCF" "$RAW_VCF" \
        "${ASSEMBLY:-unset}" "$raw_records" <<'PYVC'
import json, os, sys
out_path, run_dir, sample, gvcf, raw_vcf, assembly, records = sys.argv[1:8]


def rel(p):
    try:
        return os.path.relpath(p, run_dir).replace(os.sep, "/")
    except ValueError:
        return p


doc = {"sample": sample, "assembly": assembly, "gvcf": gvcf, "raw_vcf": raw_vcf,
       "gvcf_relative": rel(gvcf), "raw_vcf_relative": rel(raw_vcf),
       "raw_variant_records": int(records) if str(records).isdigit() else None,
       "filtering_applied": False, "next_step_ready": True}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
PYVC
    step_output variant_calling_output "$vc_json"

    complete_step
}

# =============================================================================
# 7. Optional post-core steps
#
# All optional steps are disabled by default. None of them may modify, delete
# or overwrite the core raw VCF: each writes into its own directory under
# optional/. A failure here is recorded but never invalidates the core result.
# =============================================================================

# ---------------------------------------------------------------------------
# 08_filtering
#
# [ORIGIN] previous main.sh lines 1794-1812 and 1944-1946 (filtering block).
# [OPTIONAL, default off] The preserved logic is the genotype-quality preset:
#   FILTER=PASS/. combined with FORMAT/DP, FORMAT/GQ and FORMAT/AD thresholds,
#   applied with `bcftools view -i`.
#
# IMPORTANT — two different things are often conflated:
#   * This step applies a GENOTYPE-QUALITY filter (FORMAT DP/GQ/AD). It judges
#     how well an individual genotype is supported.
#   * GATK "hard filtering" applies SITE-level annotations (QD, FS, MQ, SOR...).
#     That is a different filter and is NOT implemented here.
#   * MAF filtering against a population database is a THIRD, separate thing.
#     It is not implemented; no code in the previous main.sh performed it.
#
# The presets are kept exactly as the original author wrote them, but they are
# NOT endorsed as validated thresholds: they have not been evaluated against a
# truth set for this project. That is why this step is off by default. The
# re-activation condition is in docs/MAIN_SH_COMPLETE_GUIDE.md —
# "16. Optional filtering" (and "28. 현재 한계" for what is still unverified).
# ---------------------------------------------------------------------------
run_filtering() {
    start_step 08_filtering
    local stage_dir="$OPTIONAL_DIR/filtering"
    mkdir -p -- "$stage_dir"

    local vc_json="$RUN_DIR/06_variant_calling/variant_calling_output.json"
    [[ -s "$vc_json" ]] || { fail_step "missing_variant_calling_output" "06_variant_calling did not publish its output document"; return 1; }
    step_input variant_calling_output "$vc_json"

    SAMPLE_ID=$(json_get "$vc_json" sample)
    RAW_VCF=$(json_get "$vc_json" raw_vcf)
    [[ -s "$RAW_VCF" ]] || { fail_step "missing_raw_vcf" "Raw VCF is missing: $RAW_VCF"; return 1; }
    step_input raw_vcf "$RAW_VCF"

    local preset min_dp min_gq min_alt
    preset=$(json_get "$CONFIG_PATH" filtering.preset balanced)
    case "$preset" in
        balanced)  min_dp=5;  min_gq=10; min_alt=3 ;;
        strict)    min_dp=10; min_gq=20; min_alt=3 ;;
        pass-only) min_dp="";  min_gq="";  min_alt="" ;;
        *) fail_step "invalid_preset" "filtering.preset must be balanced, strict or pass-only (got '$preset')"; return 1 ;;
    esac
    min_dp=$(json_get "$CONFIG_PATH" filtering.min_dp "$min_dp")
    min_gq=$(json_get "$CONFIG_PATH" filtering.min_gq "$min_gq")
    min_alt=$(json_get "$CONFIG_PATH" filtering.min_alt_depth "$min_alt")

    local expr='(FILTER="PASS" || FILTER=".")'
    [[ -z "$min_dp"  ]] || expr+=" && FMT/DP>=${min_dp}"
    [[ -z "$min_gq"  ]] || expr+=" && FMT/GQ>=${min_gq}"
    [[ -z "$min_alt" ]] || expr+=" && FMT/AD[0:1]>=${min_alt}"

    step_metric filter_preset "$preset" str
    step_metric filter_expression "$expr" str
    log "  genotype-quality filter: $expr"

    local filtered="$stage_dir/${SAMPLE_ID}.filtered.vcf.gz"
    local filtered_part="${filtered}.part"
    rm -f -- "$filtered_part"

    # The expression is passed as a single argv element; it is never expanded
    # by a shell.
    require_cmd_ok "bcftools_filter" \
        bcftools view -i "$expr" "$RAW_VCF" -Oz -o "$filtered_part" \
        || { finish_step failed 1; return 1; }
    [[ -s "$filtered_part" ]] || { rm -f -- "$filtered_part"; fail_step "filter_empty" "bcftools produced no output"; return 1; }
    mv -f -- "$filtered_part" "$filtered"
    require_cmd_ok "index_filtered" bcftools index -f -t "$filtered" || { finish_step failed 1; return 1; }

    local before after
    before=$(bcftools view -H "$RAW_VCF" 2>/dev/null | wc -l | tr -d ' ')
    after=$(bcftools view -H "$filtered" 2>/dev/null | wc -l | tr -d ' ')
    step_metric records_before_filter "$before" num
    step_metric records_after_filter "$after" num
    step_check_pass "filtering" "genotype-quality filter applied: ${before} -> ${after} records"

    if [[ "$after" == "0" ]]; then
        step_warning "NO_VARIANTS_PASSED" "No variants passed the genotype-quality filter" \
            "This is a filtering outcome, not an error; the unfiltered raw VCF is unchanged" "true"
    fi

    step_output filtered_vcf "$filtered"
    add_artifact filtered_vcf "Genotype-quality filtered VCF" "$filtered" 1 1 \
        "bcftools FORMAT DP/GQ/AD filter (preset=${preset}). Thresholds are NOT validated against a truth set."
    add_artifact filtered_vcf_index "Filtered VCF index" "${filtered}.tbi" 1 0 "Tabix index"

    complete_step
}

# ---------------------------------------------------------------------------
# 10_annotation
#
# [ORIGIN] previous main.sh lines 1948-1972 (normalisation, local ClinVar
#   annotation and TSV extraction from the filtering/annotation block).
# [OPTIONAL, default off]
# [KEPT] `bcftools norm -m -any` allele splitting with optional FASTA
#   left-normalisation, `bcftools annotate` against a LOCAL ClinVar VCF, and
#   the `bcftools query` TSV extraction.
# [NOT IMPLEMENTED HERE — deliberately]
#   The original block also called the Ensembl VEP REST API and the PanelApp
#   REST API at run time. Network calls are not part of the default behaviour:
#   they make a run non-reproducible, they send variant data to a third party,
#   and the original code path could not process a whole exome anyway
#   (it refused above --max-rest-variants 2000). Those code paths are therefore
#   not carried over. Offline VEP is supported only when the bundle supplies a
#   vep_cache AND the `vep` executable is present.
#   PanelApp, BRCA Exchange, REVEL and SpliceAI are disease-panel features, not
#   general germline WES steps, and are NOT implemented. Rather than being
#   faked, they are documented in docs/MAIN_SH_COMPLETE_GUIDE.md —
#   "17. Optional annotation" and "28. 현재 한계".
# ---------------------------------------------------------------------------
run_annotation() {
    start_step 10_annotation
    local stage_dir="$OPTIONAL_DIR/annotation"
    mkdir -p -- "$stage_dir"

    local vc_json="$RUN_DIR/06_variant_calling/variant_calling_output.json"
    [[ -s "$vc_json" ]] || { fail_step "missing_variant_calling_output" "06_variant_calling did not publish its output document"; return 1; }
    step_input variant_calling_output "$vc_json"
    SAMPLE_ID=$(json_get "$vc_json" sample)

    # Prefer the filtered VCF when filtering ran; otherwise annotate the raw VCF.
    local input_vcf="$(json_get "$vc_json" raw_vcf)" source_label="raw"
    local filtered="$OPTIONAL_DIR/filtering/${SAMPLE_ID}.filtered.vcf.gz"
    if [[ "$OPT_FILTERING" == "true" && -s "$filtered" ]]; then
        input_vcf="$filtered"; source_label="filtered"
    fi
    [[ -s "$input_vcf" ]] || { fail_step "missing_input_vcf" "No input VCF for annotation: $input_vcf"; return 1; }
    step_input input_vcf "$input_vcf"
    step_metric annotation_input "$source_label" str

    # ---- normalisation ------------------------------------------------------
    local normalized="$stage_dir/${SAMPLE_ID}.normalized.vcf.gz"
    local norm_part="${normalized}.part"
    local norm_cmd=(bcftools norm -m -any)
    [[ -s "$REF_FASTA" ]] && norm_cmd+=(-f "$REF_FASTA")
    norm_cmd+=("$input_vcf" -Oz -o "$norm_part")
    rm -f -- "$norm_part"
    require_cmd_ok "bcftools_norm" "${norm_cmd[@]}" || { finish_step failed 1; return 1; }
    [[ -s "$norm_part" ]] || { rm -f -- "$norm_part"; fail_step "norm_empty" "bcftools norm produced no output"; return 1; }
    mv -f -- "$norm_part" "$normalized"
    require_cmd_ok "index_normalized" bcftools index -f -t "$normalized" || { finish_step failed 1; return 1; }
    step_check_pass "normalization" "multi-allelic records split; left-normalised against the reference"
    step_output normalized_vcf "$normalized"
    add_artifact normalized_vcf "Normalized VCF" "$normalized" 1 1 "Allele-split, left-normalised VCF"

    # ---- local ClinVar ------------------------------------------------------
    local annotated="$normalized" clinvar_matched=0
    if [[ -z "$CLINVAR_VCF" ]]; then
        step_warning "CLINVAR_NOT_CONFIGURED" "The resource bundle declares no clinvar_vcf" \
            "ClinVar annotation is skipped; normalisation output is still produced" "true"
    elif [[ ! -s "$CLINVAR_VCF" ]]; then
        step_warning "CLINVAR_MISSING" "clinvar_vcf is declared but not readable: $CLINVAR_VCF" \
            "ClinVar annotation is skipped" "true"
    else
        step_input clinvar_vcf "$CLINVAR_VCF"
        # Structural compatibility must be established before annotating:
        # annotating a callset from one reference build with a ClinVar release
        # from another produces silently wrong clinical interpretations.
        #
        # A chromosome-naming comparison alone is NOT full build verification —
        # two releases can share every contig name and still disagree. What is
        # checked here is structure: index presence, header parse, contig
        # subset, header-declared contig lengths against the reference .fai, and
        # naming convention. The guarantee that ClinVar belongs to the declared
        # assembly comes from the resource_bundle contract (every resource in
        # the bundle is of resource_bundle.assembly), and the exact release must
        # be recorded in the run config / bundle provenance.
        local clinvar_compat="" clinvar_compat_rc=0
        clinvar_compat=$(check_vcf_against_reference "$CLINVAR_VCF" "clinvar_vcf") || clinvar_compat_rc=$?
        if (( clinvar_compat_rc != 0 )); then
            step_warning "CLINVAR_INCOMPATIBLE" \
                "ClinVar VCF is not structurally compatible with the reference — ${clinvar_compat:-no detail reported}" \
                "ClinVar annotation is skipped to avoid producing silently wrong matches; the normalised VCF and the core raw VCF are unaffected" "true"
        else
            log "$clinvar_compat"
            local clinvar_out="$stage_dir/${SAMPLE_ID}.clinvar.vcf.gz"
            local clinvar_part="${clinvar_out}.part"
            rm -f -- "$clinvar_part"
            if require_cmd_ok "bcftools_annotate" \
                bcftools annotate -a "$CLINVAR_VCF" \
                    -c 'ID,INFO/CLNSIG,INFO/CLNDN,INFO/CLNREVSTAT,INFO/CLNHGVS,INFO/GENEINFO' \
                    "$normalized" -Oz -o "$clinvar_part"; then
                mv -f -- "$clinvar_part" "$clinvar_out"
                run_optional_cmd "index_clinvar" bcftools index -f -t "$clinvar_out"
                annotated="$clinvar_out"
                clinvar_matched=$(bcftools view -H "$clinvar_out" 2>/dev/null | grep -c 'CLNSIG=' || true)
                step_check_pass "clinvar_annotation" "annotated against the local ClinVar VCF"
                step_metric clinvar_matched_records "$clinvar_matched" num
                step_output clinvar_vcf "$clinvar_out"
                add_artifact annotated_vcf "ClinVar-annotated VCF" "$clinvar_out" 1 1 \
                    "Exact CHROM+POS+REF+ALT match against a local ClinVar release"
            else
                rm -f -- "$clinvar_part"
                step_warning "CLINVAR_ANNOTATE_FAILED" "bcftools annotate did not complete" \
                    "The normalised VCF is still available" "true"
            fi
        fi
    fi

    # ---- offline VEP, only when a cache is configured ------------------------
    if [[ -n "$VEP_CACHE" ]]; then
        if have_command vep; then
            step_warning "VEP_NOT_WIRED" "vep and a cache are available but the offline VEP call is not implemented" \
                "Only ClinVar annotation is applied. Implementing offline VEP requires deciding the cache version, species and transcript set." "true"
        else
            step_warning "VEP_MISSING" "vep_cache is configured but the 'vep' executable is not installed" \
                "Offline VEP annotation is skipped" "true"
        fi
    fi

    # ---- variant TSV --------------------------------------------------------
    local tsv="$stage_dir/${SAMPLE_ID}.variants.tsv"
    {
        printf 'chrom\tpos\tref\talt\tfilter\tid\tqual\tgeneinfo\tclinvar_significance\tclinvar_disease\tclinvar_review_status\tgt\tad\tdp\tgq\n'
    } > "$tsv"
    if run_cmd_stdout "bcftools_query" "$STEP_WORK/query.tsv" \
        bcftools query --allow-undef-tags \
            -f '%CHROM\t%POS\t%REF\t%ALT\t%FILTER\t%ID\t%QUAL\t%INFO/GENEINFO\t%INFO/CLNSIG\t%INFO/CLNDN\t%INFO/CLNREVSTAT[\t%GT\t%AD\t%DP\t%GQ]\n' \
            "$annotated"; then
        cat "$STEP_WORK/query.tsv" >> "$tsv"
        step_check_pass "variant_tsv" "variant table created"
        step_output variant_tsv "$tsv"
        add_artifact variant_tsv "Variant table" "$tsv" 1 0 \
            "Per-variant table. Research and education use only. Absence from ClinVar does not mean benign."
    else
        step_warning "TSV_FAILED" "bcftools query did not complete" "The annotated VCF is still available" "true"
    fi

    complete_step
}

# ---------------------------------------------------------------------------
# 11_intervar
#
# [ORIGIN] previous main.sh lines 2161-2323 (InterVar block).
# [OPTIONAL, default off]
# [KEPT] the InterVar invocation and the result-summary aggregation.
# [REMOVED confirmed errors]
#   - `git clone https://github.com/WGLab/InterVar.git` at run time (line 2213)
#   - `pip install -r requirements.txt --break-system-packages` (line 2215)
#   - `python InterVar.py --download_db -d humandb/` (line 2217), which
#     downloads tens of gigabytes during an analysis run
#   - the hard-coded `-b` build value (line 2295), which was not derived from the
#     run config and could contradict the reference build of the resources used
#     by the rest of the pipeline. The build now comes from `intervar.build`.
#   - `find ... | head -1` discovery of the input VCF (line 2192)
# InterVar and its databases must be installed beforehand; see
# docs/MAIN_SH_COMPLETE_GUIDE.md — "18. Optional InterVar", and the setup
# checklist in "6. 실행 방법과 CLI option" (실행 전 준비물).
#
# [RESULT WORDING] InterVar's own documentation describes a two-step process:
#   automatic interpretation of evidence codes, followed by manual adjustment
#   by the user. The output of this step is therefore labelled as automated
#   evidence requiring manual review, never as a final clinical classification.
# ---------------------------------------------------------------------------
run_intervar() {
    start_step 11_intervar
    local stage_dir="$OPTIONAL_DIR/intervar"
    mkdir -p -- "$stage_dir"

    local intervar_dir intervar_build humandb
    intervar_dir=$(json_get "$CONFIG_PATH" intervar.install_dir "")
    intervar_build=$(json_get "$CONFIG_PATH" intervar.build "")
    humandb=$(json_get "$CONFIG_PATH" intervar.humandb_dir "")

    if [[ -z "$intervar_dir" || ! -d "$intervar_dir" ]]; then
        fail_step "intervar_not_installed" \
            "intervar.install_dir is not set or does not exist. InterVar를 미리 설치해 두어야 합니다. 이 파이프라인은 실행 중에 clone하거나 다운로드하지 않습니다. 설치와 설정 방법은 docs/MAIN_SH_COMPLETE_GUIDE.md의 \"18. Optional InterVar\" 장을 보세요."
        return 1
    fi
    if [[ -z "$intervar_build" ]]; then
        fail_step "intervar_build_not_set" \
            "intervar.build is not set. The build must match the resource bundle (assembly=${ASSEMBLY}); it is never assumed."
        return 1
    fi

    # ---- assembly <-> InterVar build correspondence -------------------------
    # Checked HERE, inside the optional step, and never during core preflight:
    # an assembly that has no InterVar mapping yet must still be able to run the
    # whole core pipeline. Extend INTERVAR_BUILD_FOR_ASSEMBLY (section 0) to
    # adopt another assembly; no other code changes are needed.
    local assembly_key expected_build=""
    assembly_key=$(printf '%s' "$ASSEMBLY" | tr '[:upper:]' '[:lower:]')
    if [[ -n "${INTERVAR_BUILD_FOR_ASSEMBLY[$assembly_key]+set}" ]]; then
        expected_build="${INTERVAR_BUILD_FOR_ASSEMBLY[$assembly_key]}"
    fi

    local known_map="" k
    for k in "${!INTERVAR_BUILD_FOR_ASSEMBLY[@]}"; do
        known_map+="${known_map:+, }${k} -> ${INTERVAR_BUILD_FOR_ASSEMBLY[$k]}"
    done

    if [[ -z "$expected_build" ]]; then
        fail_step "intervar_assembly_unmapped" \
            "Optional InterVar step configuration problem — the CORE pipeline and the raw VCF are unaffected. The resource bundle declares assembly='${ASSEMBLY}', which has no InterVar/ANNOVAR build mapping in this script. Configured intervar.build='${intervar_build}'. Known mappings: ${known_map:-<none>}. Add the assembly to INTERVAR_BUILD_FOR_ASSEMBLY in script/main.sh once the matching ANNOVAR humandb is prepared, or turn optional_steps.intervar off."
        return 1
    fi
    if [[ "$intervar_build" != "$expected_build" ]]; then
        fail_step "intervar_build_mismatch" \
            "Optional InterVar step configuration problem — the CORE pipeline and the raw VCF are unaffected. resource_bundle.assembly='${ASSEMBLY}' expects intervar.build='${expected_build}', but the config sets intervar.build='${intervar_build}'. Annotating with a mismatched build produces coordinates that are silently wrong. Fix intervar.build, or correct the assembly if the bundle is not what you intended."
        return 1
    fi
    step_check_pass "intervar_build_matches_assembly" \
        "intervar.build='${intervar_build}' matches the declared assembly '${ASSEMBLY}'"
    if [[ -z "$humandb" || ! -d "$humandb" ]]; then
        fail_step "intervar_humandb_missing" \
            "intervar.humandb_dir is not set or does not exist. The annotation databases must be prepared beforehand."
        return 1
    fi
    [[ -x "$intervar_dir/InterVar.py" || -f "$intervar_dir/InterVar.py" ]] \
        || { fail_step "intervar_script_missing" "InterVar.py not found in $intervar_dir"; return 1; }

    local vc_json="$RUN_DIR/06_variant_calling/variant_calling_output.json"
    [[ -s "$vc_json" ]] || { fail_step "missing_variant_calling_output" "06_variant_calling did not publish its output document"; return 1; }
    SAMPLE_ID=$(json_get "$vc_json" sample)

    local input_vcf="" annotated="$OPTIONAL_DIR/annotation/${SAMPLE_ID}.clinvar.vcf.gz"
    local normalized="$OPTIONAL_DIR/annotation/${SAMPLE_ID}.normalized.vcf.gz"
    if [[ -s "$annotated" ]]; then input_vcf="$annotated"
    elif [[ -s "$normalized" ]]; then input_vcf="$normalized"
    else input_vcf=$(json_get "$vc_json" raw_vcf); fi
    [[ -s "$input_vcf" ]] || { fail_step "missing_input_vcf" "No input VCF for InterVar: $input_vcf"; return 1; }
    step_input input_vcf "$input_vcf"
    step_metric intervar_build "$intervar_build" str

    local out_prefix="$stage_dir/${SAMPLE_ID}_intervar"
    local py; py=$(resolve_python)

    # Run inside the InterVar directory because the tool resolves its helper
    # scripts relative to the working directory. A subshell keeps the change
    # local, so the pipeline's own working directory is never altered.
    local rc=0
    record_command "${CURRENT_STEP}/intervar" \
        "$py" "$intervar_dir/InterVar.py" -i "$input_vcf" --input_type VCF \
        -o "$out_prefix" -b "$intervar_build" -t intervardb -d "$humandb"
    (
        cd "$intervar_dir" || exit 1
        "$py" ./InterVar.py \
            -i "$input_vcf" --input_type VCF \
            -o "$out_prefix" -b "$intervar_build" -t intervardb \
            --table_annovar=./table_annovar.pl \
            --convert2annovar=./convert2annovar.pl \
            --annotate_variation=./annotate_variation.pl \
            -d "$humandb"
    ) >> "$LOG_DIR/${CURRENT_STEP}.intervar.stdout.log" 2>> "$LOG_DIR/${CURRENT_STEP}.intervar.stderr.log" || rc=$?

    if (( rc != 0 )); then
        fail_step "intervar_failed" "InterVar exited with code $rc; see logs/${CURRENT_STEP}.intervar.stderr.log"
        return 1
    fi

    local result_file="${out_prefix}.${intervar_build}_multianno.txt.intervar"
    [[ -s "$result_file" ]] || { fail_step "intervar_no_result" "InterVar result file not found: $result_file"; return 1; }

    local summary_json="$stage_dir/${SAMPLE_ID}_intervar_summary.json"
    "$py" - "$result_file" "$summary_json" <<'PYINTERVAR'
import json, os, sys
result_file, out_json = sys.argv[1:3]

counts, gene_counts = {}, {}
total = 0
header = None
intervar_idx = gene_idx = None
with open(result_file, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if header is None:
            header = f
            for i, c in enumerate(header):
                if c.strip().lower().startswith("intervar"):
                    intervar_idx = i
                if "Gene" in c and "refGene" in c:
                    gene_idx = i
            if intervar_idx is None:
                intervar_idx = len(header) - 1
            continue
        total += 1
        value = f[intervar_idx] if intervar_idx < len(f) else ""
        counts[value] = counts.get(value, 0) + 1
        if gene_idx is not None and "Pathogenic" in value and gene_idx < len(f):
            gene_counts[f[gene_idx]] = gene_counts.get(f[gene_idx], 0) + 1

pathogenic = sum(v for k, v in counts.items() if "Pathogenic" in k)

doc = {
    "total_variants": total,
    "automated_evidence_counts": counts,
    "automated_pathogenic_or_likely_pathogenic": pathogenic,
    "gene_counts_for_pathogenic": gene_counts,
    "interpretation_status": "automated_evidence_only",
    "requires_manual_review": True,
    "is_final_clinical_classification": False,
    "intended_use": "research and education only",
    "limitations": [
        "InterVar performs automatic interpretation of evidence codes followed by manual adjustment by the user; these counts are the automatic step only.",
        "This output is not a final ACMG classification and must not be presented as one.",
        "Absence of a pathogenic assignment does not establish that a variant is benign.",
    ],
}
tmp = out_json + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_json)
print(f"total={total} automated_pathogenic_or_lp={pathogenic}")
PYINTERVAR

    step_check_pass "intervar" "automated evidence produced; manual review is required before any interpretation"
    step_warning "AUTOMATED_EVIDENCE_ONLY" \
        "InterVar output is automated evidence, not a final clinical classification" \
        "Results must be reviewed manually; research and education use only" "true"
    step_output intervar_result "$result_file"
    step_output intervar_summary "$summary_json"
    add_artifact intervar_result "InterVar result table" "$result_file" 1 0 \
        "Automated ACMG evidence codes. Requires manual review. Not a final clinical classification."
    add_artifact intervar_summary "InterVar summary" "$summary_json" 1 0 \
        "Counts of automated evidence assignments, with explicit limitations"

    complete_step
}

# =============================================================================
# 8. Finalisation
#
# [ORIGIN] Processing source section 8: consolidated validation with
#   pass/warn/fail accounting, metrics JSON, artifact manifest and provenance
#   JSON, plus the RUN_COMPLETED / RUN_FAILED markers.
# [KEEP_WITH_INTERFACE_PATCH] The same information is produced, but the
#   artifact manifest now carries file_id and a run-relative path instead of an
#   absolute server path, and the marker set distinguishes a clean completion
#   from one with warnings.
# =============================================================================

clear_run_markers() {
    rm -f -- "$RUN_DIR/RUN_COMPLETED" "$RUN_DIR/RUN_COMPLETED_WITH_WARNINGS" \
             "$RUN_DIR/RUN_FAILED" "$RUN_DIR/RUN_CANCELLED"
}

set_run_marker() {
    local marker=$1 detail=${2:-}
    clear_run_markers
    printf '%s\n%s\n%s\n' "$marker" "$(iso_now)" "$detail" > "$RUN_DIR/$marker"
    RUN_TERMINAL_STATE="$marker"
}

# run_final_validation — one consolidated pass/warn/fail table over the whole
# run, written both as TSV (human) and folded into the finalisation step JSON.
run_final_validation() {
    printf 'check\tstatus\tdetail\n' > "$FINAL_VALIDATION"
    local pass=0 warnc=0 failc=0

    vpass() { printf '%s\tPASS\t%s\n' "$1" "$2" >> "$FINAL_VALIDATION"; pass=$(( pass + 1 )); step_check_pass "$1" "$2"; }
    vwarn() { printf '%s\tWARN\t%s\n' "$1" "$2" >> "$FINAL_VALIDATION"; warnc=$(( warnc + 1 )); }
    vfail() { printf '%s\tFAIL\t%s\n' "$1" "$2" >> "$FINAL_VALIDATION"; failc=$(( failc + 1 )); step_check_fail "$1" "$2"; }

    # Core artifacts that define a completed core run.
    local vc_json="$RUN_DIR/06_variant_calling/variant_calling_output.json"
    local proc_json="$RUN_DIR/04_processing/processing_output.json"

    if [[ -s "$proc_json" ]]; then
        local bam; bam=$(json_get "$proc_json" analysis_ready_bam "")
        if [[ -s "$bam" ]]; then vpass "analysis_ready_bam" "present"; else vfail "analysis_ready_bam" "missing"; fi
    else
        vfail "analysis_ready_bam" "04_processing produced no output document"
    fi

    if [[ -s "$vc_json" ]]; then
        local gvcf raw
        gvcf=$(json_get "$vc_json" gvcf "")
        raw=$(json_get "$vc_json" raw_vcf "")
        [[ -s "$gvcf" ]] && vpass "gvcf" "present" || vfail "gvcf" "missing"
        [[ -s "$raw" ]] && vpass "raw_vcf" "present" || vfail "raw_vcf" "missing"
        [[ -s "${raw}.tbi" ]] && vpass "raw_vcf_index" "present" || vfail "raw_vcf_index" "missing"
    else
        vfail "raw_vcf" "06_variant_calling produced no output document"
    fi

    # ---- roll up every step's recorded status  (AUD-BLOCKER-002) ----------
    #
    # Core and optional failures are NOT equivalent. A failed optional step
    # must not turn a completed core run into RUN_FAILED: the raw VCF and every
    # core artifact remain valid and downloadable. Optional failures are
    # recorded as warnings here and reported separately in the summary.
    # The list is MERGED with what run_pipeline already observed, not reset.
    # An optional step that died before writing its status document would
    # otherwise disappear from the report.
    local f step_id status kind
    for f in "$STEPS_DIR"/*.json; do
        [[ -e "$f" ]] || continue
        step_id=$(json_get "$f" step_id "")
        [[ -n "$step_id" ]] || continue
        status=$(json_get "$f" status "")
        kind=$(step_kind "$step_id")
        case "$status" in
            completed) vpass "step_${step_id}" "completed (${kind})" ;;
            warning)   vwarn "step_${step_id}" "completed with warnings (${kind})" ;;
            skipped)   vwarn "step_${step_id}" "skipped (${kind})" ;;
            failed)
                if [[ "$kind" == "optional" ]]; then
                    if [[ " ${OPTIONAL_FAILED_STEPS[*]-} " != *" $step_id "* ]]; then
                        OPTIONAL_FAILED_STEPS+=("$step_id")
                    fi
                    vwarn "step_${step_id}" \
                        "OPTIONAL step failed; core results are unaffected and remain valid"
                else
                    vfail "step_${step_id}" "core step failed"
                fi
                ;;
            *)
                if [[ "$kind" == "optional" ]]; then
                    vwarn "step_${step_id}" "optional step status=${status:-unknown}"
                else
                    vwarn "step_${step_id}" "status=${status:-unknown}"
                fi
                ;;
        esac
    done

    if (( ${#OPTIONAL_FAILED_STEPS[@]} > 0 )); then
        step_metric optional_failed_steps "${OPTIONAL_FAILED_STEPS[*]}" str
        step_warning "OPTIONAL_STEPS_FAILED" \
            "Optional step(s) failed: ${OPTIONAL_FAILED_STEPS[*]}" \
            "Core raw VCF and core artifacts are complete and valid; only the optional outputs are missing" \
            "true"
    fi

    step_metric validation_pass "$pass" num
    step_metric validation_warn "$warnc" num
    step_metric validation_fail "$failc" num
    log "  final validation: PASS=$pass WARN=$warnc FAIL=$failc"
    add_artifact final_validation "Final validation table" "$FINAL_VALIDATION" 1 0 \
        "Consolidated pass/warn/fail table for the whole run"
    return 0
}

write_artifact_manifest() {
    local out="$RUN_DIR/artifact_manifest.json"
    "$(resolve_python)" - "$ARTIFACT_DIR" "$out" "$RUN_ID" <<'PYMANIFEST' | tr -d '\r'
import json, os, sys
artifact_dir, out_path, run_id = sys.argv[1:4]
entries = []
if os.path.isdir(artifact_dir):
    for fn in sorted(os.listdir(artifact_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(artifact_dir, fn), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        entries.extend(doc.get("artifacts") or [])

doc = {"run_id": run_id, "artifact_count": len(entries), "artifacts": entries}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
print(len(entries))
PYMANIFEST
}

write_provenance() {
    local out="$RUN_DIR/provenance.json"
    local snapshot="$CONFIG_DIR/run_config.snapshot.json"
    "$(resolve_python)" - "$out" "$RUN_DIR" "$snapshot" "$VERSIONS_TXT" "$RESOURCE_SHA256" \
        "$PIPELINE_NAME" "$PIPELINE_VERSION" "$RUN_ID" <<'PYPROV'
import json, os, sys
(out_path, run_dir, snapshot, versions_txt, resource_sha,
 name, version, run_id) = sys.argv[1:9]


def read_kv(path):
    d = {}
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8", errors="replace"):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                d[k] = v
    return d


def read_checksums(path):
    out = []
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8", errors="replace"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                out.append({"sha256": parts[0], "path": parts[1].strip()})
    return out


config = {}
if os.path.isfile(snapshot):
    with open(snapshot, encoding="utf-8") as fh:
        config = json.load(fh)

steps = []
steps_dir = os.path.join(run_dir, "status", "steps")
if os.path.isdir(steps_dir):
    for fn in sorted(os.listdir(steps_dir)):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(steps_dir, fn), encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            steps.append({"step_id": d.get("step_id"), "status": d.get("status"),
                          "exit_code": d.get("exit_code"),
                          "elapsed_seconds": d.get("elapsed_seconds")})

doc = {
    "pipeline_name": name,
    "pipeline_version": version,
    "run_id": run_id,
    "run_config": config,
    "config_identity_sha256": config.get("config_identity_sha256"),
    "software_versions": read_kv(versions_txt),
    "resource_checksums": read_checksums(resource_sha),
    "steps": steps,
    "commands": "logs/commands.sh",
    "stage_status_tsv": "logs/stage_status.tsv",
    "execution_trace_tsv": "logs/execution_trace.tsv",
    "pipeline_log": "logs/pipeline.log",
    "final_validation": "final_validation.tsv",
    "artifact_manifest": "artifact_manifest.json",
    "intended_use": "research and education only; not a diagnostic result",
}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
PYPROV
}

write_final_report() {
    local out="$RUN_DIR/methods.md"
    local summary="$RUN_DIR/core_summary.json"

    "$(resolve_python)" - "$RUN_DIR" "$summary" "$RUN_ID" "$PIPELINE_NAME" "$PIPELINE_VERSION" <<'PYSUMMARY'
import json, os, sys
run_dir, out_path, run_id, name, version = sys.argv[1:6]


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


metrics = {}
mdir = os.path.join(run_dir, "metrics")
if os.path.isdir(mdir):
    for fn in sorted(os.listdir(mdir)):
        if fn.endswith(".json"):
            d = load(os.path.join(mdir, fn))
            metrics[d.get("step_id", fn[:-5])] = d.get("metrics", {})

steps, warnings = [], []
sdir = os.path.join(run_dir, "status", "steps")
if os.path.isdir(sdir):
    for fn in sorted(os.listdir(sdir)):
        if not fn.endswith(".json"):
            continue
        d = load(os.path.join(sdir, fn))
        steps.append({"step_id": d.get("step_id"), "status": d.get("status"),
                      "elapsed_seconds": d.get("elapsed_seconds")})
        for w in d.get("warnings") or []:
            warnings.append({"step_id": d.get("step_id"), **w})

vc = load(os.path.join(run_dir, "06_variant_calling", "variant_calling_output.json"))
proc = load(os.path.join(run_dir, "04_processing", "processing_output.json"))

core_complete = bool(vc.get("raw_vcf")) and os.path.isfile(vc.get("raw_vcf", ""))

doc = {
    "pipeline_name": name, "pipeline_version": version, "run_id": run_id,
    "sample": vc.get("sample") or proc.get("sample"),
    "assembly": vc.get("assembly"),
    "core_complete": core_complete,
    "core_endpoint": "raw VCF (no filtering applied)",
    "raw_variant_records": vc.get("raw_variant_records"),
    "nm_md_repaired": proc.get("nm_md_repaired"),
    "steps": steps,
    "warnings": warnings,
    "warning_count": len(warnings),
    "metrics": metrics,
    "intended_use": "research and education only; not a diagnostic result",
}
tmp = out_path + ".part"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2); fh.write("\n")
os.replace(tmp, out_path)
PYSUMMARY

    # methods.md — a short, factual record for humans. It is not a clinical
    # report and deliberately makes no interpretive claim.
    {
        printf '# Methods — run `%s`\n\n' "$RUN_ID"
        printf '- Pipeline: %s %s\n' "$PIPELINE_NAME" "$PIPELINE_VERSION"
        printf '- Sample: `%s`\n' "${SAMPLE_ID:-unknown}"
        printf '- Assay: whole exome sequencing, paired-end Illumina, germline\n'
        printf '- Reference bundle: `%s` (assembly `%s`, contig style `%s`, as declared in the run config)\n' \
            "${BUNDLE_ID:-unnamed}" "$ASSEMBLY" "$CONTIG_STYLE"
        printf '- Capture design: `%s` `%s` (version `%s`, design ID `%s`)\n' \
            "$TARGET_BED_MANUFACTURER" "$TARGET_BED_CAPTURE_KIT_NAME" \
            "$TARGET_BED_CAPTURE_KIT_VERSION" "$TARGET_BED_DESIGN_ID"
        printf '- Capture-kit profile: `%s` (selection mode `%s`)\n' \
            "$CAPTURE_KIT_ID" "$CAPTURE_KIT_MODE"
        printf '- Target BED: `%s` (build `%s`, source `%s`, declared SHA-256 `%s`)\n' \
            "$TARGET_BED_FILE_NAME" "$TARGET_BED_GENOME_BUILD" \
            "$TARGET_BED_SOURCE" "$TARGET_BED_SHA256"
        printf '- Coverage BED: `%s` (declared SHA-256 `%s`)\n' \
            "$(basename -- "$COVERAGE_BED")" "$COVERAGE_BED_SHA256"
        if [[ -n "$TARGET_BED_SOURCE_URL" ]]; then
            printf '- Target BED source URL: %s\n' "$TARGET_BED_SOURCE_URL"
        fi
        printf '- Core endpoint: raw VCF. **No variant filtering was applied to it.**\n\n'
        printf '## Steps executed\n\n'
        printf '| Step | Status | Seconds |\n|---|---|---|\n'
        local f sid st el
        for f in "$STEPS_DIR"/*.json; do
            [[ -e "$f" ]] || continue
            sid=$(json_get "$f" step_id "")
            st=$(json_get "$f" status "")
            el=$(json_get "$f" elapsed_seconds "")
            printf '| %s | %s | %s |\n' "$sid" "$st" "$el"
        done
        printf '\n## Tool versions\n\n```\n'
        [[ -s "$VERSIONS_TXT" ]] && cat "$VERSIONS_TXT"
        printf '```\n\n'
        printf '## Resource checksums\n\n```\n'
        [[ -s "$RESOURCE_SHA256" ]] && cat "$RESOURCE_SHA256"
        printf '```\n\n'
        printf '## Exact commands\n\nSee `logs/commands.sh`.\n\n'
        printf '## Limitations\n\n'
        printf -- '- Research and education use only. This is not a diagnostic result.\n'
        printf -- '- The raw VCF is unfiltered. Variant-level and genotype-level filtering are separate, optional steps.\n'
        printf -- '- Coverage metrics are reported without a pass/fail verdict based on mean depth alone.\n'
        printf -- '- No benchmark against a truth set was performed in this run.\n'
        printf -- '- Reference resources were checked for structural compatibility (contig names, contig lengths, coordinate ranges). That is not proof of shared build provenance: the assembly above is the one declared in the run config, and the exact release of each resource is the operator'"'"'s record, not a pipeline measurement.\n'
    } > "${out}.part"
    mv -f -- "${out}.part" "$out"
}

run_finalization() {
    start_step "$FINAL_STEP"
    run_final_validation

    local artifact_count
    artifact_count=$(write_artifact_manifest)
    step_metric artifact_count "${artifact_count:-0}" num
    write_provenance
    write_final_report

    step_output artifact_manifest "$RUN_DIR/artifact_manifest.json"
    step_output provenance "$RUN_DIR/provenance.json"
    step_output methods "$RUN_DIR/methods.md"
    step_output core_summary "$RUN_DIR/core_summary.json"
    add_artifact provenance "Provenance" "$RUN_DIR/provenance.json" 1 0 "Config, tool versions and resource checksums"
    add_artifact core_summary "Core summary" "$RUN_DIR/core_summary.json" 1 0 "Machine-readable run summary"
    add_artifact methods "Methods" "$RUN_DIR/methods.md" 1 0 "Human-readable methods record"

    # complete_step() fails the step when any failure was recorded. After the
    # AUD-BLOCKER-002 change, only CORE step failures and missing core
    # artifacts produce failures here, so an optional step failing can no
    # longer make finalization — and therefore the whole run — fail.
    complete_step
}

# =============================================================================
# 9. Execution control: step plan, resume and --from-step / --to-step
# =============================================================================

build_step_plan() {
    STEP_PLAN=("${CORE_STEPS[@]}")
    [[ "$OPT_FILTERING"  == "true" ]] && STEP_PLAN+=(08_filtering)
    [[ "$OPT_ANNOTATION" == "true" ]] && STEP_PLAN+=(10_annotation)
    [[ "$OPT_INTERVAR"   == "true" ]] && STEP_PLAN+=(11_intervar)
    STEP_PLAN+=("$FINAL_STEP")

    local known=("${CORE_STEPS[@]}" "${OPTIONAL_STEPS[@]}" "$FINAL_STEP") s found
    for s in "$FROM_STEP" "$TO_STEP"; do
        [[ -n "$s" ]] || continue
        found=0
        local k
        for k in "${known[@]}"; do [[ "$k" == "$s" ]] && found=1; done
        (( found == 1 )) || die "Unknown step id: $s
Known steps: ${known[*]}"
    done

    # AUD-HIGH-003: reject --from-step positioned after --to-step. Both IDs
    # existing is not enough; the range must be meaningful in the active plan.
    if [[ -n "$FROM_STEP" && -n "$TO_STEP" ]]; then
        local from_pos=-1 to_pos=-1 i
        for i in "${!STEP_PLAN[@]}"; do
            [[ "${STEP_PLAN[$i]}" == "$FROM_STEP" ]] && from_pos=$i
            [[ "${STEP_PLAN[$i]}" == "$TO_STEP"   ]] && to_pos=$i
        done
        if (( from_pos < 0 )); then
            die "--from-step $FROM_STEP is not in this run's step plan.
Active plan: ${STEP_PLAN[*]}
An optional step must be enabled in the run config before it can be selected."
        fi
        if (( to_pos < 0 )); then
            die "--to-step $TO_STEP is not in this run's step plan.
Active plan: ${STEP_PLAN[*]}
An optional step must be enabled in the run config before it can be selected."
        fi
        if (( from_pos > to_pos )); then
            die "--from-step $FROM_STEP comes after --to-step $TO_STEP in the step plan, so the range is empty.
Active plan: ${STEP_PLAN[*]}"
        fi
    fi
}

# report_identity_diff <old_snapshot> <new_snapshot>
# Prints the specific fields that differ, so a refused resume says WHY.
report_identity_diff() {
    "$(resolve_python)" - "$1" "$2" <<'PYDIFF' | tr -d '\r'
import json, sys


def load(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh).get("resume_identity_detail") or {}
    except (OSError, ValueError):
        return {}


old, new = load(sys.argv[1]), load(sys.argv[2])


def walk(a, b, path=""):
    keys = sorted(set(a) | set(b))
    for k in keys:
        pa, pb = a.get(k), b.get(k)
        here = f"{path}.{k}" if path else k
        if isinstance(pa, dict) and isinstance(pb, dict):
            walk(pa, pb, here)
        elif pa != pb:
            print(f"    - {here}: recorded={pa!r} requested={pb!r}")


if not old and not new:
    print("    - (no identity detail recorded; cannot show field-level differences)")
else:
    walk(old, new)
PYDIFF
}

# ---------------------------------------------------------------------------
# Per-step artifact integrity validation  (AUD-BLOCKER-003)
#
# Existence is not evidence of validity. Before a step is reused, its outputs
# are re-checked with the same kind of validation the step itself performs:
# BAMs must pass quickcheck and carry the expected sample, VCFs must parse and
# have a readable index, JSON must parse and match this run and step.
#
# Returns 0 when the artifacts are trustworthy; otherwise prints the reason and
# returns non-zero.
# ---------------------------------------------------------------------------
validate_step_artifacts() {
    local step_id=$1
    local doc="$STEPS_DIR/${step_id}.json"
    local reason=""

    # --- every recorded output must exist and be non-empty -----------------
    local bad
    bad=$("$(resolve_python)" - "$doc" "$RUN_DIR" <<'PYOUT' | tr -d '\r'
import json, os, sys
doc_path, run_dir = sys.argv[1:3]
try:
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
except (OSError, ValueError) as exc:
    print(f"status document unreadable: {exc}")
    raise SystemExit(0)
problems = []
for o in doc.get("outputs") or []:
    p = o.get("path") or ""
    full = p if os.path.isabs(p) else os.path.join(run_dir, p)
    if not os.path.exists(full):
        problems.append(f"missing output {p}")
    elif os.path.isfile(full) and os.path.getsize(full) == 0:
        problems.append(f"empty output {p}")
print("; ".join(problems))
PYOUT
)
    if [[ -n "$bad" ]]; then
        printf '%s' "$bad"
        return 1
    fi

    # --- JSON hand-off documents must parse and belong to this run/step ----
    local run_in_doc step_in_doc
    run_in_doc=$(json_get "$doc" run_id "" 2>/dev/null || echo "")
    step_in_doc=$(json_get "$doc" step_id "" 2>/dev/null || echo "")
    if [[ "$run_in_doc" != "$RUN_ID" ]]; then
        printf 'status document belongs to run %s, not %s' "${run_in_doc:-<none>}" "$RUN_ID"
        return 1
    fi
    if [[ "$step_in_doc" != "$step_id" ]]; then
        printf 'status document reports step %s, not %s' "${step_in_doc:-<none>}" "$step_id"
        return 1
    fi

    # --- step-specific semantic checks -------------------------------------
    case "$step_id" in
        00_input_validation)
            local mani="$RUN_DIR/00_input_validation/manifest.tsv"
            [[ -s "$mani" ]] || { printf 'manifest.tsv missing or empty'; return 1; }
            json_get "$CONFIG_DIR/normalized_manifest.json" sample >/dev/null 2>&1 \
                || { printf 'normalized_manifest.json unreadable'; return 1; }
            ;;
        02_preprocessing)
            local fqm="$RUN_DIR/02_preprocessing/fastq_manifest.tsv"
            [[ -s "$fqm" ]] || { printf 'fastq_manifest.tsv missing or empty'; return 1; }
            local s l r lb p pu f1 f2
            while IFS=$'\t' read -r s l r lb p pu f1 f2; do
                [[ -n "$s" ]] || continue
                [[ -s "$f1" && -s "$f2" ]] || { printf 'declared FASTQ missing: %s / %s' "$f1" "$f2"; return 1; }
            done < "$fqm"
            ;;
        03_alignment)
            local aj="$RUN_DIR/03_alignment/alignment_output.json" bam bai sample
            [[ -s "$aj" ]] || { printf 'alignment_output.json missing'; return 1; }
            bam=$(json_get "$aj" sample_bam "" 2>/dev/null || echo "")
            bai=$(json_get "$aj" sample_bai "" 2>/dev/null || echo "")
            sample=$(json_get "$aj" sample "" 2>/dev/null || echo "")
            [[ -s "$bam" ]] || { printf 'sample BAM missing: %s' "$bam"; return 1; }
            [[ -s "$bai" ]] || { printf 'sample BAM index missing: %s' "$bai"; return 1; }
            validate_bam_artifact "$bam" "$sample" || return 1
            ;;
        04_processing)
            local pj="$RUN_DIR/04_processing/processing_output.json" bam sample
            [[ -s "$pj" ]] || { printf 'processing_output.json missing'; return 1; }
            bam=$(json_get "$pj" analysis_ready_bam "" 2>/dev/null || echo "")
            sample=$(json_get "$pj" sample "" 2>/dev/null || echo "")
            [[ -s "$bam" ]] || { printf 'analysis-ready BAM missing: %s' "$bam"; return 1; }
            [[ -s "${bam}.bai" ]] || { printf 'analysis-ready BAM index missing: %s.bai' "$bam"; return 1; }
            validate_bam_artifact "$bam" "$sample" || return 1
            ;;
        05_coverage_qc)
            [[ -s "$RUN_DIR/05_coverage_qc/coverage_metrics.json" ]] \
                || { printf 'coverage_metrics.json missing'; return 1; }
            ;;
        06_variant_calling)
            local vj="$RUN_DIR/06_variant_calling/variant_calling_output.json" gvcf raw sample
            [[ -s "$vj" ]] || { printf 'variant_calling_output.json missing'; return 1; }
            gvcf=$(json_get "$vj" gvcf "" 2>/dev/null || echo "")
            raw=$(json_get "$vj" raw_vcf "" 2>/dev/null || echo "")
            sample=$(json_get "$vj" sample "" 2>/dev/null || echo "")
            validate_vcf_artifact "$gvcf" "" || return 1
            validate_vcf_artifact "$raw" "$sample" || return 1
            ;;
        08_filtering|10_annotation|11_intervar)
            : # outputs already existence-checked above; optional steps are
              # re-run cheaply and are never a prerequisite for core results.
            ;;
    esac
    return 0
}

# validate_bam_artifact <bam> <expected_sample>
validate_bam_artifact() {
    local bam=$1 expect=$2
    have_command samtools || { printf 'samtools unavailable, cannot verify %s' "$(basename -- "$bam")"; return 1; }
    samtools quickcheck -q "$bam" 2>/dev/null \
        || { printf 'samtools quickcheck failed on %s' "$(basename -- "$bam")"; return 1; }
    [[ -s "${bam}.bai" || -s "${bam%.bam}.bai" ]] \
        || { printf 'BAM index missing for %s' "$(basename -- "$bam")"; return 1; }
    samtools idxstats "$bam" >/dev/null 2>&1 \
        || { printf 'BAM index unreadable for %s' "$(basename -- "$bam")"; return 1; }
    local header
    header=$(read_bam_header "$bam") \
        || { printf 'cannot read the BAM header of %s' "$(basename -- "$bam")"; return 1; }
    bam_header_sorted_by_coordinate "$header" \
        || { printf '%s is not coordinate-sorted' "$(basename -- "$bam")"; return 1; }
    if [[ -n "$expect" ]]; then
        bam_header_has_sample "$header" "$expect" \
            || { printf '%s does not carry SM:%s' "$(basename -- "$bam")" "$expect"; return 1; }
    fi
    return 0
}

# validate_vcf_artifact <vcf> <expected_sample|"">
validate_vcf_artifact() {
    local vcf=$1 expect=$2
    [[ -s "$vcf" ]] || { printf 'VCF missing or empty: %s' "$(basename -- "${vcf:-<unset>}")"; return 1; }
    have_command bcftools || { printf 'bcftools unavailable, cannot verify %s' "$(basename -- "$vcf")"; return 1; }
    bcftools view -h "$vcf" >/dev/null 2>&1 \
        || { printf 'cannot parse VCF header: %s' "$(basename -- "$vcf")"; return 1; }
    [[ -s "${vcf}.tbi" || -s "${vcf}.csi" ]] \
        || { printf 'VCF index missing for %s' "$(basename -- "$vcf")"; return 1; }
    if have_command tabix; then
        tabix -l "$vcf" >/dev/null 2>&1 \
            || { printf 'VCF index unreadable for %s' "$(basename -- "$vcf")"; return 1; }
    fi
    if [[ -n "$expect" ]]; then
        local got
        got=$(bcftools query -l "$vcf" 2>/dev/null | head -n 1 || true)
        [[ "$got" == "$expect" ]] \
            || { printf '%s sample column is %s, expected %s' "$(basename -- "$vcf")" "${got:-<none>}" "$expect"; return 1; }
    fi
    return 0
}

# step_is_reusable <step_id>
#
# resume may skip a step only when all of these hold:
#   - a status document exists and reports completed / warning / skipped
#   - next_step_ready is true
#   - the recorded configuration identity matches (checked once in main())
#   - every upstream dependency is itself reusable      (AUD, section 7)
#   - the step's artifacts pass real integrity validation (AUD-BLOCKER-003)
# A `.done` marker alone is never sufficient.
step_is_reusable() {
    local step_id=$1
    local doc="$STEPS_DIR/${step_id}.json"
    [[ -s "$doc" ]] || return 1

    # Downstream invalidation: if anything this step consumes was invalidated,
    # this step cannot be reused either.
    local dep
    for dep in ${STEP_DEPENDS[$step_id]:-}; do
        if [[ " ${INVALIDATED_STEPS[*]-} " == *" $dep "* ]]; then
            log "  [RESUME] $step_id cannot be reused: its dependency $dep was invalidated"
            return 1
        fi
    done

    local status ready
    status=$(json_get "$doc" status "")
    ready=$(json_get "$doc" next_step_ready "false")
    case "$status" in
        completed|warning|skipped) : ;;
        *) return 1 ;;
    esac
    [[ "$ready" == "true" ]] || return 1

    local why
    if ! why=$(validate_step_artifacts "$step_id"); then
        log "  [RESUME] $step_id cannot be reused: ${why:-artifact validation failed}"
        return 1
    fi
    return 0
}

should_run_step() {
    local step_id=$1

    if [[ -n "$FROM_STEP" ]]; then
        local reached=0 s
        for s in "${STEP_PLAN[@]}"; do
            [[ "$s" == "$FROM_STEP" ]] && reached=1
            [[ "$s" == "$step_id" ]] && break
        done
        (( reached == 1 )) || { log "  [SKIP] $step_id is before --from-step $FROM_STEP"; return 1; }
    fi

    if (( RESUME == 1 )) && step_is_reusable "$step_id"; then
        log "  [SKIP] $step_id already completed and still validates (resume)"
        return 1
    fi

    # This step will run, so anything downstream of it must not be reused.
    mark_step_invalidated "$step_id"
    return 0
}

# mark_step_invalidated <step_id>
# Records that a step is being re-executed, so step_is_reusable refuses to
# reuse anything that depends on it (transitively, because each step is checked
# in plan order and marks itself before its dependants are considered).
mark_step_invalidated() {
    local step_id=$1
    [[ " ${INVALIDATED_STEPS[*]-} " == *" $step_id "* ]] && return 0
    INVALIDATED_STEPS+=("$step_id")
}

# assert_from_step_inputs — with --from-step, the selected step's upstream
# artifacts must still be valid, otherwise starting there would consume
# outputs that were never verified.  (AUD, section 7)
assert_from_step_inputs() {
    [[ -n "$FROM_STEP" ]] || return 0
    local dep why
    for dep in ${STEP_DEPENDS[$FROM_STEP]:-}; do
        if [[ ! -s "$STEPS_DIR/${dep}.json" ]]; then
            die "--from-step $FROM_STEP requires $dep to have completed, but no status document exists for it.
Run the pipeline from an earlier step, or drop --from-step."
        fi
        if ! why=$(validate_step_artifacts "$dep"); then
            die "--from-step $FROM_STEP cannot start: its input from $dep is not valid.
Reason: ${why:-artifact validation failed}
Re-run from $dep (or earlier) instead."
        fi
    done
    log "--from-step $FROM_STEP: upstream artifacts from [${STEP_DEPENDS[$FROM_STEP]:-none}] validated."
}

dispatch_step() {
    case "$1" in
        00_input_validation) run_input_validation ;;
        01_raw_qc)           run_raw_qc ;;
        02_preprocessing)    run_preprocessing ;;
        03_alignment)        run_alignment ;;
        04_processing)       run_processing ;;
        05_coverage_qc)      run_coverage_qc ;;
        06_variant_calling)  run_variant_calling ;;
        08_filtering)        run_filtering ;;
        10_annotation)       run_annotation ;;
        11_intervar)         run_intervar ;;
        "$FINAL_STEP")       run_finalization ;;
        *) die "No handler for step: $1" ;;
    esac
}

# is_optional_step / is_core_step are defined once, near the step metadata
# table at the top of this file. They are not redefined here.

# gate_next_step <previous_step_id>
#
# The next step runs only when the previous one reported a terminal status of
# completed / warning / skipped AND next_step_ready is true. A zero exit code
# on its own is never sufficient.
gate_next_step() {
    local step_id=$1
    local doc="$STEPS_DIR/${step_id}.json"
    [[ -s "$doc" ]] || { warn "No status document for $step_id"; return 1; }
    local status ready
    status=$(json_get "$doc" status "")
    ready=$(json_get "$doc" next_step_ready "false")
    case "$status" in
        completed|warning|skipped) : ;;
        *) return 1 ;;
    esac
    [[ "$ready" == "true" ]] || return 1
    return 0
}

run_pipeline() {
    local step rc
    for step in "${STEP_PLAN[@]}"; do
        if ! should_run_step "$step"; then
            continue
        fi

        rc=0
        dispatch_step "$step" || rc=$?

        if (( rc != 0 )) || ! gate_next_step "$step"; then
            if is_optional_step "$step"; then
                # An optional step never invalidates the core result. It is
                # recorded here and reported by finalization, but it does not
                # change the run's terminal state to failed.
                warn "Optional step $step did not complete successfully; core results are preserved."
                RUN_HAS_WARNINGS=1
                OPTIONAL_FAILED_STEPS+=("$step")
                continue
            fi
            write_run_status failed
            set_run_marker RUN_FAILED "step $step did not satisfy the next-step conditions"
            log "============================================================"
            log "RUN FAILED at $step"
            log "  status  : $STEPS_DIR/${step}.json"
            log "  log     : $PIPELINE_LOG"
            log "============================================================"
            return 1
        fi

        if [[ -n "$TO_STEP" && "$step" == "$TO_STEP" ]]; then
            log "Reached --to-step $TO_STEP; stopping as requested."
            write_run_status stopped_at_requested_step
            return 0
        fi
    done

    # ---- terminal state  (AUD-BLOCKER-002) --------------------------------
    #
    # Reaching this point means every CORE step satisfied its gate. Optional
    # failures downgrade the run to completed-with-warnings; they never make it
    # failed, and the core raw VCF stays a valid, downloadable artifact.
    local detail="core pipeline finished; see final_validation.tsv"
    if (( ${#OPTIONAL_FAILED_STEPS[@]} > 0 )); then
        detail="core pipeline finished; optional step(s) failed: ${OPTIONAL_FAILED_STEPS[*]}"
        log "Optional step(s) failed: ${OPTIONAL_FAILED_STEPS[*]}. Core results are complete and valid."
        write_run_status completed_with_warnings
        set_run_marker RUN_COMPLETED_WITH_WARNINGS "$detail"
    elif (( RUN_HAS_WARNINGS == 1 )); then
        write_run_status completed_with_warnings
        set_run_marker RUN_COMPLETED_WITH_WARNINGS "$detail"
    else
        write_run_status completed
        set_run_marker RUN_COMPLETED "core pipeline finished"
    fi
    return 0
}

# =============================================================================
# 10. Trap handlers
#
# Bash cannot supervise arbitrary descendants. Cancellation terminates the
# children this shell started; a grandchild that detached is not reachable.
# The limitation is recorded in docs/MAIN_SH_COMPLETE_GUIDE.md —
# "28. 현재 한계".
# =============================================================================
on_signal() {
    local sig=$1
    trap - INT TERM ERR EXIT
    warn "Received SIG${sig}; cancelling run ${RUN_ID:-unknown}"
    pkill -TERM -P $$ 2>/dev/null || true
    if (( STEP_FINALIZED == 0 )) && [[ -n "$CURRENT_STEP" && -d "$STEP_WORK" ]]; then
        finish_step cancelled 130
    fi
    if [[ -n "$RUN_DIR" && -d "$RUN_DIR" ]]; then
        write_run_status cancelled
        set_run_marker RUN_CANCELLED "received SIG${sig}"
    fi
    release_run_lock
    exit 130
}

on_error() {
    local rc=$?
    local line=${BASH_LINENO[0]:-unknown}
    local cmd=${BASH_COMMAND:-unknown}
    trap - ERR EXIT
    warn "Unexpected error at line $line (exit $rc): $cmd"
    if (( STEP_FINALIZED == 0 )) && [[ -n "$CURRENT_STEP" && -d "$STEP_WORK" ]]; then
        step_check_fail "unexpected_error" "line $line: $cmd (exit $rc)"
        finish_step failed "$rc"
    fi
    if [[ -n "$RUN_DIR" && -d "$RUN_DIR" ]]; then
        write_run_status failed
        set_run_marker RUN_FAILED "unexpected error at line $line (exit $rc)"
    fi
    release_run_lock
    exit "$rc"
}

on_exit() {
    release_run_lock
}

# =============================================================================
# 11. Entry point
# =============================================================================
main() {
    local rc=0
    parse_args "$@" || rc=$?
    if (( rc == 10 )); then return 0; fi          # --help
    (( rc == 0 )) || return "$rc"

    [[ -n "$CONFIG_PATH" ]] || { usage >&2; die "--config is required"; }

    require_python
    load_config
    normalize_config

    # Build and validate the step plan before any side effect: an impossible
    # --from-step/--to-step range must be rejected before a run directory is
    # created or locked.
    build_step_plan

    initialize_run

    trap 'on_signal INT' INT
    trap 'on_signal TERM' TERM
    trap 'on_error' ERR
    trap 'on_exit' EXIT

    # ---------------------------------------------------------------------
    # Configuration snapshot / resume identity  (AUD-BLOCKER-001)
    #
    # On resume the canonical snapshot is READ FIRST and never overwritten, so
    # a changed configuration is actually detectable. On a fresh run the
    # snapshot is written normally.
    # ---------------------------------------------------------------------
    local snapshot="$CONFIG_DIR/run_config.snapshot.json"
    if (( RESUME == 1 )) && [[ -s "$snapshot" ]]; then
        local pending="$CONFIG_DIR/.run_config.requested.json"
        CONFIG_IDENTITY=$(render_config_snapshot "$pending")
        RECORDED_IDENTITY=$(json_get "$snapshot" config_identity_sha256 "" 2>/dev/null || echo "")

        if [[ -z "$RECORDED_IDENTITY" ]]; then
            rm -f -- "$pending"
            die "The existing run has no recorded configuration identity, so resume cannot prove the settings match.
Snapshot: $snapshot
Start a new run with a different run_id instead."
        fi

        if [[ "$RECORDED_IDENTITY" != "$CONFIG_IDENTITY" ]]; then
            # Keep the rejected request for inspection; never overwrite the
            # snapshot that describes what actually produced the outputs.
            local audit="$CONFIG_DIR/run_config.rejected_resume.json"
            mv -f -- "$pending" "$audit"
            log "============================================================"
            log "RESUME REFUSED — the configuration changed since this run was created."
            log "  recorded identity : $RECORDED_IDENTITY"
            log "  requested identity: $CONFIG_IDENTITY"
            log "  original config   : config/run_config.snapshot.json  (unchanged)"
            log "  rejected request  : config/run_config.rejected_resume.json"
            log "  differences:"
            report_identity_diff "$snapshot" "$audit"
            log "  Start a new run with a different run_id, or restore the original settings."
            log "============================================================"
            write_run_status resume_refused
            release_run_lock
            return 1
        fi

        # Identities match. The snapshot still is not rewritten; the incoming
        # request is retained only as an audit copy.
        mv -f -- "$pending" "$CONFIG_DIR/run_config.resume_request.json"
        log "resume identity verified against the preserved snapshot: $CONFIG_IDENTITY"
    else
        if (( RESUME == 1 )); then
            log "--resume was given but no previous snapshot exists; treating this as a fresh run."
        fi
        CONFIG_IDENTITY=$(render_config_snapshot "$snapshot")
        log "config identity: $CONFIG_IDENTITY"
    fi

    assert_from_step_inputs

    if (( CHECK_ONLY == 1 )); then
        log "--check-only: running preflight validation only. No analysis tool will be executed."
        local check_rc=0
        run_input_validation || check_rc=$?
        write_run_status check_only
        if (( check_rc == 0 )) && gate_next_step 00_input_validation; then
            log "============================================================"
            log "PRECHECK PASSED — no analysis output was produced."
            log "============================================================"
            release_run_lock
            return 0
        fi
        # Deliberately no RUN_* marker here: --check-only produces no analysis
        # output, so it must not leave a terminal marker describing a run that
        # never started. The failure is in status/steps/00_input_validation.json.
        clear_run_markers
        log "============================================================"
        log "PRECHECK FAILED — see status/steps/00_input_validation.json under $RUN_DIR"
        log "============================================================"
        release_run_lock
        return 1
    fi

    clear_run_markers
    local pipeline_rc=0
    run_pipeline || pipeline_rc=$?

    if (( pipeline_rc == 0 )); then
        log "============================================================"
        log "RUN ${RUN_TERMINAL_STATE:-FINISHED}"
        log "  run dir  : $RUN_DIR"
        [[ -n "$RAW_VCF" ]] && log "  raw VCF  : $RAW_VCF"
        log "  status   : status/run_status.json"
        log "  artifacts: artifact_manifest.json"
        log "  methods  : methods.md"
        log "============================================================"
    fi

    release_run_lock
    return "$pipeline_rc"
}

main "$@"
