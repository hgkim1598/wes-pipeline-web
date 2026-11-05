"""One rewrite after a gate rejection, and nothing more.

WES_SYNTHESIS_REPAIR (config.SYNTHESIS_REPAIR) lets an answer that a runtime
safety gate rejected go back to the same provider once, with what the gate
found. These tests pin the four things that make that safe:

  bounded      at most two provider calls per request, and a second call only
               after a gate rejection -- never after a provider failure
  same gates   the rewrite is judged by the same `_check`, against the same
               facts and allowed ids as the first answer; nothing is credited
               because the rewrite asked for it
  off is off   with the switch off, a rejected answer is discarded exactly as
               before, after one call
  recorded     the trace says whether repair was on, how many calls were made
               and what rejected the first answer -- and still nothing of what
               either answer said

No model is called. Every provider is a fake that answers from a script and
records what it was asked.
"""

from __future__ import annotations

import json

import pytest

from app import config, db
from app.services.explanation import deterministic, run_context
from app.services.explanation.llm import contract, prompt, provider, trace
from app.services.explanation.llm import synthesis as llm_synthesis

from .test_tool_using_synthesis import (
    FULL_PLAN,
    JOB_ID,
    _answer,
    real_evidence,
    sink_path_of,
)
from app.services.agent.tool_sink import ToolEvidenceSink


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def explanation(client, make_job, run):
    """A real deterministic explanation of a finished full run."""
    job = make_job(JOB_ID, run_mode="full", planned=FULL_PLAN, sample_id="DEMO01")
    run(job).as_completed_full()
    context = run_context.build_run_diagnostic_context(job)
    return deterministic.build_run_explanation(context)


def _valid(text: str = "경고가 기록되었습니다.") -> dict:
    """An answer every gate accepts: one supplied id, no number, plain words."""
    return _answer(text, "run:status")


def scripted(*steps, opens_on_first: tuple[str, ...] = ()):
    """A fake provider that answers from a script, one entry per call.

    Each entry is an answer dict, or a ProviderError category string to raise.
    A call beyond the script fails the test: the bound is asserted by the fake
    itself, not only by counting afterwards. `opens_on_first` makes the first
    call open steps through the tool sink, the way the MCP server would.
    """
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        assert len(calls) <= len(steps), "more provider calls than the script allows"
        if len(calls) == 1:
            for step_id in opens_on_first:
                ToolEvidenceSink(path=sink_path_of(kwargs["mcp_config"])).record(
                    "get_step_detail", real_evidence(step_id)
                )
        step = steps[len(calls) - 1]
        if isinstance(step, str):
            raise provider.ProviderError(step, "boom")
        return provider.ProviderResult(
            payload=step,
            models=[f"model-{len(calls)}"],
            durationMs=1000 * len(calls),
            numTurns=2,
        )

    fake.calls = calls
    return fake


def synthesise(explanation, fake, *, repair=True, record=False):
    traces: list[trace.SynthesisTrace] = []

    def observe(item: trace.SynthesisTrace) -> None:
        traces.append(item)
        if record:
            trace.record(JOB_ID, item)

    result = llm_synthesis.build_run_synthesis(
        explanation, run_provider=fake, on_trace=observe, repair=repair
    )
    assert len(traces) == 1, "exactly one trace per request"
    return result, traces[0]


def _findings_of(call: dict) -> list[dict]:
    """The <check_findings> block of a rewrite request, parsed back."""
    text = call["user_prompt"]
    block = text.split("<check_findings>\n", 1)[1].split("\n</check_findings>", 1)[0]
    return json.loads(block)


def _previous_answer_of(call: dict) -> dict:
    text = call["user_prompt"]
    block = text.split("<previous_answer>\n", 1)[1].split("\n</previous_answer>", 1)[0]
    return json.loads(block)


# --- T01. a first answer that passes is served after one call ----------------


def test_t01_a_passing_first_answer_costs_one_call(explanation):
    fake = scripted(_valid())

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert len(fake.calls) == 1
    assert seen.attempts == 1
    assert seen.repairEnabled is True
    assert seen.firstRejection is None
    assert seen.repairAttempted is False


# --- T02. an unknown evidence id, then a correct rewrite ---------------------


