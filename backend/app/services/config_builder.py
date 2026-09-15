"""Turn a frontend submission into the two files main.sh v1.2.0 actually reads.

    POST /api/jobs body  ->  <run_dir>/input/samplesheet.csv
                         ->  <run_dir>/input/run_config.json

Everything here is written against the real script, not against documentation:

  run_id regex, required config keys      script/main.sh  load_config / normalize_config
  capture-kit registry mode               script/main.sh  resolve_capture_kit_profile
  samplesheet columns and FASTQ rules     script/main.sh  validate_samplesheet
  step plan                               script/main.sh  build_step_plan

Two constraints from resolve_capture_kit_profile drive the shape of the config:

  * registry mode is selected by capture_kit.{id,registry};
  * in registry mode the config MUST NOT also carry resource_bundle.target_bed,
    target_bed_metadata.* or coverage_bed. main.sh dies with
    "capture_kit registry mode cannot be combined with direct resource_bundle
    target/coverage BED fields" if any of them is non-empty.

So the backend never reconstructs the nine target_bed_metadata fields by hand;
it hands over the kit ID and lets main.sh resolve the profile.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import config

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Mirrors CORE_STEPS / OPTIONAL_STEPS / FINAL_STEP at the top of main.sh.
CORE_STEPS = [
    "00_input_validation",
    "01_raw_qc",
    "02_preprocessing",
    "03_alignment",
    "04_processing",
    "05_coverage_qc",
    "06_variant_calling",
]
FINAL_STEP = "99_finalization"

# UI option key -> how it reaches main.sh. Only options with a real counterpart
# in the run config are listed; everything else is recorded verbatim in the DB
# and reported to the client as unsupported, never silently invented into the
# config.
SUPPORTED_OPTION_KEYS = {
    "capture_kit_id": "capture_kit.id",
    "assembly": "resource_bundle.assembly (validated against server bundle)",
    # Conditional: only honoured when this server has an InterVar bundle
    # configured. resolve_intervar() decides, and the caller moves the key to
    # the unsupported list when it cannot be honoured.
    "run_acmg": "optional_steps.intervar",
}


class ConfigBuildError(Exception):
    """Rejection that should surface as a 4xx with a readable message."""


def new_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"wes-{stamp}-{secrets.token_hex(3)}"
    if not RUN_ID_RE.fullmatch(run_id):  # defensive; the format cannot fail this
        raise ConfigBuildError(f"generated run_id is not acceptable to main.sh: {run_id}")
    return run_id


def load_capture_kit_registry() -> dict[str, Any]:
    path = config.CAPTURE_KIT_REGISTRY
    if not path.is_file():
        raise ConfigBuildError(f"capture-kit registry is missing: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigBuildError(f"capture-kit registry is unreadable: {exc}") from exc


def resolve_capture_kit_id(capture_kit_id: str | None, options: dict[str, Any]) -> str:
    """Pick the kit ID and refuse anything main.sh would later die on.

    main.sh checks this too, but it does so with `die`, which happens before the
    run directory exists and therefore produces no status JSON. Checking here
    turns those cases into a clear 4xx instead.
    """
    from_options = options.get("capture_kit_id")
    candidates = {str(v).strip() for v in (capture_kit_id, from_options) if v}
    if not candidates:
        raise ConfigBuildError("capture kit is required (captureKitId or options.capture_kit_id)")
    if len(candidates) > 1:
        raise ConfigBuildError(
            f"conflicting capture kit ids: {', '.join(sorted(candidates))}"
        )
    kit_id = candidates.pop()

    if not RUN_ID_RE.fullmatch(kit_id):
        raise ConfigBuildError(f"capture_kit.id contains unsupported characters: {kit_id}")

    kits = load_capture_kit_registry().get("kits", {})
    profile = kits.get(kit_id)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(kits)) or "<none>"
        raise ConfigBuildError(f"capture kit '{kit_id}' is not registered; available: {available}")

    status = str(profile.get("status", "")).strip().lower()
    if status != "confirmed":
        raise ConfigBuildError(
            f"capture kit '{kit_id}' has status '{status or 'unknown'}'. main.sh only "
            "accepts 'confirmed' profiles; its BED and checksum must be verified first."
        )
    return kit_id


def split_options(options: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    supported = {k: v for k, v in options.items() if k in SUPPORTED_OPTION_KEYS}
    unsupported = sorted(k for k in options if k not in SUPPORTED_OPTION_KEYS)
    return supported, unsupported


def resolve_intervar(options: dict[str, Any]) -> tuple[bool, bool]:
    """Decide once whether 11_intervar will run.

    Returns (enabled, requested_but_unavailable).

    This is the single decision behind three things that must never disagree:
    planned_steps(), run_config.optional_steps.intervar and the run_config
    `intervar` block. Deriving them separately is how a plan that promises
    11_intervar ends up next to a config that switches it off.

    `requested_but_unavailable` is true when the user asked for ACMG
    classification on a server with no InterVar bundle. The caller reports that
    through the existing unsupported-options channel; it is never dropped.
    """
    requested = bool(options.get("run_acmg", False))
    if not requested:
        return False, False
    if config.INTERVAR is None:
        return False, True
    return True, False


def planned_steps(run_mode: str, intervar: bool) -> list[str]:
    """The steps that will actually execute, in main.sh's order.

    --check-only runs run_input_validation and nothing else (see main()), so the
    plan for that mode is a single step. Reporting the full 8-step plan there
    would make progress permanently understate itself.
    """
    if run_mode == "check_only":
        return ["00_input_validation"]
    steps = list(CORE_STEPS)
    if intervar:
        steps.append("11_intervar")
    steps.append(FINAL_STEP)
    return steps


def _as_config_path(path: Path) -> str:
    """Absolute path in a form both main.sh's helpers accept.

    normalize_path() feeds the value to os.path.realpath in whichever Python is
    on PATH. Forward slashes survive that on both platforms: on Windows
    "C:/x/y" normalises to "C:\\x\\y", and MSYS test operators accept the
    result; on Linux the string is already canonical.
    """
    return path.resolve().as_posix()


def write_samplesheet(dest: Path, sample_id: str, fastq_1: Path, fastq_2: Path) -> None:
    """One sample, one lane. Columns are the four main.sh marks required.

    rg_id/library/platform/platform_unit are omitted deliberately: validate_
    samplesheet fills them in as sample.lane / sample / ILLUMINA / lane, which is
    exactly what a single-lane run wants. Written with \\n line endings because
    the file is consumed by csv.DictReader under bash.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "sample,lane,fastq_1,fastq_2",
        f"{sample_id},L001,{_as_config_path(fastq_1)},{_as_config_path(fastq_2)}",
    ]
    dest.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


