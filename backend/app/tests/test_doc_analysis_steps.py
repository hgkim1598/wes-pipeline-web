"""Analysis-step failures as document-search inputs (development log 65).

Before this, only step-00 resource causes and the VCF step checks became search
inputs; a failed `samtools index` in 03 or `gatk MarkDuplicates` in 04 was listed
as "no command in the pipeline code". The pipeline records those failures with
`require_cmd_ok <label> <argv...>` (and a few fixed `fail_step` codes right after
one command), so the command IS a fact of main.sh -- the same rule as the
existing check families.

What these tests pin:
  * every new label maps to the exact command main.sh runs for it;
  * checks produced by a file-size / presence / grep test, or by a two-command
    pipe, map to NOTHING (a command would be invented);
  * a lane-labelled check keeps only its family (the lane unit can carry the
    sample name);
  * the input is searched against a manual of the same tool and skipped with a
    reason otherwise -- never against the curated cause-kind excerpts.

Synthetic text only; no process, no model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ..services.doc_search import commands
from .doc_corpus_fixture import synthetic_passages  # noqa: F401  (fixture)
from .test_doc_search import _chunk, search, write_manual
from .test_resource_bundle_diagnosis import RUN_ID, SAMPLE
from .. import config

REPO = Path(__file__).resolve().parents[3]
MAIN_SH = (REPO / "script" / "main.sh").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Shell continuation lines joined, runs of spaces collapsed (indentation is not the contract)."""
    return " ".join(text.replace("\\\n", " ").split())


MAIN_FLAT = _flat(MAIN_SH)


# (check name as recorded, family kept, command display, main.sh text that runs it)
ANALYSIS_CHECKS = [
    (f"fastqc_{SAMPLE}_L001", "fastqc", "fastqc", 'require_cmd_ok "fastqc_${unit}" \\\n            fastqc '),
    (f"fastp_{SAMPLE}_L001", "fastp", "fastp", 'require_cmd_ok "fastp_${unit}" \\\n            fastp '),
    (f"index_{SAMPLE}_L001", "index_lane", "samtools index", 'require_cmd_ok "index_${unit}" samtools index'),
    ("merge", "merge", "samtools merge", 'require_cmd_ok "merge" samtools merge'),
    ("index_sample", "index_sample", "samtools index", 'require_cmd_ok "index_sample" samtools index'),
    ("markduplicates", "markduplicates", "gatk MarkDuplicates", 'require_cmd_ok "markduplicates" \\\n        gatk --java-options "$java_opts" MarkDuplicates'),
    ("index_markdup", "index_markdup", "samtools index", 'require_cmd_ok "index_markdup" samtools index'),
    ("base_recalibrator", "base_recalibrator", "gatk BaseRecalibrator", 'require_cmd_ok "base_recalibrator" \\\n        gatk --java-options "$java_opts" BaseRecalibrator'),
    ("apply_bqsr", "apply_bqsr", "gatk ApplyBQSR", 'require_cmd_ok "apply_bqsr" \\\n        gatk --java-options "$java_opts" ApplyBQSR'),
    ("index_analysis_ready", "index_analysis_ready", "samtools index", 'require_cmd_ok "index_analysis_ready" samtools index'),
    ("mosdepth", "mosdepth", "mosdepth", 'require_cmd_ok "mosdepth" \\\n        mosdepth '),
    ("haplotypecaller", "haplotypecaller", "gatk HaplotypeCaller", 'require_cmd_ok "haplotypecaller" \\\n        gatk --java-options "$java_opts" HaplotypeCaller'),
    ("index_gvcf", "index_gvcf", "tabix -p", 'require_cmd_ok "index_gvcf" tabix -p vcf'),
    ("genotype_gvcfs", "genotype_gvcfs", "gatk GenotypeGVCFs", 'require_cmd_ok "genotype_gvcfs" \\\n        gatk --java-options "$java_opts" GenotypeGVCFs'),
    ("index_raw_vcf", "index_raw_vcf", "tabix -p", 'require_cmd_ok "index_raw_vcf" tabix -p vcf'),
    ("bcftools_filter", "bcftools_filter", "bcftools view -i", 'require_cmd_ok "bcftools_filter" \\\n        bcftools view -i'),
    ("index_filtered", "index_filtered", "bcftools index -f", 'require_cmd_ok "index_filtered" bcftools index -f'),
    ("bcftools_norm", "bcftools_norm", "bcftools norm -m", 'local norm_cmd=(bcftools norm -m -any)'),
    ("index_normalized", "index_normalized", "bcftools index -f", 'require_cmd_ok "index_normalized" bcftools index -f'),
    ("bcftools_annotate", "bcftools_annotate", "bcftools annotate -a", 'require_cmd_ok "bcftools_annotate" \\\n            bcftools annotate -a'),
    # fail_step right after one command, whose outcome the check reports.
    ("merge_quickcheck", "merge_quickcheck", "samtools quickcheck", 'if ! samtools quickcheck -v "$sample_part"'),
    ("markdup_quickcheck", "markdup_quickcheck", "samtools quickcheck", 'if ! samtools quickcheck -v "$markdup_part"'),
    ("calmd_quickcheck", "calmd_quickcheck", "samtools quickcheck", 'if ! samtools quickcheck -v "$markdup_nm_part"'),
    ("apply_bqsr_quickcheck", "apply_bqsr_quickcheck", "samtools quickcheck", 'if ! samtools quickcheck -v "$final_part"'),
    ("invalid_lane_bam", "invalid_lane_bam", "samtools quickcheck", 'samtools quickcheck -q "$bam" || { fail_step "invalid_lane_bam"'),
    ("calmd_failed", "calmd_failed", "samtools calmd", 'fail_step "calmd_failed" "samtools calmd exited'),
    ("raw_vcf_parse", "raw_vcf_parse", "bcftools view -h", 'if ! bcftools view -h "$raw_part"'),
    ("gvcf_parse", "gvcf_parse", "bcftools view -h", 'if ! bcftools view -h "$gvcf_part"'),
]


