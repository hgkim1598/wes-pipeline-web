#!/usr/bin/env bash
#
# Start (or restart) the FastAPI backend on a Linux deployment.
#
# The backend is two environments at once, and confusing them has broken this
# deployment twice:
#
#   * the INTERPRETER is wes-dev's python. It is selected by absolute path, so
#     no PATH ordering can take it away (2026-09-04: prepending wes-tools/bin
#     replaced `python` and uvicorn "disappeared").
#   * the ANALYSIS TOOLS are wes-tools' bwa/samtools/gatk/... They are found
#     through PATH by main.sh, which the backend runs as a subprocess, so they
#     must be on the PATH of THIS process before uvicorn starts (2026-09-17:
#     they were not, and 00_input_validation reported all eight missing).
#
# Both rules are applied here so that restarting the server does not depend on
# what the operator's shell happened to look like.
#
# Linux deployment tool. Windows development is unchanged: keep using the
# command in backend/README.md.
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

# Deployment layout. Every default is derived from $HOME: no machine-specific
# home directory is written into this repository.
DEPLOY_ROOT=${WES_DEPLOY_ROOT:-"$HOME/sideprojects/wes-web"}
CONDA_ROOT=${WES_CONDA_ROOT:-"$HOME/miniconda3"}
TOOLS_BIN=${WES_TOOLS_BIN-"$CONDA_ROOT/envs/wes-tools/bin"}
BACKEND_HOST=${WES_BACKEND_HOST:-0.0.0.0}
BACKEND_PORT=${WES_BACKEND_PORT:-8000}
HEALTH_TIMEOUT=${WES_HEALTH_TIMEOUT:-60}
STOP_TIMEOUT=${WES_STOP_TIMEOUT:-20}

usage() {
    cat <<'EOF'
Usage: script/start_backend.sh [--foreground] [-h|--help]

Default (detached): stops any backend this script previously started, then
starts uvicorn against the current release with the wes-dev interpreter and
wes-tools on PATH, waits for /api/health, and returns. The pid and log live in
<release>/runtime/.

--foreground: resolves and checks exactly the same things, then exec()s uvicorn
in place instead of detaching. For a process supervisor -- systemd runs this
mode (see script/systemd/). No pid file and no log file are written: the
supervisor owns the process, and stdout/stderr go to it (the journal). Nothing
is stopped either; restarting is the supervisor's job.

Environment overrides (defaults in parentheses):
  WES_DEPLOY_ROOT    deployment root          ($HOME/sideprojects/wes-web)
  WES_RELEASE_DIR    release to serve         ($WES_DEPLOY_ROOT/current, else this checkout)
  WES_CONDA_ROOT     conda installation       ($HOME/miniconda3)
  WES_PYTHON_BIN     backend interpreter      ($WES_CONDA_ROOT/envs/wes-dev/bin/python,
                                               else <release>/backend/.venv/bin/python)
  WES_TOOLS_BIN      pipeline tool directory  ($WES_CONDA_ROOT/envs/wes-tools/bin)
                     set to an empty string to start without it
  WES_BACKEND_HOST   uvicorn bind address     (0.0.0.0)
  WES_BACKEND_PORT   uvicorn port             (8000)
  WES_RUNTIME_DIR    pid/log directory        (<release>/runtime; detached mode only)
  WES_HEALTH_TIMEOUT seconds to wait for /api/health (60; detached mode only)
  WES_STOP_TIMEOUT   seconds to wait for a clean shutdown (20; detached mode only)

Exit code: detached -- 0 once /api/health answers, 1 otherwise (the log tail is
printed). Foreground -- whatever uvicorn exits with.
EOF
}

FOREGROUND=false
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --foreground) FOREGROUND=true ;;
    "") ;;
    *) usage >&2; printf 'ERROR: unsupported argument: %s\n' "$1" >&2; exit 2 ;;
esac

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '%-14s %s\n' "$1" "$2"; }

