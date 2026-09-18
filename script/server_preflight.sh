#!/usr/bin/env bash
#
# Deployment preflight: is THIS server ready to start a full WES run?
#
# This is not a second copy of the pipeline's own validation. main.sh's
# 00_input_validation still checks everything it checks, per run, against the
# actual submitted FASTQ. What this script answers is the question that comes
# earlier and has no run to attach itself to:
#
#     "If someone submits a job on this box right now, will it die in the first
#      second for a reason the operator could have seen beforehand?"
#
# The two failures that motivated it, both observed on 2026-09-17:
#   * the backend process was started without wes-tools/bin on PATH, so every
#     analysis tool was reported missing by 00_input_validation;
#   * a new release directory was created without resources/capture_beds, so
#     the capture-kit registry resolved to BED files that did not exist.
#
# Neither was visible in GET /api/health, and both are cheap to detect here.
#
# Source of truth, never a copy:
#   * the required-tool list is read out of script/main.sh itself;
#   * capture-kit paths and checksums are read out of config/capture_kits.grch38.json,
#     resolved relative to the registry file exactly as main.sh resolves them;
#   * reference-bundle locations are read from backend/.env with the same
#     precedence backend/app/config.py uses (a real environment variable wins).
#
# Linux deployment tool. Running it on the Windows development machine is
# harmless but will report the analysis tools as missing, because they are.
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

MAIN_SH="$REPO_ROOT/script/main.sh"
CAPTURE_KIT_REGISTRY="$REPO_ROOT/config/capture_kits.grch38.json"
ENV_FILE=${WES_ENV_FILE:-"$REPO_ROOT/backend/.env"}

usage() {
    cat <<'EOF'
Usage: script/server_preflight.sh [-h|--help]

Checks that this server can start a full WES run: pipeline tools on PATH,
reference bundle, capture-kit BED files and their checksums, persistent
storage, and disk/memory as information.

Run it from the release you are about to serve, e.g.

    ~/sideprojects/wes-web/current/script/server_preflight.sh

Environment overrides:
  WES_ENV_FILE       backend .env to read      (default: <release>/backend/.env)
  WES_PYTHON_BIN     interpreter for JSON/sha256 work (default: python3, python)

Every reference and storage value is read from the environment first and from
the .env file second, which is the precedence backend/app/config.py uses.

Exit code: 0 when no check FAILed, 1 otherwise. WARN does not fail the run.
EOF
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) usage >&2; printf 'ERROR: unsupported argument: %s\n' "$1" >&2; exit 2 ;;
esac

# --- reporting -------------------------------------------------------------

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
SKIP_COUNT=0

report() { printf '%-6s %-30s %s\n' "$1" "$2" "$3"; }
pass() { PASS_COUNT=$((PASS_COUNT + 1)); report "[PASS]" "$1" "$2"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); report "[FAIL]" "$1" "$2"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); report "[WARN]" "$1" "$2"; }
skip() { SKIP_COUNT=$((SKIP_COUNT + 1)); report "[SKIP]" "$1" "$2"; }
info() { report "[INFO]" "$1" "$2"; }
section() { printf '\n== %s ==\n' "$1"; }

die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

# --- settings: environment first, then .env (mirrors config.py) ------------

