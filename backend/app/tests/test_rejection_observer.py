"""The `on_rejection` observer: a discarded answer reaches the eval, nothing else.

Found in a real evaluation (development log 16.8): gate 6 discarded two answers
in a row and the record kept only the category, so the sentence that tripped it
could not be read. Patching the gate without that sentence would have been a
guess. The observer hands the discarded answer and the findings to the caller
that asked for them -- the eval harness -- and changes nothing a user gets.
"""

from __future__ import annotations

from app.services.explanation.llm import synthesis as llm_synthesis
from app.services.explanation.llm import trace

from .test_synthesis_repair import (  # noqa: F401 -- fixtures
    _answer,
    _valid,
    explanation,
    scripted,
)

_INVENTED = "이 실행은 987654초가 걸렸습니다."


def _run(explanation, fake, *, repair):
    rejected: list[dict] = []
    traces: list[trace.SynthesisTrace] = []
    result = llm_synthesis.build_run_synthesis(
        explanation,
        run_provider=fake,
        on_trace=traces.append,
        on_rejection=rejected.append,
        repair=repair,
    )
    return result, rejected, traces


def test_a_discarded_answer_and_its_findings_reach_the_observer(explanation):
    fake = scripted(_answer(_INVENTED, "run:status"))

    result, rejected, _ = _run(explanation, fake, repair=False)

    assert result.available is False
    assert len(rejected) == 1
    seen = rejected[0]
    assert (seen["attempt"], seen["category"]) == (1, "unsupportedNumber")
    assert seen["answer"]["importantFindings"][0]["statement"] == _INVENTED
    # The locations point into the answer that was handed over.
    locations = [loc for f in seen["findings"] for loc in f["locations"]]
    assert locations and all(isinstance(loc, str) for loc in locations)


def test_a_served_answer_fires_nothing(explanation):
    fake = scripted(_valid())

    result, rejected, _ = _run(explanation, fake, repair=False)

    assert result.available is True
    assert rejected == []


def test_with_repair_only_the_finally_discarded_answer_is_reported(explanation):
    first = _answer(_INVENTED, "run:status")
    second = _answer("이 실행은 123456초가 걸렸습니다.", "run:status")
    fake = scripted(first, second)

    _, rejected, _ = _run(explanation, fake, repair=True)

    assert [r["attempt"] for r in rejected] == [2]


def test_a_rewrite_that_passes_reports_no_rejection(explanation):
    fake = scripted(_answer(_INVENTED, "run:status"), _valid())

    result, rejected, _ = _run(explanation, fake, repair=True)

    assert result.available is True
    assert rejected == []


def test_a_shape_error_reports_no_answer(explanation):
    fake = scripted({"summary": 42})

    _, rejected, _ = _run(explanation, fake, repair=False)

    assert rejected[0]["category"] == "invalidSynthesis"
    assert rejected[0]["answer"] is None


def test_the_observer_changes_neither_the_result_nor_the_trace(explanation):
    bad = _answer(_INVENTED, "run:status")
    watched, _, watched_traces = _run(explanation, scripted(bad), repair=False)
    plain_traces: list[trace.SynthesisTrace] = []
    plain = llm_synthesis.build_run_synthesis(
        explanation, run_provider=scripted(bad), on_trace=plain_traces.append, repair=False
    )

    assert watched.model_dump() == plain.model_dump()
    assert watched_traces == plain_traces
    # The user-facing result carries no part of the discarded answer.
    assert _INVENTED not in watched.model_dump_json()


# --- Codex review of this unit (2026-11-16): M (deep copy: not behaviourally tested) ------------------------------


def test_a_failing_observer_changes_neither_the_result_nor_the_trace(explanation):
    bad = _answer(_INVENTED, "run:status")

    def broken(_rejected):
        raise RuntimeError(_INVENTED)

    traces: list[trace.SynthesisTrace] = []
    result = llm_synthesis.build_run_synthesis(
        explanation, run_provider=scripted(bad), on_trace=traces.append,
        on_rejection=broken, repair=False,
    )
    plain_traces: list[trace.SynthesisTrace] = []
    plain = llm_synthesis.build_run_synthesis(
        explanation, run_provider=scripted(bad), on_trace=plain_traces.append, repair=False
    )
    assert result.model_dump() == plain.model_dump()
    assert traces == plain_traces
