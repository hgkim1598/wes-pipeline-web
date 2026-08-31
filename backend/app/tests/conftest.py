"""Shared test harness for the result layer.

Nothing here runs the pipeline. Every fixture builds a synthetic run directory
whose document shapes are copied from the code in script/main.sh that writes
them:

    status/run_status.json                          write_run_status()
    status/steps/<id>.json                          finish_step()
    metrics/<id>.json                               finish_step()
    artifacts/<id>.json                             finish_step()
    artifact_manifest.json                          write_artifact_manifest()
    core_summary.json                               write_final_report()
    05_coverage_qc/coverage_metrics.json            run_coverage_qc()
    06_variant_calling/variant_calling_output.json  run_variant_calling()

The precheck fixtures additionally reproduce the shape observed in the real
check-only runs under runs/wes-20260813-*. Those directories are never read or
modified by the tests; only their structure was used as the reference.

file_id is derived the way main.sh derives it, so a test can compute the id of
an artifact it just wrote instead of hard-coding a digest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app
from app.services import worker

SCHEMA_VERSION = "1.0"

# Deliberately non-ASCII: main.sh emits Korean in check details and failure
# messages, and reading those back with the platform default encoding raises
# UnicodeDecodeError on a cp949 Windows box. Every fixture carries some, so the
# encoding="utf-8" contract is exercised by the whole suite rather than by one
# dedicated test.
KOREAN_DETAIL = (
    "missing from PATH: bwa samtools gatk. 실행 전에 직접 설치하세요. "
    "이 파이프라인은 도구를 스스로 설치하지 않습니다."
)

# What 00_input_validation records via step_metric when the resource bundle
# validates cleanly. A precheck that fails earlier records only a subset, which
# is why every consumer of this data treats each field as optional.
PRECHECK_METRICS = {
    "sample": "SRR2962669.subset_5M",
    "lane_count": 1,
    "assembly": "GRCh38",
    "contig_style": "chr",
    "bundle_id": "grch38_wes_germline",
    "capture_kit_id": "idt_xgen_exome_hyb_panel_v2",
    "capture_kit_mode": "registry",
    "target_bed_sha256": (
        "9b18f157033c49380e146ab370258976aa0eaf2a48e4f466c05a5e9f4e41df3a"
    ),
    "coverage_bed_sha256": "a" * 64,
}


def write_json(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def artifact_file_id(run_id: str, step_id: str, relative_path: str) -> str:
    """Mirror of the seed used by the artifact writer inside finish_step()."""
    seed = f"{run_id}:{step_id}:{relative_path}".encode("utf-8")
    return "f_" + hashlib.sha256(seed).hexdigest()[:16]


class RunBuilder:
    """Writes the documents main.sh would have written, and nothing else."""

    def __init__(self, runs_root: Path, run_id: str) -> None:
        self.run_id = run_id
        self.run_dir = runs_root / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # --- plain files ------------------------------------------------------

    def file(self, relative_path: str, content: bytes | str = b"payload") -> Path:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8", newline="\n")
        else:
            path.write_bytes(content)
        return path

    def raw(self, relative_path: str, text: str) -> Path:
        """Write a file verbatim; used to plant malformed JSON."""
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    # --- status -----------------------------------------------------------

    def run_status(
        self,
        status: str,
        *,
        current_step: str | None = None,
        steps: list[dict] | None = None,
    ) -> None:
        steps = steps or []
        write_json(
            self.run_dir / "status" / "run_status.json",
            {
                "schema_version": SCHEMA_VERSION,
                "pipeline_name": "variant-pipeline-lab-wes",
                "pipeline_version": "1.2.0",
                "run_id": self.run_id,
                "status": status,
                "current_step": current_step,
                "steps": steps,
                "completed_steps": [
                    s["step_id"]
                    for s in steps
                    if s.get("status") in ("completed", "warning", "skipped")
                ],
                "failed_steps": [
                    s["step_id"] for s in steps if s.get("status") == "failed"
                ],
                "updated_at": "2026-08-21T14:27:22.000000+09:00",
            },
        )

    def step(
        self,
        step_id: str,
        *,
        status: str = "completed",
        elapsed_seconds: int = 5,
        checks: list[dict] | None = None,
        warnings: list[dict] | None = None,
        failures: list[dict] | None = None,
        outputs: list[dict] | None = None,
        inputs: list[dict] | None = None,
    ) -> None:
        checks = checks or []
        warnings = warnings or []
        failures = failures or []
        if inputs is None:
            # main.sh writes a run-relative path here, and for the backend's own
            # generated inputs that path escapes the run directory as
            # "../_jobs/...". Reproduced verbatim so the readers are exercised
            # against the real shape rather than an idealised one.
            inputs = [
                {
                    "type": "run_config",
                    "path": f"../_jobs/{self.run_id}/run_config.json",
                },
                {
                    "type": "samplesheet",
                    "path": f"../_jobs/{self.run_id}/samplesheet.csv",
                },
            ]
        write_json(
            self.run_dir / "status" / "steps" / f"{step_id}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "step_id": step_id,
                "status": status,
                "exit_code": 1 if status == "failed" else 0,
                "started_at": "2026-08-21T14:26:59+09:00",
                "finished_at": "2026-08-21T14:27:22+09:00",
                "elapsed_seconds": elapsed_seconds,
                "inputs": inputs,
                "outputs": outputs or [],
                "validation": {
                    "status": "fail" if failures else ("warn" if warnings else "pass"),
                    "checks": len(checks),
                    "warnings": len(warnings),
                    "failures": len(failures),
                    "results": checks,
                },
                "warnings": warnings,
                "failures": failures,
                "metrics_file": f"metrics/{step_id}.json",
                "artifacts_file": f"artifacts/{step_id}.json",
                "next_step_ready": (
                    status in ("completed", "warning", "skipped") and not failures
                ),
            },
        )

    def stage_status(self, rows: list[tuple[str, str, str]] | None = None) -> None:
        """Write logs/stage_status.tsv the way append_status_tsv() does.

        Rows are (timestamp, step, status); exit_code is filled in as main.sh
        does. The header is always written first, because append_status_tsv
        writes it before the first row.
        """
        lines = ["timestamp\tstep\tstatus\texit_code"]
        for timestamp, step, status in rows or []:
            code = "1" if status.upper() == "FAILED" else "0"
            lines.append(f"{timestamp}\t{step}\t{status}\t{code}")
        self.raw("logs/stage_status.tsv", "\n".join(lines) + "\n")

    def metrics(self, step_id: str, metrics: dict) -> None:
        write_json(
            self.run_dir / "metrics" / f"{step_id}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "step_id": step_id,
                "metrics": metrics,
            },
        )

    # --- artifacts --------------------------------------------------------

    def entry(
        self,
        step_id: str,
        kind: str,
        display_name: str,
        relative_path: str,
        *,
        downloadable: bool = True,
        sha256: str | None = None,
        size_bytes: int = 7,
        description: str = "",
        file_id: str | None = None,
    ) -> dict:
        return {
            "file_id": file_id or artifact_file_id(self.run_id, step_id, relative_path),
            "step_id": step_id,
            "kind": kind,
            "display_name": display_name,
            "relative_path": relative_path,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "downloadable": downloadable,
            "description": description,
        }

    def artifacts(self, step_id: str, entries: list[dict]) -> None:
        write_json(
            self.run_dir / "artifacts" / f"{step_id}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "step_id": step_id,
                "artifacts": entries,
            },
        )

    def manifest(self, entries: list[dict]) -> None:
        write_json(
            self.run_dir / "artifact_manifest.json",
            {
                "run_id": self.run_id,
                "artifact_count": len(entries),
                "artifacts": entries,
            },
        )

    # --- full-run result documents ---------------------------------------

    def core_summary(self, **overrides: object) -> None:
        doc: dict = {
            "pipeline_name": "variant-pipeline-lab-wes",
            "pipeline_version": "1.2.0",
            "run_id": self.run_id,
            "sample": "SRR2962669.subset_5M",
            "assembly": "GRCh38",
            "core_complete": True,
            "core_endpoint": "raw VCF (no filtering applied)",
            "raw_variant_records": 48210,
            "nm_md_repaired": False,
            "steps": [
                {
                    "step_id": "00_input_validation",
                    "status": "warning",
                    "elapsed_seconds": 23,
                },
                {
                    "step_id": "06_variant_calling",
                    "status": "completed",
                    "elapsed_seconds": 900,
                },
            ],
            "warnings": [
                {
                    "step_id": "01_raw_qc",
                    "code": "MULTIQC_MISSING",
                    "message": "MultiQC is not installed",
                    "impact": "집계 리포트만 없습니다",
                    "can_continue": True,
                }
            ],
            "warning_count": 1,
            # write_final_report() folds every metrics/*.json into this block,
            # so the preflight metadata is reachable from core_summary alone.
            "metrics": {
                "00_input_validation": dict(PRECHECK_METRICS),
                "05_coverage_qc": {"mean_target_depth": 85.2},
            },
            "intended_use": "research and education only; not a diagnostic result",
        }
        doc.update(overrides)
        write_json(self.run_dir / "core_summary.json", doc)

    def coverage_metrics(self, **overrides: object) -> None:
        doc: dict = {
            "target_nonoverlap_bases": 34567890,
            "mean_target_depth": 85.2,
            "low_coverage_bases_pct": 5.8,
            "uncovered_bases_pct": 0.42,
            "low_coverage_threshold_x": 20.0,
            "low_coverage_intervals": 812,
            "low_coverage_bases": 200000,
            "uncovered_intervals": 91,
            "uncovered_bases": 14500,
            "target_bases_ge_1X_pct": 99.1,
            "target_bases_ge_10X_pct": 97.4,
            "target_bases_ge_20X_pct": 94.2,
            "target_bases_ge_30X_pct": 89.0,
            "target_bases_ge_50X_pct": 71.3,
            "target_bases_ge_100X_pct": 40.2,
            # main.sh always writes null here, with a stated reason.
            "median_target_depth": None,
            "median_note": (
                "not computed: mosdepth runs with --no-per-base, "
                "so per-base depths are unavailable"
            ),
        }
        doc.update(overrides)
        write_json(self.run_dir / "05_coverage_qc" / "coverage_metrics.json", doc)

    def variant_calling_output(self, **overrides: object) -> None:
        sample = "SRR2962669.subset_5M"
        stage = f"06_variant_calling/{sample}"
        doc: dict = {
            "sample": sample,
            "assembly": "GRCh38",
            # Absolute paths, exactly as main.sh writes them. The reader must
            # never let these reach a response.
            "gvcf": f"/srv/wes/runs/{self.run_id}/{stage}.g.vcf.gz",
            "raw_vcf": f"/srv/wes/runs/{self.run_id}/{stage}.raw.vcf.gz",
            "gvcf_relative": f"{stage}.g.vcf.gz",
            "raw_vcf_relative": f"{stage}.raw.vcf.gz",
            "raw_variant_records": 48210,
            "filtering_applied": False,
            "next_step_ready": True,
        }
        doc.update(overrides)
        write_json(
            self.run_dir / "06_variant_calling" / "variant_calling_output.json", doc
        )

    def snapshot(
        self,
        *,
        filtering: bool = False,
        annotation: bool = False,
        intervar: bool = False,
    ) -> None:
        write_json(
            self.run_dir / "config" / "run_config.snapshot.json",
            {
                "run_id": self.run_id,
                "config_identity_sha256": "0" * 64,
                "optional_steps": {
                    "filtering": filtering,
                    "annotation": annotation,
                    "intervar": intervar,
                },
            },
        )

    # --- composed scenarios ----------------------------------------------

    def as_passing_precheck(self) -> "RunBuilder":
        """The shape of the 2026-08-21 Linux check-only run."""
        self.file("logs/software_versions.txt", "bwa=0.7.17\n")
        self.file("config/normalized_manifest.json", '{"sample": "x"}\n')
        self.file("00_input_validation/samplesheet_validation.txt", "ok\n")
        self.step(
            "00_input_validation",
            status="warning",
            elapsed_seconds=23,
            checks=[
                {
                    "name": "samplesheet",
                    "status": "PASS",
                    "detail": "columns, IDs, FASTQ pairs and metadata are consistent",
                },
                {
                    "name": "resource_bundle",
                    "status": "PASS",
                    "detail": "reference, indexes, target/coverage BEDs are compatible",
                },
                {
                    "name": "MULTIQC_MISSING",
                    "status": "WARN",
                    "detail": "MultiQC is not installed",
                },
            ],
            warnings=[
                {
                    "code": "MULTIQC_MISSING",
                    "message": "MultiQC is not installed",
                    "impact": "Per-lane FastQC still runs; only the aggregated report is unavailable",
                    "can_continue": True,
                }
            ],
        )
        self.metrics("00_input_validation", dict(PRECHECK_METRICS))
        self.artifacts(
            "00_input_validation",
            [
                self.entry(
                    "00_input_validation",
                    "software_versions",
                    "Software versions",
                    "logs/software_versions.txt",
                    description="Tool versions captured at preflight",
                ),
                self.entry(
                    "00_input_validation",
                    "manifest",
                    "Normalized run manifest",
                    "config/normalized_manifest.json",
                    sha256="74abdcbe1b603f8ba2890900a5631f9f749098d4907e8432c1e3f630e7ee4bbd",
                ),
                self.entry(
                    "00_input_validation",
                    "validation_report",
                    "Samplesheet validation report",
                    "00_input_validation/samplesheet_validation.txt",
                ),
            ],
        )
        self.run_status(
            "check_only",
            current_step="00_input_validation",
            steps=[
                {
                    "step_id": "00_input_validation",
                    "status": "warning",
                    "exit_code": 0,
                    "elapsed_seconds": 23,
                    "warnings": 1,
                    "failures": 0,
                    "next_step_ready": True,
                }
            ],
        )
        return self

    def as_failing_precheck(self) -> "RunBuilder":
        self.step(
            "00_input_validation",
            status="failed",
            elapsed_seconds=4,
            checks=[
                {"name": "required_tools", "status": "FAIL", "detail": KOREAN_DETAIL},
                {
                    "name": "MULTIQC_MISSING",
                    "status": "WARN",
                    "detail": "MultiQC is not installed",
                },
                {
                    "name": "samplesheet",
                    "status": "PASS",
                    "detail": "columns, IDs, FASTQ pairs and metadata are consistent",
                },
            ],
            warnings=[
                {
                    "code": "MULTIQC_MISSING",
                    "message": "MultiQC is not installed",
                    "impact": "Per-lane FastQC still runs",
                    "can_continue": True,
                }
            ],
            failures=[{"code": "required_tools", "message": KOREAN_DETAIL}],
        )
        self.metrics(
            "00_input_validation", {"sample": "DEMO01_S1", "lane_count": 1}
        )
        self.run_status(
            "check_only",
            current_step="00_input_validation",
            steps=[
                {
                    "step_id": "00_input_validation",
                    "status": "failed",
                    "exit_code": 1,
                    "elapsed_seconds": 4,
                    "warnings": 1,
                    "failures": 1,
                    "next_step_ready": False,
                }
            ],
        )
        return self

    def as_completed_full(self) -> "RunBuilder":
        """A finished core run, including the artifact_manifest.json gap.

        write_artifact_manifest() runs before finish_step() publishes the
        finalization step's own artifacts, so the manifest on disk cannot
        contain them. The fixture reproduces that omission on purpose.
        """
        sample = "SRR2962669.subset_5M"
        self.file("logs/software_versions.txt", "bwa=0.7.17\n")
        self.file(f"06_variant_calling/{sample}.raw.vcf.gz", b"\x1f\x8bRAWVCF")
        self.file("05_coverage_qc/mosdepth.regions.bed.gz", b"\x1f\x8bREGIONS")
        self.file("final_validation.tsv", "check\tstatus\tdetail\n")
        self.file("core_summary.json.placeholder", "unused")
        self.file("methods.md", "# Methods\n")

        early = [
            self.entry(
                "00_input_validation",
                "software_versions",
                "Software versions",
                "logs/software_versions.txt",
            ),
            self.entry(
                "05_coverage_qc",
                "coverage_regions",
                "mosdepth regions",
                "05_coverage_qc/mosdepth.regions.bed.gz",
            ),
            self.entry(
                "06_variant_calling",
                "raw_vcf",
                "Raw VCF",
                f"06_variant_calling/{sample}.raw.vcf.gz",
                sha256="b" * 64,
                description="GenotypeGVCFs output - the core completion artifact.",
            ),
        ]
        self.artifacts("00_input_validation", [early[0]])
        self.artifacts("05_coverage_qc", [early[1]])
        self.artifacts("06_variant_calling", [early[2]])

        # Written last by finish_step(), therefore absent from the manifest.
        late = [
            self.entry(
                "99_finalization",
                "final_validation",
                "Final validation table",
                "final_validation.tsv",
            ),
            self.entry("99_finalization", "methods", "Methods", "methods.md"),
        ]
        self.artifacts("99_finalization", late)
        self.manifest(early)

        self.coverage_metrics()
        self.variant_calling_output()
        self.core_summary()
        self.snapshot()
        self.metrics("00_input_validation", dict(PRECHECK_METRICS))
        self.step("05_coverage_qc")
        self.step("06_variant_calling")
        self.step(
            "99_finalization",
            checks=[
                {"name": "raw_vcf", "status": "PASS", "detail": "present"},
                {"name": "analysis_ready_bam", "status": "PASS", "detail": "present"},
            ],
        )
        self.run_status(
            "completed_with_warnings",
            steps=[
                {
                    "step_id": "06_variant_calling",
                    "status": "completed",
                    "exit_code": 0,
                    "elapsed_seconds": 900,
                    "warnings": 0,
                    "failures": 0,
                    "next_step_ready": True,
                }
            ],
        )
        return self


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point every filesystem location and the database at tmp_path."""
    runs_root = tmp_path / "runs"
    jobs_root = runs_root / "_jobs"
    upload_root = tmp_path / "uploads"
    for directory in (runs_root, jobs_root, upload_root):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(config, "JOBS_ROOT", jobs_root)
    monkeypatch.setattr(config, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")

    previous = db._conn
    db._conn = None
    try:
        yield runs_root
    finally:
        if db._conn is not None:
            db._conn.close()
        db._conn = previous


@pytest.fixture
def client(env):
    """TestClient without the lifespan.

    The lifespan starts the pipeline worker thread. These tests never execute a
    pipeline, so it is deliberately not started; db.connect() is lazy, so every
    endpoint still works. raise_server_exceptions=False lets the 500 mapping be
    asserted as a response instead of propagating out of the client.
    """
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def make_job(env):
    """Insert an orchestration row the way POST /api/jobs would."""

    def _make(
        run_id: str = "wes-20260821-142659-c66d6e",
        *,
        run_mode: str = "check_only",
        status: str = worker.DONE,
        profile_id: str = "germline-illumina-wes-breast",
        planned: list[str] | None = None,
        run_dir: Path | None = None,
        error: str | None = None,
        # None reproduces a row written before jobs.sample_id existed.
        sample_id: str | None = None,
        created_at: str | None = None,
    ) -> str:
        if planned is None:
            planned = (
                ["00_input_validation"]
                if run_mode == "check_only"
                else [
                    "00_input_validation",
                    "01_raw_qc",
                    "02_preprocessing",
                    "03_alignment",
                    "04_processing",
                    "05_coverage_qc",
                    "06_variant_calling",
                    "99_finalization",
                ]
            )
        db.execute(
            """INSERT INTO jobs
               (job_id, run_id, profile_id, capture_kit_id, sample_id, status, run_dir,
                config_path, samplesheet_path, run_mode, planned_steps,
                original_options, unsupported_options, error, started_at,
                finished_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                run_id,
                profile_id,
                "idt_xgen_exome_hyb_panel_v2",
                sample_id,
                status,
                str(run_dir if run_dir is not None else config.RUNS_ROOT / run_id),
                str(config.JOBS_ROOT / run_id / "run_config.json"),
                str(config.JOBS_ROOT / run_id / "samplesheet.csv"),
                run_mode,
                json.dumps(planned),
                json.dumps({"capture_kit_id": "idt_xgen_exome_hyb_panel_v2"}),
                json.dumps(["min_depth", "min_gq", "variant_caller"]),
                error,
                "2026-08-21T14:26:59+09:00",
                "2026-08-21T14:27:22+09:00",
                created_at or db.now_iso(),
                db.now_iso(),
            ),
        )
        return run_id

    return _make


@pytest.fixture
def run(env):
    """A RunBuilder rooted at the temporary runs directory."""

    def _run(run_id: str = "wes-20260821-142659-c66d6e") -> RunBuilder:
        return RunBuilder(env, run_id)

    return _run


@pytest.fixture
def make_upload(env):
    """A completed upload row plus the gzip file it points at.

    POST /api/jobs resolves the token through the database, so a submission
    test needs a real row and a real file. Going through the chunk endpoints
    would exercise uploads.py, which these tests are not about.
    """

    def _make(name: str = "demo_R1.fastq.gz") -> str:
        upload_id = "upl_" + hashlib.sha256(name.encode()).hexdigest()[:24]
        final_dir = config.UPLOAD_ROOT / upload_id
        final_dir.mkdir(parents=True, exist_ok=True)
        final_path = final_dir / name
        final_path.write_bytes(b"\x1f\x8bFASTQ")
        db.execute(
            """INSERT INTO uploads
               (upload_id, original_filename, stored_filename, sample_id, slot_id,
                expected_size, chunk_dir, final_path, completed, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (
                upload_id,
                name,
                name,
                "DEMO01",
                "r1",
                final_path.stat().st_size,
                str(final_dir / "chunks"),
                str(final_path),
                db.now_iso(),
            ),
        )
        return upload_id

    return _make


@pytest.fixture
def reference_configured(monkeypatch):
    """The minimum server configuration build_run_config() insists on."""
    monkeypatch.setattr(config, "REFERENCE_FASTA", "/refs/GRCh38.fa")
    monkeypatch.setattr(config, "CONTIG_STYLE", "chr")
    monkeypatch.setattr(config, "RUN_MODE", "full")