trim_ws() {
    local s=$1
    s=${s#"${s%%[![:space:]]*}"}
    s=${s%"${s##*[![:space:]]}"}
    printf '%s' "$s"
}

declare -A ENV_FILE_VALUES=()

load_env_file() {
    local path=$1 line key value
    if [[ ! -f "$path" ]]; then
        return 0
    fi
    while IFS= read -r line || [[ -n "$line" ]]; do
        line=${line%$'\r'}          # the repo is edited on Windows; tolerate CRLF
        line=$(trim_ws "$line")
        if [[ -z "$line" || "$line" == "#"* || "$line" != *"="* ]]; then
            continue
        fi
        key=$(trim_ws "${line%%=*}")
        value=$(trim_ws "${line#*=}")
        value=${value%\"}; value=${value#\"}
        value=${value%\'}; value=${value#\'}
        if [[ -z "$key" ]]; then
            continue
        fi
        # First occurrence wins, matching _load_env_file()'s "do not override".
        if [[ -z "${ENV_FILE_VALUES[$key]+x}" ]]; then
            ENV_FILE_VALUES[$key]=$value
        fi
    done < "$path"
}

setting() {
    local key=$1 default=${2:-}
    if [[ -n "${!key:-}" ]]; then
        printf '%s' "${!key}"
        return 0
    fi
    printf '%s' "${ENV_FILE_VALUES[$key]-$default}"
}

resolve_python() {
    local candidate
    for candidate in "${WES_PYTHON_BIN:-}" python3 python; do
        if [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1 \
           && "$candidate" -c 'import json,hashlib,sys' >/dev/null 2>&1; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

# --- 1. release layout -----------------------------------------------------

section "release layout"

info "repo root" "$REPO_ROOT"
if [[ -L "$REPO_ROOT" ]]; then
    info "release" "$REPO_ROOT -> $(readlink -f -- "$REPO_ROOT" 2>/dev/null || true)"
fi

if [[ -f "$MAIN_SH" ]]; then
    pass "pipeline script" "$MAIN_SH"
else
    fail "pipeline script" "missing: $MAIN_SH"
fi

if [[ -f "$ENV_FILE" ]]; then
    pass "backend .env" "$ENV_FILE"
    load_env_file "$ENV_FILE"
else
    # Not fatal on its own: every value may come from the process environment.
    warn "backend .env" "not found: $ENV_FILE (reading the environment only)"
fi

RUN_MODE=$(setting WES_RUN_MODE check_only)
info "run mode" "$RUN_MODE"
if [[ "$RUN_MODE" != "full" && "$RUN_MODE" != "check_only" ]]; then
    fail "run mode" "invalid WES_RUN_MODE: '$RUN_MODE' (backend refuses to start)"
fi

PYTHON_BIN=$(resolve_python) || die "no working Python interpreter found (tried python3, python)"
info "python" "$PYTHON_BIN"

# --- 2. pipeline tools -----------------------------------------------------
#
# The list is main.sh's own `validate_tools` array. Extracting it keeps one
# source of truth: if that line moves, this script fails loudly instead of
# checking a stale copy and reporting a readiness it cannot vouch for.

section "pipeline tools"

REQUIRED_TOOLS_LINE=$(sed -n 's/^[[:space:]]*local required=(\(.*\))[[:space:]]*$/\1/p' "$MAIN_SH" 2>/dev/null | head -1 || true)

if [[ -z "$REQUIRED_TOOLS_LINE" ]]; then
    fail "required tool list" \
        "could not read validate_tools()'s 'local required=(...)' from main.sh; update this script rather than guessing the list"
else
    read -r -a REQUIRED_TOOLS <<< "$REQUIRED_TOOLS_LINE"
    for tool in "${REQUIRED_TOOLS[@]}"; do
        if resolved=$(command -v "$tool" 2>/dev/null); then
            pass "tool $tool" "$resolved"
        else
            fail "tool $tool" "not on PATH"
        fi
    done
fi

# main.sh treats MultiQC as a warning, not a failure (MULTIQC_MISSING): per-lane
# FastQC still runs, only the aggregated report is unavailable. Same verdict here.
if resolved=$(command -v multiqc 2>/dev/null); then
    pass "tool multiqc" "$resolved"
else
    warn "tool multiqc" "not on PATH; per-lane FastQC still runs, aggregated report unavailable"
fi

info "PATH" "$PATH"

# --- 3. reference bundle ---------------------------------------------------
#
# File-level presence only. main.sh's validate_reference_bundle() does the
# structural work (contig order, lengths, naming convention); duplicating that
# here would be a second validation framework, which this script must not be.
# The BWA index rule is reproduced because it decides presence, not structure:
# bwa probes "<ref>.64.bwt" first and never falls back to the other prefix.

section "reference bundle"

REFERENCE_FASTA=$(setting WES_REFERENCE_FASTA)
CONTIG_STYLE=$(setting WES_CONTIG_STYLE)
ASSEMBLY=$(setting WES_ASSEMBLY GRCh38)
KNOWN_SITES_RAW=$(setting WES_KNOWN_SITES)
DBSNP_VCF=$(setting WES_DBSNP_VCF)

info "assembly" "$ASSEMBLY"

if [[ -z "$CONTIG_STYLE" ]]; then
    fail "contig style" "WES_CONTIG_STYLE is not set; read the first column of the reference .fai and declare it"
else
    # Declared only. main.sh compares it against the real .fai at run time.
    info "contig style" "$CONTIG_STYLE (declared; main.sh verifies it against the .fai)"
fi

check_file() {
    local path=$1 label=$2
    if [[ -z "$path" ]]; then
        fail "$label" "not configured"
        return 0
    fi
    if [[ -s "$path" ]]; then
        pass "$label" "$path"
    else
        fail "$label" "missing or empty: $path"
    fi
}

if [[ -z "$REFERENCE_FASTA" ]]; then
    fail "reference FASTA" "WES_REFERENCE_FASTA is not set"
else
    check_file "$REFERENCE_FASTA" "reference FASTA"
    check_file "${REFERENCE_FASTA}.fai" "reference .fai"
    # os.path.splitext(ref)[0] + ".dict", the same rule main.sh applies.
    check_file "${REFERENCE_FASTA%.*}.dict" "sequence dictionary"

    bwa_prefix=""
    for suffix in ".64" ""; do
        if [[ -f "${REFERENCE_FASTA}${suffix}.bwt" ]]; then
            bwa_prefix="${REFERENCE_FASTA}${suffix}"
            break
        fi
    done
    if [[ -z "$bwa_prefix" ]]; then
        fail "BWA index" "neither ${REFERENCE_FASTA}.64.bwt nor ${REFERENCE_FASTA}.bwt exists; run 'bwa index'"
    else
        missing=()
        for ext in amb ann bwt pac sa; do
            if [[ ! -s "${bwa_prefix}.${ext}" ]]; then
                missing+=(".${ext}")
            fi
        done
        if (( ${#missing[@]} > 0 )); then
            fail "BWA index" "incomplete at ${bwa_prefix}.*: missing ${missing[*]} (bwa resolves this prefix and never falls back)"
        else
            pass "BWA index" "${bwa_prefix}.* complete"
        fi
    fi
fi

check_indexed_vcf() {
    local path=$1 label=$2
    check_file "$path" "$label"
    if [[ -s "$path" ]]; then
        if [[ -s "${path}.tbi" || -s "${path}.csi" ]]; then
            pass "$label index" "$(if [[ -s "${path}.tbi" ]]; then printf '%s' "${path}.tbi"; else printf '%s' "${path}.csi"; fi)"
        else
            fail "$label index" "missing (.tbi or .csi): $path"
        fi
    fi
}

if [[ -z "$KNOWN_SITES_RAW" ]]; then
    fail "known-sites" "WES_KNOWN_SITES is not set; BQSR needs at least one known-sites VCF"
else
    known_index=0
    IFS=',' read -r -a known_sites <<< "$KNOWN_SITES_RAW"
    for site in "${known_sites[@]}"; do
        site=$(trim_ws "$site")
        if [[ -z "$site" ]]; then
            continue
        fi
        known_index=$((known_index + 1))
        check_indexed_vcf "$site" "known-sites $known_index"
    done
    if (( known_index == 0 )); then
        fail "known-sites" "WES_KNOWN_SITES contains no usable path"
    fi
fi

if [[ -z "$DBSNP_VCF" ]]; then
    # Optional by design: without it rsIDs are not added, variant calling still runs.
    skip "dbSNP" "WES_DBSNP_VCF not set (optional; rsIDs are not annotated)"
else
    check_indexed_vcf "$DBSNP_VCF" "dbSNP"
fi

# --- 4. capture-kit registry ----------------------------------------------
#
# Registry entry present != BED present. That distinction is the whole point of
# this section: on 2026-09-17 the registry was intact and the BED files were not
# in the release at all.

section "capture-kit registry"

if [[ ! -f "$CAPTURE_KIT_REGISTRY" ]]; then
    fail "capture registry" "missing: $CAPTURE_KIT_REGISTRY"
else
    pass "capture registry" "$CAPTURE_KIT_REGISTRY"
    registry_report=$("$PYTHON_BIN" - "$CAPTURE_KIT_REGISTRY" <<'PYREGISTRY' || true
"""Report one line per capture-kit BED: STATUS<TAB>label<TAB>message.

Paths are resolved relative to the realpath of the registry file's directory,
which is how main.sh's resolve_capture_kit_profile() resolves them. Only
status=confirmed kits are checked: the backend refuses anything else
(config_builder.resolve_capture_kit_id), so an unconfirmed kit cannot fail a
run and must not fail this preflight either.
"""
import hashlib
import json
import os
import sys

registry_path = sys.argv[1]
rows = []


def emit(status, label, message):
    rows.append(f"{status}\t{label}\t{message}")


try:
    with open(registry_path, encoding="utf-8") as fh:
        doc = json.load(fh)
except Exception as exc:  # noqa: BLE001
    emit("FAIL", "capture registry", f"cannot read: {exc}")
    print("\n".join(rows))
    raise SystemExit(0)

kits = doc.get("kits")
if not isinstance(kits, dict):
    emit("FAIL", "capture registry", "no 'kits' object")
    print("\n".join(rows))
    raise SystemExit(0)

base = os.path.dirname(os.path.realpath(registry_path))


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


for kit_id in sorted(kits):
    profile = kits[kit_id] if isinstance(kits[kit_id], dict) else {}
    status = str(profile.get("status", "")).strip().lower()
    # Keep "<kit> coverage" inside the report's label column.
    short = kit_id if len(kit_id) <= 20 else kit_id[:17] + "..."

    if status != "confirmed":
        emit("SKIP", short,
             f"status='{status or 'unknown'}'; the backend does not accept it, "
             "so its BED files are not required")
        continue

    for role, path_key, sha_key in (
        ("target", "target_bed", "target_bed_sha256"),
        ("coverage", "coverage_bed", "coverage_bed_sha256"),
    ):
        raw = str(profile.get(path_key, "") or "").strip()
        expected = str(profile.get(sha_key, "") or "").strip().lower()
        if not raw:
            # coverage_bed defaults to target_bed in main.sh; nothing to check twice.
            if role == "coverage":
                emit("SKIP", f"{short} {role}", "not declared; main.sh reuses target_bed")
                continue
            emit("FAIL", f"{short} {role}", f"{path_key} is not set in the registry")
            continue

        resolved = os.path.expanduser(raw)
        resolved = os.path.realpath(
            resolved if os.path.isabs(resolved) else os.path.join(base, resolved)
        )
        if not os.path.isfile(resolved) or os.path.getsize(resolved) == 0:
            emit("FAIL", f"{short} {role}",
                 f"BED missing or empty: {resolved} "
                 "(registry entry exists; the file does not)")
            continue
        if not expected:
            emit("FAIL", f"{short} {role}", f"{sha_key} is not set in the registry")
            continue
        actual = sha256_of(resolved)
        if actual != expected:
            emit("FAIL", f"{short} {role}",
                 f"sha256 mismatch: registry {expected[:12]}... file {actual[:12]}... ({resolved})")
        else:
            emit("PASS", f"{short} {role}", f"{os.path.basename(resolved)} sha256 ok")

print("\n".join(rows))
PYREGISTRY
)
    if [[ -z "$registry_report" ]]; then
        fail "capture registry" "checker produced no output"
    else
        while IFS=$'\t' read -r status label message; do
            if [[ -z "$status" ]]; then
                continue
            fi
            case "$status" in
                PASS) pass "$label" "$message" ;;
                FAIL) fail "$label" "$message" ;;
                SKIP) skip "$label" "$message" ;;
                *) info "$label" "$message" ;;
            esac
        done <<< "$registry_report"
    fi
fi

# --- 5. persistent storage -------------------------------------------------
#
# Defaults mirror backend/app/config.py: RUNS_ROOT, UPLOAD_ROOT and DB_PATH fall
# back to paths inside the repository (that is, inside the release) unless the
# operator overrides them. A release swap then leaves past runs behind, which is
# the reason the deployment keeps them in shared/ and links them in.

section "persistent storage"

RUNS_ROOT=$(setting WES_RUNS_ROOT "$REPO_ROOT/runs")
UPLOAD_ROOT=$(setting WES_UPLOAD_ROOT "$REPO_ROOT/uploads")
DB_PATH=$(setting WES_DB_PATH "$REPO_ROOT/backend/data/app.db")

check_persistent_dir() {
    local path=$1 label=$2 target=""
    if [[ -L "$path" ]]; then
        target=$(readlink -f -- "$path" 2>/dev/null || true)
    fi
    if [[ ! -e "$path" ]]; then
        warn "$label" "does not exist yet: $path (the backend creates it at startup)"
        return 0
    fi
    if [[ ! -d "$path" ]]; then
        fail "$label" "exists but is not a directory: $path"
        return 0
    fi
    if [[ ! -w "$path" ]]; then
        fail "$label" "not writable: $path"
        return 0
    fi
    if [[ -n "$target" ]]; then
        pass "$label" "$path -> $target"
    else
        local resolved
        resolved=$(readlink -f -- "$path" 2>/dev/null || printf '%s' "$path")
        case "$resolved" in
            "$REPO_ROOT"/*)
                warn "$label" "real directory inside the release: $resolved (a release swap leaves it behind; link it to shared storage)" ;;
            *)
                pass "$label" "$resolved" ;;
        esac
    fi
}

check_persistent_dir "$RUNS_ROOT" "runs root"
check_persistent_dir "$UPLOAD_ROOT" "uploads root"
check_persistent_dir "$(dirname -- "$DB_PATH")" "backend data dir"

if [[ -f "$DB_PATH" ]]; then
    pass "job database" "$(readlink -f -- "$DB_PATH" 2>/dev/null || printf '%s' "$DB_PATH")"
else
    # Not a failure: db.py creates it. It does mean this server has no job history.
    warn "job database" "not present yet: $DB_PATH (created on first start; no job history on this server)"
fi

# --- 6. machine resources (information only) -------------------------------
#
# No thresholds here on purpose. main.sh computes its own requirement per run
# (roughly FASTQ bytes * 7 + 20 GiB) and refuses the run itself when it is short;
# inventing a second number here would only disagree with it.

section "machine resources"

if command -v df >/dev/null 2>&1; then
    df_target=$RUNS_ROOT
    if [[ ! -e "$df_target" ]]; then
        df_target=$REPO_ROOT
    fi
    info "disk (runs root)" "$(df -h -- "$df_target" 2>/dev/null | tail -1 || printf 'unavailable')"
fi

if command -v free >/dev/null 2>&1; then
    info "memory" "$(free -h 2>/dev/null | awk '/^Mem:/ {printf "total %s, available %s", $2, $7}' || printf 'unavailable')"
    info "swap" "$(free -h 2>/dev/null | awk '/^Swap:/ {printf "total %s, used %s", $2, $3}' || printf 'unavailable')"
fi

if command -v nproc >/dev/null 2>&1; then
    info "cpu" "$(nproc) logical cores; WES_THREADS=$(setting WES_THREADS 4), WES_JAVA_MEM_GB=$(setting WES_JAVA_MEM_GB 8)"
fi

# --- summary ---------------------------------------------------------------

section "summary"

printf 'PASS %d  FAIL %d  WARN %d  SKIP %d\n' \
    "$PASS_COUNT" "$FAIL_COUNT" "$WARN_COUNT" "$SKIP_COUNT"

if (( FAIL_COUNT > 0 )); then
    cat >&2 <<EOF

Not ready. Fix the FAIL lines above before submitting a run.
A run started now would fail in 00_input_validation, which costs an upload and
produces a failed run directory for a reason already visible here.
EOF
    exit 1
fi

if (( WARN_COUNT > 0 )); then
    printf '\nReady, with warnings. Read the WARN lines: none of them stops a run,\n'
    printf 'but they describe state that will matter at the next release swap.\n'
else
    printf '\nReady.\n'
fi

printf 'This checks the server, not a submission: main.sh still validates the\n'
printf 'actual FASTQ, contig style and disk requirement for each run.\n'