@pytest.mark.parametrize("check, family, display, shell", ANALYSIS_CHECKS, ids=[c[1] for c in ANALYSIS_CHECKS])
def test_each_analysis_check_maps_to_the_command_main_sh_runs(check, family, display, shell):
    assert _flat(shell) in MAIN_FLAT, f"main.sh no longer contains: {shell!r}"
    mapped = commands.for_check(check)
    assert mapped is not None, check
    got_family, cmd = mapped
    assert got_family == family
    assert cmd.display() == display
    assert cmd.display().split(" -")[0].split(" ")[0] in shell
    assert SAMPLE not in got_family


@pytest.mark.parametrize("name", [
    # presence / size / grep / python tests: no command produced the check.
    "fastp_missing", "fastp_empty_output", "norm_empty", "filter_empty", "recal_table",
    "coverage_metrics", "missing_lane_bam", "missing_known_sites", "coverage_bed_invalid",
    # a two-command pipe (bwa | samtools sort): which one failed is in the message, not the check.
    f"alignment_{SAMPLE}_L001",
    # the ERR trap records the shell text of whatever line failed.
    "unexpected_error",
    # several different commands share this name across 04.
    "bam_validation",
])
def test_checks_not_produced_by_one_command_map_to_nothing(name):
    assert commands.for_check(name) is None


def _failed_step(run, step_id, check_name, detail="x"):
    builder = run(RUN_ID)
    builder.step(step_id, status="failed", checks=[
        {"name": check_name, "status": "FAIL", "detail": detail}],
        failures=[{"code": check_name, "message": detail}])
    builder.run_status("failed", current_step=step_id, steps=[])
    return builder


SAMTOOLS_ROWS = [
    _chunk("s#index#00", "COMMANDS AND OPTIONS > samtools index [ -bc ] aln.sam.gz",
           "Index a coordinate-sorted BGZIP-compressed SAM, BAM or CRAM file for fast random access."),
    _chunk("s#quick#00", "COMMANDS AND OPTIONS > samtools quickcheck [ -qv ] in.bam",
           "Quickly check that input files appear to be intact: header present and EOF block present."),
    _chunk("s#merge#00", "COMMANDS AND OPTIONS > samtools merge [ options ] out.bam in1.bam",
           "Merge multiple sorted alignment files, producing a single sorted output file."),
]


@pytest.fixture
def samtools_manual(tmp_path, monkeypatch):
    path = write_manual(tmp_path, rows=SAMTOOLS_ROWS, title="samtools(1)")
    monkeypatch.setattr(config, "DOC_MANUAL_CHUNKS", str(path))
    return path


def test_a_failed_lane_index_becomes_an_input_without_the_lane_name(
        client, make_job, run, samtools_manual, synthetic_passages):
    _failed_step(run, "03_alignment", f"index_{SAMPLE}_L001", detail=f"{SAMPLE} failed")
    make_job(RUN_ID, sample_id=SAMPLE, run_mode="full", planned=["03_alignment"])
    body = search(client)
    assert SAMPLE not in json.dumps(body)
    [item] = body["inputs"]
    assert item["origin"] == "stepCheck" and item["stepId"] == "03_alignment"
    assert item["kind"] == "index_lane" and item["tool"] == "samtools"
    assert item["command"]["display"] == "samtools index"
    assert body["excludedObservations"] == []


def test_an_analysis_input_is_searched_in_its_own_tools_manual_section(
        client, make_job, run, samtools_manual, synthetic_passages):
    _failed_step(run, "04_processing", "markdup_quickcheck")
    make_job(RUN_ID, sample_id=SAMPLE, run_mode="full", planned=["04_processing"])
    body = search(client)
    [item] = body["inputs"]
    manual_hits = [h for h in body["hits"] if h["corpus"] == "manual"]
    assert manual_hits and manual_hits[0]["relation"] == "sameCommandSection"
    assert manual_hits[0]["evidenceId"] == "manual:s#quick#00"
    # never filed under a resource-cause kind: no curated excerpt for a step check.
    assert not [h for h in body["hits"] if h["corpus"] == "curated"]
    assert any(s["corpus"] == "curated" for s in item["skipped"])


def test_another_tools_failure_is_skipped_with_a_reason_not_searched(
        client, make_job, run, samtools_manual, synthetic_passages):
    _failed_step(run, "04_processing", "markduplicates")
    make_job(RUN_ID, sample_id=SAMPLE, run_mode="full", planned=["04_processing"])
    body = search(client)
    [item] = body["inputs"]
    assert item["tool"] == "gatk" and item["command"]["display"] == "gatk MarkDuplicates"
    assert body["hits"] == []
    assert any(s["corpus"] == "manual" and "gatk" in s["reason"] for s in item["skipped"])


def test_a_presence_test_stays_excluded(client, make_job, run, samtools_manual, synthetic_passages):
    _failed_step(run, "02_preprocessing", "fastp_missing")
    make_job(RUN_ID, sample_id=SAMPLE, run_mode="full", planned=["02_preprocessing"])
    body = search(client)
    assert body["inputs"] == [] and body["hits"] == []
    assert body["excludedObservations"][0]["kind"] == "fastp_missing"
