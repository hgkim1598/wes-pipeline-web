"""The agent loop: a model that may fetch one step, checked against what it got.

No test here calls a model. What is under test is the part that has to be right
*before* a model is involved:

    the menu        does the payload say which steps exist, and only that
    the credit      does evidence the tool really returned become quotable
    the refusal     does everything else stay exactly as forbidden as before

The fake provider stands in for Claude, and it does what Claude would do: it
writes into the same sink the MCP server writes into -- through the path this
layer put in the server's environment -- and only then answers. That is what
makes these tests about the wiring rather than about a stub.

The evidence it records is produced by the real projection
(`read_step_evidence`), not hand-written, so a change to what the tool returns
shows up here too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config
from app.agent_mcp import launch
from app.services.agent import run_scope
from app.services.agent.step_evidence import read_step_evidence
from app.services.agent.tool_sink import ToolEvidenceSink
from app.services.explanation import deterministic, run_context
from app.services.explanation.llm import contract, provider
from app.services.explanation.llm import synthesis as llm_synthesis
from app.services.explanation.llm import tools

JOB_ID = "wes-20260821-142659-c66d6e"

FULL_PLAN = [
    "00_input_validation",
    "01_raw_qc",
    "02_preprocessing",
    "03_alignment",
    "04_processing",
    "05_coverage_qc",
    "06_variant_calling",
    "99_finalization",
]


@pytest.fixture
def explanation(client, make_job, run):
    """A real deterministic explanation of a finished full run."""
    job = make_job(JOB_ID, run_mode="full", planned=FULL_PLAN, sample_id="DEMO01")
    run(job).as_completed_full()
    context = run_context.build_run_diagnostic_context(job)
    return deterministic.build_run_explanation(context)


def sink_path_of(mcp_config: dict) -> Path:
    """Where this request told the server to record its answers."""
    env = mcp_config["mcpServers"][launch.MCP_SERVER_KEY]["env"]
    return Path(env["WES_AGENT_EVIDENCE_SINK"])


def real_evidence(step_id: str) -> dict:
    """What `get_step_detail` would actually return for this step."""
    scope = run_scope.for_job(JOB_ID)
    return read_step_evidence(scope, step_id).model_dump()


def _statement(text: str, ref: str) -> dict:
    return {"statement": text, "evidenceRefs": [ref]}


def _answer(text: str, ref: str, *, summary: str = "실행을 확인했습니다.") -> dict:
    """A well-formed synthesis whose one finding rests on `ref`."""
    return {
        "summary": summary,
        "importantFindings": [_statement(text, ref)],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }


def provider_that(answer: dict, *, opens: list[str] | None = None):
    """A fake Claude: optionally opens steps through the sink, then answers.

    It also records what it was handed, so the wiring itself can be asserted.
    """
    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        for step_id in opens or []:
            ToolEvidenceSink(path=sink_path_of(kwargs["mcp_config"])).record(
                "get_step_detail", real_evidence(step_id)
            )
        return provider.ProviderResult(payload=answer, models=["test-model"])

    fake.seen = seen
    return fake


# --- the menu: step summary in the initial payload ---------------------------


def test_the_payload_lists_the_planned_steps(explanation):
    payload, allowed = contract.build_payload(explanation)

    assert [row["stepId"] for row in payload["steps"]["planned"]] == FULL_PLAN
    assert payload["steps"]["evidenceId"] == "run:steps"
    assert "run:steps" in allowed


def test_the_step_summary_carries_three_fields_and_no_detail(explanation):
    """A menu, not a report: detail is what the tool is for."""
    payload, _allowed = contract.build_payload(explanation)

    for row in payload["steps"]["planned"]:
        assert set(row) == {"stepId", "status", "elapsedSeconds"}


def test_step_metrics_are_not_in_the_initial_payload(explanation):
    """The values a tool call must be made to see."""
    payload, _allowed = contract.build_payload(explanation)
    blob = json.dumps(payload, ensure_ascii=False)

    assert "percent_duplication" not in blob
    assert "nextStepReady" not in blob
    assert "withheldMetricCount" not in blob


def test_a_run_without_recorded_steps_sends_no_step_section(explanation):
    """Eval fixtures predate the field; their payload must not change shape."""
    stripped = explanation.model_copy(update={"steps": []})

    payload, allowed = contract.build_payload(stripped)

    assert "steps" not in payload
    assert "run:steps" not in allowed


# --- the tool channel this layer offers --------------------------------------


def test_the_provider_is_offered_exactly_one_tool(explanation):
    fake = provider_that(_answer("경고가 기록되었습니다.", "run:status"))

    llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    assert fake.seen["allowed_tools"] == (launch.STEP_DETAIL_TOOL,)
    servers = fake.seen["mcp_config"]["mcpServers"]
    assert list(servers) == [launch.MCP_SERVER_KEY]
    assert servers[launch.MCP_SERVER_KEY]["args"] == ["-m", "app.agent_mcp"]


def test_the_run_is_fixed_in_the_server_environment_not_in_the_prompt(explanation):
    """The model picks a STEP. It can never pick a RUN."""
    fake = provider_that(_answer("경고가 기록되었습니다.", "run:status"))

    llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    env = fake.seen["mcp_config"]["mcpServers"][launch.MCP_SERVER_KEY]["env"]
    assert env["WES_AGENT_JOB_ID"] == JOB_ID
    assert env["WES_AGENT_MAX_STEPS"] == str(run_scope.DEFAULT_MAX_DISTINCT_STEPS)
    assert JOB_ID not in fake.seen["user_prompt"]


def test_the_sink_lives_outside_the_run_directory_and_is_removed(explanation):
    fake = provider_that(
        _answer("경고가 기록되었습니다.", "run:status"), opens=["04_processing"]
    )

    llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    path = sink_path_of(fake.seen["mcp_config"])
    parents = set(path.parents)
    assert config.RUNS_ROOT not in parents
    assert config.ROOT not in parents
    # The request is over: nothing about this model call is left on disk.
    assert not path.exists()


# --- crediting what the tool actually returned -------------------------------


def test_a_number_the_tool_returned_is_accepted(explanation):
    """The whole point: fetched evidence must not read as invention."""
    evidence = real_evidence("06_variant_calling")
    fake = provider_that(
        _answer(
            f"이 단계는 {evidence['elapsedSeconds']}초가 걸렸습니다.",
            evidence["evidenceId"],
        ),
        opens=["06_variant_calling"],
    )

    result = llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    assert result.errorCategory is None
    assert result.available is True


def test_citing_a_step_that_was_never_opened_is_rejected(explanation):
    """A `step:` id is easy to compose from the step list. It is not evidence."""
    fake = provider_that(
        _answer("05 단계는 문제가 없었습니다.", "step:05_coverage_qc"),
        opens=["04_processing"],
    )

    result = llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    assert result.available is False
    assert result.errorCategory == "unknownEvidenceRef"


def test_a_number_in_neither_the_payload_nor_the_tool_is_still_rejected(explanation):
    fake = provider_that(
        _answer("이 단계는 987654초가 걸렸습니다.", "step:04_processing"),
        opens=["04_processing"],
    )

    result = llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    assert result.available is False
    assert result.errorCategory == "unsupportedNumber"


def test_a_property_name_from_the_tool_output_is_rejected(explanation):
    """Gate 5 now covers the tool's vocabulary too, not just the payload's."""
    fake = provider_that(
        _answer("nextStepReady 값이 참입니다.", "step:04_processing"),
        opens=["04_processing"],
    )

    result = llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    assert result.available is False
    assert result.errorCategory == "internalFieldName"


def test_an_answer_without_any_tool_call_still_works(explanation):
    """Not calling the tool is a valid outcome, and the old path is unchanged."""
    fake = provider_that(_answer("경고가 기록되었습니다.", "run:status"))

    result = llm_synthesis.build_run_synthesis(explanation, run_provider=fake)

    assert result.available is True


def test_a_provider_failure_still_leaves_the_deterministic_explanation(explanation):
    def failing(**_kwargs):
        raise provider.ProviderError("timeout", "boom")

    result = llm_synthesis.build_run_synthesis(explanation, run_provider=failing)

    assert result.available is False
    assert result.errorCategory == "timeout"
    assert result.synthesis is None


# --- the crediting rule on its own -------------------------------------------


def test_credit_adds_only_returned_evidence():
    payload = {"run": {"evidenceId": "run:status"}}
    returned = [{"evidenceId": "step:04_processing", "elapsedSeconds": 2531}]

    facts, refs = tools.credit(payload, {"run:status"}, returned)

    assert refs == {"run:status", "step:04_processing"}
    assert facts == [payload, returned[0]]


def test_credit_without_tool_results_changes_nothing():
    payload = {"run": {"evidenceId": "run:status"}}

    facts, refs = tools.credit(payload, {"run:status"}, [])

    assert refs == {"run:status"}
    assert facts == [payload]