def test_t02_an_unknown_ref_is_rewritten_and_the_rewrite_is_served(explanation):
    invented = _answer("05 단계는 문제가 없었습니다.", "src:invented-paper-2024")
    fake = scripted(invented, _valid())

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert result.synthesis is not None
    assert result.synthesis.importantFindings[0].evidenceRefs == ["run:status"]
    assert len(fake.calls) == 2
    assert (seen.attempts, seen.firstRejection, seen.errorCategory) == (
        2,
        "unknownEvidenceRef",
        None,
    )

    # What the rewrite was told: the offending id, and the ids it may use.
    _payload, allowed = contract.build_payload(explanation)
    [finding] = _findings_of(fake.calls[1])
    assert finding["check"] == "unknownEvidenceRef"
    assert finding["values"] == ["src:invented-paper-2024"]
    assert finding["allowedEvidenceIds"] == sorted(allowed)
    assert _previous_answer_of(fake.calls[1]) == invented


# --- T03. an unsupported number, then a correct rewrite ----------------------


def test_t03_an_invented_number_is_rewritten_and_the_rewrite_is_served(explanation):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, _valid())

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert (seen.attempts, seen.firstRejection) == (2, "unsupportedNumber")
    [finding] = _findings_of(fake.calls[1])
    assert finding == {
        "check": "unsupportedNumber",
        "problem": finding["problem"],
        "values": ["987654"],
        "locations": ["importantFindings.0"],
    }


# --- T04. a rewrite that still fails is discarded -----------------------------


def test_t04_a_rewrite_with_the_same_error_is_discarded(explanation):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, invented)

    result, seen = synthesise(explanation, fake)

    assert result.available is False
    assert result.synthesis is None
    assert result.errorCategory == "unsupportedNumber"
    # The curated message a rejection has always carried, nothing new.
    assert result.errorMessage == llm_synthesis._SAFE_MESSAGES["unsupportedNumber"]
    assert (seen.attempts, seen.firstRejection, seen.available) == (
        2,
        "unsupportedNumber",
        False,
    )


def test_t04_the_rewrite_earns_no_credit_from_the_findings(explanation):
    """The rejected number is in the rewrite request (as a finding). It must
    not thereby become a known number: the fact set is the first call's."""
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, _answer("다시 보니 987654초입니다.", "run:status"))

    result, _seen = synthesise(explanation, fake)

    assert "987654" in fake.calls[1]["user_prompt"]
    assert result.available is False
    assert result.errorCategory == "unsupportedNumber"


# --- T05. provider failures are never retried --------------------------------


@pytest.mark.parametrize(
    "category", ["timeout", "notAuthenticated", "usageLimit", "providerFailed"]
)
def test_t05_a_first_call_provider_failure_is_not_retried(explanation, category):
    fake = scripted(category)  # a second call would trip the script's bound

    result, seen = synthesise(explanation, fake)

    assert result.available is False
    assert result.errorCategory == category
    assert len(fake.calls) == 1
    assert (seen.attempts, seen.firstRejection) == (1, None)


def test_t05_a_rewrite_that_fails_at_the_provider_ends_the_request(explanation):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, "timeout")

    result, seen = synthesise(explanation, fake)

    assert result.available is False
    assert result.errorCategory == "timeout"
    assert result.errorMessage == llm_synthesis._SAFE_MESSAGES["timeout"]
    assert len(fake.calls) == 2
    assert (seen.attempts, seen.firstRejection) == (2, "unsupportedNumber")


# --- T06. switched off, nothing changes ---------------------------------------


@pytest.mark.parametrize(
    "bad, category",
    [
        (_answer("05 단계는 문제가 없었습니다.", "src:invented"), "unknownEvidenceRef"),
        (_answer("이 실행은 987654초가 걸렸습니다.", "run:status"), "unsupportedNumber"),
        ({"summary": 42}, "invalidSynthesis"),
    ],
)
def test_t06_off_discards_after_one_call_as_before(explanation, bad, category):
    fake = scripted(bad)

    result, seen = synthesise(explanation, fake, repair=False)

    assert result.available is False
    assert result.errorCategory == category
    assert result.errorMessage == llm_synthesis._SAFE_MESSAGES[category]
    assert len(fake.calls) == 1
    assert (seen.repairEnabled, seen.attempts) == (False, 1)
    # Recorded even with repair off, so the first-answer failure rate stays
    # measurable whichever way the switch is set.
    assert seen.firstRejection == category


