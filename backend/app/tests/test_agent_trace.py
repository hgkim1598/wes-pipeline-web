"""The execution record one synthesis leaves behind.

Two things are under test and they pull in opposite directions:

  completeness  every attempt leaves a row, including the ones that failed --
                a run that died at a guardrail after opening a step is exactly
                the run someone will want to look at later
  restraint     the row says what happened and nothing about how the model
                thought. No prompt, no reasoning, no tool result, no sentence
                it wrote, no sample name, no path

No model is called. The provider is faked, and when a test needs the agent to
have used the tool, the fake writes into the same sink the MCP server writes
into -- so the trace is built from a real recorded tool result rather than from
a hand-made observation.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import db
from app.services.explanation import deterministic, run_context
from app.services.explanation.llm import provider, trace
from app.services.explanation.llm import synthesis as llm_synthesis

from .test_tool_using_synthesis import (  # the fixtures this file also needs
    FULL_PLAN,
    JOB_ID,
    _answer,
    provider_that,
)


@pytest.fixture
def explanation(client, make_job, run):
    job = make_job(JOB_ID, run_mode="full", planned=FULL_PLAN, sample_id="DEMO01")
    run(job).as_completed_full()
    context = run_context.build_run_diagnostic_context(job)
    return deterministic.build_run_explanation(context)


def synthesise(explanation, fake):
    """One request, recorded the way the route records it."""
    return llm_synthesis.build_run_synthesis(
        explanation, run_provider=fake, on_trace=trace.recorder(JOB_ID)
    )


def only_trace() -> dict:
    rows = trace.recent()
    assert len(rows) == 1, rows
    return rows[0]


# --- a trace exists for every outcome ---------------------------------------


def test_a_successful_run_that_used_the_tool(explanation):
    result = synthesise(
        explanation,
        provider_that(
            _answer("경고가 기록되었습니다.", "run:status"), opens=["04_processing"]
        ),
    )

    assert result.available is True
    row = only_trace()
    assert row["jobId"] == JOB_ID
    assert row["openedStepIds"] == ["04_processing"]
    assert row["available"] is True
    assert row["errorCategory"] is None
    assert row["models"] == ["test-model"]
    assert row["createdAt"]


def test_a_successful_run_that_did_not_use_the_tool(explanation):
    """An empty list is a fact -- "it answered without looking" -- not a gap."""
    synthesise(explanation, provider_that(_answer("경고가 기록되었습니다.", "run:status")))

    row = only_trace()
    assert row["openedStepIds"] == []
    assert row["available"] is True


def test_a_guardrail_rejection_still_records_where_the_agent_went(explanation):
    """The most useful failed trace: it searched, then the answer was refused."""
    result = synthesise(
        explanation,
        provider_that(
            _answer("이 단계는 987654초가 걸렸습니다.", "step:04_processing"),
            opens=["04_processing"],
        ),
    )

    assert result.available is False
    row = only_trace()
    assert row["errorCategory"] == "unsupportedNumber"
    assert row["openedStepIds"] == ["04_processing"]
    assert row["available"] is False


def test_an_unknown_evidence_ref_is_recorded_with_its_category(explanation):
    synthesise(
        explanation,
        provider_that(
            _answer("05 단계는 문제가 없었습니다.", "step:05_coverage_qc"),
            opens=["04_processing"],
        ),
    )

    assert only_trace()["errorCategory"] == "unknownEvidenceRef"


def test_a_provider_failure_is_recorded(explanation):
    def failing(**_kwargs):
        raise provider.ProviderError("timeout", "boom")

    synthesise(explanation, failing)

    row = only_trace()
    assert row["available"] is False
    assert row["errorCategory"] == "timeout"
    assert row["openedStepIds"] == []
    assert row["models"] == []
    assert row["durationMs"] is None


def test_a_provider_failure_after_a_tool_call_keeps_the_step(explanation):
    """Timing out AFTER opening a step is a different event from timing out
    immediately, and the record has to be able to tell them apart."""
    opened = provider_that(_answer("x", "run:status"), opens=["04_processing"])

    def failing_after_tool_use(**kwargs):
        opened(**kwargs)  # writes the tool result into this request's sink
        raise provider.ProviderError("timeout", "boom")

    synthesise(explanation, failing_after_tool_use)

    row = only_trace()
    assert row["errorCategory"] == "timeout"
    assert row["openedStepIds"] == ["04_processing"]


def test_provider_metadata_is_carried(explanation):
    def fake(**_kwargs):
        return provider.ProviderResult(
            payload=_answer("경고가 기록되었습니다.", "run:status"),
            models=["claude-sonnet-5"],
            durationMs=22305,
            numTurns=3,
        )

    synthesise(explanation, fake)

    row = only_trace()
    assert row["models"] == ["claude-sonnet-5"]
    assert row["durationMs"] == 22305
    # Collected by the provider since the beginning and never used until now.
    assert row["numTurns"] == 3


# --- what the record must not contain ---------------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        "SRR2962669",  # the sample name in the fixture's own documents
        "markdup",  # a file name
        "/srv",  # an absolute path
        "run_data",  # the prompt's data block
        "경고가 기록되었습니다",  # a sentence the model wrote
        "percent_duplication",  # a metric the tool returned
        "evidenceRefs",  # anything of the synthesis body
    ],
)
def test_the_stored_row_says_nothing_about_content(explanation, forbidden):
    synthesise(
        explanation,
        provider_that(
            _answer("경고가 기록되었습니다.", "run:status"), opens=["04_processing"]
        ),
    )

    stored = db.query_all("SELECT * FROM synthesis_traces")
    blob = json.dumps([dict(row) for row in stored], ensure_ascii=False)
    assert forbidden not in blob


def test_the_row_has_exactly_the_agreed_columns(explanation):
    """Adding a column must be a decision, not a convenience."""
    synthesise(explanation, provider_that(_answer("x", "run:status")))

    row = db.query_all("SELECT * FROM synthesis_traces")[0]
    assert set(row.keys()) == {
        "trace_id",
        "job_id",
        "created_at",
        "models",
        "duration_ms",
        "num_turns",
        "opened_step_ids",
        "available",
        "error_category",
        # The repair record (WES_SYNTHESIS_REPAIR): counts and gate names,
        # still nothing of what was written.
        "repair_enabled",
        "attempts",
        "first_rejection",
    }


# --- observability must not break the feature -------------------------------


def test_a_failed_write_does_not_fail_the_synthesis(explanation, monkeypatch):
    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "execute", broken)

    result = synthesise(explanation, provider_that(_answer("x", "run:status")))

    assert result.available is True
    assert result.synthesis is not None


def test_recording_is_opt_in(explanation):
    """A caller that passes no observer writes nothing."""
    llm_synthesis.build_run_synthesis(
        explanation, run_provider=provider_that(_answer("x", "run:status"))
    )

    assert trace.recent() == []


# --- the route is what wires it in production -------------------------------


def test_the_endpoint_records_one_trace_and_returns_none_of_it(
    client, explanation, monkeypatch
):
    monkeypatch.setattr(
        provider,
        "run_structured",
        provider_that(
            _answer("경고가 기록되었습니다.", "run:status"), opens=["04_processing"]
        ),
    )

    response = client.post(f"/api/jobs/{JOB_ID}/synthesis")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    # The response schema is unchanged: no trace, no tool use, no step ids.
    assert "trace" not in body
    assert "openedStepIds" not in json.dumps(body)

    rows = trace.recent(JOB_ID)
    assert len(rows) == 1
    assert rows[0]["openedStepIds"] == ["04_processing"]


def test_traces_accumulate_per_job(client, explanation, monkeypatch):
    """One job explained twice leaves two records, newest first."""
    monkeypatch.setattr(
        provider, "run_structured", provider_that(_answer("x", "run:status"))
    )

    client.post(f"/api/jobs/{JOB_ID}/synthesis")
    client.post(f"/api/jobs/{JOB_ID}/synthesis")

    assert len(trace.recent(JOB_ID)) == 2
    assert trace.recent("wes-someone-else") == []
