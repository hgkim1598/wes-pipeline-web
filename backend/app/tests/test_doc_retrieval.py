"""Official-document excerpts (local RAG, log 18). No model, no network.

What these pin:
  * the store agrees with the rest of the knowledge (sources, cause kinds);
  * titles and links come from wes_sources.json, so what the agent is told it
    read and what the UI links to are the same document;
  * retrieval never leaves the classified cause kind, and an unknown kind gets
    nothing -- an excerpt cannot name a cause;
  * evidence text cannot become FTS syntax;
  * with the switch off the tool result is byte-identical to before;
  * only returned, existing doc ids become citable.
"""

from __future__ import annotations

import json
import re

import pytest

from app import config
from app.schemas import ResourceBundleCause, ResourceBundleDiagnosis
from app.services import resource_bundle_causes as rules
from app.services.agent import doc_retrieval
from app.services.agent.privacy import Redactor
from app.services.agent.step_evidence import DOC_NOTE, cause_guidance
from app.services.explanation import knowledge
from app.services.explanation.llm import tools
from .doc_corpus_fixture import SYNTHETIC_CORPUS, synthetic_passages

pytestmark = pytest.mark.usefixtures("synthetic_passages")
PASSAGES = [
    doc_retrieval.DocPassage.model_validate(p)
    for p in json.loads(SYNTHETIC_CORPUS.read_text(encoding="utf-8"))["passages"]
]
KINDS_WITH_DOCS = sorted({k for p in PASSAGES for k in p.causeKinds})


def _diagnosis(*causes: tuple[str, str, str]) -> ResourceBundleDiagnosis:
    return ResourceBundleDiagnosis(
        state="parsed",
        source="report",
        causes=[
            ResourceBundleCause(kind=k, resourceRole=r, tool=None, evidenceText=t)
            for k, r, t in causes
        ],
        truncated=False,
        withheldTextCount=0,
    )


# --- the store ------------------------------------------------------------------


def test_every_passage_names_a_known_source_and_known_kinds():
    kinds = {row.kind for row in knowledge.all_cause_kinds()}
    for p in PASSAGES:
        assert knowledge.source(p.sourceId) is not None, p.id
        assert set(p.causeKinds) <= kinds, p.id


def test_title_and_link_are_the_sources_own():
    """One place decides a document's name and address: wes_sources.json."""
    for p in PASSAGES:
        src = knowledge.source(p.sourceId)
        assert doc_retrieval.source_title(p) == src.title
        assert doc_retrieval.source_url(p) == src.locator
        assert src.locator.startswith("https://"), p.id
    raw = json.loads(config.DOC_PASSAGE_KNOWLEDGE.read_text(encoding="utf-8"))
    for row in raw["passages"]:
        assert not {"url", "title", "locator"} & set(row), row["id"]


def test_every_passage_records_where_and_when_it_was_checked():
    for p in PASSAGES:
        assert p.toolVersion and p.license and p.checkedOn, p.id


def test_the_store_covers_every_kind_that_has_remedies():
    """The remedies' kinds are the ones with primary sources (log 17.4); each
    now has at least one verified excerpt. Kinds without remedies may have
    none -- no source is attached to a kind for the sake of coverage."""
    with_remedies = {row.kind for row in knowledge.all_cause_kinds() if row.remedies}
    assert with_remedies <= set(KINDS_WITH_DOCS)


def test_no_excerpt_text_would_be_changed_by_the_model_input_check():
    redactor = Redactor(literals=(("SYNTHQX7", "<sample>"),))
    texts = [
        s
        for p in PASSAGES
        for s in (p.heading, p.quote, p.explains, p.limits, doc_retrieval.source_title(p))
    ] + [DOC_NOTE]
    assert [t for t in texts if redactor.release(t) != t] == []
    assert [t for t in texts if "://" in t or "/" in t or "\\" in t] == []


# --- retrieval ------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS_WITH_DOCS)
def test_retrieval_stays_inside_the_classified_kind(kind):
    # Hostile evidence: words that belong to OTHER kinds' excerpts.
    text = "checksum bed mandatory dictionary bwtsw tabix bgzip overlapping contigs htslib"
    got = doc_retrieval.retrieve(kind, text)
    assert got
    assert all(kind in p.causeKinds for p in got)
    assert len(got) <= doc_retrieval.MAX_PASSAGES_PER_CAUSE


def test_an_unknown_or_unfiled_kind_gets_nothing():
    assert doc_retrieval.retrieve(rules.UNKNOWN, "tabix index missing") == []
    unfiled = {row.kind for row in knowledge.all_cause_kinds()} - set(KINDS_WITH_DOCS)
    for kind in unfiled:
        assert doc_retrieval.retrieve(kind, "tabix index missing") == [], kind