def test_t06_the_default_follows_config(explanation, monkeypatch):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")

    monkeypatch.setattr(config, "SYNTHESIS_REPAIR", False)
    off = scripted(invented)
    result, _ = synthesise(explanation, off, repair=None)
    assert (result.available, len(off.calls)) == (False, 1)

    monkeypatch.setattr(config, "SYNTHESIS_REPAIR", True)
    on = scripted(invented, _valid())
    result, _ = synthesise(explanation, on, repair=None)
    assert (result.available, len(on.calls)) == (True, 2)


def test_t06_config_is_off_unless_set():
    assert config.SYNTHESIS_REPAIR is False


@pytest.mark.parametrize(
    "raw, expected",
    [("", False), ("off", False), ("0", False), ("on", True), ("TRUE", True), ("1", True)],
)
def test_t06_the_switch_parses(monkeypatch, raw, expected):
    monkeypatch.setenv("WES_SYNTHESIS_REPAIR", raw)
    assert config._resolve_synthesis_repair() is expected


def test_t06_an_unrecognised_switch_value_stops_the_server(monkeypatch):
    monkeypatch.setenv("WES_SYNTHESIS_REPAIR", "maybe")
    with pytest.raises(config.ConfigError, match="WES_SYNTHESIS_REPAIR"):
        config._resolve_synthesis_repair()


# --- T07. a rewrite that fixes one thing and breaks another ------------------


def test_t07_a_new_error_in_the_rewrite_is_caught_by_the_recheck(explanation):
    first = _answer("05 단계는 문제가 없었습니다.", "src:invented-paper-2024")
    second = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(first, second)

    result, seen = synthesise(explanation, fake)

    assert result.available is False
    assert result.errorCategory == "unsupportedNumber"
    assert (seen.firstRejection, seen.errorCategory, seen.attempts) == (
        "unknownEvidenceRef",
        "unsupportedNumber",
        2,
    )


# --- T08. the trace -----------------------------------------------------------


def test_t08_the_stored_trace_matches_what_happened(explanation):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, _valid())

    synthesise(explanation, fake, record=True)

    [row] = trace.recent(JOB_ID)
    assert row["repairEnabled"] is True
    assert row["attempts"] == 2
    assert row["firstRejection"] == "unsupportedNumber"
    assert row["available"] is True
    assert row["errorCategory"] is None
    # One request's cost: both calls' models, durations and turns.
    assert row["models"] == ["model-1", "model-2"]
    assert row["durationMs"] == 3000
    assert row["numTurns"] == 4


def test_t08_the_trace_keeps_nothing_either_answer_said(explanation):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, _valid("두 번째 답변의 문장입니다."))

    synthesise(explanation, fake, record=True)

    blob = json.dumps(
        [dict(r) for r in db.query_all("SELECT * FROM synthesis_traces")],
        ensure_ascii=False,
    )
    for forbidden in ("987654", "두 번째 답변", "걸렸습니다", "check_findings", "run:status"):
        assert forbidden not in blob


def test_t08_a_row_from_before_the_repair_columns_reads_as_unknown(explanation):
    """An older backend's row: NULL in all three, not False/1/None-as-passed."""
    db.execute(
        """INSERT INTO synthesis_traces
           (trace_id, job_id, created_at, models, duration_ms, num_turns,
            opened_step_ids, available, error_category)
           VALUES ('tr_old', ?, ?, '[]', NULL, NULL, '[]', 0, 'timeout')""",
        (JOB_ID, db.now_iso()),
    )
    [row] = trace.recent(JOB_ID)
    assert (row["repairEnabled"], row["attempts"], row["firstRejection"]) == (
        None,
        None,
        None,
    )


# --- T09. a shape error, then a correct rewrite ------------------------------


