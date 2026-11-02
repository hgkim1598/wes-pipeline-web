"""The enrichment must be sourced, grounded in the pipeline, and free of verdicts.

`title` and `meaning` say what a code means. The enrichment added on top says
why it can happen, where to look and what a value does *not* establish -- the
questions a synthesis layer will be asked. That material is only worth having if
it cannot quietly become invention, so these tests defend three properties:

  sourced     every claim cites a source that exists
  grounded    every "look here" points at something main.sh actually emits
  no verdict  no threshold judgement can enter, by shape and by wording

The first two are structural and are the real protection. The third is a
backstop: a naming test can always be written around, so it is deliberately
narrow (decimal literals and a short list of verdict words) rather than a large
banned-phrase list pretending to be a policy.

An empty bucket is a legitimate answer here and is asserted as such. The point
of the exercise is that unsourced explanations stay out, not that every field
gets filled.
"""

from __future__ import annotations

import json
import re

import pytest

from .. import config
from ..services.explanation import knowledge

# Enriched in this slice, chosen because a real run exercised them or because a
# reader demonstrably misread the underlying value. Asserted exactly: a fifth
# entry appearing without a deliberate decision is the drift this guards.
ENRICHED_DIAGNOSTICS = {
    "NM_MD_REPAIRED",
    "DBSNP_NOT_CONFIGURED",
    "ZERO_COVERAGE_TARGET_BASES",
    "MULTIQC_MISSING",
}

CURATED_FAILURES = {"required_tools", "resource_bundle"}

CONCEPTS = {
    "coverage-measurement-levels",
    "unfiltered-variant-output",
    "intended-use-ruo",
}


@pytest.fixture(scope="module")
def main_sh() -> str:
    return config.PIPELINE_SH.read_text(encoding="utf-8")


def _all_grounding() -> list[tuple[str, knowledge.Grounding]]:
    """(owner, grounding) for everything enriched, across all three documents."""
    out: list[tuple[str, knowledge.Grounding]] = []
    for row in knowledge.all_diagnostics():
        if row.grounding is not None:
            out.append((row.code, row.grounding))
    for failure in knowledge.all_failures():
        if failure.grounding is not None:
            out.append((failure.code, failure.grounding))
    for concept in knowledge.all_concepts():
        if concept.grounding is not None:
            out.append((concept.id, concept.grounding))
    return out


def _statements(grounding: knowledge.Grounding) -> list[str]:
    texts = [claim.statement for claim in grounding.possibleCauses]
    texts += [claim.statement for claim in grounding.scope]
    texts += [check.statement for check in grounding.checks]
    for action in grounding.actions:
        texts.append(action.statement)
        texts.append(action.effect)
    return texts


def _source_id_groups(grounding: knowledge.Grounding) -> list[list[str]]:
    groups = [claim.sourceIds for claim in grounding.possibleCauses]
    groups += [claim.sourceIds for claim in grounding.scope]
    groups += [check.sourceIds for check in grounding.checks]
    groups += [action.sourceIds for action in grounding.actions]
    return groups


# --- the existing contract still holds --------------------------------------


def test_enrichment_did_not_change_the_existing_registries():
    """Additive by construction. The counts are the cheapest proof."""
    assert len(knowledge.all_diagnostics()) == 29
    assert len(knowledge.all_steps()) == 11


def test_unenriched_diagnostics_keep_grounding_none():
    """`None` means "not written yet" and must not be filled with a default.

    A Grounding with four empty lists would look the same to a careless reader
    but claims something different -- that we looked and found nothing. Only the
    codes we actually worked on may carry that claim.
    """
    enriched = {
        row.code for row in knowledge.all_diagnostics() if row.grounding is not None
    }
    assert enriched == ENRICHED_DIAGNOSTICS


def test_legacy_status_survives_enrichment():
    legacy = knowledge.diagnostic("UNCOVERED_TARGETS")
    assert legacy is not None
    assert legacy.status == "legacy"
    # Deliberately not enriched: the pipeline no longer emits it, so writing
    # causes for it would be archaeology, not knowledge.
    assert legacy.grounding is None


# --- sourced ----------------------------------------------------------------


def test_every_claim_cites_at_least_one_source():
    for owner, grounding in _all_grounding():
        for ids in _source_id_groups(grounding):
            assert ids, f"{owner} has a claim with no sourceIds"