# --- 1. which release ------------------------------------------------------
#
# `current` is a symlink to the release being served. Resolving it here, once,
# means the pid file, the log and the started process all refer to the same
# release even if the symlink is repointed afterwards.

if [[ -n "${WES_RELEASE_DIR:-}" ]]; then
    RELEASE_DIR=$WES_RELEASE_DIR
    RELEASE_SOURCE="WES_RELEASE_DIR"
elif [[ -d "$DEPLOY_ROOT/current" ]]; then
    RELEASE_DIR="$DEPLOY_ROOT/current"
    RELEASE_SOURCE="$DEPLOY_ROOT/current"
else
    # A plain checkout with no deployment root: serve the tree this script is in.
    RELEASE_DIR=$REPO_ROOT
    RELEASE_SOURCE="this checkout (no $DEPLOY_ROOT/current)"
fi

[[ -d "$RELEASE_DIR" ]] || die "release directory does not exist: $RELEASE_DIR"
RELEASE_REAL=$(cd -- "$RELEASE_DIR" && pwd -P)

[[ -f "$RELEASE_REAL/backend/app/main.py" ]] \
    || die "not a release directory (no backend/app/main.py): $RELEASE_REAL"
[[ -f "$RELEASE_REAL/script/main.sh" ]] \
    || die "not a release directory (no script/main.sh): $RELEASE_REAL"

# Detached mode owns a pid file and a log file. Under a supervisor neither is
# ours to write: the supervisor tracks the process and captures its output, and
# a second pid file would only go stale.
RUNTIME_DIR=${WES_RUNTIME_DIR:-"$RELEASE_REAL/runtime"}
PID_FILE="$RUNTIME_DIR/backend.pid"
LOG_FILE="$RUNTIME_DIR/backend.log"
if [[ "$FOREGROUND" != "true" ]]; then
    mkdir -p -- "$RUNTIME_DIR"
fi

# --- 2. which interpreter --------------------------------------------------

if [[ -n "${WES_PYTHON_BIN:-}" ]]; then
    PYTHON_BIN=$WES_PYTHON_BIN
    [[ -x "$PYTHON_BIN" ]] || die "WES_PYTHON_BIN is not executable: $PYTHON_BIN"
elif [[ -x "$CONDA_ROOT/envs/wes-dev/bin/python" ]]; then
    PYTHON_BIN="$CONDA_ROOT/envs/wes-dev/bin/python"
elif [[ -x "$RELEASE_REAL/backend/.venv/bin/python" ]]; then
    PYTHON_BIN="$RELEASE_REAL/backend/.venv/bin/python"
else
    die "no backend interpreter found. Looked at $CONDA_ROOT/envs/wes-dev/bin/python and $RELEASE_REAL/backend/.venv/bin/python. Set WES_PYTHON_BIN."
fi

"$PYTHON_BIN" -c 'import uvicorn' 2>/dev/null \
    || die "uvicorn is not installed for $PYTHON_BIN. Install backend/requirements.txt into that environment; do not switch interpreters by changing PATH."

# --- 3. PATH for the pipeline subprocess -----------------------------------
#
# Order matters and is the one recorded after the 2026-09-04 incident: the
# interpreter's own directory first, the tool directory after it. The
# interpreter is invoked by absolute path anyway, so this ordering is belt and
# braces -- what actually matters is that TOOLS_BIN is present at all, because
# main.sh resolves bwa/samtools/gatk through PATH.

PYTHON_DIR=$(cd -- "$(dirname -- "$PYTHON_BIN")" && pwd -P)
export PATH="$PYTHON_DIR:$PATH"

if [[ -n "$TOOLS_BIN" ]]; then
    [[ -d "$TOOLS_BIN" ]] \
        || die "pipeline tool directory does not exist: $TOOLS_BIN. Set WES_TOOLS_BIN to the right path, or to an empty string to start a check_only server without analysis tools."
    export PATH="$PYTHON_DIR:$TOOLS_BIN:$PATH"
fi