def test_every_rule_template_retrieves_only_its_own_kind():
    """The pipeline's own sentences, classified by the rule table, then
    retrieved: the excerpts are always about the cause the RULE assigned."""
    sentences = [
        "BWA index at '/x/ref.fa' is incomplete: missing or empty .sa",
        "BWA index not found: /x/ref.fa",
        "reference .fai and .dict disagree on contig order or lengths",
        "contig_style='ensembl' declares no 'chr' prefix but the reference uses 'chr'",
        "known_sites entry index missing (.tbi or .csi): /x/k.vcf.gz",
        "dbsnp_vcf declares contig lengths that differ from the reference: /x: ['chr1']",
        "dbsnp_vcf contigs absent from the reference: /x: ['chrUn']",
        "target_bed SHA-256 mismatch: metadata=aa actual=bb",
        "bcftools unavailable for /x/k.vcf.gz: [Errno 2] No such file or directory",
        "target_bed line 3: fewer than 3 columns",
    ]
    for sentence in sentences:
        kind = rules.classify(sentence).kind
        assert kind != rules.UNKNOWN, sentence
        got = doc_retrieval.retrieve(kind, sentence)
        # Every kind here has excerpts, so an empty result would be a failure,
        # not a vacuous pass (Codex round 1).
        assert kind in KINDS_WITH_DOCS and got, sentence
        for p in got:
            assert kind in p.causeKinds, (sentence, p.id)


@pytest.mark.parametrize(
    "text",
    ['NEAR(index csi) OR "x', "col:quote * ^", "AND OR NOT", '""""', "-t --tbi", ""],
)
def test_evidence_text_never_becomes_fts_syntax(text):
    query = doc_retrieval.match_query(text)
    if query is not None:
        assert all(re.fullmatch(r'"[a-z0-9]+"', part) for part in query.split(" OR "))
    doc_retrieval.retrieve("vcf_index_missing", text)  # must not raise
    doc_retrieval.search_all(text)


def test_ranking_follows_the_message_but_never_changes_the_set():
    a = doc_retrieval.retrieve("bwa_index_incomplete", "missing or empty .sa")
    b = doc_retrieval.retrieve("bwa_index_incomplete", "completely unrelated words")
    assert {p.id for p in a} == {p.id for p in b}


# --- the tool result ------------------------------------------------------------

_PAIR = _diagnosis(
    ("bwa_index_incomplete", "bwa_index", "BWA index at '<path>' is incomplete: missing or empty .sa"),
    ("reference_index_mismatch", "reference_fasta", "reference .fai and .dict disagree on contig order or lengths"),
    ("unknown", "unknown", "reference_fasta: unexpected bytes after sequence header"),
)


def test_switched_off_the_guidance_carries_no_doc_keys_at_all():
    """Omission only; equality with the switched-on result minus the excerpts
    is pinned in evals/test_doc_rag_variant.py."""
    for entry in cause_guidance(_PAIR, with_docs=False):
        dumped = entry.model_dump()
        assert "officialDocs" not in dumped and "docNote" not in dumped
        assert "officialDocs" not in entry.model_dump_json()


def test_the_default_follows_config(monkeypatch):
    monkeypatch.setattr(config, "DOC_RAG", False)
    assert all(e.officialDocs is None for e in cause_guidance(_PAIR))
    monkeypatch.setattr(config, "DOC_RAG", True)
    assert all(e.officialDocs for e in cause_guidance(_PAIR))


def test_switched_on_each_classified_cause_carries_its_own_excerpts_and_the_note():
    entries = {e.kind: e for e in cause_guidance(_PAIR, with_docs=True)}
    assert set(entries) == {"bwa_index_incomplete", "reference_index_mismatch"}  # no unknown
    for kind, entry in entries.items():
        assert entry.docNote == DOC_NOTE
        for doc in entry.officialDocs:
            p = doc_retrieval.by_evidence_id(doc.evidenceId)
            assert p is not None and kind in p.causeKinds
            assert doc.source == doc_retrieval.source_title(p)
            assert doc.quote == p.quote
    ids = {d.evidenceId for d in entries["reference_index_mismatch"].officialDocs}
    assert "doc:synthetic-picard-dict-no-overwrite" in ids


def test_the_note_separates_documents_from_this_runs_records():
    assert "do not show what happened in this run" in DOC_NOTE
    assert "never present a command" in DOC_NOTE


# --- citability -----------------------------------------------------------------


def _tool_item(entries) -> dict:
    return {"evidenceId": "step:00_input_validation", "causeGuidance": [e.model_dump() for e in entries]}


def test_returned_doc_ids_become_citable_and_nothing_else():
    item = _tool_item(cause_guidance(_PAIR, with_docs=True))
    item["causeGuidance"][0]["officialDocs"].append({"evidenceId": "doc:not-a-passage"})
    item["causeGuidance"][0]["officialDocs"].append({"evidenceId": "src:bwa-manual"})
    _facts, refs = tools.credit({}, {"fail:resource_bundle"}, [item])
    docs = {r for r in refs if r.startswith("doc:")}
    returned = {d["evidenceId"] for e in item["causeGuidance"] for d in e["officialDocs"]}
    assert docs == {r for r in returned if doc_retrieval.by_evidence_id(r)}
    assert "doc:not-a-passage" not in refs and "src:bwa-manual" not in refs


def test_with_the_switch_off_no_doc_id_is_citable():
    item = _tool_item(cause_guidance(_PAIR, with_docs=False))
    _facts, refs = tools.credit({}, set(), [item])
    assert not {r for r in refs if r.startswith("doc:")}
