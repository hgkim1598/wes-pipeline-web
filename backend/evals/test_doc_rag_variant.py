"""v3 vs v3rag differ in exactly one thing: officialDocs in the tool result.

No model. These are the conditions that make the planned comparison fair:
same prompt hash, same initial payload, same tool, and the switch reaching the
MCP server process -- not just the eval process.
"""

from __future__ import annotations

import json

import pytest

from app import config
from app.agent_mcp import launch
from app.services.agent import run_scope, step_evidence
from app.services.explanation.llm import contract

from . import agent_cases, run_eval
from app.tests.doc_corpus_fixture import synthetic_passages

pytestmark = pytest.mark.usefixtures("synthetic_passages")


@pytest.fixture(autouse=True)
def _restore_switch(monkeypatch):
    monkeypatch.setattr(config, "DOC_RAG", config.DOC_RAG)


def test_v3rag_sends_the_same_rules_and_offers_the_same_tool():
    assert run_eval.VARIANTS["v3rag"] is run_eval.VARIANTS["v3"] is True
    assert run_eval._prompt_hash("v3rag") == run_eval._prompt_hash("v3")
    assert run_eval.DOC_RAG_VARIANTS == {"v3rag"}


@pytest.mark.parametrize("variant,expected", [("v1", False), ("v3", False), ("v3rag", True)])
def test_the_variant_sets_the_switch(variant, expected):
    run_eval.apply_variant_settings(variant)
    assert config.DOC_RAG is expected


@pytest.mark.parametrize("on", [False, True])
def test_the_switch_reaches_the_mcp_server_environment(on, tmp_path):
    config.DOC_RAG = on

    class _Sink:
        path = tmp_path / "sink.jsonl"

    cfg = launch.build_mcp_config(job_id="wes-x", sink=_Sink(), max_distinct_steps=2)
    env = cfg["mcpServers"][launch.MCP_SERVER_KEY]["env"]
    assert env["WES_DOC_RAG"] == ("1" if on else "0")


def _view_and_payload(name: str):
    with agent_cases.materialise(agent_cases.CASES[name]) as explanation:
        payload, _allowed = contract.build_payload(explanation)
        view = step_evidence.read_step_evidence(
            run_scope.for_job(agent_cases.RUN_ID), "00_input_validation"
        ).model_dump()
    return view, payload


def test_the_switch_changes_the_tool_result_and_nothing_in_the_initial_payload():
    config.DOC_RAG = False
    off_view, off_payload = _view_and_payload("agent_resource_index_pair")
    config.DOC_RAG = True
    on_view, on_payload = _view_and_payload("agent_resource_index_pair")

    assert off_payload == on_payload
    assert "officialDocs" not in json.dumps(off_view)
    # Remove the excerpts and the two results are identical.
    for entry in on_view["causeGuidance"]:
        assert entry.pop("officialDocs") and entry.pop("docNote")
    assert on_view == off_view


def test_the_unclassified_sentence_gets_no_excerpt_with_the_switch_on():
    config.DOC_RAG = True
    view, _payload = _view_and_payload("agent_resource_unclassified")
    kinds_with_docs = [g["kind"] for g in view["causeGuidance"] if g.get("officialDocs")]
    assert kinds_with_docs == ["vcf_contig_length_mismatch"]


def test_excerpts_carry_no_answer_key_text():
    config.DOC_RAG = True
    for name in ("agent_resource_unclassified", "agent_resource_index_pair", "agent_resource_heldout"):
        view, _payload = _view_and_payload(name)
        text = json.dumps(view, ensure_ascii=False)
        key = run_eval.load_expectations(name)
        assert [s for s in run_eval.answer_key_strings(key) if s in text] == []