def test_t09_a_shape_error_is_rewritten_with_its_locations(explanation):
    malformed = {"summary": 42, "importantFindings": [{"statement": 7}]}
    fake = scripted(malformed, _valid())

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert (seen.attempts, seen.firstRejection) == (2, "invalidSynthesis")
    [finding] = _findings_of(fake.calls[1])
    assert finding["check"] == "invalidSynthesis"
    locations = {error["location"] for error in finding["errors"]}
    assert "summary" in locations
    # A nested error names the item and the field, not just the list.
    assert any(loc.startswith("importantFindings.0.") for loc in locations)
    # Pydantic's echo of the input is left out of what the model is told.
    assert all(set(error) == {"location", "message"} for error in finding["errors"])


def test_t09_the_first_verdict_is_the_one_repair_off_gives(explanation):
    """Same gates, same order: the category that triggers a rewrite is exactly
    the category the same answer is discarded under with repair off."""
    _payload, allowed = contract.build_payload(explanation)
    several = _answer("기록이 99,999,999건입니다.", "src:invented-paper-2024")
    for bad in ({"summary": 42}, several):
        _off, off_trace = synthesise(explanation, scripted(bad), repair=False)
        _on, on_trace = synthesise(explanation, scripted(bad, _valid()), repair=True)
        assert on_trace.firstRejection == off_trace.errorCategory


def test_t09_every_gate_that_found_something_is_reported(explanation):
    """The rewrite hears about every failing content gate, in gate order, not
    only the first -- otherwise it fixes one and fails on the next."""
    several = _answer("기록이 99,999,999건입니다.", "src:invented-paper-2024")
    fake = scripted(several, _valid())

    synthesise(explanation, fake)

    assert [f["check"] for f in _findings_of(fake.calls[1])] == [
        "unknownEvidenceRef",
        "unsupportedNumber",
    ]


# --- T10. an internal property name, then a correct rewrite ------------------


def test_t10_an_exposed_property_name_is_rewritten(explanation):
    exposed = _answer("rawVariantRecords 값을 확인하세요.", "run:status")
    fake = scripted(exposed, _valid())

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert (seen.attempts, seen.firstRejection) == (2, "internalFieldName")
    [finding] = _findings_of(fake.calls[1])
    assert finding["check"] == "internalFieldName"
    assert "rawVariantRecords" in finding["values"]


def test_t10_the_same_name_in_the_rewrite_is_rejected_again(explanation):
    exposed = _answer("rawVariantRecords 값을 확인하세요.", "run:status")
    fake = scripted(exposed, exposed)

    result, _seen = synthesise(explanation, fake)

    assert (result.available, result.errorCategory) == (False, "internalFieldName")


# --- the rewrite request itself ----------------------------------------------


def test_the_rewrite_is_asked_with_the_same_data_and_no_tool(explanation):
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    fake = scripted(invented, _valid())

    synthesise(explanation, fake)

    first, second = fake.calls
    assert first["mcp_config"] is not None  # the first call is offered the tool
    assert second["mcp_config"] is None
    assert tuple(second["allowed_tools"]) == ()
    for key in ("json_schema", "model", "timeout_seconds"):
        assert second[key] == first[key]

    # The data block is byte-for-byte the first call's.
    def run_data(text: str) -> str:
        return text.split("<run_data>\n", 1)[1].split("\n</run_data>", 1)[0]

    assert run_data(second["user_prompt"]) == run_data(first["user_prompt"])
    assert second["user_prompt"].startswith(prompt.REPAIR_CONSTRAINTS)
    # Rules first, then data, then the material to correct.
    text = second["user_prompt"]
    assert text.index("<run_data>") < text.index("<previous_answer>")
    assert text.index("<previous_answer>") < text.index("<check_findings>")


def test_the_first_call_prompt_is_unchanged_by_the_feature(explanation):
    """With repair on, the first request is exactly what it always was."""
    on = scripted(_valid())
    off = scripted(_valid())
    synthesise(explanation, on, repair=True)
    synthesise(explanation, off, repair=False)

    payload, _ = contract.build_payload(explanation)
    assert on.calls[0]["user_prompt"] == off.calls[0]["user_prompt"]
    assert on.calls[0]["user_prompt"] == prompt.build_user_prompt(payload)
    assert "REVISION" not in on.calls[0]["user_prompt"]


