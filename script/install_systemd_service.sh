#!/usr/bin/env bash
#
# Install the WES backend as a systemd service, so a reboot brings it back.
#
# This script does one thing: it renders script/systemd/wes-backend.service.template
# for THIS machine and hands it to systemd. It does not start backends, check
# readiness or provision anything -- those are start_backend.sh,
# server_preflight.sh and bootstrap_server.sh respectively.
#
# The unit runs `start_backend.sh --foreground`, so the rules about which
# interpreter and which PATH the backend gets stay in one place instead of being
# duplicated into a unit file.
#
# sudo: --system mode needs it, for three commands, each announced before it runs.
#       --user mode needs none (see the linger note at the end).
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
TEMPLATE="$SCRIPT_DIR/systemd/wes-backend.service.template"

DEPLOY_ROOT=${WES_DEPLOY_ROOT:-"$HOME/sideprojects/wes-web"}
CONDA_ROOT=${WES_CONDA_ROOT:-"$HOME/miniconda3"}
SERVICE_NAME=${WES_SERVICE_NAME:-wes-backend}

MODE=system
DRY_RUN=false

usage() {
    cat <<'EOF'
Usage: script/install_systemd_service.sh [--system|--user] [--dry-run] [-h]

  --system   install to /etc/systemd/system (default). Starts at boot.
             Needs sudo for three commands, each printed before it runs.
  --user     install to ~/.config/systemd/user. No sudo, but see the linger
             note printed at the end -- without it the service starts at
             login, not at boot.
  --dry-run  render the unit and print every command, change nothing.

Environment overrides:
  WES_DEPLOY_ROOT   deployment root      ($HOME/sideprojects/wes-web)
  WES_CONDA_ROOT    conda installation   ($HOME/miniconda3)
  WES_SERVICE_NAME  unit name            (wes-backend)

Per-host settings (port, bind address, storage roots) do NOT belong in the
unit: put them in $WES_DEPLOY_ROOT/shared/backend.env, which the unit reads if
it exists.

The service is enabled but NOT started: run server_preflight.sh first, then
start it yourself.
EOF
}

while (( $# > 0 )); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --system) MODE=system ;;
        --user) MODE=user ;;
        --dry-run) DRY_RUN=true ;;
        *) usage >&2; printf 'ERROR: unsupported argument: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s ==\n' "$*"; }

# Announce anything that changes the system, then run it. Nothing that needs
# privileges happens without the command being visible first.
run_cmd() {
    printf '>>> %s\n' "$*"
    if [[ "$DRY_RUN" == "true" ]]; then
        return 0
    fi
    "$@"
}

# --- 1. can this machine run the unit at all -------------------------------

step "checks"

[[ -f "$TEMPLATE" ]] || die "template not found: $TEMPLATE"

command -v systemctl >/dev/null 2>&1 \
    || die "systemctl not found. This host does not use systemd; keep using script/start_backend.sh, or run it from your own supervisor."
[[ -d /run/systemd/system ]] \
    || die "systemd is not the running init on this host (no /run/systemd/system). Nothing to install into."

ENTRYPOINT="$DEPLOY_ROOT/current/script/start_backend.sh"
if [[ ! -x "$ENTRYPOINT" ]]; then
    die "the unit's ExecStart would not be runnable: $ENTRYPOINT
Create the deployment layout first (script/bootstrap_server.sh), point
$DEPLOY_ROOT/current at a release, and make sure the script is executable."
fi
printf 'entrypoint    %s\n' "$ENTRYPOINT"
printf 'deploy root   %s\n' "$DEPLOY_ROOT"
printf 'conda root    %s\n' "$CONDA_ROOT"
printf 'mode          %s\n' "$MODE"

# --- 2. render -------------------------------------------------------------

step "render"

if [[ "$MODE" == "system" ]]; then
    USER_LINE="User=$(id -un)"
    WANTED_BY="multi-user.target"
    UNIT_DIR="/etc/systemd/system"
    SYSTEMCTL=(systemctl)
    NEEDS_SUDO=true
else
    # A user unit already runs as the user; a User= line is invalid there.
    USER_LINE="# (user unit: runs as $(id -un))"
    WANTED_BY="default.target"
    UNIT_DIR="$HOME/.config/systemd/user"
    SYSTEMCTL=(systemctl --user)
    NEEDS_SUDO=false