def build_run_config(
    *,
    run_id: str,
    samplesheet: Path,
    capture_kit_id: str,
    intervar: bool,
) -> dict[str, Any]:
    """Assemble run_config.json.

    Resource locations come from the server environment only. The browser
    chooses a capture kit by ID and nothing else; it can never name a path on
    this machine.
    """
    if not config.REFERENCE_FASTA:
        raise ConfigBuildError(
            "server is not configured: WES_REFERENCE_FASTA is unset. Set the reference "
            "bundle in backend/.env before submitting a run."
        )
    if not config.CONTIG_STYLE:
        raise ConfigBuildError(
            "server is not configured: WES_CONTIG_STYLE is unset. Read the first column "
            "of the reference .fai and declare 'chr' or 'plain'; do not guess."
        )

    doc: dict[str, Any] = {
        "run_id": run_id,
        "samplesheet": _as_config_path(samplesheet),
        "output_root": _as_config_path(config.RUNS_ROOT),
        "threads": config.THREADS,
        "java_mem_gb": config.JAVA_MEM_GB,
        "trim_mode": "skip",
        "capture_kit": {
            "id": capture_kit_id,
            "registry": _as_config_path(config.CAPTURE_KIT_REGISTRY),
        },
        "resource_bundle": {
            "bundle_id": config.BUNDLE_ID,
            "assembly": config.ASSEMBLY,
            "contig_style": config.CONTIG_STYLE,
            "reference_fasta": config.REFERENCE_FASTA,
            "known_sites": list(config.KNOWN_SITES),
            # No target_bed / target_bed_metadata / coverage_bed here: in registry
            # mode main.sh refuses a config that carries both sources of truth.
        },
        "optional_steps": {
            "filtering": False,
            "annotation": False,
            "intervar": bool(intervar),
        },
    }
    if config.DBSNP_VCF:
        doc["resource_bundle"]["dbsnp_vcf"] = config.DBSNP_VCF
    if intervar:
        # run_intervar() reads exactly these three keys and fails the step when
        # any is missing, so enabling the step without them would guarantee the
        # failure this block exists to prevent.
        if config.INTERVAR is None:
            raise ConfigBuildError(
                "internal: InterVar was enabled for this run but the server has no "
                "InterVar bundle configured. resolve_intervar() is the only thing "
                "allowed to enable it."
            )
        doc["intervar"] = dict(config.INTERVAR)
    return doc


def write_run_config(dest: Path, doc: dict[str, Any]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