def test_what_the_tool_returned_stays_citable_in_the_rewrite(explanation):
    """The first call opened a step; the rewrite gets it as data, may cite its
    id, and is checked against it -- without being offered the tool again."""
    first = _answer("처리 단계는 987654초가 걸렸습니다.", "step:04_processing")
    second = _answer("처리 단계에서 경고가 기록되었습니다.", "step:04_processing")
    fake = scripted(first, second, opens_on_first=("04_processing",))

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert (seen.openedStepIds, seen.attempts) == (("04_processing",), 2)
    text = fake.calls[1]["user_prompt"]
    assert "<step_details>\n" in text
    details = json.loads(
        text.split("<step_details>\n", 1)[1].split("\n</step_details>", 1)[0]
    )
    assert [d["evidenceId"] for d in details] == ["step:04_processing"]


def test_a_step_nobody_opened_is_still_uncitable_in_the_rewrite(explanation):
    first = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    second = _answer("커버리지 단계는 문제가 없었습니다.", "step:05_coverage_qc")
    fake = scripted(first, second)

    result, _seen = synthesise(explanation, fake)

    # The rules mention the block by name; the block itself is absent.
    assert "<step_details>\n" not in fake.calls[1]["user_prompt"]
    assert (result.available, result.errorCategory) == (False, "unknownEvidenceRef")


# --- the route ----------------------------------------------------------------


def test_the_endpoint_serves_a_rewrite_in_the_unchanged_shape(
    client, explanation, monkeypatch
):
    monkeypatch.setattr(config, "SYNTHESIS_REPAIR", True)
    fake = scripted(_answer("이 실행은 987654초가 걸렸습니다.", "run:status"), _valid())
    monkeypatch.setattr(provider, "run_structured", fake)

    response = client.post(f"/api/jobs/{JOB_ID}/synthesis")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    # The response model is unchanged: the repair lives in the trace only.
    assert set(body) == {"available", "synthesis", "provenance", "errorCategory", "errorMessage"}
    assert set(body["provenance"]) == {
        "provider",
        "models",
        "generatedAt",
        "contextKind",
        "runStatus",
        "durationMs",
    }
    assert "attempts" not in json.dumps(body)
    assert len(fake.calls) == 2
    [row] = trace.recent(JOB_ID)
    assert (row["attempts"], row["firstRejection"]) == (2, "unsupportedNumber")


def test_the_endpoint_keeps_the_safe_message_when_the_rewrite_fails(
    client, explanation, monkeypatch
):
    monkeypatch.setattr(config, "SYNTHESIS_REPAIR", True)
    invented = _answer("이 실행은 987654초가 걸렸습니다.", "run:status")
    monkeypatch.setattr(provider, "run_structured", scripted(invented, invented))

    body = client.post(f"/api/jobs/{JOB_ID}/synthesis").json()

    assert body["available"] is False
    assert body["synthesis"] is None
    assert body["errorCategory"] == "unsupportedNumber"
    assert body["errorMessage"] == llm_synthesis._SAFE_MESSAGES["unsupportedNumber"]
    assert "987654" not in json.dumps(body, ensure_ascii=False)


def test_the_endpoint_with_repair_off_is_one_call(client, explanation, monkeypatch):
    monkeypatch.setattr(config, "SYNTHESIS_REPAIR", False)
    fake = scripted(_answer("이 실행은 987654초가 걸렸습니다.", "run:status"))
    monkeypatch.setattr(provider, "run_structured", fake)

    body = client.post(f"/api/jobs/{JOB_ID}/synthesis").json()

    assert (body["available"], body["errorCategory"]) == (False, "unsupportedNumber")
    assert len(fake.calls) == 1
    [row] = trace.recent(JOB_ID)
    assert (row["repairEnabled"], row["attempts"]) == (False, 1)


# --- gates 6 and 7 in the rewrite, and what the rewrite may change ------------
#
# The fixture run's mean depth is 85.2; 5.8 is in the payload as another
# figure, so "5.8배" passes the number gate and is caught by gate 6.


def _two(first: str, second: str, *, summary: str = "실행을 확인했습니다.") -> dict:
    return {
        "summary": summary,
        "importantFindings": [
            {"statement": first, "evidenceRefs": ["run:coverage"]},
            {"statement": second, "evidenceRefs": ["run:status"]},
        ],
        "limitations": [],
        "nextChecks": [],
        "uncertainties": [],
    }


