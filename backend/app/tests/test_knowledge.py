"""The shared knowledge source must load, validate and agree with the pipeline.

config/knowledge/*.json is the canonical source for diagnostic and step
knowledge. The frontend imports the same two files; this suite is the backend
half of that contract.

Two kinds of assertion live here and they are different in kind:

  contract    the documents parse, are complete, and have no duplicate keys
  agreement   what they claim matches script/main.sh

The second kind is the point. The defect that motivated this whole source was a
registry claiming `08_filtering` used GATK and `10_annotation` used ANNOVAR
when the pipeline runs neither -- and nothing caught it, because nothing
compared the two. These tests compare them.
"""

from __future__ import annotations

import json
import re

import pytest

from .. import config
from ..services.explanation import knowledge

EXPECTED_DIAGNOSTIC_COUNT = 29
EXPECTED_STEP_COUNT = 11


# --- contract ---------------------------------------------------------------


def test_both_documents_load():
    assert len(knowledge.all_diagnostics()) == EXPECTED_DIAGNOSTIC_COUNT
    assert len(knowledge.all_steps()) == EXPECTED_STEP_COUNT


def test_every_diagnostic_is_complete():
    """Required fields are required. No entry may be half-filled."""
    for item in knowledge.all_diagnostics():
        assert item.code
        assert item.severity in ("attention", "info")
        assert item.resolution in ("repaired", None)
        assert item.status in ("active", "legacy")
        assert item.title, item.code
        assert item.meaning, item.code


def test_every_step_is_complete():
    for item in knowledge.all_steps():
        assert item.stepId
        assert item.label, item.stepId
        assert item.purpose, item.stepId
        assert isinstance(item.tools, list)


def test_lookup_returns_none_for_unknown_keys():
    """None is a real answer -- main.sh can add a code before this file knows it."""
    assert knowledge.diagnostic("NO_SUCH_CODE") is None
    assert knowledge.step("42_nonexistent") is None


# --- representative lookups -------------------------------------------------


def test_nm_md_repaired_carries_both_axes():
    """severity and resolution are independent; this entry is the only one
    that exercises the resolution axis."""
    item = knowledge.diagnostic("NM_MD_REPAIRED")
    assert item is not None
    assert item.severity == "info"
    assert item.resolution == "repaired"
    assert item.status == "active"
    assert item.relatedSteps == ["04_processing"]


def test_dbsnp_not_configured_is_info_without_resolution():
    """The pipeline states the calls themselves are unaffected, so this is a
    note, not something to act on -- and nothing was repaired."""
    item = knowledge.diagnostic("DBSNP_NOT_CONFIGURED")
    assert item is not None
    assert item.severity == "info"
    assert item.resolution is None
    assert item.relatedSteps == ["06_variant_calling"]


def test_dbsnp_missing_is_attention_unlike_dbsnp_not_configured():
    """The two arrive in identical shapes from the pipeline. Distinguishing
    them is the reason severity exists."""
    missing = knowledge.diagnostic("DBSNP_MISSING")
    not_configured = knowledge.diagnostic("DBSNP_NOT_CONFIGURED")
    assert missing is not None and not_configured is not None
    assert missing.severity == "attention"
    assert not_configured.severity == "info"


def test_uncovered_targets_is_marked_legacy():
    """main.sh no longer emits it (replaced by ZERO_COVERAGE_TARGET_BASES), but
    runs recorded before the rename still carry it and must stay readable."""
    item = knowledge.diagnostic("UNCOVERED_TARGETS")
    assert item is not None
    assert item.status == "legacy"

    replacement = knowledge.diagnostic("ZERO_COVERAGE_TARGET_BASES")
    assert replacement is not None
    assert replacement.status == "active"


def test_a_diagnostic_can_relate_to_several_steps():
    """MULTIQC_MISSING is raised from validate_tools (reached through
    00_input_validation) and from run_raw_qc. relatedSteps is therefore a list,
    and it says where the code CAN occur -- not where it did."""
    item = knowledge.diagnostic("MULTIQC_MISSING")
    assert item is not None
    assert item.relatedSteps == ["00_input_validation", "01_raw_qc"]


def test_representative_steps():
    processing = knowledge.step("04_processing")
    assert processing is not None
    assert processing.label == "BAM 정리·보정"
    assert processing.tools == ["gatk", "samtools"]

    filtering = knowledge.step("08_filtering")
    assert filtering is not None
    assert filtering.tools == ["bcftools"]

    annotation = knowledge.step("10_annotation")
    assert annotation is not None
    assert annotation.tools == ["bcftools"]


# --- agreement with the pipeline -------------------------------------------


