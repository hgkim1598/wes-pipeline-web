"""The recorded command's section opening is a structural manual hit (log 31).

Synthetic manual only (invented wording, the shape of a manual): no run, no
process, no network. The lab measurement that motivated the rule is in the
development log; these tests pin the rule itself, not the measurement.
"""

from __future__ import annotations

import pytest

from ..services.agent.privacy import Redactor
from ..services.doc_search import agent_input, engine, manual_corpus
from ..services.doc_search.models import ObservedCommand, SearchInput
from .test_doc_search import _chunk, write_manual

CONCAT = "COMMANDS AND OPTIONS > bcftools concat [OPTIONS] FILE1 FILE2"
ROWS = [
    _chunk("m#intro#00", "DESCRIPTION", "The toolkit reads variant files."),
    # The opening paragraph shares no word with the error sentence below.
    _chunk("m#concat#00", CONCAT, "Joins files; every input must list identical columns in identical order."),
    _chunk("m#concat#01", CONCAT, "-a, --allow-overlaps permit overlapping inputs\n--threads sample names option"),
    _chunk("m#concat#02", CONCAT, "--names sample names different output names"),
    _chunk("m#concat#03", CONCAT, "--rename sample names different names list"),
    _chunk("m#merge#00", "COMMANDS AND OPTIONS > bcftools merge [ OPTIONS ] A B",
           "merge different sample names files"),
]


@pytest.fixture
def corpus(tmp_path):
    manual_corpus.clear_cache()
    yield manual_corpus.load(write_manual(tmp_path, ROWS))
    manual_corpus.clear_cache()


def _item(sub, options=(), sentence=""):
    cmd = ObservedCommand(tool="bcftools", subcommand=sub, options=list(options),
                          display=" ".join(["bcftools", sub, *options]), recordedBy="test")
    terms = engine._query_terms("", type("C", (), {"subcommand": sub})(), "bcftools",
                                engine._terms(sentence, Redactor()))
    return SearchInput(inputId="in-1", origin="stepCheck", stepId="s", kind="test", tool="bcftools",
                       command=cmd, queryTerms=terms)


def test_the_intro_is_the_first_chunk_of_the_section_in_manual_order(corpus):
    assert corpus.section_intro("concat") == "m#concat#00"
    assert corpus.section_intro("merge") == "m#merge#00"
    assert corpus.section_intro("sort") is None  # no such section: no hit is invented


def test_an_intro_fts_would_rank_last_reaches_the_agent_candidates(corpus):
    item = _item("concat", sentence="Different sample names in b.vcf.gz.")
    # Precondition: by FTS order alone the opening is past the per-failure cap
    # (it matches only through the section heading words).
    same = [c for c in corpus.search(item.queryTerms, 20) if corpus.chunks[c].section_command == "concat"]
    assert same.index("m#concat#00") >= agent_input.MAX_PER_INPUT
    hits = engine._search_manual(item, corpus)
    first = hits[0]
    assert first.evidence_id == "manual:m#concat#00"
    assert first.matched_by[0] == "sectionIntro" and first.relation == "sameCommandSection"
    candidates = [h.evidence_id for h in hits if h.relation in agent_input.CANDIDATE_RELATIONS]
    assert "manual:m#concat#00" in candidates[: agent_input.MAX_PER_INPUT]


def test_recorded_options_still_come_first(corpus):
    hits = engine._search_manual(_item("concat", options=("-a", "--allow-overlaps")), corpus)
    assert [h.evidence_id for h in hits[:2]] == ["manual:m#concat#01", "manual:m#concat#00"]
    assert hits[0].matched_by[0] == "optionLookup" and hits[1].matched_by[0] == "sectionIntro"


def test_an_intro_found_by_fts_too_is_one_hit_with_both_reasons(corpus):
    hits = engine._search_manual(_item("concat", sentence="identical columns order"), corpus)
    ids = [h.evidence_id for h in hits]
    assert ids.count("manual:m#concat#00") == 1
    assert hits[0].matched_by == ["sectionIntro", "fts5"]


def test_a_command_without_a_section_gets_no_intro_and_fts_still_answers(corpus):
    hits = engine._search_manual(_item("sort", sentence="different sample names"), corpus)
    assert hits  # FTS results from other sections are still returned
    assert all("sectionIntro" not in h.matched_by for h in hits)
    assert all(h.relation != "sameCommandSection" for h in hits)
