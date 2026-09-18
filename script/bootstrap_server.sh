#!/usr/bin/env bash
#
# First-run provisioning for a fresh Linux server.
#
# Scope, deliberately narrow -- this script PREPARES a machine. It does not
# decide whether the machine is ready (server_preflight.sh), it does not run the
# backend (start_backend.sh), and it does not manage it across reboots
# (install_systemd_service.sh). It ends by calling preflight, which is the one
# that answers "ready or not".
#
# Rules it follows:
#   * idempotent -- an environment or directory that already exists is left
#     exactly as it is. Nothing is recreated "to be sure".
#   * non-destructive -- no rm, no overwrite of an existing .env, no replacing a
#     directory that holds data. Where it cannot proceed safely it says so and
#     moves on.
#   * honest about what it cannot do -- the reference bundle and any
#     licence-gated resource are reported as operator work, not faked.
#
# Every step is labelled with what it needs:
#   [local]    filesystem only, no network, no privileges
#   [network]  downloads from the internet
#   [manual]   the operator has to do it; this script only checks and explains
#
# No step in this script needs sudo. Everything lives under $HOME. Installing
# the systemd unit does need sudo, and that is a separate script.
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

DEPLOY_ROOT=${WES_DEPLOY_ROOT:-"$HOME/sideprojects/wes-web"}
CONDA_ROOT=${WES_CONDA_ROOT:-"$HOME/miniconda3"}
PYTHON_ENV=${WES_PYTHON_ENV:-wes-dev}
TOOLS_ENV=${WES_TOOLS_ENV:-wes-tools}
PYTHON_VERSION=${WES_PYTHON_VERSION:-3.12}
RELEASE_DIR=${WES_RELEASE_DIR:-"$REPO_ROOT"}

# Conda package names for the pipeline's tools. These are PACKAGES, not the
# binaries main.sh looks for: gatk4 provides `gatk`, htslib provides `tabix` and
# `bgzip`. The list is the one in docs/MAIN_SH_COMPLETE_GUIDE.md chapter 6.
# Whether the binaries actually resolve afterwards is server_preflight.sh's
# question, and it reads main.sh's own required list to answer it.
TOOLS_PACKAGES=(bwa samtools gatk4 bcftools htslib mosdepth fastqc fastp multiqc)

DRY_RUN=false
SKIP_ENVS=false
SKIP_BEDS=false
SKIP_PREFLIGHT=false

usage() {
    cat <<'EOF'
Usage: script/bootstrap_server.sh [options]

Prepares a fresh Linux server: deployment layout, shared storage, conda
environments, capture BED resources, and a backend/.env to fill in. Ends by
running server_preflight.sh.

Safe to re-run: existing environments, directories and .env are left alone.

Options:
  --dry-run         print every command, change nothing
  --skip-envs       do not create/update conda environments (no network)
  --skip-beds       do not download capture BED files (no network)
  --skip-preflight  do not run server_preflight.sh at the end
  -h, --help        this text

Environment overrides:
  WES_DEPLOY_ROOT     deployment root        ($HOME/sideprojects/wes-web)
  WES_RELEASE_DIR     release being prepared (this checkout)
  WES_CONDA_ROOT      conda installation     ($HOME/miniconda3)
  WES_PYTHON_ENV      backend env name       (wes-dev)
  WES_TOOLS_ENV       pipeline tool env name (wes-tools)
  WES_PYTHON_VERSION  backend Python         (3.12)

Needs no sudo. The reference bundle is NOT downloaded -- see step 7.
EOF
}

while (( $# > 0 )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY_RUN=true ;;
        --skip-envs) SKIP_ENVS=true ;;
        --skip-beds) SKIP_BEDS=true ;;
        --skip-preflight) SKIP_PREFLIGHT=true ;;
        *) usage >&2; printf 'ERROR: unsupported argument: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s ==\n' "$*"; }
note() { printf '  %-12s %s\n' "$1" "$2"; }
ok() { printf '  ok           %s\n' "$*"; }
skipped() { printf '  skip         %s\n' "$*"; }

# Work the operator still has to do. Collected as we go, printed at the end --
# a message 200 lines up has already scrolled away.
MANUAL_ACTIONS=()
remember_manual() { MANUAL_ACTIONS+=("$1"); }