def test_every_cited_source_resolves():
    known = {source.id for source in knowledge.all_sources()}
    for owner, grounding in _all_grounding():
        for ids in _source_id_groups(grounding):
            for source_id in ids:
                assert source_id in known, f"{owner} cites unknown source {source_id}"


def test_an_unknown_source_is_rejected_at_load(tmp_path, monkeypatch):
    """The referential check is the difference between provenance and decoration.

    Without it `sourceIds: ["something-plausible"]` would validate, and a claim
    could cite a source that was never written.
    """
    doc = json.loads(config.DIAGNOSTIC_KNOWLEDGE.read_text(encoding="utf-8"))
    for row in doc["diagnostics"]:
        if row["code"] == "NM_MD_REPAIRED":
            row["grounding"]["possibleCauses"][0]["sourceIds"] = ["no-such-source"]
    broken = tmp_path / "wes_diagnostics.json"
    broken.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(config, "DIAGNOSTIC_KNOWLEDGE", broken)
    knowledge.reload()
    try:
        with pytest.raises(knowledge.KnowledgeError, match="no-such-source"):
            knowledge.all_diagnostics()
    finally:
        monkeypatch.undo()
        knowledge.reload()


def test_a_claim_without_sources_cannot_be_constructed():
    """min_length=1 on sourceIds, asserted so a schema relaxation is caught."""
    with pytest.raises(Exception):
        knowledge.Claim(statement="unsourced", sourceIds=[])


def test_every_source_is_actually_cited():
    """An uncited source is a citation someone removed without cleaning up.

    Kept strict while the registry is small: 14 entries written for 9 enriched
    subjects. If a future source is added ahead of the claim that needs it, this
    is the test to relax deliberately.
    """
    cited: set[str] = set()
    for _owner, grounding in _all_grounding():
        for ids in _source_id_groups(grounding):
            cited.update(ids)
    # Term definitions are claims too (wes_terms.json); some sources exist only
    # for them -- the SAM and VCF specs, NCBI's dbSNP page.
    for term in knowledge.all_terms():
        for claim in [term.definition, *term.misreadings]:
            cited.update(claim.sourceIds)
    declared = {source.id for source in knowledge.all_sources()}
    assert declared - cited == set(), f"uncited sources: {sorted(declared - cited)}"


def test_in_repo_sources_point_at_files_that_exist():
    for source in knowledge.all_sources():
        if source.type in ("pipeline", "project-doc"):
            path, _, anchor = source.locator.partition("#")
            assert (config.ROOT / path).is_file(), f"{source.id}: missing {path}"
            # The anchor must be a string that greps, not a line number: line
            # numbers move and the citation silently becomes wrong.
            assert anchor, f"{source.id}: locator has no anchor"
            assert not anchor.isdigit(), f"{source.id}: anchor is a line number"
            text = (config.ROOT / path).read_text(encoding="utf-8")
            assert anchor in text, f"{source.id}: anchor {anchor!r} not found in {path}"
        else:
            assert source.locator.startswith("https://"), source.id


# --- grounded ---------------------------------------------------------------


def test_every_check_locator_exists_in_the_pipeline(main_sh):
    """A "look here" that points at nothing is worse than no pointer.

    Each locator kind is matched against the call main.sh actually uses to
    produce it, so a renamed artifact or metric fails here rather than sending
    a reader to a file the run never wrote.
    """
    for owner, grounding in _all_grounding():
        for check in grounding.checks:
            kind, identifier = check.locator.kind, check.locator.id
            if kind == "artifact":
                needle = f"add_artifact {identifier} "
            elif kind == "metric":
                needle = f"step_metric {identifier} "
            elif kind == "check":
                needle = f'"{identifier}"'
            elif kind == "stepFile":
                needle = identifier.rsplit("/", maxsplit=1)[-1]
            else:  # pragma: no cover - Literal makes this unreachable
                raise AssertionError(f"unhandled locator kind {kind}")
            assert needle in main_sh, (
                f"{owner}: {kind} locator {identifier!r} does not appear in main.sh"
            )