# --- 4. stop what is already running ---------------------------------------
#
# Only processes this script started, identified by the pid file AND by their
# command line. Never kill by port: something else listening there is the
# operator's problem to see, not this script's to terminate.

is_our_backend() {
    local pid=$1 cmdline=""
    if [[ -r "/proc/$pid/cmdline" ]]; then
        cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    elif command -v ps >/dev/null 2>&1; then
        # No /proc (not Linux). Fall back rather than assuming the pid is ours.
        cmdline=$(ps -p "$pid" -o args= 2>/dev/null || true)
    fi
    [[ -n "$cmdline" && "$cmdline" == *uvicorn* && "$cmdline" == *app.main:app* ]]
}

stop_existing() {
    local pid waited
    [[ -f "$PID_FILE" ]] || return 0
    pid=$(tr -cd '0-9' < "$PID_FILE" || true)
    if [[ -z "$pid" ]]; then
        rm -f -- "$PID_FILE"
        return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        note "previous" "pid $pid is not running (stale pid file removed)"
        rm -f -- "$PID_FILE"
        return 0
    fi
    if ! is_our_backend "$pid"; then
        die "pid $pid from $PID_FILE is not this backend. Refusing to kill it; check the process and remove the pid file yourself."
    fi

    note "stopping" "pid $pid (SIGTERM)"
    kill -TERM "$pid" 2>/dev/null || true
    waited=0
    while kill -0 "$pid" 2>/dev/null && (( waited < STOP_TIMEOUT )); do
        sleep 1
        waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        note "stopping" "still alive after ${STOP_TIMEOUT}s (SIGKILL)"
        kill -KILL "$pid" 2>/dev/null || true
        sleep 1
    fi
    rm -f -- "$PID_FILE"
}

# Under a supervisor, stopping the previous instance is the supervisor's job --
# and the pid file belongs to detached mode, so there is nothing here to stop.
if [[ "$FOREGROUND" != "true" ]]; then
    stop_existing
fi

# Something else on the port would make every check below lie: uvicorn fails to
# bind, exits, and the health poll is answered by the foreign server instead.
# Report the holder; do not kill it.
port_holder() {
    local port=$1 detail=""
    if command -v ss >/dev/null 2>&1; then
        detail=$(ss -ltnpH 2>/dev/null | awk -v p=":$port\$" '$4 ~ p' || true)
    fi
    if [[ -z "$detail" ]] && command -v lsof >/dev/null 2>&1; then
        detail=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2 || true)
    fi
    if [[ -z "$detail" ]] && command -v netstat >/dev/null 2>&1; then
        detail=$(netstat -ltnp 2>/dev/null | awk -v p=":$port\$" '$4 ~ p' || true)
    fi
    printf '%s' "$detail"
}

PORT_HOLDER=$(port_holder "$BACKEND_PORT")
if [[ -n "$PORT_HOLDER" ]]; then
    die "port $BACKEND_PORT is already in use and it is not a backend this script started:
$PORT_HOLDER
Stop that process yourself, or set WES_BACKEND_PORT."
fi

# --- 5. start --------------------------------------------------------------
#
# setsid detaches the backend from this shell's session, so closing the SSH
# session does not take the server (and the pipeline it may be running) with it.

cd -- "$RELEASE_REAL"

# Foreground: replace this shell with uvicorn. The supervisor's MAINPID is then
# the server itself, so its SIGTERM reaches uvicorn directly rather than a
# wrapper that would have to forward it.
if [[ "$FOREGROUND" == "true" ]]; then
    note "release" "$RELEASE_REAL"
    note "resolved from" "$RELEASE_SOURCE"
    note "python" "$PYTHON_BIN"
    note "tools bin" "${TOOLS_BIN:-<none>}"
    note "listening" "$BACKEND_HOST:$BACKEND_PORT"
    note "mode" "foreground (supervisor owns the process and its output)"
    exec "$PYTHON_BIN" -m uvicorn app.main:app \
        --app-dir "$RELEASE_REAL/backend" \
        --host "$BACKEND_HOST" --port "$BACKEND_PORT"