fi

UNIT_FILE="$UNIT_DIR/$SERVICE_NAME.service"
RENDERED=$(mktemp "${TMPDIR:-/tmp}/$SERVICE_NAME.service.XXXXXX") \
    || die "could not create a temporary file"
trap 'rm -f -- "${RENDERED:-}"' EXIT

sed \
    -e "s|__DEPLOY_ROOT__|$DEPLOY_ROOT|g" \
    -e "s|__CONDA_ROOT__|$CONDA_ROOT|g" \
    -e "s|__USER_LINE__|$USER_LINE|g" \
    -e "s|__WANTED_BY__|$WANTED_BY|g" \
    "$TEMPLATE" > "$RENDERED"

if grep -q '__[A-Z_]*__' "$RENDERED"; then
    printf '%s\n' "$(grep -n '__[A-Z_]*__' "$RENDERED")" >&2
    die "the rendered unit still contains placeholders (lines above). Refusing to install it."
fi

printf 'rendered      %s -> %s\n' "$(basename -- "$TEMPLATE")" "$UNIT_FILE"

if [[ "$DRY_RUN" == "true" ]]; then
    step "rendered unit (--dry-run, nothing installed)"
    cat -- "$RENDERED"
fi

# Replacing an existing unit is the normal case on a redeploy. Show what
# changes rather than swapping it silently.
if [[ -f "$UNIT_FILE" ]]; then
    if command -v diff >/dev/null 2>&1 && ! diff -q -- "$UNIT_FILE" "$RENDERED" >/dev/null 2>&1; then
        step "existing unit differs"
        diff -u -- "$UNIT_FILE" "$RENDERED" || true
    else
        printf 'existing unit is identical; install is a no-op\n'
    fi
fi

# --- 3. install ------------------------------------------------------------

step "install"

if [[ "$NEEDS_SUDO" == "true" ]]; then
    cat <<EOF
The next three commands need root. They are the only privileged operations here:
  install -m 0644 <rendered unit> $UNIT_FILE
  systemctl daemon-reload
  systemctl enable $SERVICE_NAME.service
EOF
    run_cmd sudo install -D -m 0644 -- "$RENDERED" "$UNIT_FILE"
    run_cmd sudo systemctl daemon-reload
    run_cmd sudo systemctl enable "$SERVICE_NAME.service"
else
    run_cmd mkdir -p -- "$UNIT_DIR"
    run_cmd install -m 0644 -- "$RENDERED" "$UNIT_FILE"
    run_cmd "${SYSTEMCTL[@]}" daemon-reload
    run_cmd "${SYSTEMCTL[@]}" enable "$SERVICE_NAME.service"
fi

# --- 4. what to do next ----------------------------------------------------

step "next"

SUDO_PREFIX=""
if [[ "$NEEDS_SUDO" == "true" ]]; then
    SUDO_PREFIX="sudo "
fi

cat <<EOF
The service is enabled (it will start at boot) but has NOT been started.
Check the server first, then start it:

  $DEPLOY_ROOT/current/script/server_preflight.sh
  ${SUDO_PREFIX}systemctl ${SYSTEMCTL[1]:+--user }start $SERVICE_NAME
  ${SUDO_PREFIX}systemctl ${SYSTEMCTL[1]:+--user }status $SERVICE_NAME
  curl -s http://127.0.0.1:8000/api/health

Logs (the journal is the log in this mode):
  journalctl ${SYSTEMCTL[1]:+--user }-u $SERVICE_NAME -f

After deploying a new release, repoint current and restart -- the unit follows
current and needs no edit:
  ln -sfn "$DEPLOY_ROOT/releases/<new>" "$DEPLOY_ROOT/current"
  ${SUDO_PREFIX}systemctl ${SYSTEMCTL[1]:+--user }restart $SERVICE_NAME
EOF

if [[ "$MODE" == "user" ]]; then
    cat <<EOF

NOTE -- a user unit starts when you log in, not when the machine boots.
For boot-time start without a login session, lingering must be enabled once
(this needs privileges):

  sudo loginctl enable-linger $(id -un)
EOF
fi

if [[ "$DRY_RUN" == "true" ]]; then
    printf '\n(--dry-run: nothing above was executed)\n'
fi
