"""Adapt the pipeline's result documents into one summary shape.

This is a read-only adapter. It never recomputes a pipeline value, never fills
a gap with a plausible number, and never returns a server filesystem path.

Two result types, discriminated by ``status/status/run_status.json``:

  precheck   ``--check-only``. No analysis output exists, but a real verdict
             does: the named checks, warnings and failures recorded by
             ``00_input_validation``, plus the resource metadata it captured.
             This is a result, not an absence.

  full       A run that reached finalization. ``core_summary.json`` is the
             primary source; coverage and variant-calling summaries come from
             the two stage documents that own those numbers.

Sources, in the order they are consulted:

    status/run_status.json                          discriminate + status
    status/steps/00_input_validation.json           precheck evidence
    metrics/00_input_validation.json                precheck input metadata
    core_summary.json                               full summary
    05_coverage_qc/coverage_metrics.json            coverage
    06_variant_calling/variant_calling_output.json  variant calling
    config/run_config.snapshot.json                 optional-step plan
    status/steps/99_finalization.json               full-run check table

Missing and malformed are treated differently on purpose. A document that is
not there yet means the run has not produced it (409 upstream, or a null
field). A document that is there but unparseable is a data fault and is
reported as one -- it is never quietly normalised into a valid-looking result.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OPTIONAL_STEP_IDS = ("08_filtering", "10_annotation", "11_intervar")
OPTIONAL_STEP_CONFIG_KEYS = {
    "08_filtering": "filtering",
    "10_annotation": "annotation",
    "11_intervar": "intervar",
}

PRECHECK_STEP_ID = "00_input_validation"
FINAL_STEP_ID = "99_finalization"

# main.sh derives these key names from the mosdepth thresholds header, so the
# set depends on how mosdepth was invoked. Matched by pattern rather than
# hard-coded, so a different --thresholds list needs no code change.
BREADTH_KEY_RE = re.compile(r"^target_bases_ge_([0-9]+X)_pct$")


class ResultError(Exception):
    """Base class for the failures this module reports."""


class ResultsNotReady(ResultError):
    """The run exists but has not produced the document being asked for."""


class MalformedPipelineDocument(ResultError):
    """A pipeline document exists but cannot be parsed.

    The message is for the server log. The API layer replies with a generic
    500 so that no path or parser detail reaches the client.
    """


# --- reading ----------------------------------------------------------------


def _read_json(path: Path, *, required: bool) -> Any:
    """Read one pipeline document as UTF-8.

    encoding is explicit: main.sh writes UTF-8 and embeds Korean in check
    details, which raises UnicodeDecodeError under a cp949 locale if the
    platform default is used.

    Missing -> None. Present but unparseable -> MalformedPipelineDocument,
    whether or not the caller considers the document required; ``required``
    only controls the wording.
    """
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            doc = json.load(handle)
    except (ValueError, UnicodeDecodeError) as exc:
        log.error("malformed pipeline document %s: %s", path, exc)
        raise MalformedPipelineDocument(f"{path.name} is not valid JSON") from exc
    except OSError as exc:
        if required:
            log.error("unreadable pipeline document %s: %s", path, exc)
            raise MalformedPipelineDocument(f"{path.name} could not be read") from exc
        return None
    if not isinstance(doc, dict):
        log.error("pipeline document %s is not an object", path)
        raise MalformedPipelineDocument(f"{path.name} is not a JSON object")
    return doc


def _step_document(run_dir: Path, step_id: str) -> dict | None:
    return _read_json(run_dir / "status" / "steps" / f"{step_id}.json", required=False)


# --- shared adapters --------------------------------------------------------
#
# These three read a step document's own vocabulary and are public because
# step_reader reuses them for GET /api/jobs/{id}/steps/{step_id}. Both
# endpoints must describe the same warning in the same shape, which a second
# copy of this mapping would not guarantee.


def checks_of(doc: dict | None) -> list[dict]:
    """The named check table, PASS rows included.

    GET /api/jobs/{id} keeps only warnings and failures, because the step
    timeline has nowhere to show a passing check. Here the PASS rows are the
    point: they are what makes a precheck a result rather than a silence.
    """
    if not isinstance(doc, dict):
        return []
    validation = doc.get("validation")
    results = validation.get("results") if isinstance(validation, dict) else None
    if not isinstance(results, list):
        return []
    out = []
    for item in results:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        out.append(
            {
                "name": str(item["name"]),
                "status": str(item.get("status") or ""),
                "detail": str(item.get("detail") or ""),
            }
        )
    return out


def warnings_of(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        out.append(
            {
                "stepId": str(item["step_id"]) if item.get("step_id") else None,
                "code": str(item.get("code") or ""),
                "message": str(item["message"]),
                "impact": str(item.get("impact") or ""),
                "canContinue": item.get("can_continue") is True,
            }
        )
    return out


def failures_of(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        out.append(
            {
                "stepId": str(item["step_id"]) if item.get("step_id") else None,
                "code": str(item.get("code") or ""),
                "message": str(item["message"]),
            }
        )
    return out


def _input_summary(metrics: Any) -> dict | None:
    """Resource metadata recorded by 00_input_validation.

    Every field is optional: the metrics document only carries what validation
    got far enough to record. A precheck that failed on required_tools has just
    sample and lane_count.
    """
    if not isinstance(metrics, dict) or not metrics:
        return None
    lane_count = metrics.get("lane_count")
    return {
        "sample": _as_str(metrics.get("sample")),
        "laneCount": lane_count if isinstance(lane_count, int) else None,
        "assembly": _as_str(metrics.get("assembly")),
        "contigStyle": _as_str(metrics.get("contig_style")),
        "bundleId": _as_str(metrics.get("bundle_id")),
        "captureKitId": _as_str(metrics.get("capture_kit_id")),
        "captureKitMode": _as_str(metrics.get("capture_kit_mode")),
        "targetBedSha256": _as_str(metrics.get("target_bed_sha256")),
        "coverageBedSha256": _as_str(metrics.get("coverage_bed_sha256")),
    }


def _as_str(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int, float)) and value != "" else None


def _as_number(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# --- coverage ---------------------------------------------------------------


def _coverage(run_dir: Path) -> dict | None:
    """Adapt 05_coverage_qc/coverage_metrics.json verbatim.

    Nothing is recomputed here; mosdepth and main.sh already did the work. The
    document is a flat dict with no schema wrapper.
    """
    doc = _read_json(
        run_dir / "05_coverage_qc" / "coverage_metrics.json", required=False
    )
    if doc is None:
        return None

    breadth: dict[str, float] = {}
    for key, value in doc.items():
        match = BREADTH_KEY_RE.fullmatch(str(key))
        number = _as_number(value)
        if match and number is not None:
            breadth[match.group(1)] = float(number)
    # Numeric order, so 100X does not sort before 20X.
    breadth = dict(sorted(breadth.items(), key=lambda kv: int(kv[0][:-1])))

    return {
        "meanTargetDepth": _as_number(doc.get("mean_target_depth")),
        "targetNonoverlapBases": _as_number(doc.get("target_nonoverlap_bases")),
        "breadth": breadth,
        # Base level. Derived only as documented in _zero_coverage().
        **_zero_coverage(doc, breadth),
        # Interval level. New key wins; the old key is the same measurement
        # under its old name, so falling back to it is a rename, not a
        # reinterpretation.
        "lowMeanDepthThresholdX": _first_number(
            doc, "low_mean_depth_threshold_x", "low_coverage_threshold_x"
        ),
        "lowMeanDepthIntervals": _first_number(
            doc, "low_mean_depth_intervals", "low_coverage_intervals"
        ),
        "basesInLowMeanDepthIntervals": _first_number(
            doc, "bases_in_low_mean_depth_intervals", "low_coverage_bases"
        ),
        "basesInLowMeanDepthIntervalsPct": _first_number(
            doc, "bases_in_low_mean_depth_intervals_pct", "low_coverage_bases_pct"
        ),
        "fullyUncoveredIntervals": _first_number(
            doc, "fully_uncovered_intervals", "uncovered_intervals"
        ),
        "basesInFullyUncoveredIntervals": _first_number(
            doc, "bases_in_fully_uncovered_intervals", "uncovered_bases"
        ),
        "basesInFullyUncoveredIntervalsPct": _first_number(
            doc, "bases_in_fully_uncovered_intervals_pct", "uncovered_bases_pct"
        ),
        # main.sh writes null with a stated reason: mosdepth ran with
        # --no-per-base, so per-base depths were never materialised. Passed
        # through as null; a median is never synthesised here.
        "medianTargetDepth": _as_number(doc.get("median_target_depth")),
        "medianNote": _as_str(doc.get("median_note")),
    }


def _first_number(doc: dict, *keys: str) -> float | int | None:
    """The first key present with a numeric value, in the order given.

    Used for metrics that were renamed. The keys must name the SAME
    measurement -- this is a rename bridge, never a substitution of one
    quantity for a different one.
    """
    for key in keys:
        number = _as_number(doc.get(key))
        if number is not None:
            return number
    return None


def _zero_coverage(doc: dict, breadth: dict[str, float]) -> dict:
    """Target bases that never reached 1x. Base level.

    Three cases, in order:

    1. The run recorded the keys directly (main.sh computes them from the 1X
       column of thresholds.bed.gz). Use them.

    2. An older run did not, but reported target_bases_ge_1X_pct, which is the
       same base-level measurement expressed the other way round. The
       percentage is derived as 100 - that value. The COUNT is not derivable
       from a rounded percentage, so it stays null rather than being invented.

    3. Neither is present. Both stay null.

    ``uncovered_bases_pct`` is deliberately NOT consulted. That key is
    interval level -- the share of target length inside intervals whose MEAN
    depth is 0 -- and mapping it here would silently understate zero-coverage
    bases, which is the confusion this whole change exists to remove.
    """
    recorded_pct = _as_number(doc.get("zero_coverage_bases_pct"))
    recorded_count = _as_number(doc.get("zero_coverage_bases"))
    if recorded_pct is not None or recorded_count is not None:
        return {
            "zeroCoverageBases": recorded_count,
            "zeroCoverageBasesPct": recorded_pct,
        }

    ge_1x = breadth.get("1X")
    if ge_1x is not None:
        return {
            "zeroCoverageBases": None,
            "zeroCoverageBasesPct": round(100.0 - ge_1x, 4),
        }

    return {"zeroCoverageBases": None, "zeroCoverageBasesPct": None}


def _variant_calling(run_dir: Path) -> dict | None:
    """Adapt 06_variant_calling/variant_calling_output.json.

    That document carries both absolute (`raw_vcf`) and run-relative
    (`raw_vcf_relative`) forms of the same path. Only the relative form is read;
    the absolute one is a server path and must not reach a response.
    """
    doc = _read_json(
        run_dir / "06_variant_calling" / "variant_calling_output.json", required=False
    )
    if doc is None:
        return None
    return {
        "sample": _as_str(doc.get("sample")),
        "assembly": _as_str(doc.get("assembly")),
        "rawVariantRecords": _as_number(doc.get("raw_variant_records")),
        "filteringApplied": doc.get("filtering_applied") is True,
        "coreEndpoint": "raw VCF (no filtering applied)",
        "rawVcfRelative": _as_str(doc.get("raw_vcf_relative")),
        "gvcfRelative": _as_str(doc.get("gvcf_relative")),
    }


# --- optional steps ---------------------------------------------------------


def _optional_steps(run_dir: Path) -> dict[str, str]:
    """Classify each optional step from what the run actually recorded.

    Derived only from the config snapshot, the step documents and the presence
    of the outputs those documents declare. Nothing is inferred about steps the
    run never mentioned.

    ``unsupported`` and ``unavailable`` are part of the vocabulary but are not
    emitted in this iteration: distinguishing them would mean inspecting the
    InterVar configuration, which is out of scope here.
    """
    snapshot = _read_json(
        run_dir / "config" / "run_config.snapshot.json", required=False
    )
    if snapshot is None:
        return {}
    configured = snapshot.get("optional_steps")
    if not isinstance(configured, dict):
        return {}

    states: dict[str, str] = {}
    for step_id in OPTIONAL_STEP_IDS:
        enabled = configured.get(OPTIONAL_STEP_CONFIG_KEYS[step_id]) is True
        if not enabled:
            states[step_id] = "not_run"
            continue

        doc = _step_document(run_dir, step_id)
        if doc is None:
            # Enabled in the config but the run never reached it.
            states[step_id] = "not_run"
            continue

        status = str(doc.get("status") or "")
        if status in ("failed", "cancelled"):
            states[step_id] = "failed"
        elif status == "skipped":
            states[step_id] = "not_run"
        elif status in ("completed", "warning"):
            states[step_id] = (
                "completed" if _outputs_present(run_dir, doc) else "file_missing"
            )
        else:
            states[step_id] = "failed"
    return states


def _outputs_present(run_dir: Path, step_doc: dict) -> bool:
    """True when every output the step declared is still on disk.

    Output paths come from the same writer as artifact paths and can point
    outside the run directory, so anything that does not resolve inside it is
    not treated as evidence either way.
    """
    outputs = step_doc.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return True
    try:
        root = run_dir.resolve(strict=True)
    except OSError:
        return True
    for item in outputs:
        if not isinstance(item, dict):
            continue
        raw = item.get("path")
        if not isinstance(raw, str) or not raw or ".." in raw.split("/"):
            continue
        try:
            target = (root / raw).resolve()
        except (OSError, ValueError):
            continue
        if not target.is_relative_to(root):
            continue
        if not target.is_file():
            return False
    return True


# --- entry point ------------------------------------------------------------


def read(run_dir: Path | str) -> dict[str, Any]:
    """Build the pipeline-derived half of the results response.

    The caller supplies jobId, runId, the reconciled status and artifactCount.

    Raises ResultsNotReady when the run has not produced a readable result yet,
    and MalformedPipelineDocument when one exists but cannot be parsed.
    """
    root = Path(run_dir)
    if not root.is_dir():
        raise ResultsNotReady("the run directory does not exist yet")

    run_status = _read_json(root / "status" / "run_status.json", required=True)
    if run_status is None:
        raise ResultsNotReady("the pipeline has not written a run status document")

    pipeline_status = str(run_status.get("status") or "")
    if pipeline_status == "check_only":
        return _read_precheck(root, run_status)
    return _read_full(root, run_status)


def _read_precheck(run_dir: Path, run_status: dict) -> dict[str, Any]:
    step = _step_document(run_dir, PRECHECK_STEP_ID)
    if step is None:
        raise ResultsNotReady(
            "the preflight produced no status document for 00_input_validation"
        )

    metrics_doc = _read_json(
        run_dir / "metrics" / f"{PRECHECK_STEP_ID}.json", required=False
    )
    metrics = metrics_doc.get("metrics") if isinstance(metrics_doc, dict) else None
    elapsed = step.get("elapsed_seconds")

    return {
        "resultType": "precheck",
        # --check-only executes no analysis tool at all; main.sh says so in its
        # own log line before running preflight.
        "analysisOutputProduced": False,
        "pipelineStatus": pipeline_status_of(run_status),
        "schemaVersion": _as_str(step.get("schema_version")),
        "sample": _as_str((metrics or {}).get("sample")),
        "elapsedSeconds": elapsed if isinstance(elapsed, int) else None,
        "checks": checks_of(step),
        "warnings": warnings_of(step.get("warnings")),
        "failures": failures_of(step.get("failures")),
        "inputSummary": _input_summary(metrics),
        "coverage": None,
        "variantCalling": None,
        "optionalSteps": {},
        "availableViews": [],
        "intendedUse": None,
    }


def _read_full(run_dir: Path, run_status: dict) -> dict[str, Any]:
    summary = _read_json(run_dir / "core_summary.json", required=True)
    if summary is None:
        # Reached finalization is what produces this document. Its absence
        # means the run stopped earlier -- mid-flight, failed or cancelled --
        # so there is no full result to report yet.
        raise ResultsNotReady("the run has not produced core_summary.json")

    metrics_by_step = summary.get("metrics")
    metrics_by_step = metrics_by_step if isinstance(metrics_by_step, dict) else {}
    input_metrics = metrics_by_step.get(PRECHECK_STEP_ID)
    if not isinstance(input_metrics, dict):
        fallback = _read_json(
            run_dir / "metrics" / f"{PRECHECK_STEP_ID}.json", required=False
        )
        input_metrics = fallback.get("metrics") if isinstance(fallback, dict) else None

    coverage = _coverage(run_dir)
    variant_calling = _variant_calling(run_dir)

    steps = summary.get("steps")
    elapsed_total = None
    if isinstance(steps, list):
        seconds = [
            s.get("elapsed_seconds")
            for s in steps
            if isinstance(s, dict) and isinstance(s.get("elapsed_seconds"), int)
        ]
        elapsed_total = sum(seconds) if seconds else None

    return {
        "resultType": "full",
        "analysisOutputProduced": summary.get("core_complete") is True,
        "pipelineStatus": pipeline_status_of(run_status),
        "schemaVersion": _as_str(summary.get("pipeline_version")),
        "sample": _as_str(summary.get("sample")),
        "elapsedSeconds": elapsed_total,
        # The consolidated pass/warn/fail table, as finalization recorded it.
        "checks": checks_of(_step_document(run_dir, FINAL_STEP_ID)),
        "warnings": warnings_of(summary.get("warnings")),
        "failures": _full_failures(run_dir, run_status),
        "inputSummary": _input_summary(input_metrics),
        "coverage": coverage,
        "variantCalling": variant_calling,
        "optionalSteps": _optional_steps(run_dir),
        "availableViews": ["coverage-summary"] if coverage else [],
        "intendedUse": _as_str(summary.get("intended_use")),
    }


def _full_failures(run_dir: Path, run_status: dict) -> list[dict]:
    """Failures of the steps run_status names as failed."""
    failed_steps = run_status.get("failed_steps")
    if not isinstance(failed_steps, list):
        return []
    out: list[dict] = []
    for step_id in failed_steps:
        doc = _step_document(run_dir, str(step_id))
        if not isinstance(doc, dict):
            continue
        for failure in failures_of(doc.get("failures")):
            failure["stepId"] = str(step_id)
            out.append(failure)
    return out


def pipeline_status_of(run_status: dict) -> str | None:
    return _as_str(run_status.get("status"))
