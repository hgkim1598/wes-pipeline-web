"""Server-side settings.

Every filesystem location the backend touches is derived from the repository
root, which is computed from this file's own location. Nothing is hard-coded to
Windows or to a particular checkout, so the same code runs on the Linux box that
will eventually execute the full pipeline.

Reference-bundle locations come from the environment, never from the browser.
The frontend selects a capture kit by ID; it can never name a server path.
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/app/config.py -> app -> backend -> <repo root>
ROOT = Path(__file__).resolve().parents[2]

BACKEND_DIR = ROOT / "backend"
ENV_FILE = BACKEND_DIR / ".env"


def _load_env_file(path: Path) -> None:
    """Populate os.environ from a KEY=VALUE file, without overriding real env vars.

    Deliberately hand-rolled: it keeps .env support from depending on a package
    that only happens to be present as a transitive dependency of fastapi-cli.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(ENV_FILE)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- pipeline -------------------------------------------------------------
PIPELINE_SH = ROOT / "script" / "main.sh"
CAPTURE_KIT_REGISTRY = ROOT / "config" / "capture_kits.grch38.json"

# `bash` must be on PATH. On Windows this is Git Bash; on Linux the system bash.
BASH_BIN = _env("WES_BASH", "bash")

# check_only -> `main.sh --check-only` (preflight only, no analysis tool runs)
# full       -> the whole pipeline
# There is no third mode: a "simulated" run is never produced.
RUN_MODE_CHOICES = ("check_only", "full")
DEFAULT_RUN_MODE = "check_only"


class ConfigError(RuntimeError):
    """The environment asks for something this backend must not do."""


def _resolve_run_mode() -> str:
    """Validate WES_RUN_MODE against an allowlist, fail-closed.

    build_command() only adds --check-only for the exact string "check_only",
    so any unrecognised value would otherwise be treated as `full` and launch
    the entire pipeline. A typo like "chek_only" must stop the server, not
    quietly widen what gets executed.

    Unset or empty resolves to the safer default; the resolved value is then
    checked like any other, so the allowlist is the single gate.
    """
    raw = _env("WES_RUN_MODE") or DEFAULT_RUN_MODE
    mode = raw.lower()
    if mode not in RUN_MODE_CHOICES:
        raise ConfigError(
            f"Invalid WES_RUN_MODE: {raw!r}. "
            f"Expected one of: {', '.join(RUN_MODE_CHOICES)}."
        )
    return mode


RUN_MODE = _resolve_run_mode()

# --- storage --------------------------------------------------------------
RUNS_ROOT = Path(_env("WES_RUNS_ROOT") or (ROOT / "runs"))
UPLOAD_ROOT = Path(_env("WES_UPLOAD_ROOT") or (ROOT / "uploads"))
DB_PATH = Path(_env("WES_DB_PATH") or (BACKEND_DIR / "data" / "app.db"))

# Backend-owned inputs (generated samplesheet, run config, executor log).
#
# These must NOT live under RUNS_ROOT/<run_id>: initialize_run() hard-fails when
# the run directory already exists without --resume, so pre-creating it would
# stop the pipeline before it started. "_jobs" cannot collide with a real run
# directory because main.sh requires run_id to start with an alphanumeric.
JOBS_ROOT = RUNS_ROOT / "_jobs"

# --- reference bundle (operator supplied) ---------------------------------
# These are written verbatim into run_config.json. If they point at resources
# that are not installed yet, main.sh's own preflight reports that truthfully;
# the backend never substitutes or invents a resource.
REFERENCE_FASTA = _env("WES_REFERENCE_FASTA")
ASSEMBLY = _env("WES_ASSEMBLY", "GRCh38")
CONTIG_STYLE = _env("WES_CONTIG_STYLE")
BUNDLE_ID = _env("WES_BUNDLE_ID", "grch38_wes_germline")
DBSNP_VCF = _env("WES_DBSNP_VCF")
KNOWN_SITES = [p for p in (s.strip() for s in _env("WES_KNOWN_SITES").split(",")) if p]

# --- optional InterVar capability (operator supplied) ---------------------
# main.sh's run_intervar() reads intervar.install_dir, intervar.build and
# intervar.humandb_dir out of the run config and fails the step when any of
# them is missing. This server therefore claims the capability only when the
# operator has supplied all three; INTERVAR is None otherwise, and the ACMG
# option is reported back as unsupported rather than silently dropped.
#
# The assembly -> ANNOVAR build correspondence (GRCh38 -> hg38) lives in
# main.sh's INTERVAR_BUILD_FOR_ASSEMBLY and is deliberately NOT duplicated
# here. main.sh validates the pair itself; a copy would only drift from it.
INTERVAR_KEYS = ("install_dir", "build", "humandb_dir")
_INTERVAR_ENV = {
    "install_dir": "WES_INTERVAR_DIR",
    "build": "WES_INTERVAR_BUILD",
    "humandb_dir": "WES_INTERVAR_HUMANDB",
}


def _resolve_intervar() -> dict[str, str] | None:
    """All three set -> the profile. None set -> None. Partial -> ConfigError.

    Fail-closed for the same reason _resolve_run_mode() is: a half-configured
    InterVar bundle is an operator mistake, and treating it as "capability
    absent" would hide the mistake behind a run that merely looks fine.
    """
    values = {key: _env(_INTERVAR_ENV[key]) for key in INTERVAR_KEYS}
    if not any(values.values()):
        return None

    missing = [_INTERVAR_ENV[k] for k in INTERVAR_KEYS if not values[k]]
    if missing:
        raise ConfigError(
            "Incomplete InterVar configuration: "
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} unset. "
            f"Set all of {', '.join(_INTERVAR_ENV.values())}, or none of them to "
            "run without ACMG classification."
        )

    for key in ("install_dir", "humandb_dir"):
        if not Path(values[key]).is_dir():
            raise ConfigError(
                f"{_INTERVAR_ENV[key]} does not point at a directory: {values[key]}. "
                "InterVar and its ANNOVAR humandb must be installed before the "
                "server claims the capability; main.sh never installs them."
            )
    return values


INTERVAR = _resolve_intervar()

# --- compute --------------------------------------------------------------
THREADS = int(_env("WES_THREADS", "4"))
JAVA_MEM_GB = int(_env("WES_JAVA_MEM_GB", "8"))

# --- upload ---------------------------------------------------------------
CHUNK_SIZE = 8 * 1024 * 1024
ALLOWED_FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz")


def ensure_dirs() -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
