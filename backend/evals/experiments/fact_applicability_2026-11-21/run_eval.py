"""실행 사실·지식 적용 조건 평가 (PROTOCOL.md). 구현 전에 작성했다.

    cd backend
    .venv/Scripts/python.exe evals/experiments/fact_applicability_2026-11-21/run_eval.py before
    .venv/Scripts/python.exe evals/experiments/fact_applicability_2026-11-21/run_eval.py after

같은 스크립트로 현재 코드(before)와 구현 뒤(after)를 잰다. 구현이 없는 코드에서도
돌도록 새 필드(executionLedger, knowledgeDecisions)는 getattr로만 읽는다.

Claude를 부르지 않는다(provider를 예외 함수로 바꾼다). 실제 Run은 기존 eval의
복원 함수가 임시 폴더에 꺼낸 것을 읽는다. 결과 파일에 sample/run 식별자를 쓰지 않는다.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
EVALS = BACKEND / "evals"
sys.path.insert(0, str(BACKEND))

from app import db  # noqa: E402
from app.services import worker  # noqa: E402
from app.services.agent import run_scope  # noqa: E402
from app.services.explanation import deterministic, run_context  # noqa: E402
from app.services.explanation.deterministic import RunExplanation  # noqa: E402
from app.services.explanation.llm import contract, provider  # noqa: E402
from evals import agent_cases, archive_runs, real_runs  # noqa: E402
from evals.agent_cases import FULL_PLAN, AgentCase, RunBuilder  # noqa: E402


def _no_model(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("model call attempted inside the applicability eval")


provider.run_structured = _no_model  # type: ignore[assignment]

KEY = json.loads((HERE / "answer_key.json").read_text(encoding="utf-8"))

# --- 모순 검출기 (PROTOCOL.md에 고정) -----------------------------------------
DETECTORS = {
    "C-FASTQC": re.compile(
        r"FastQC[^.。]*?(생성되|만들어지|만들어졌|그대로 있|still runs|unaffected|remain|영향이 없|영향을 받지)",
        re.I,
    ),
    "C-CALLING": re.compile(
        r"(variant calling proceeds|분석은 그대로 진행되었|변이 검출[^.。]*?(진행되었|영향받지 않았))", re.I
    ),
    "C-CORE": re.compile(r"(core raw VCF and core artifacts are complete|핵심 분석[^.。]*?모두 끝났)", re.I),
}
GUARANTEE = re.compile(r"다음 실행부터[^.。]*?(생성됩니다|채워집니다|적용됩니다)")
OK_RAN = {"ranCompleted", "ranWarning"}


def active_detectors(case: dict[str, Any]) -> list[str]:
    not_run = set(case.get("notExecuted") or [])
    out = []
    if "01_raw_qc" in not_run:
        out.append("C-FASTQC")
    if "06_variant_calling" in not_run:
        out.append("C-CALLING")
    if not_run & {"03_alignment", "04_processing", "06_variant_calling"}:
        out.append("C-CORE")
    return out


def strings(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for value in node.values():
            out.extend(strings(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(strings(value))
    elif isinstance(node, str):
        out.append(node)
    return out


def contradictions(texts: list[str], rules: list[str]) -> list[dict[str, str]]:
    found = []
    for text in texts:
        for rule in rules:
            match = DETECTORS[rule].search(text)
            if match:
                found.append({"rule": rule, "excerpt": text[max(0, match.start() - 20): match.end() + 20]})
    return found


# --- 보류 합성 사례 H1~H7 (PROTOCOL.md 표) -------------------------------------
LOW_MEAN = {
    "code": "LOW_MEAN_COVERAGE",
    "message": "mean target depth 12.3x is below the configured reference value 30x",
    "impact": "Variant sensitivity may be reduced in low-coverage targets; the run continues and variant calling proceeds",
    "can_continue": True,
}
OLD_MULTIQC_IMPACT = "Per-lane FastQC still runs; only the aggregated report is unavailable"


def _done(builder: RunBuilder, steps: list[str]) -> list[dict[str, Any]]:
    rows = []
    for step_id in steps:
        builder.step(step_id, elapsed_seconds=30)
        rows.append({"step_id": step_id, "status": "completed", "exit_code": 0, "elapsed_seconds": 30})
    return rows


def _h1(b: RunBuilder) -> None:
    rows = _done(b, FULL_PLAN[:3])
    b.run_status("cancelled", current_step="03_alignment", steps=rows)


def _h2(b: RunBuilder) -> None:
    rows = _done(b, FULL_PLAN[:4])
    b.run_status("stopped_at_requested_step", current_step=None, steps=rows)


def _h3(b: RunBuilder) -> None:
    rows = _done(b, FULL_PLAN[:5])
    b.step("05_coverage_qc", status="warning", warnings=[LOW_MEAN])
    b.step("06_variant_calling", status="failed",
           failures=[{"code": "haplotypecaller", "message": "HaplotypeCaller exited with code 1"}])
    rows += [{"step_id": "05_coverage_qc", "status": "warning"}, {"step_id": "06_variant_calling", "status": "failed"}]
    b.run_status("failed", current_step="06_variant_calling", steps=rows)


def _h4(b: RunBuilder) -> None:
    rows = _done(b, FULL_PLAN[:5])
    b.step("05_coverage_qc", status="failed", warnings=[LOW_MEAN],
           failures=[{"code": "coverage_outputs", "message": "mosdepth thresholds output is missing"}])
    rows += [{"step_id": "05_coverage_qc", "status": "failed"}]
    b.run_status("failed", current_step="05_coverage_qc", steps=rows)


def _h5(b: RunBuilder) -> None:
    b.as_completed_full()
    _done(b, FULL_PLAN[:5])
    (b.run_dir / "status" / "steps" / "05_coverage_qc.json").unlink()


def _h6(b: RunBuilder) -> None:
    b.file("logs/pipeline.log", "executor failed before main.sh wrote a status document\n")


def _h7(b: RunBuilder) -> None:
    b.step(
        "00_input_validation", status="failed", elapsed_seconds=4,
        warnings=[{"code": "MULTIQC_MISSING", "message": "MultiQC is not installed",
                   "impact": OLD_MULTIQC_IMPACT, "can_continue": True}],
        failures=[{"code": "required_tools", "message": "missing from PATH: fastqc"}],
    )
    b.run_status("check_only", current_step="00_input_validation",
                 steps=[{"step_id": "00_input_validation", "status": "failed", "exit_code": 1}])


HELDOUT = {
    "H1": AgentCase("H1", "취소", "full", tuple(FULL_PLAN), worker.CANCELLED, _h1),
    "H2": AgentCase("H2", "요청 단계에서 멈춤", "full", tuple(FULL_PLAN), worker.DONE, _h2),
    "H3": AgentCase("H3", "06 실패, 05 경고", "full", tuple(FULL_PLAN), worker.DONE, _h3),
    "H4": AgentCase("H4", "05 경고 뒤 05 실패", "full", tuple(FULL_PLAN), worker.DONE, _h4),
    "H5": AgentCase("H5", "완료 Run, 05 문서 없음", "full", tuple(FULL_PLAN), worker.DONE, _h5),
    "H6": AgentCase("H6", "실행기 실패", "full", tuple(FULL_PLAN), worker.EXEC_FAILED, _h6),
    "H7": AgentCase("H7", "check-only 실패", "check_only", ("00_input_validation",), worker.DONE, _h7),
}


def source(case: str):
    """(context manager yielding RunExplanation, run id or None, kind)."""
    if case in HELDOUT:
        return agent_cases.materialise(HELDOUT[case]), agent_cases.RUN_ID, "synthetic-heldout"
    if case in archive_runs.ARCHIVE_RUNS:
        run = archive_runs.ARCHIVE_RUNS[case]
        if not archive_runs.archive_available(run):
            return None, None, "archive-missing"
        return archive_runs.materialise(run), run.run_id, "archive"
    if case in real_runs.REAL_RUNS:
        run = real_runs.REAL_RUNS[case]
        if not real_runs.capture_available(run):
            return None, None, "capture-missing"
        return real_runs.materialise(run), run.run_id, "capture"
    if case in agent_cases.CASES:
        return agent_cases.materialise(agent_cases.CASES[case]), agent_cases.RUN_ID, "synthetic"
    fixture = EVALS / "fixtures" / f"{case}.json"
    if fixture.is_file():
        explanation = RunExplanation.model_validate_json(fixture.read_text(encoding="utf-8"))
        return nullcontext(explanation), None, "fixture"
    return None, None, "no-source"


DOC_MAP = {"completed": "ranCompleted", "warning": "ranWarning", "failed": "ranFailed", "skipped": "skipped"}


def expected_steps(spec: dict[str, Any], planned: list[str], run_dir: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    default = spec.get("*")
    for step_id in planned:
        value = spec.get(step_id, default)
        if value == "fromDocument":
            doc = run_dir / "status" / "steps" / f"{step_id}.json" if run_dir else None
            if doc is None or not doc.is_file():
                value = "unknown"
            else:
                value = DOC_MAP.get(json.loads(doc.read_text(encoding="utf-8")).get("status"), "unknown")
        out[step_id] = value
    return out


def ledger_of(explanation: Any) -> dict[str, Any] | None:
    ledger = getattr(explanation, "executionLedger", None)
    if ledger is None:
        return None
    return ledger.model_dump() if hasattr(ledger, "model_dump") else dict(ledger)


def decisions_of(explanation: Any) -> list[dict[str, Any]]:
    rows = getattr(explanation, "knowledgeDecisions", None) or []
    return [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in rows]


def display_texts(explanation: Any, decisions: list[dict[str, Any]]) -> list[str]:
    """화면 표시 데이터의 대리값: 진단·실패마다 의미와 파이프라인 영향 문구.

    프론트는 meaning을 같은 Knowledge 파일에서 읽고(describeDiagnostic), impact는
    /explanation 값을 그대로 보인다. 보류 판정이 있으면 그 부분을 뺀다.
    """
    from app.services.explanation import knowledge

    withheld = {(d.get("section"), d.get("index"), d.get("part")) for d in decisions if d.get("withheld")}
    out: list[str] = []
    for index, item in enumerate(explanation.diagnostics):
        entry = knowledge.diagnostic(item.code)
        if entry is not None and ("diagnostics", index, "meaning") not in withheld:
            out.append(entry.meaning)
        if item.impact and ("diagnostics", index, "impact") not in withheld:
            out.append(item.impact)
    for index, item in enumerate(explanation.failures):
        entry = knowledge.failure(item.code)
        if entry is not None and ("failures", index, "meaning") not in withheld:
            out.append(entry.meaning)
    return out


def timing(run_id: str | None, explanation: Any) -> float:
    """설명 생성 + payload + 직렬화, 20회 중앙값(ms). context 읽기(IO)는 뺀다."""
    context = run_context.build_run_diagnostic_context(run_id) if run_id else None
    samples = []
    for _ in range(20):
        start = time.perf_counter()
        exp = deterministic.build_run_explanation(context) if context is not None else explanation
        contract.build_payload(exp)
        exp.model_dump()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 3)


def evaluate(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    ctx, run_id, kind = source(name)
    if ctx is None:
        return {"case": name, "evaluable": False, "reason": kind}
    with ctx as explanation:
        run_dir = None
        redactor = None
        if run_id is not None:
            row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (run_id,))
            if row is not None:
                run_dir = Path(row["run_dir"])
                redactor = run_scope.redactor_for_row(row)
        planned = [s.stepId for s in explanation.steps]
        payload, _allowed = contract.build_payload(explanation, redactor=redactor)
        decisions = decisions_of(explanation)
        ledger = ledger_of(explanation)
        ms = timing(run_id, explanation)
        display = display_texts(explanation, decisions)
        # 기대 상태는 임시 Run 디렉터리가 지워지기 전에 읽는다("fromDocument").
        # 사후 변경 1 참고: 처음에는 with 블록 밖에서 읽어 모두 unknown이 됐다.
        expected = (
            expected_steps(spec["steps"], planned, run_dir)
            if spec.get("stepsKnown") is not False else None
        )

    # 지표 1
    if expected is None:
        step_eval = {"expected": "no step list", "stepsKnown": None if ledger is None else ledger.get("stepsKnown"),
                     "correct": 0, "total": 0,
                     "stepsKnownCorrect": ledger is not None and ledger.get("stepsKnown") is False}
    else:
        got = {s["stepId"]: s["execution"] for s in (ledger or {}).get("steps", [])}
        wrong = {k: {"expected": v, "got": got.get(k)} for k, v in expected.items() if got.get(k) != v}
        step_eval = {"correct": len(expected) - len(wrong), "total": len(expected), "wrong": wrong}

    # 지표 4 · 5
    rules = active_detectors(spec)
    payload_hits = contradictions(strings(payload), rules)
    display_hits = contradictions(display, rules)

    # 지표 6 · 9
    allowed = re.compile(spec["withholdAllowed"]) if spec.get("withholdAllowed") else None
    false_withhold, unknown_withhold = [], []
    for d in decisions:
        if not d.get("withheld"):
            continue
        text = d.get("text") or ""
        if d.get("decision") == "unknown" and spec.get("unknownAllowed"):
            unknown_withhold.append({"part": d.get("part"), "target": d.get("target")})
        elif allowed is None or not allowed.search(text):
            false_withhold.append({"part": d.get("part"), "target": d.get("target"), "decision": d.get("decision")})
    for pattern in spec.get("mustRemain") or []:
        for d in decisions:
            if d.get("withheld") and re.search(pattern, d.get("text") or ""):
                false_withhold.append({"part": d.get("part"), "target": d.get("target"), "mustRemain": pattern})
    # 한 문장은 한 번만 센다(사후 변경 4: unknown 보류와 mustRemain에 동시에 걸리면 2로 셌다).
    seen, unique = set(), []
    for row in false_withhold:
        key = (row.get("part"), row.get("target"))
        if key not in seen:
            seen.add(key)
            unique.append(row)
    false_withhold = unique
    unknown_as_applicable = [
        d for d in decisions
        if d.get("decision") == "unknown" and not d.get("withheld")
    ]

    return {
        "case": name,
        "split": "dev" if name in KEY["split"]["dev"] else "heldout",
        "evaluable": True,
        "kind": kind,
        "plannedSteps": len(planned),
        "steps": step_eval,
        "ledgerPresent": ledger is not None,
        "payloadContradictions": payload_hits,
        "displayContradictions": display_hits,
        "guaranteeSentences": sum(1 for t in strings(payload) if GUARANTEE.search(t)),
        "decisions": len(decisions),
        "withheld": sum(1 for d in decisions if d.get("withheld")),
        "unknownDecisions": sum(1 for d in decisions if d.get("decision") == "unknown"),
        "unregisteredPipelineTexts": sum(1 for d in decisions if d.get("kind") == "unregisteredPipelineText"),
        "falseWithhold": false_withhold,
        "unknownWithhold": unknown_withhold,
        "unknownTreatedApplicable": len(unknown_as_applicable),
        "msMedian": ms,
    }


def main(label: str) -> None:
    results = []
    with agent_cases.isolated_environment():
        for name, spec in KEY["cases"].items():
            results.append(evaluate(name, spec))
    ok = [r for r in results if r["evaluable"]]
    summary = {
        "label": label,
        "evaluable": f"{len(ok)}/{len(results)}",
        "notEvaluable": [{"case": r["case"], "reason": r["reason"]} for r in results if not r["evaluable"]],
        "stepStates": {
            split: f"{sum(r['steps'].get('correct', 0) for r in ok if r['split'] == split)}"
                   f"/{sum(r['steps'].get('total', 0) for r in ok if r['split'] == split)}"
            for split in ("dev", "heldout")
        },
        "noStepListCasesRecognised": f"{sum(1 for r in ok if r['steps'].get('stepsKnownCorrect'))}"
                                     f"/{sum(1 for r in ok if 'stepsKnownCorrect' in r['steps'])}",
        "payloadContradictions": sum(len(r["payloadContradictions"]) for r in ok),
        "displayContradictions": sum(len(r["displayContradictions"]) for r in ok),
        "guaranteeSentences": sum(r["guaranteeSentences"] for r in ok),
        "decisions": sum(r["decisions"] for r in ok),
        "withheld": sum(r["withheld"] for r in ok),
        "falseWithhold": sum(len(r["falseWithhold"]) for r in ok),
        "unknownDecisions": sum(r["unknownDecisions"] for r in ok),
        "unknownWithhold": sum(len(r["unknownWithhold"]) for r in ok),
        "unknownTreatedApplicable": sum(r["unknownTreatedApplicable"] for r in ok),
        "unregisteredPipelineTexts": sum(r["unregisteredPipelineTexts"] for r in ok),
        "noStepListCases": sum(1 for r in ok if "stepsKnownCorrect" in r["steps"]),
        "msMedianMax": max((r["msMedian"] for r in ok), default=None),
    }
    out = {"summary": summary, "cases": results}
    (HERE / f"results_{label}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "before")