def test_check_locator_names_a_check_the_pipeline_records(main_sh):
    """`check` locators must name a real step_check_pass/fail argument."""
    for owner, grounding in _all_grounding():
        for check in grounding.checks:
            if check.locator.kind != "check":
                continue
            identifier = check.locator.id
            assert (
                f'step_check_pass "{identifier}"' in main_sh
                or f'step_check_fail "{identifier}"' in main_sh
            ), f"{owner}: {identifier!r} is not a recorded check"


def test_enriched_diagnostic_codes_are_real_pipeline_codes(main_sh):
    for code in ENRICHED_DIAGNOSTICS:
        assert f'step_warning "{code}"' in main_sh


def test_curated_failure_codes_are_real_pipeline_codes(main_sh):
    for code in CURATED_FAILURES:
        assert f'step_check_fail "{code}"' in main_sh


# --- no verdict -------------------------------------------------------------

# Decimal literals are how a threshold enters ("7.2%", "20x"). Whole numbers
# survive because they appear in legitimate structural statements ("0x bases",
# "0보다"). This is narrow on purpose -- see the module docstring.
_DECIMAL = re.compile(r"\d+\.\d+")

# Words that turn a measurement into a verdict. Short by design: a long list
# would read as the policy, and the policy is the schema.
_VERDICT_WORDS = (
    "충분",
    "불충분",
    "양호",
    "불량",
    "심각",
    "우수",
    "정상 범위",
    "권장합니다",
    "좋습니다",
    "나쁩니다",
)


def test_no_enrichment_statement_carries_a_numeric_threshold():
    for owner, grounding in _all_grounding():
        for text in _statements(grounding):
            found = _DECIMAL.findall(text)
            assert not found, f"{owner}: numeric threshold {found} in {text[:60]!r}"


def test_no_enrichment_statement_delivers_a_verdict():
    for owner, grounding in _all_grounding():
        for text in _statements(grounding):
            for word in _VERDICT_WORDS:
                assert word not in text, f"{owner}: verdict word {word!r} in {text[:60]!r}"


def test_the_schema_has_no_place_to_put_a_verdict():
    """The primary guard is shape, not wording.

    Grounding has four buckets and none is a judgement; Claim, Check and
    Action carry only text plus provenance. There is no severity, score,
    threshold or rating field, so a verdict is unrepresentable rather than
    discouraged. Asserted because adding such a field is exactly the change that
    would need a second opinion.
    """
    assert set(knowledge.Grounding.model_fields) == {
        "possibleCauses",
        "scope",
        "checks",
        "actions",
    }
    assert set(knowledge.Claim.model_fields) == {"statement", "sourceIds"}
    assert set(knowledge.Check.model_fields) == {"statement", "locator", "sourceIds"}
    # `effect` is required: a bare imperative is a recommendation, stating what
    # it changes keeps it a fact about the pipeline.
    assert set(knowledge.Action.model_fields) == {"statement", "effect", "sourceIds"}
    assert knowledge.Action.model_fields["effect"].is_required()


def test_zero_coverage_has_no_causes_and_says_why():
    """The deliberate gap, asserted so it is not "fixed" by guessing.

    The usual explanations for uncovered targets are plausible and unsourced.
    What *is* established is that this project has set no pass/fail threshold,
    so that is stated as scope instead of a cause.
    """
    entry = knowledge.diagnostic("ZERO_COVERAGE_TARGET_BASES")
    assert entry is not None and entry.grounding is not None
    assert entry.grounding.possibleCauses == []
    assert entry.grounding.actions == []
    assert entry.grounding.scope, "the empty causes must be explained, not silent"
    assert any("기준" in claim.statement for claim in entry.grounding.scope)


def test_nm_md_repaired_does_not_blame_an_aligner():
    """The project audit established an observation, not a culprit.

    The SAM specification says NM has historically been ill-defined and that
    tools disagreeing with the definition exist. That is the sourced statement.
    Naming a specific aligner would be a conclusion the audit did not reach.
    """
    entry = knowledge.diagnostic("NM_MD_REPAIRED")
    assert entry is not None and entry.grounding is not None
    text = " ".join(_statements(entry.grounding))
    for tool in ("BWA", "bwa", "버그", "결함이다"):
        assert tool not in text, f"NM_MD_REPAIRED attributes the cause: {tool}"
    assert any("sam-tags-spec" in ids for ids in _source_id_groups(entry.grounding))