@pytest.fixture(scope="module")
def main_sh() -> str:
    return config.PIPELINE_SH.read_text(encoding="utf-8")


def test_no_step_claims_a_tool_the_pipeline_does_not_run(main_sh):
    """The regression that motivated this source.

    steps.ts claimed GATK for 08_filtering and ANNOVAR for 10_annotation. The
    pipeline runs bcftools in both. Nothing compared the two, so nothing
    noticed -- and both steps are currently `not_run`, so it never reached a
    screen either.
    """
    for item in knowledge.all_steps():
        for tool in item.tools:
            assert tool in main_sh, f"{item.stepId} claims {tool!r}, absent from main.sh"


def test_annovar_and_gatk_hard_filtering_are_not_claimed():
    """Tools the pipeline does not run must not appear as current implementation.

    ANNOVAR is never invoked. VEP is present only as a `have_command` check that
    raises VEP_NOT_WIRED. Registering either as a step tool would make any
    explanation built on this source state something false.
    """
    claimed = {tool for item in knowledge.all_steps() for tool in item.tools}
    assert "ANNOVAR" not in claimed
    assert "annovar" not in claimed
    assert "vep" not in claimed
    assert knowledge.step("08_filtering").tools == ["bcftools"]


def test_every_active_diagnostic_code_exists_in_main_sh(main_sh):
    """An active code the pipeline cannot emit is either a typo or stale."""
    emitted = set(re.findall(r'step_warning "([A-Z_]+)"', main_sh))
    for item in knowledge.all_diagnostics():
        if item.status == "legacy":
            continue
        assert item.code in emitted, f"{item.code} is active but main.sh never emits it"


def test_legacy_codes_are_no_longer_emitted(main_sh):
    """The inverse: a code marked legacy must really be gone from main.sh."""
    emitted = set(re.findall(r'step_warning "([A-Z_]+)"', main_sh))
    for item in knowledge.all_diagnostics():
        if item.status == "legacy":
            assert item.code not in emitted, f"{item.code} is marked legacy but still emitted"


def test_every_emitted_code_is_registered(main_sh):
    """No code may reach a screen without knowledge behind it."""
    emitted = set(re.findall(r'step_warning "([A-Z_]+)"', main_sh))
    registered = {item.code for item in knowledge.all_diagnostics()}
    assert emitted - registered == set()


def test_related_steps_name_real_steps():
    known = {item.stepId for item in knowledge.all_steps()}
    for item in knowledge.all_diagnostics():
        for step_id in item.relatedSteps:
            assert step_id in known, f"{item.code} relates to unknown step {step_id}"


# --- the two sides read the same file ---------------------------------------


def test_the_frontend_reads_the_same_paths():
    """Guards against a copy appearing under front/ or backend/.

    Two copies drift. That is the whole defect this source removes, so the
    location is asserted rather than assumed.
    """
    assert config.KNOWLEDGE_DIR == config.ROOT / "config" / "knowledge"
    assert config.DIAGNOSTIC_KNOWLEDGE.is_file()
    assert config.STEP_KNOWLEDGE.is_file()

    vite = (config.ROOT / "front" / "vite.config.ts").read_text(encoding="utf-8")
    assert "'@shared'" in vite
    assert "'../config'" in vite

    registries = config.ROOT / "front" / "src" / "registries"
    diagnostics_ts = (registries / "diagnostics.ts").read_text(encoding="utf-8")
    steps_ts = (registries / "steps.ts").read_text(encoding="utf-8")

    # Both read the shared loader rather than declaring their own tables.
    assert "@/registries/knowledge" in diagnostics_ts
    assert "@/registries/knowledge" in steps_ts

    # No per-code knowledge table may survive in the presentation layer. A
    # single fallback default for unknown codes is fine and is not a table, so
    # the test counts code-shaped keys instead of matching field names.
    code_keys = re.findall(r"^\s{2}[A-Z][A-Z0-9_]{3,}:\s*\{", diagnostics_ts, re.M)
    assert code_keys == [], f"diagnostics.ts still declares knowledge: {code_keys}"

    # Same for steps: no per-step knowledge table. STEP_SUBTITLE is a flat
    # string map, not a table of definitions, so it does not match this shape.
    step_keys = re.findall(r"^\s{2}'\d\d_[a-z_]+':\s*\{", steps_ts, re.M)
    assert step_keys == [], f"steps.ts still declares knowledge: {step_keys}"


def test_documents_are_utf8_json_with_a_schema_version():
    for path in (config.DIAGNOSTIC_KNOWLEDGE, config.STEP_KNOWLEDGE):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schemaVersion"] == "1.0", path.name
