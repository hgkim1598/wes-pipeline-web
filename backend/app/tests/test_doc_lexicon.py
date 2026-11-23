"""Wording lexicon: a kind SUGGESTED for a sentence the rule table left unknown (log 62).

What must hold:
  * a suggestion needs every concept of one rule, and two disagreeing rules
    suggest nothing;
  * the run's cause kind stays `unknown` -- the suggestion lives on the search
    input and on hits with their own relation;
  * a suggested passage is never an Agent input;
  * a sentence the rule table classifies is not touched.
No model, no process.
"""

from __future__ import annotations

import pytest

from .. import db
from ..services import resource_bundle_causes as rbc
from ..services.agent.privacy import Redactor
from ..services.doc_search import agent_input, engine, lexicon
from .doc_corpus_fixture import synthetic_passages  # noqa: F401  (fixture)
from .test_resource_bundle_diagnosis import RUN_ID, SAMPLE, failed_precheck

# --- the lexicon alone ----------------------------------------------------------


@pytest.mark.parametrize("sentence, kind", [
    ("tabix index (.tbi) not found for known_sites VCF <path>", "vcf_index_missing"),
    ("bash: bcftools: command not found", "vcf_tool_unavailable"),
    ("tabix: command not found", "vcf_tool_unavailable"),
    ("bwa index files are missing (.bwt, .sa) for reference <path>", "bwa_index_not_found"),
    ("BWA index incomplete: .pac file missing", "bwa_index_incomplete"),
    ("sequence dictionary (.dict) does not match the FASTA index (.fai)", "reference_index_mismatch"),
    ("checksum mismatch (sha256) for target_bed", "checksum_mismatch"),
    ("BED file has only 2 columns at line 5", "bed_content_invalid"),
])
def test_a_sentence_with_every_concept_of_one_rule_gets_that_kind(sentence, kind):
    found = lexicon.suggest(sentence)
    assert found is not None and found.kind == kind
    assert found.rule_id in lexicon.RULE_IDS


@pytest.mark.parametrize("sentence", [
    "BAM index (.bai) not found for <path>",          # an alignment index, not a VCF index
    "bash: samtools: command not found",              # a tool nothing curated covers
    "sha256sum: targets.bed: OK",                     # a passing checksum
    "BED file sorted and merged: 1200 intervals",      # BED, but no problem
    "picard CreateSequenceDictionary finished",       # dictionary, but success
    "bwa mem finished aligning 2000000 reads",         # bwa, but not its index
    "MultiQC not found; skipping the combined report",  # "not found" alone
    "FASTQ read names in R1 and R2 do not match",      # "do not match" alone
    "something unexpected happened",
    "",
    "   ",
])
def test_a_sentence_missing_a_concept_gets_nothing(sentence):
    assert lexicon.suggest(sentence) is None


def test_two_rules_that_disagree_suggest_nothing():
    # tool missing (L-VCF-TOOL) and a checksum failure (L-CHECKSUM) in one line
    assert lexicon.suggest("tabix: command not found; checksum mismatch (sha256)") is None


def test_ascii_words_next_to_korean_particles_still_match():
    # A Hangul syllable is a word character for `\b`; the lexicon must not depend on it.
    found = lexicon.suggest("참조 유전체 fai랑 dict가 서로 안 맞아요")
    assert found is not None and found.kind == "reference_index_mismatch"


def test_a_word_inside_a_longer_ascii_word_is_not_a_match():
    assert not lexicon.FAI.search("prefai")
    assert not lexicon.BWA.search("xbwa")
    assert lexicon.BWA.search("bwa_idx_load_from_disk")


def test_every_suggested_kind_is_a_kind_the_rule_table_can_assign():
    table_kinds = {rule.kind for rule in rbc._RULES}
    probes = [
        "tabix index (.tbi) not found for VCF", "bash: bcftools: command not found",
        "bwa index missing", "bwa index incomplete", "dict and fai mismatch",
        "checksum mismatch", "BED file has only 2 columns",
    ]
    kinds = {lexicon.suggest(p).kind for p in probes}
    assert len(kinds) == 7
    assert kinds <= table_kinds


# --- through the search ---------------------------------------------------------

HEADER = rbc.HEADER


def _job(make_job, run, *sentences: str):
    items = "\n".join(f"  - {s}" for s in sentences)
    failed_precheck(run, report=f"{HEADER}\n{items}\n")
    make_job(RUN_ID, sample_id=SAMPLE)
    return db.query_one("SELECT * FROM jobs WHERE job_id = ?", (RUN_ID,))


def test_the_input_kind_stays_unknown_and_the_hits_say_they_are_a_guess(
        client, make_job, run, synthetic_passages):
    row = _job(make_job, run, "tabix: command not found")
    record = engine.run_search(row)
    (item,) = [i for i in record.inputs if i.origin == "resourceBundleCause"]
    assert item.kind == "unknown"
    assert item.suggestedKind == "vcf_tool_unavailable"
    assert item.suggestionRule == "L-VCF-TOOL"
    curated = [h for h in record.hits if h.corpus == "curated"]
    assert curated
    assert {h.relation for h in curated} == {"suggestedByWording"}
    assert {tuple(h.matched_by) for h in curated} == {("wordingLexicon",)}
    assert len(curated) <= engine.MAX_SUGGESTED_PASSAGES


def test_an_unclassified_sentence_without_a_suggestion_says_why_nothing_came_back(
        client, make_job, run, synthetic_passages):
    row = _job(make_job, run, "something unexpected happened while reading the bundle")
    record = engine.run_search(row)
    (item,) = [i for i in record.inputs if i.origin == "resourceBundleCause"]
    assert item.kind == "unknown" and item.suggestedKind is None
    assert not [h for h in record.hits if h.corpus == "curated"]
    assert engine.REASON_CURATED_UNCLASSIFIED in [s.reason for s in item.skipped]


def test_a_classified_sentence_is_not_given_a_suggestion(client, make_job, run, synthetic_passages):
    row = _job(make_job, run, "tabix unavailable for <path>")
    record = engine.run_search(row)
    (item,) = [i for i in record.inputs if i.origin == "resourceBundleCause"]
    assert item.kind == "vcf_tool_unavailable"
    assert item.suggestedKind is None and item.suggestionRule is None
    assert {h.relation for h in record.hits if h.corpus == "curated"} == {"filedUnderCauseKind"}


def test_a_suggested_passage_is_never_an_agent_input(client, make_job, run, synthetic_passages):
    row = _job(make_job, run, "tabix: command not found")
    record = engine.run_search(row)
    built = agent_input.build(record, Redactor([]))
    assert built.selected_ids == ()
    assert built.selections
    assert {s.reason for s in built.selections} == {agent_input.REASON_WORDING}