run_cmd() {
    printf '  >>> %s\n' "$*"
    if [[ "$DRY_RUN" == "true" ]]; then
        return 0
    fi
    "$@"
}

printf 'WES server bootstrap\n'
note "release" "$RELEASE_DIR"
note "deploy root" "$DEPLOY_ROOT"
note "conda root" "$CONDA_ROOT"
if [[ "$DRY_RUN" == "true" ]]; then
    note "mode" "dry run -- nothing will be changed"
fi

[[ -f "$RELEASE_DIR/backend/app/main.py" && -f "$RELEASE_DIR/script/main.sh" ]] \
    || die "not a release directory: $RELEASE_DIR (expected backend/app/main.py and script/main.sh)"

# --- 1. deployment layout [local] -----------------------------------------

step "1. deployment layout  [local]"

SHARED_ROOT="$DEPLOY_ROOT/shared"
for dir in "$DEPLOY_ROOT" "$DEPLOY_ROOT/releases" "$SHARED_ROOT" \
           "$SHARED_ROOT/runs" "$SHARED_ROOT/uploads" "$SHARED_ROOT/backend-data"; do
    if [[ -d "$dir" ]]; then
        skipped "exists: $dir"
    else
        run_cmd mkdir -p -- "$dir"
    fi
done

case "$RELEASE_DIR" in
    "$DEPLOY_ROOT/releases"/*)
        ok "release sits under $DEPLOY_ROOT/releases" ;;
    *)
        note "note" "this release is outside $DEPLOY_ROOT/releases."
        note "" "That is fine for a checkout, but the documented layout puts"
        note "" "releases there so 'current' can be repointed. See docs/DEPLOYMENT.md." ;;
esac

# `current` is created when absent; it is never repointed here. Switching
# releases is a deliberate deployment step with its own checklist, not a side
# effect of running bootstrap in an old release.
CURRENT_LINK="$DEPLOY_ROOT/current"
if [[ -L "$CURRENT_LINK" ]]; then
    note "current" "-> $(readlink -- "$CURRENT_LINK")"
    if [[ "$(readlink -f -- "$CURRENT_LINK" 2>/dev/null || true)" != "$(readlink -f -- "$RELEASE_DIR" 2>/dev/null || true)" ]]; then
        note "" "points at a different release; left untouched."
        remember_manual "point 'current' at this release when you mean to switch: ln -sfn \"$RELEASE_DIR\" \"$CURRENT_LINK\""
    fi
elif [[ -e "$CURRENT_LINK" ]]; then
    note "current" "exists and is NOT a symlink: $CURRENT_LINK -- left untouched"
    remember_manual "inspect $CURRENT_LINK: the layout expects a symlink to a release"
else
    run_cmd ln -s -- "$RELEASE_DIR" "$CURRENT_LINK"
fi

# --- 2. persistent storage [local] ----------------------------------------
#
# runs/, uploads/ and backend/data hold everything a release swap must not
# lose. They are symlinked out to shared/. Alternative: point WES_RUNS_ROOT /
# WES_UPLOAD_ROOT / WES_DB_PATH at the shared paths in backend/.env, which
# backend/app/config.py supports; the links are the documented default.

step "2. persistent storage  [local]"

link_shared() {
    local target=$1 link=$2 label=$3 current=""
    if [[ -L "$link" ]]; then
        current=$(readlink -f -- "$link" 2>/dev/null || true)
        if [[ "$current" == "$(readlink -f -- "$target" 2>/dev/null || true)" ]]; then
            skipped "$label already linked to shared storage"
        else
            note "$label" "symlink points elsewhere: $current -- left untouched"
            remember_manual "$label ($link) points at $current, not $target. Check which one holds the data."
        fi
        return 0
    fi
    if [[ -d "$link" ]]; then
        # rmdir only succeeds on an empty directory, which is the only case
        # where replacing it with a link loses nothing. Anything else is data.
        if rmdir -- "$link" 2>/dev/null; then
            run_cmd ln -s -- "$target" "$link"
            ok "$label was an empty directory; replaced with a link"
        else
            note "$label" "is a non-empty directory: $link -- left untouched"
            remember_manual "$label ($link) already holds data. Move it into $target yourself, then link it."
        fi
        return 0
    fi
    if [[ -e "$link" ]]; then
        note "$label" "exists and is not a directory or symlink: $link -- left untouched"
        remember_manual "inspect $link"
        return 0
    fi
    if [[ ! -d "$(dirname -- "$link")" ]]; then
        run_cmd mkdir -p -- "$(dirname -- "$link")"
    fi
    run_cmd ln -s -- "$target" "$link"
}

link_shared "$SHARED_ROOT/runs" "$RELEASE_DIR/runs" "runs"
link_shared "$SHARED_ROOT/uploads" "$RELEASE_DIR/uploads" "uploads"
link_shared "$SHARED_ROOT/backend-data" "$RELEASE_DIR/backend/data" "backend data"

# --- 3. conda [check] ------------------------------------------------------

step "3. conda  [check]"

CONDA_BIN=""
if [[ -x "$CONDA_ROOT/bin/conda" ]]; then
    CONDA_BIN="$CONDA_ROOT/bin/conda"
elif command -v conda >/dev/null 2>&1; then
    CONDA_BIN=$(command -v conda)
    note "note" "no conda at $CONDA_ROOT; using the one on PATH instead."
    note "" "Environments are still created at prefixes under WES_CONDA_ROOT,"
    note "" "which is where start_backend.sh looks for them."
fi

if [[ -z "$CONDA_BIN" ]]; then
    # Deliberately not installed here: it is a large third-party installer whose
    # placement and channel policy belong to whoever owns the machine.
    note "conda" "NOT FOUND (looked at $CONDA_ROOT/bin/conda and PATH)"
    remember_manual "install a conda distribution (Miniconda/Miniforge) at $CONDA_ROOT, then re-run this script"
    SKIP_ENVS=true
else
    ok "$CONDA_BIN"
fi

env_prefix() { printf '%s/envs/%s' "$CONDA_ROOT" "$1"; }

# --- 4. backend Python environment [network] -------------------------------

step "4. backend Python env '$PYTHON_ENV'  [network]"

PY_PREFIX=$(env_prefix "$PYTHON_ENV")
if [[ "$SKIP_ENVS" == "true" ]]; then
    skipped "environment work disabled"
elif [[ -d "$PY_PREFIX" ]]; then
    ok "exists: $PY_PREFIX"
    run_cmd "$PY_PREFIX/bin/python" -m pip install --quiet -r "$RELEASE_DIR/backend/requirements.txt"
    ok "backend requirements installed/up to date"
else
    run_cmd "$CONDA_BIN" create -y -p "$PY_PREFIX" "python=$PYTHON_VERSION"
    run_cmd "$PY_PREFIX/bin/python" -m pip install --quiet -r "$RELEASE_DIR/backend/requirements.txt"
fi

# --- 5. pipeline tool environment [network] --------------------------------

step "5. pipeline tools env '$TOOLS_ENV'  [network]"

TOOLS_PREFIX=$(env_prefix "$TOOLS_ENV")
if [[ "$SKIP_ENVS" == "true" ]]; then
    skipped "environment work disabled"
elif [[ -d "$TOOLS_PREFIX" ]]; then
    # Not touched: re-solving a bioconda environment can move tool versions
    # under a pipeline whose results were produced with the current ones.
    ok "exists: $TOOLS_PREFIX (left as it is)"
    note "note" "preflight checks whether the tools actually resolve"
else
    note "note" "this downloads several hundred MB from bioconda and takes a while"
    run_cmd "$CONDA_BIN" create -y -p "$TOOLS_PREFIX" \
        -c conda-forge -c bioconda "${TOOLS_PACKAGES[@]}"
fi

# --- 6. capture BED resources [network] ------------------------------------

step "6. capture BED resources  [network]"

BED_SCRIPT="$RELEASE_DIR/script/download_capture_beds.sh"
if [[ "$SKIP_BEDS" == "true" ]]; then
    skipped "BED download disabled"
elif [[ ! -x "$BED_SCRIPT" ]]; then
    note "note" "not executable: $BED_SCRIPT"
    remember_manual "run: bash $BED_SCRIPT all"
else
    # That script already verifies SHA-256, validates BED shape and skips files
    # it has already verified. Nothing to reimplement here.
    run_cmd "$BED_SCRIPT" all
fi

# --- 7. reference bundle [manual] ------------------------------------------
#
# Not downloaded, and that is a decision rather than an omission: it is tens of
# gigabytes, its URLs are not pinned anywhere in this repository, and a wrong or
# partial reference is worse than an absent one (main.sh is fail-closed).

step "7. reference bundle  [manual]"

cat <<'EOF'
  This script does not download the reference bundle. Prepare it once per
  server, outside the release directory, and point backend/.env at it:

    <reference>.fasta            + .fai + .dict
    <reference>.fasta.64.{amb,ann,bwt,pac,sa}   (or the unsuffixed set)
    known-sites VCF, at least one, each with .tbi or .csi

  What each file is for: docs/MAIN_SH_COMPLETE_GUIDE.md section 4.2.
  server_preflight.sh verifies all of it, including the index naming rule bwa
  actually uses.
EOF
remember_manual "prepare the reference bundle and set WES_REFERENCE_FASTA / WES_KNOWN_SITES / WES_CONTIG_STYLE in backend/.env"

# --- 8. backend/.env [local] -----------------------------------------------

step "8. backend/.env  [local]"

ENV_FILE="$RELEASE_DIR/backend/.env"
ENV_EXAMPLE="$RELEASE_DIR/backend/.env.example"

if [[ -f "$ENV_FILE" ]]; then
    # Never overwritten: it is the one file on the server holding operator
    # decisions, and a fresh copy would silently revert them.
    ok "exists: $ENV_FILE (left as it is)"
elif [[ -f "$ENV_EXAMPLE" ]]; then
    run_cmd cp -- "$ENV_EXAMPLE" "$ENV_FILE"
    if [[ -f "$ENV_FILE" ]]; then
        ok "created from .env.example -- values still need filling in"
    fi
else
    note "note" "no .env and no .env.example found"
    remember_manual "create $ENV_FILE"
fi

if [[ -f "$ENV_FILE" ]]; then
    empty_keys=()
    for key in WES_RUN_MODE WES_CONTIG_STYLE WES_REFERENCE_FASTA WES_KNOWN_SITES; do
        value=$(sed -n "s/^[[:space:]]*$key[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | head -1 || true)
        if [[ -z "$value" ]]; then
            empty_keys+=("$key")
        fi
    done
    if (( ${#empty_keys[@]} > 0 )); then
        note "to fill in" "${empty_keys[*]}"
        remember_manual "fill in ${empty_keys[*]} in $ENV_FILE"
    else
        ok "the four operator-supplied keys have values (preflight checks what they point at)"
    fi
fi

# --- 9. readiness [check] --------------------------------------------------

step "9. readiness  [check]"

PREFLIGHT="$RELEASE_DIR/script/server_preflight.sh"
PREFLIGHT_RC=0
if [[ "$SKIP_PREFLIGHT" == "true" || "$DRY_RUN" == "true" ]]; then
    skipped "preflight not run"
elif [[ -x "$PREFLIGHT" ]]; then
    printf '  running %s\n\n' "$PREFLIGHT"
    "$PREFLIGHT" || PREFLIGHT_RC=$?
else
    note "note" "not executable: $PREFLIGHT"
    PREFLIGHT_RC=0
fi

# --- summary ---------------------------------------------------------------

step "still to do"

if (( ${#MANUAL_ACTIONS[@]} == 0 )); then
    printf '  nothing this script could see.\n'
else
    for action in "${MANUAL_ACTIONS[@]}"; do
        printf '  - %s\n' "$action"
    done
fi

step "next"

cat <<EOF
  1. finish the items above
  2. $PREFLIGHT                       # until it reports FAIL 0
  3. $RELEASE_DIR/script/start_backend.sh     # start it once by hand
  4. $RELEASE_DIR/script/install_systemd_service.sh   # start at boot (needs sudo)

  Full procedure and the reasoning behind this layout: docs/DEPLOYMENT.md
EOF

# Bootstrap succeeded at what it does even when the server is not ready yet:
# preflight's verdict is reported, not swallowed.
if (( PREFLIGHT_RC != 0 )); then
    printf '\npreflight reported failures (exit %s). The server is prepared but NOT ready.\n' "$PREFLIGHT_RC"
    exit "$PREFLIGHT_RC"
fi
