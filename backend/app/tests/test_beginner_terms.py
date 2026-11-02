"""Beginner terms: what is defined, when it is sent, and how it is cited.

    knowledge   wes_terms.json is sourced, carries no number or verdict, and
                says for which sections and codes each term is needed
    selection   only the terms this run's payload needs are sent
    citing      `term:` ids are minted with the entry, accepted by the gate
                only when sent, and grounding carries its code's evidenceId

No test here calls a model or runs a pipeline: answers come from a fake provider.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from app import config
from app.services.explanation import deterministic, knowledge, run_context
from app.services.explanation.deterministic import RunExplanation
from app.services.explanation.llm import contract, provider
from app.services.explanation.llm import synthesis as llm_synthesis

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"

TERMS = [
    "read",
    "target",
    "depth",
    "zero-coverage",
    "bam",
    "vcf",
    "dbsnp-rsid",
    "nm-md-tags",
]

# Sections build_payload adds only when the run produced them. A term can only
# be tied to one of these: the others are present in every payload.
CONDITIONAL_SECTIONS = {"coverage", "variantCalling", "intendedUse", "steps"}


def _fixture(name: str) -> RunExplanation:
    raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return RunExplanation.model_validate(raw)


def _term_ids(payload: dict[str, Any]) -> list[str]:
    return [entry["evidenceId"] for entry in payload.get("terms", [])]


def _texts(term: knowledge.TermKnowledge) -> list[str]:
    return [term.plain, term.definition.statement, *(c.statement for c in term.misreadings)]


def _mentions(text: str, spellings: list[str]) -> bool:
    # A Latin-letter boundary on both sides, so "depth" does not match
    # "mosdepth" and "MD" does not match an identifier containing it. Korean
    # particles directly after a term ("read가") still match.
    return any(
        re.search(rf"(?<![A-Za-z]){re.escape(s)}(?![A-Za-z])", text) for s in spellings
    )


def _grounding_texts(grounding: knowledge.Grounding | None) -> list[str]:
    if grounding is None:
        return []
    out = [c.statement for c in grounding.possibleCauses]
    out += [c.statement for c in grounding.scope]
    out += [c.statement for c in grounding.checks]
    for action in grounding.actions:
        out += [action.statement, action.effect]
    return out


def _walk_evidence_ids(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidenceId" and isinstance(value, str):
                found.add(value)
            else:
                found |= _walk_evidence_ids(value)
    elif isinstance(node, list):
        for value in node:
            found |= _walk_evidence_ids(value)
    return found


# --- knowledge ----------------------------------------------------------------


def test_the_registered_terms_are_the_eight_beginner_terms():
    assert [term.id for term in knowledge.all_terms()] == TERMS


def test_terms_are_not_a_second_copy_of_the_concepts():
    """Concepts are interpretation boundaries; terms are words. No shared id."""
    concept_ids = {row.id for row in knowledge.all_concepts()}
    assert concept_ids.isdisjoint(TERMS)


def test_every_term_claim_cites_a_registered_source():
    known = {source.id for source in knowledge.all_sources()}
    for term in knowledge.all_terms():
        for claim in [term.definition, *term.misreadings]:
            assert claim.sourceIds
            assert set(claim.sourceIds) <= known, term.id


def test_a_term_citing_an_unknown_source_is_rejected_at_load(tmp_path, monkeypatch):
    doc = json.loads(config.TERM_KNOWLEDGE.read_text(encoding="utf-8"))
    doc["terms"][0]["definition"]["sourceIds"] = ["no-such-source"]
    broken = tmp_path / "wes_terms.json"
    broken.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "TERM_KNOWLEDGE", broken)
    knowledge.reload()
    try:
        with pytest.raises(knowledge.KnowledgeError, match="no-such-source"):
            knowledge.all_terms()
    finally:
        monkeypatch.undo()
        knowledge.reload()


def test_a_term_used_for_an_unknown_diagnostic_is_rejected_at_load(tmp_path, monkeypatch):
    """A typo in usedWhen would otherwise mean the term is silently never sent."""
    doc = json.loads(config.TERM_KNOWLEDGE.read_text(encoding="utf-8"))
    doc["terms"][0]["usedWhen"]["diagnostics"].append("NO_SUCH_CODE")
    broken = tmp_path / "wes_terms.json"
    broken.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "TERM_KNOWLEDGE", broken)
    knowledge.reload()
    try:
        with pytest.raises(knowledge.KnowledgeError, match="NO_SUCH_CODE"):
            knowledge.all_terms()
    finally:
        monkeypatch.undo()
        knowledge.reload()


def test_term_text_carries_no_number():
    """No measurement or threshold. The one digit allowed is the 0 of "0×" --
    the name of the term itself -- which the number gate exempts anyway."""
    for term in knowledge.all_terms():
        for text in [term.label, *term.aliases, *_texts(term)]:
            numbers = re.findall(r"\d+(?:[.,]\d+)*", text)
            assert set(numbers) <= {"0"}, f"{term.id}: {numbers} in {text[:50]!r}"


_VERDICT_OR_CLINICAL = (
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
    "병원성",
    "질병",
    "환자",
    "진단합니다",
)


def test_term_text_delivers_no_verdict_and_nothing_clinical():
    for term in knowledge.all_terms():
        for text in _texts(term):
            for word in _VERDICT_OR_CLINICAL:
                assert word not in text, f"{term.id}: {word!r} in {text[:50]!r}"


def test_terms_are_tied_only_to_sections_that_can_be_absent():
    for term in knowledge.all_terms():
        assert set(term.usedWhen.sections) <= CONDITIONAL_SECTIONS, term.id


def test_failure_codes_a_term_names_are_curated_failures():
    curated = {row.code for row in knowledge.all_failures()}
    for term in knowledge.all_terms():
        assert set(term.usedWhen.failures) <= curated, term.id


def test_every_code_whose_knowledge_uses_a_term_sends_it():
    """No needed term is left out.

    If a diagnostic's or failure's title, meaning or grounding uses a term, the
    term must be sent with that code -- otherwise the model is handed a word to
    explain with no definition beside it.
    """
    for term in knowledge.all_terms():
        for row in knowledge.all_diagnostics():
            texts = [row.title, row.meaning, *_grounding_texts(row.grounding)]
            if any(_mentions(t, term.mentions) for t in texts):
                assert row.code in term.usedWhen.diagnostics, (term.id, row.code)
        for failure in knowledge.all_failures():
            texts = [failure.title, failure.meaning, *_grounding_texts(failure.grounding)]
            if any(_mentions(t, term.mentions) for t in texts):
                assert failure.code in term.usedWhen.failures, (term.id, failure.code)


def test_every_concept_that_uses_a_term_has_it_sent_with_its_section():
    section_of = {concept_id: s for s, concept_id in contract._CONCEPT_FOR_SECTION.items()}
    for term in knowledge.all_terms():
        for concept in knowledge.all_concepts():
            texts = [concept.label, concept.summary, *_grounding_texts(concept.grounding)]
            if any(_mentions(t, term.mentions) for t in texts):
                assert section_of[concept.id] in term.usedWhen.sections, (term.id, concept.id)


def test_a_term_used_in_another_terms_definition_is_sent_with_it():
    """Closure: defining "depth" with "read" is no use if "read" is not sent."""
    terms = knowledge.all_terms()
    for outer in terms:
        for inner in terms:
            if inner.id == outer.id:
                continue
            if not any(_mentions(t, inner.mentions) for t in _texts(outer)):
                continue
            for bucket in ("sections", "diagnostics", "failures"):
                missing = set(getattr(outer.usedWhen, bucket)) - set(
                    getattr(inner.usedWhen, bucket)
                )
                assert not missing, f"{inner.id} must be sent wherever {outer.id} is: {missing}"


def test_every_listed_code_actually_needs_the_term():
    """No term is added for nothing: a listed code uses the term itself, or
    uses another term whose definition does (the closure above)."""
    terms = knowledge.all_terms()
    for term in terms:
        via_other = set()
        for other in terms:
            if other.id != term.id and any(_mentions(t, term.mentions) for t in _texts(other)):
                via_other |= set(other.usedWhen.diagnostics) | set(other.usedWhen.failures)
        for code in term.usedWhen.diagnostics:
            row = knowledge.diagnostic(code)
            assert row is not None
            texts = [row.title, row.meaning, *_grounding_texts(row.grounding)]
            assert any(_mentions(t, term.mentions) for t in texts) or code in via_other, (
                term.id,
                code,
            )
        for code in term.usedWhen.failures:
            failure = knowledge.failure(code)
            assert failure is not None
            texts = [failure.title, failure.meaning, *_grounding_texts(failure.grounding)]
            assert any(_mentions(t, term.mentions) for t in texts) or code in via_other, (
                term.id,
                code,
            )


# --- selection ----------------------------------------------------------------


def test_a_full_run_with_coverage_variants_and_three_warnings_gets_every_term():
    payload, _allowed = contract.build_payload(_fixture("full_completed_with_warnings"))
    assert _term_ids(payload) == [f"term:{t}" for t in TERMS]


@pytest.mark.parametrize("case", ["execution_failed", "in_progress"])
def test_a_run_that_needs_no_term_has_no_terms_section(case):
    """Absent, not empty: such a payload is exactly what it was before."""
    payload, allowed = contract.build_payload(_fixture(case))
    assert "terms" not in payload
    assert not any(ref.startswith("term:") for ref in allowed)


def test_a_precheck_failure_gets_only_the_terms_its_failure_uses():
    """resource_bundle names target BED and dbSNP; the dbSNP definition uses VCF."""
    payload, _allowed = contract.build_payload(_fixture("precheck_failed"))
    assert _term_ids(payload) == ["term:target", "term:vcf", "term:dbsnp-rsid"]


def test_a_single_warning_brings_only_its_own_terms():
    """Nothing about coverage in a run whose only warning is the NM/MD repair."""
    base = _fixture("full_completed_with_warnings")
    nm_md = [d for d in base.diagnostics if d.code == "NM_MD_REPAIRED"]
    explanation = base.model_copy(
        update={"diagnostics": nm_md, "coverage": None, "variantCalling": None}
    )
    payload, _allowed = contract.build_payload(explanation)
    assert _term_ids(payload) == ["term:read", "term:bam", "term:nm-md-tags"]


def test_coverage_alone_brings_the_coverage_terms_and_nothing_else():
    base = _fixture("full_completed_with_warnings")
    explanation = base.model_copy(update={"diagnostics": [], "variantCalling": None})
    payload, _allowed = contract.build_payload(explanation)
    assert _term_ids(payload) == [
        "term:read",
        "term:target",
        "term:depth",
        "term:zero-coverage",
    ]


# --- citing -------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", ["full_completed_with_warnings", "precheck_failed", "execution_failed", "in_progress"]
)
def test_the_allowed_ids_are_exactly_the_ids_written_in_the_payload(case):
    """Nothing citable that the model cannot see, nothing visible it cannot cite."""
    payload, allowed = contract.build_payload(_fixture(case))
    assert _walk_evidence_ids(payload) == allowed


def test_every_source_a_term_lists_is_citable():
    payload, allowed = contract.build_payload(_fixture("full_completed_with_warnings"))
    listed = {s["evidenceId"] for s in payload["sources"]}
    for entry in payload["terms"]:
        for claim in [entry["definition"], *entry.get("misreadings", [])]:
            for source_id in claim["sourceIds"]:
                assert f"src:{source_id}" in allowed
                assert f"src:{source_id}" in listed


@pytest.mark.parametrize("case", ["full_completed_with_warnings", "precheck_failed"])
def test_grounding_carries_the_evidence_id_of_its_own_diagnostic_or_failure(case):
    payload, _allowed = contract.build_payload(_fixture(case))
    assert payload["grounding"], case
    raised = {d["evidenceId"] for d in payload["diagnostics"]} | {
        f["evidenceId"] for f in payload["failures"]
    }
    for key, entry in payload["grounding"].items():
        assert entry["evidenceId"] == key
        assert entry["evidenceId"] in raised


def test_a_term_entry_has_no_selection_metadata():
    payload, _allowed = contract.build_payload(_fixture("full_completed_with_warnings"))
    for entry in payload["terms"]:
        assert "usedWhen" not in entry and "mentions" not in entry


def test_term_entries_carry_no_sample_identifier_or_path():
    payload, _allowed = contract.build_payload(_fixture("full_completed_with_warnings"))
    text = json.dumps(payload["terms"], ensure_ascii=False)
    assert "EVAL_SAMPLE_CANARY" not in text
    assert not re.search(r"[A-Za-z]:\\|/home/|/Users/", text)


def _answer(refs: list[str]) -> dict:
    return {
        "summary": "실행을 확인했습니다.",
        "importantFindings": [
            {"statement": "정렬 파일의 보조 표시가 보정되었습니다.", "evidenceRefs": refs}
        ],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }


def _fake(answer: dict):
    def fake(**_kwargs):
        return provider.ProviderResult(payload=answer, models=["test-model"])

    return fake


def test_a_sent_term_id_is_accepted_beside_the_fact_it_explains():
    explanation = _fixture("full_completed_with_warnings")
    result = llm_synthesis.build_run_synthesis(
        explanation,
        run_provider=_fake(_answer(["dx:NM_MD_REPAIRED", "term:nm-md-tags"])),
        offer_tools=False,
    )
    assert result.available is True


def test_a_term_id_that_was_not_sent_is_rejected():
    """`term:depth` is a real term, but this run has no coverage: not minted."""
    base = _fixture("full_completed_with_warnings")
    nm_md = [d for d in base.diagnostics if d.code == "NM_MD_REPAIRED"]
    explanation = base.model_copy(
        update={"diagnostics": nm_md, "coverage": None, "variantCalling": None}
    )
    result = llm_synthesis.build_run_synthesis(
        explanation,
        run_provider=_fake(_answer(["dx:NM_MD_REPAIRED", "term:depth"])),
        offer_tools=False,
    )
    assert result.available is False
    assert result.errorCategory == "unknownEvidenceRef"


@pytest.mark.parametrize("ref", ["term:no-such-term", "terms:read", "term:", "grounding:dx:NM_MD_REPAIRED"])
def test_an_unminted_or_assembled_id_is_still_rejected(ref):
    result = llm_synthesis.build_run_synthesis(
        _fixture("full_completed_with_warnings"),
        run_provider=_fake(_answer(["dx:NM_MD_REPAIRED", ref])),
        offer_tools=False,
    )
    assert result.available is False
    assert result.errorCategory == "unknownEvidenceRef"


def test_the_production_path_sends_terms_too(client, make_job, run):
    """The DB-backed explanation (V3 default) reaches the same term section."""
    job = make_job(
        "wes-20260821-142659-c66d6e",
        run_mode="full",
        planned=[
            "00_input_validation",
            "01_raw_qc",
            "02_preprocessing",
            "03_alignment",
            "04_processing",
            "05_coverage_qc",
            "06_variant_calling",
            "99_finalization",
        ],
        sample_id="DEMO01",
    )
    run(job).as_completed_full()
    explanation = deterministic.build_run_explanation(
        run_context.build_run_diagnostic_context(job)
    )
    payload, allowed = contract.build_payload(explanation)
    assert payload.get("terms"), "a completed full run has coverage, so terms are sent"
    assert set(_term_ids(payload)) <= allowed
    assert _walk_evidence_ids(payload) == allowed


# --- provenance of a record ---------------------------------------------------


def test_the_knowledge_hash_covers_the_terms_file(tmp_path, monkeypatch):
    """A term edit must show in a baseline's knowledgeHash."""
    from evals import run_eval

    before = run_eval._knowledge_hash()
    copy = tmp_path / "knowledge"
    shutil.copytree(config.KNOWLEDGE_DIR, copy)
    terms = copy / "wes_terms.json"
    terms.write_text(terms.read_text(encoding="utf-8").replace("짧은", "짧은 "), encoding="utf-8")
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", copy)
    assert run_eval._knowledge_hash() != before