def test_a_run_fact_mismatch_reaches_the_rewrite_with_its_location(explanation):
    bad = _two("평균 깊이는 5.8배입니다.", "실행이 끝났습니다.")
    fixed = _two("평균 깊이는 85.2배입니다.", "실행이 끝났습니다.")
    fake = scripted(bad, fixed)

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert (seen.attempts, seen.firstRejection) == (2, "runFactMismatch")
    [finding] = _findings_of(fake.calls[1])
    assert finding["check"] == "runFactMismatch"
    assert finding["locations"] == ["importantFindings.0"]
    assert "85.2" in finding["values"][0]


def test_items_the_findings_did_not_name_are_kept_from_the_first_answer(explanation):
    # The real-model case: a rewrite asked to fix one item also reworded the
    # summary and another statement. Neither change reaches the reader.
    bad = _two("평균 깊이는 5.8배입니다.", "실행이 끝났습니다.", summary="원래 요약입니다.")
    reworded = _two("평균 깊이는 85.2배입니다.", "실행이 무사히 끝났습니다.", summary="바뀐 요약입니다.")
    fake = scripted(bad, reworded)

    result, _ = synthesise(explanation, fake)

    assert result.available is True
    assert result.synthesis.summary == "원래 요약입니다."
    assert [s.statement for s in result.synthesis.importantFindings] == [
        "평균 깊이는 85.2배입니다.",
        "실행이 끝났습니다.",
    ]


def test_an_error_the_rewrite_puts_in_an_unnamed_item_never_reaches_the_reader(explanation):
    bad = _two("평균 깊이는 5.8배입니다.", "실행이 끝났습니다.")
    worse = _two("평균 깊이는 85.2배입니다.", "경고 단계는 3개입니다.")
    fake = scripted(bad, worse)

    result, _ = synthesise(explanation, fake)

    assert result.available is True
    assert result.synthesis.importantFindings[1].statement == "실행이 끝났습니다."


def test_a_new_error_in_the_named_item_is_caught_by_the_recheck(explanation):
    bad = _two("평균 깊이는 5.8배입니다.", "실행이 끝났습니다.")
    still_wrong = _two("세 단계에서 경고가 기록됐습니다.", "실행이 끝났습니다.")
    fake = scripted(bad, still_wrong)  # a third call would fail the fake

    result, seen = synthesise(explanation, fake)

    assert result.available is False
    assert result.errorCategory == "runFactMismatch"
    assert seen.attempts == 2


def test_a_named_item_the_rewrite_drops_takes_the_rewrites_group(explanation):
    bad = _two("평균 깊이는 5.8배입니다.", "실행이 끝났습니다.")
    dropped = {**bad, "importantFindings": [bad["importantFindings"][1]]}
    fake = scripted(bad, dropped)

    result, _ = synthesise(explanation, fake)

    assert result.available is True
    assert [s.statement for s in result.synthesis.importantFindings] == ["실행이 끝났습니다."]


def test_a_missing_qualification_is_rewritten_at_the_stating_item(explanation):
    bad = _answer("변이 후보 기록은 48,210개입니다.", "run:variantCalling")
    fixed = {**bad, "importantFindings": [
        {"statement": "변이 후보 기록은 48,210개입니다.",
         "evidenceRefs": ["run:variantCalling", "lim:UNFILTERED_VARIANTS"]}
    ]}
    fake = scripted(bad, fixed)

    result, seen = synthesise(explanation, fake)

    assert result.available is True
    assert seen.firstRejection == "evidenceMismatch"
    [finding] = _findings_of(fake.calls[1])
    assert finding["locations"] == ["importantFindings.0"]


def test_a_shape_error_is_not_spliced(explanation):
    # No item of a malformed answer can be kept, so the rewrite stands alone.
    fixed = _two("평균 깊이는 85.2배입니다.", "실행이 끝났습니다.", summary="새 요약입니다.")
    fake = scripted({"summary": 42}, fixed)

    result, _ = synthesise(explanation, fake)

    assert result.available is True
    assert result.synthesis.summary == "새 요약입니다."


def test_the_rewrite_rules_name_locations():
    assert "`locations`" in prompt.REPAIR_CONSTRAINTS
    assert "runFactMismatch" in prompt.REPAIR_CONSTRAINTS
    assert "evidenceMismatch" in prompt.REPAIR_CONSTRAINTS
