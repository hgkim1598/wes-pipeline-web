"""An answer that names the sample, a path or an address is not served (P4).

The input is redacted (test_payload_redaction.py), but the answer is model
output: it can still carry a value the model met somewhere else -- the CLI's
own context (its working directory is in the system prompt), a tool result, or
an invention that happens to be real. The gate rejects the WHOLE answer, like
gates 3 to 7, rather than substituting placeholders into it: a sentence with
"<path>" spliced in can read as a different claim, and the reader would not
know a substitution happened.

What it looks for is deliberately narrow. The shared residual-path detector
(privacy._RESIDUAL) is built for pipeline text and flags ordinary explanatory
prose such as "PASS/WARN/FAIL" or "R1/R2"; discarding an answer for that would
be a false positive the user cannot act on. So the gate matches only

  * this job's own identifiers (sample, run and job id),
  * an absolute path: a drive letter, a UNC share, "~/" or a rooted POSIX path
    of at least two segments,
  * an e-mail address.

No process is started; the provider is an injected stub.
"""

from __future__ import annotations

import logging

import pytest

from ..services.agent.privacy import Redactor
from ..services.explanation import deterministic, run_context
from ..services.explanation.llm import contract
from ..services.explanation.llm import synthesis as llm_synthesis
from ..services.explanation.llm import provider

SAMPLE = "PATIENT_Q7_canary"
REDACTOR = Redactor(literals=((SAMPLE, "<sample>"),))


@pytest.fixture
def explanation(client, make_job, run):
    job = make_job()
    run(job).as_completed_full()
    return deterministic.build_run_explanation(run_context.build_run_diagnostic_context(job))


def _answer(allowed: set[str], text: str, where: str = "importantFindings") -> dict:
    ref = sorted(allowed)[0]
    base = {
        "summary": "이 실행은 끝났고 확인할 사항이 있습니다.",
        "importantFindings": [{"statement": "경고가 기록되었습니다.", "evidenceRefs": [ref]}],
        "limitations": [{"statement": "필터가 적용되지 않았습니다.", "evidenceRefs": [ref]}],
        "nextChecks": [{"statement": "산출물을 확인할 수 있습니다.", "evidenceRefs": [ref]}],
        "uncertainties": [{"statement": "충분한지는 알 수 없습니다.", "evidenceRefs": [ref]}],
    }
    if where == "summary":
        base["summary"] = text
    else:
        base[where] = [{"statement": text, "evidenceRefs": [ref]}]
    return base


def _run(explanation, text, *, where="importantFindings", redactor=REDACTOR, repair=False):
    _payload, allowed = contract.build_payload(explanation, redactor=redactor)
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return provider.ProviderResult(payload=_answer(allowed, text, where), models=["m"])

    result = llm_synthesis.build_run_synthesis(
        explanation, run_provider=fake, redactor=redactor, repair=repair
    )
    return result, calls


@pytest.mark.parametrize(
    "text",
    [
        f"샘플 {SAMPLE}의 정렬 단계가 실패했습니다.",
        f"샘플 {SAMPLE.lower()}의 정렬 단계가 실패했습니다.",
        "C:\\Users\\kim\\runs\\a.bam 파일을 열 수 없었습니다.",
        "C:/Users/kim/runs 폴더를 확인하세요.",
        "\\\\labserver\\share\\run1 경로를 확인하세요.",
        "/home/kim/wes/runs/a.bam 파일이 없습니다.",
        "로그(/var/log/wes)를 확인하세요.",
        "~/wes/runs 폴더를 확인하세요.",
        "문의는 kim.lab@example.org 로 하세요.",
    ],
)
def test_a_sensitive_value_rejects_the_whole_answer(explanation, text):
    result, _ = _run(explanation, text)
    assert result.available is False
    assert result.errorCategory == "sensitiveOutput"
    assert result.synthesis is None
    assert result.errorMessage and "kim" not in result.errorMessage


def test_the_summary_is_checked_too(explanation):
    result, _ = _run(explanation, "/srv/wes/runs/x 결과입니다.", where="summary")
    assert result.errorCategory == "sensitiveOutput"


@pytest.mark.parametrize(
    "text",
    [
        "검사 결과는 PASS/WARN/FAIL 중 WARN입니다.",
        "R1/R2 리드 수가 다릅니다.",
        "BAM/CRAM 파일과 TP/FP/FN 지표는 다릅니다.",
        "입력/출력/로그를 차례로 확인하세요.",
        "<path> 파일을 열 수 없었다는 기록이 있습니다.",
        "<sample> 샘플의 정렬 단계 기록입니다.",
        "3/4 단계까지 진행되었습니다.",
        "자세한 내용은 https://samtools.github.io/hts-specs/SAMv1.pdf 에 있습니다.",
        "mosdepth.summary.txt 산출물을 확인하세요.",
    ],
)
def test_ordinary_explanatory_text_is_not_a_false_positive(explanation, text):
    result, _ = _run(explanation, text)
    assert result.errorCategory != "sensitiveOutput", text


def test_without_the_jobs_literals_paths_are_still_caught(explanation):
    result, _ = _run(explanation, "/home/kim/x/y 확인", redactor=None)
    assert result.errorCategory == "sensitiveOutput"


def test_a_sensitive_answer_is_never_sent_back_for_a_rewrite(explanation):
    """The rewrite prompt quotes the previous answer to the model. An answer
    holding the sample name or a path must not travel out a second time."""
    result, calls = _run(explanation, f"{SAMPLE} 실패", repair=True)
    assert result.errorCategory == "sensitiveOutput"
    assert len(calls) == 1


def test_the_value_is_not_logged_or_traced(explanation, caplog):
    traces = []
    _payload, allowed = contract.build_payload(explanation, redactor=REDACTOR)

    def fake(**_kwargs):
        return provider.ProviderResult(
            payload=_answer(allowed, f"/home/kim/{SAMPLE}/a.bam 없음"), models=["m"]
        )

    with caplog.at_level(logging.DEBUG):
        llm_synthesis.build_run_synthesis(
            explanation, run_provider=fake, redactor=REDACTOR, on_trace=traces.append
        )
    assert SAMPLE not in caplog.text and "/home/kim" not in caplog.text
    assert traces and SAMPLE not in repr(traces[0]) and "/home/kim" not in repr(traces[0])
    assert traces[0].errorCategory == "sensitiveOutput"