fi

{
    printf '\n===== %s start_backend.sh =====\n' "$(date -Is 2>/dev/null || date)"
    printf 'release    %s\n' "$RELEASE_REAL"
    printf 'python     %s\n' "$PYTHON_BIN"
    printf 'tools bin  %s\n' "${TOOLS_BIN:-<none>}"
    printf 'listen     %s:%s\n' "$BACKEND_HOST" "$BACKEND_PORT"
} >> "$LOG_FILE"

if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$PYTHON_BIN" -m uvicorn app.main:app \
        --app-dir "$RELEASE_REAL/backend" \
        --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
        >> "$LOG_FILE" 2>&1 &
else
    nohup "$PYTHON_BIN" -m uvicorn app.main:app \
        --app-dir "$RELEASE_REAL/backend" \
        --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
        >> "$LOG_FILE" 2>&1 &
fi
BACKEND_PID=$!
printf '%s\n' "$BACKEND_PID" > "$PID_FILE"

# --- 6. wait for health ----------------------------------------------------
#
# The same interpreter that runs the server polls it: no curl dependency, and a
# health check that answers proves the interpreter, the app import, the config
# validation and the port binding all worked.

HEALTH_URL="http://127.0.0.1:$BACKEND_PORT/api/health"

health_json=""
health_error="no answer from $HEALTH_URL within ${HEALTH_TIMEOUT}s"
waited=0
while (( waited < HEALTH_TIMEOUT )); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        health_error="the uvicorn process (pid $BACKEND_PID) exited before answering"
        break
    fi
    if health_json=$("$PYTHON_BIN" - "$HEALTH_URL" 2>/dev/null <<'PYHEALTH'
import json
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
    payload = json.load(response)
if payload.get("status") != "ok":
    raise SystemExit(1)
print(json.dumps(payload, indent=2, sort_keys=True))
PYHEALTH
    ); then
        break
    fi
    health_json=""
    sleep 1
    waited=$((waited + 1))
done

# An answer is not proof that WE are the server answering: if uvicorn failed to
# bind, the reply came from whatever already held the port. Settle, then require
# the process this script started to still be alive.
if [[ -n "$health_json" ]]; then
    sleep 1
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        health_error="$HEALTH_URL answered, but the uvicorn started here (pid $BACKEND_PID) is gone -- another server is holding port $BACKEND_PORT"
        health_json=""
    fi
fi

if [[ -z "$health_json" ]]; then
    rm -f -- "$PID_FILE"
    printf 'ERROR: %s\n\n' "$health_error" >&2
    printf -- '--- last 40 lines of %s ---\n' "$LOG_FILE" >&2
    tail -n 40 -- "$LOG_FILE" >&2 2>/dev/null || true
    exit 1
fi

# --- 7. report -------------------------------------------------------------

note "release" "$RELEASE_REAL"
note "resolved from" "$RELEASE_SOURCE"
note "python" "$PYTHON_BIN"
note "tools bin" "${TOOLS_BIN:-<none>}"
note "pid" "$BACKEND_PID"
note "log" "$LOG_FILE"
note "listening" "$BACKEND_HOST:$BACKEND_PORT"
printf '\n%s\n' "$health_json"

# The incident this script exists for: health says ok, the run mode says full,
# and the analysis tools the pipeline needs are still not resolvable. Say so
# here rather than letting 00_input_validation say it after an upload.
if printf '%s' "$health_json" | grep -q '"runMode": "full"'; then
    if ! command -v bwa >/dev/null 2>&1; then
        printf '\nWARNING: runMode is full but bwa is not on this process PATH.\n' >&2
        printf 'A submitted run would fail in 00_input_validation. Check WES_TOOLS_BIN,\n' >&2
        printf 'then run script/server_preflight.sh before submitting anything.\n' >&2
    fi
fi

printf '\nNext: %s/script/server_preflight.sh\n' "$RELEASE_REAL"