def test_project_specific_observations_stay_out_of_shared_knowledge():
    """One run's observation is not general knowledge.

    The 2026-09-07 audit counted 37 INVALID_TAG_NM records in one run. That
    number belongs to that run and reaches a reader through the run's own
    metrics and validation reports -- which is what the `checks` locators point
    at. Putting it here would make one run's numbers look like a property of the
    code.
    """
    for owner, grounding in _all_grounding():
        text = " ".join(_statements(grounding))
        assert "37" not in text, f"{owner} carries a specific run's count"
        for word in ("이번 실행에서는", "관찰됐습니다", "관찰되었습니다"):
            assert word not in text, f"{owner} states a single run's observation"


# --- failures are an open set -----------------------------------------------


def test_failure_knowledge_is_declared_open():
    doc = json.loads(config.FAILURE_KNOWLEDGE.read_text(encoding="utf-8"))
    assert doc["closedSet"] is False
    assert {row.code for row in knowledge.all_failures()} == CURATED_FAILURES


def test_a_closed_failure_set_is_rejected(tmp_path, monkeypatch):
    """main.sh composes codes from run values, so the set cannot be closed.

    Declaring it closed would make every composed code -- `alignment_${unit}`,
    `sort_order_<sample>.L001` -- look like an unregistered defect.
    """
    doc = json.loads(config.FAILURE_KNOWLEDGE.read_text(encoding="utf-8"))
    doc["closedSet"] = True
    broken = tmp_path / "wes_failures.json"
    broken.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(config, "FAILURE_KNOWLEDGE", broken)
    knowledge.reload()
    try:
        with pytest.raises(knowledge.KnowledgeError, match="closedSet"):
            knowledge.all_failures()
    finally:
        monkeypatch.undo()
        knowledge.reload()


def test_an_uncurated_failure_code_returns_none():
    """The common case, and the caller must handle it as normal.

    A composed code is not a gap in the registry; the run's own message is the
    explanation.
    """
    assert knowledge.failure("sort_order_DEMO_WES.L001") is None
    assert knowledge.failure("alignment_DEMO") is None


# --- concepts ---------------------------------------------------------------


def test_concepts_are_the_three_interpretation_facts():
    assert {row.id for row in knowledge.all_concepts()} == CONCEPTS


def test_coverage_concept_states_that_no_threshold_exists():
    """The direct answer to "is this coverage good enough": we cannot say.

    Recorded as knowledge rather than left to the caller, because the absence of
    a threshold is itself a fact about this project.
    """
    entry = knowledge.concept("coverage-measurement-levels")
    assert entry is not None and entry.grounding is not None
    assert any("임계값" in claim.statement for claim in entry.grounding.scope)


def test_unfiltered_output_is_described_as_structural_not_per_run():
    """`filtering_applied` is hard-coded False in main.sh.

    A reader who takes it for a per-run outcome will read "no filtering" as
    something that happened this time. It is a property of the pipeline.
    """
    entry = knowledge.concept("unfiltered-variant-output")
    assert entry is not None and entry.grounding is not None
    text = " ".join(_statements(entry.grounding))
    assert "파이프라인의 성질" in text


# --- one source, two consumers ----------------------------------------------


def test_the_frontend_reads_the_shared_failure_knowledge():
    """The reason the failure text moved out of the frontend at all.

    Backend explanation and the failure card must say the same thing about the
    same code. A curated copy under front/ is how `steps.ts` drifted from the
    pipeline, so its absence is asserted rather than trusted.
    """
    assert config.FAILURE_KNOWLEDGE.is_file()
    registry = (
        config.ROOT / "front" / "src" / "registries" / "failures.ts"
    ).read_text(encoding="utf-8")

    assert "@/registries/knowledge" in registry
    # helpPath is a frontend route and legitimately stays. Any other per-code
    # table would be a second copy of the knowledge.
    tables = re.findall(r"^const ([A-Z_]+): Record<string, [^>]+> = \{", registry, re.M)
    assert tables == ["HELP_PATH"], f"failures.ts declares knowledge: {tables}"

    for code in CURATED_FAILURES:
        entry = knowledge.failure(code)
        assert entry is not None
        # The text itself must not have been left behind in the frontend.
        assert entry.title not in registry
        assert entry.meaning not in registry
