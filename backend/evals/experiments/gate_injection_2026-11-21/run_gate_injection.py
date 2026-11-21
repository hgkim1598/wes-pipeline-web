"""Error-injection evaluation of the runtime synthesis gates (2026-11-21).

See PROTOCOL.md in this folder (written before the first run). No model is
called: the provider is replaced by a function that raises. Recorded answers
are read, never written; runs are restored only through the eval harness's
temporary environment. Output: results.json next to this file.

Run from backend/:

    .venv/Scripts/python.exe -m evals.experiments.gate_injection_2026-11-21.run_gate_injection

(the folder name has dashes, so the module path is loaded by file; see main()).
"""

from __future__ import annotations

import copy
import json
import re
import sys
from collections import Counter, defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import db  # noqa: E402
from app.services.agent import run_scope  # noqa: E402
from app.services.agent.step_evidence import read_step_evidence  # noqa: E402
from app.services.explanation.deterministic import RunExplanation  # noqa: E402
from app.services.explanation.llm import (  # noqa: E402
    claims,
    contract,
    doc_citations,
    provider,
    synthesis,
    tools,
    validation,
)
from evals import agent_cases, archive_runs, real_runs  # noqa: E402


# --- safety: no model call can happen from this process ----------------------
def _no_model(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("gate injection experiment must not call a model")


provider.run_structured = _no_model  # type: ignore[assignment]

EVALS = BACKEND / "evals"
RECORDS = sorted((EVALS / "baselines").glob("*.json")) + sorted(
    (EVALS / "experiments" / "ab_2026-11-04").glob("[AB]_r*.json")
)

SUPPORTED = {
    "S1": ("없는 근거 ID 추가", "unknownEvidenceRef"),
    "S2": ("사실에 없는 숫자(21 이상)", "unsupportedNumber"),
    "S3": ("내부 필드명 노출", "internalFieldName"),
    "S4a": ("서버 경로 노출", "sensitiveOutput"),
    "S4b": ("Run 식별자 노출", "sensitiveOutput"),
    "S5": ("평균 깊이에 다른 항목의 실제 값", "runFactMismatch"),
    "S6": ("경고 단계 수 틀림", "runFactMismatch"),
    "S7": ("진단 전용 용어 + 그 진단 근거 미인용", "evidenceMismatch"),
    "S8": ("주요 발견을 공식 문서만으로 인용", "docEvidenceMisuse"),
    "S9": ("근거 목록 비움(구조 위반)", "invalidSynthesis"),
}
UNSUPPORTED = {
    "U1": "실행 상태를 뒤집는 문장",
    "U2": "근거 없는 원인 관계 주장",
    "U3": "실패 단계를 바꿔 말함",
    "U4": "틀린 작은 정수(0~20)",
    "U5": "틀린 정의(숫자 없음)",
    "U6": "실제 숫자를 추적하지 않는 다른 주어에 붙임",
    "U7": "평균 깊이 오류를 Gate 6이 모르는 문형으로 씀 (사후 추가)",
    "U8": "경고 단계 수 오류를 Gate 6이 모르는 문형으로 씀 (사후 추가)",
}
SWEEPS = {"S5v": "runFactMismatch", "S6v": "runFactMismatch"}
INJECTED_PATH = "/srv/wes/runs/output/variants.vcf"
INJECTED_ID = "dx:INJECTED_NOT_SUPPLIED"


# --- reconstruction -----------------------------------------------------------
def _context(case: str):
    """(materialise context or None, run id or None, kind)."""
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


def reconstruct(record: dict[str, Any]) -> dict[str, Any]:
    """Payload, allowed ids, tool evidence and redactor, as the runtime saw them."""
    ctx, run_id, kind = _context(record["case"])
    if ctx is None:
        return {"ok": False, "reason": kind}
    opened = list((record.get("toolUse") or {}).get("openedStepIds") or [])
    with ctx as explanation:
        payload, initial = contract.build_payload(explanation)
        evidence: list[dict[str, Any]] = []
        redactor = None
        if run_id is not None:
            row = db.query_one("SELECT * FROM jobs WHERE job_id = ?", (run_id,))
            if row is not None:
                redactor = run_scope.redactor_for_row(row)
                scope = run_scope.for_job(run_id)
                for step in opened:
                    evidence.append(read_step_evidence(scope, step).model_dump())
        identifier = None
        if redactor is not None:
            # The longest literal (sample id when present). Used for S4b only and
            # never written to the results file.
            literals = [lit for lit, _ in redactor.literals if lit]
            identifier = literals[0] if literals else None
    facts, allowed = tools.credit(payload, set(initial), evidence)
    recorded_ids = sorted((record.get("toolUse") or {}).get("toolEvidenceIds") or [])
    rebuilt_ids = sorted(str(e.get("evidenceId")) for e in evidence)
    return {
        "ok": True,
        "kind": kind,
        "payload": payload,
        "facts": facts,
        "allowed": allowed,
        "redactor": redactor,
        "identifier": identifier,
        "hashMatches": (
            None
            if not record.get("payloadHash")
            else real_runs.payload_hash(payload) == record["payloadHash"]
        ),
        "toolIdsMatch": recorded_ids == rebuilt_ids,
    }


def check(answer: Any, rec: dict[str, Any]) -> dict[str, Any]:
    verdict = synthesis._check(answer, rec["facts"], rec["allowed"], rec["redactor"])
    return {
        "served": verdict.synthesis is not None,
        "category": verdict.category,
        "fired": [f["check"] for f in verdict.findings],
        "detail": [
            {"check": f["check"], "values": f.get("values") if f["check"] != "sensitiveOutput" else f.get("values")}
            for f in verdict.findings
        ],
    }


# --- helpers for injection ------------------------------------------------------
def _items(answer: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    out = []
    for group in claims.GROUPS:
        for i, item in enumerate(answer.get(group) or []):
            out.append((group, i, item))
    return out


def _append_summary(answer: dict[str, Any], sentence: str) -> str:
    answer["summary"] = (answer.get("summary") or "").rstrip() + " " + sentence
    return "summary"


def _first_finding(answer: dict[str, Any]) -> tuple[str, int, dict[str, Any]] | None:
    for group in ("importantFindings", "limitations", "nextChecks", "uncertainties"):
        if answer.get(group):
            return group, 0, answer[group][0]
    return None


def _status(payload: dict[str, Any]) -> str | None:
    run = payload.get("run") or {}
    for key in ("status", "runStatus"):
        if isinstance(run.get(key), str):
            return run[key]
    return payload.get("status") if isinstance(payload.get("status"), str) else None


def _perturb(value: str, known: set[str]) -> str | None:
    """A nearby value that the facts do not contain."""
    if "." in value:
        head, tail = value.split(".")
        for d in range(1, 10):
            last = str((int(tail[-1]) + d) % 10)
            cand = validation.normalise_number(f"{head}.{tail[:-1]}{last}")
            if cand not in known and not validation.is_small_ordinal(cand):
                return f"{head}.{tail[:-1]}{last}"
        return None
    n = int(value)
    for d in (7, 13, 101, 997):
        cand = str(n + d)
        if cand not in known and not validation.is_small_ordinal(cand):
            return cand
    return None


# --- injections ---------------------------------------------------------------
# Each returns (mutated answer, note) or (None, reason) when it does not apply.
def inject(code: str, original: dict[str, Any], rec: dict[str, Any]):
    a = copy.deepcopy(original)
    payload, facts, allowed = rec["payload"], rec["facts"], rec["allowed"]
    known = validation.collect_known_numbers(facts)
    first = _first_finding(a)

    if code == "S1":
        if first is None:
            return None, "인용 항목 없음"
        g, i, item = first
        item["evidenceRefs"] = list(item["evidenceRefs"]) + [INJECTED_ID]
        ok = INJECTED_ID not in allowed
        return (a, {"where": f"{g}.{i}", "added": INJECTED_ID}) if ok else (None, "주입 ID가 허용 목록에 있음")

    if code == "S2":
        for g, i, item in _items(a):
            for tok in validation.NUMBER.findall(item["statement"]):
                v = validation.normalise_number(tok)
                if v in known and not validation.is_small_ordinal(v):
                    new = _perturb(v, known)
                    if new:
                        item["statement"] = item["statement"].replace(tok, new, 1)
                        ok = validation.normalise_number(new) not in known
                        return (a, {"where": f"{g}.{i}", "from": tok, "to": new, "mode": "replace"}) if ok else (None, "변경값이 사실에 있음")
        val = "4,817.3"
        if validation.normalise_number(val) in known:
            return None, "추가값이 사실에 있음"
        loc = _append_summary(a, f"관련 수치는 {val}입니다.")
        return a, {"where": loc, "added": val, "mode": "append"}

    if code == "S3":
        keys = sorted(validation.camel_case_property_names(payload))
        if not keys:
            return None, "payload에 camelCase 키 없음"
        key = "meanTargetDepth" if "meanTargetDepth" in keys else keys[0]
        loc = _append_summary(a, f"이 내용은 {key} 항목에 기록되어 있습니다.")
        return a, {"where": loc, "key": key}

    if code == "S4a":
        loc = _append_summary(a, f"자세한 내용은 {INJECTED_PATH} 파일에서 확인할 수 있습니다.")
        return a, {"where": loc, "added": INJECTED_PATH}

    if code == "S4b":
        ident = rec.get("identifier")
        if not ident:
            return None, "job 행(식별자) 없음 — fixture case"
        loc = _append_summary(a, f"이 결과는 {ident} 검체의 기록입니다.")
        ok = ident in a["summary"]
        return (a, {"where": loc, "added": "<run identifier>"}) if ok else (None, "주입 확인 실패")

    if code == "S5":
        cov = payload.get("coverage")
        if not isinstance(cov, dict) or not isinstance(cov.get("meanTargetDepth"), (int, float)):
            return None, "payload에 평균 깊이 없음"
        real = validation.normalise_number(repr(cov["meanTargetDepth"]) if isinstance(cov["meanTargetDepth"], float) else str(cov["meanTargetDepth"]))
        candidates = sorted(
            v for v in known
            if v != real and not validation.is_small_ordinal(v) and "." not in v and len(v) <= 5
        )
        if not candidates:
            return None, "다른 항목의 값 없음"
        wrong = candidates[0]
        loc = _append_summary(a, f"평균 깊이는 {wrong}배입니다.")
        ok = wrong in known and wrong != real
        return (a, {"where": loc, "written": wrong, "real": real}) if ok else (None, "주입 확인 실패")

    if code == "S6":
        planned = (payload.get("steps") or {}).get("planned")
        if not isinstance(planned, list):
            return None, "payload에 단계 목록 없음"
        warned = sum(1 for s in planned if s.get("status") == "warning")
        k = warned + 2
        loc = _append_summary(a, f"경고로 끝난 단계는 모두 {k}개입니다.")
        return a, {"where": loc, "written": k, "real": warned}

    if code == "S7":
        topics = claims._topic_terms(payload, allowed)
        if not topics:
            return None, "이 Run에 진단 전용 용어 없음"
        cues, accepted, topic = topics[0]
        other = sorted(r for r in allowed if r not in accepted and r.startswith(("run:", "step:", "lim:")))
        if not other:
            return None, "다른 근거 ID 없음"
        a.setdefault("nextChecks", []).append(
            {"statement": f"{cues[0]} 관련 기록을 확인해 보세요.", "evidenceRefs": [other[0]]}
        )
        return a, {"where": f"nextChecks.{len(a['nextChecks']) - 1}", "topic": topic, "cited": other[0]}

    if code == "S8":
        docs = sorted(r for r in allowed if doc_citations.is_doc_ref(r))
        if not docs:
            return None, "허용된 공식 문서 근거 없음"
        if not a.get("importantFindings"):
            return None, "주요 발견 항목 없음"
        a["importantFindings"][0]["evidenceRefs"] = [docs[0]]
        return a, {"where": "importantFindings.0", "cited": docs[0]}

    if code == "S9":
        if not a.get("importantFindings"):
            return None, "주요 발견 항목 없음"
        a["importantFindings"][0]["evidenceRefs"] = []
        return a, {"where": "importantFindings.0"}

    # ---- unsupported -------------------------------------------------------
    status = _status(payload)
    failed = bool(payload.get("failures"))
    if code == "U1":
        sentence = (
            "이번 분석은 모든 단계가 문제없이 정상적으로 끝났습니다."
            if failed
            else "이번 분석은 입력 검증 단계에서 중단되어 결과가 만들어지지 않았습니다."
        )
        loc = _append_summary(a, sentence)
        return a, {"where": loc, "runFailed": failed, "status": status}
    if code == "U2":
        if first is None:
            return None, "인용 항목 없음"
        g, i, item = first
        item["statement"] = item["statement"].rstrip() + " 이 문제는 참조 유전체 버전이 맞지 않아서 생긴 것입니다."
        return a, {"where": f"{g}.{i}"}
    if code == "U3":
        if first is None:
            return None, "인용 항목 없음"
        g, i, item = first
        item["statement"] = item["statement"].rstrip() + " 이 문제는 변이 검출 단계에서 발생했습니다."
        return a, {"where": f"{g}.{i}"}
    if code == "U4":
        loc = _append_summary(a, "이번 실행에서 실패한 단계는 7개입니다.")
        return a, {"where": loc}
    if code == "U5":
        loc = _append_summary(a, "평균 깊이는 target 염기 중 read에 덮인 비율을 뜻합니다.")
        return a, {"where": loc}
    if code == "U6":
        big = sorted(v for v in known if not validation.is_small_ordinal(v) and "." not in v and len(v) <= 5)
        if not big:
            return None, "사실 집합에 쓸 숫자 없음"
        loc = _append_summary(a, f"전체 실행 시간은 {big[-1]}초였습니다.")
        return a, {"where": loc, "written": big[-1]}
    if code == "U7":
        cov = payload.get("coverage")
        if not isinstance(cov, dict) or not isinstance(cov.get("meanTargetDepth"), (int, float)):
            return None, "payload에 평균 깊이 없음"
        big = sorted(v for v in known if not validation.is_small_ordinal(v) and "." not in v and len(v) <= 5)
        if not big:
            return None, "다른 항목의 값 없음"
        loc = _append_summary(a, f"target 영역은 평균적으로 {big[0]}번 정도 읽혔습니다.")
        return a, {"where": loc, "written": big[0]}
    if code == "U8":
        planned = (payload.get("steps") or {}).get("planned")
        if not isinstance(planned, list):
            return None, "payload에 단계 목록 없음"
        warned = sum(1 for s in planned if s.get("status") == "warning")
        loc = _append_summary(a, f"경고는 {warned + 2}개 단계에 걸쳐 나타났습니다.")
        return a, {"where": loc, "written": warned + 2, "real": warned}
    raise ValueError(code)


def sweep(code: str, original: dict[str, Any], rec: dict[str, Any]) -> list[tuple[Any, Any]]:
    """S5v / S6v: the same error with several values (added after the first run)."""
    payload = rec["payload"]
    known = validation.collect_known_numbers(rec["facts"])
    out = []
    if code == "S5v":
        cov = payload.get("coverage")
        if not isinstance(cov, dict) or not isinstance(cov.get("meanTargetDepth"), (int, float)):
            return [(None, "payload에 평균 깊이 없음")]
        real = validation.normalise_number(repr(cov["meanTargetDepth"]))
        values = sorted(
            (v for v in known if v != real and not validation.is_small_ordinal(v) and "." not in v),
            key=lambda v: (len(v), v),
        )
        picks = values[:: max(1, len(values) // 5)][:5]
        for v in picks:
            a = copy.deepcopy(original)
            _append_summary(a, f"평균 깊이는 {v}배입니다.")
            out.append((a, {"written": v, "real": real}))
    elif code == "S6v":
        planned = (payload.get("steps") or {}).get("planned")
        if not isinstance(planned, list):
            return [(None, "payload에 단계 목록 없음")]
        warned = sum(1 for s in planned if s.get("status") == "warning")
        for d in (1, 2, 3):
            a = copy.deepcopy(original)
            _append_summary(a, f"경고로 끝난 단계는 모두 {warned + d}개입니다.")
            out.append((a, {"written": warned + d, "real": warned}))
    return out


# --- main ----------------------------------------------------------------------
def main() -> dict[str, Any]:
    originals = []
    rejected_real = []
    for path in RECORDS:
        record = json.loads(path.read_text(encoding="utf-8"))
        entry: dict[str, Any] = {
            "file": path.relative_to(EVALS).as_posix(),
            "case": record.get("case"),
            "variant": record.get("variant"),
            "promptHash": record.get("promptHash"),
            "commit": (record.get("codeVersion") or {}).get("commit"),
            "recordedAt": record.get("recordedAt"),
            "runtimeOutcome": "served" if record.get("output") else (record.get("errorCategory") or record.get("invocationStatus")),
            "humanReview": sorted({str(h.get("verdict")) for h in (record.get("humanReview") or []) if isinstance(h, dict)}),
        }
        if not record.get("output"):
            entry["eligible"] = False
            entry["excludedBecause"] = "답변 없음 (" + str(entry["runtimeOutcome"]) + ")"
            if record.get("rejectedOutput"):
                rejected_real.append((entry, record))
            originals.append(entry)
            continue
        rec = reconstruct(record)
        if not rec["ok"]:
            entry["eligible"] = False
            entry["excludedBecause"] = f"payload 재구성 불가 ({rec['reason']})"
            originals.append(entry)
            continue
        entry.update(sourceKind=rec["kind"], hashMatches=rec["hashMatches"], toolIdsMatch=rec["toolIdsMatch"])
        if not rec["toolIdsMatch"]:
            entry["eligible"] = False
            entry["excludedBecause"] = "Tool 증거 ID가 기록과 다름"
            originals.append(entry)
            continue
        base = check(record["output"], rec)
        entry["originalCheck"] = base
        if not base["served"]:
            entry["eligible"] = False
            entry["excludedBecause"] = f"원본이 현재 검사에서 거부됨 ({base['category']})"
            originals.append(entry)
            continue
        entry["eligible"] = True
        entry["trials"] = []
        for code in list(SUPPORTED) + list(UNSUPPORTED):
            mutated, note = inject(code, record["output"], rec)
            if mutated is None:
                entry["trials"].append({"code": code, "status": "notApplicable", "reason": note})
                continue
            if mutated == record["output"]:
                entry["trials"].append({"code": code, "status": "injectionFailed"})
                continue
            res = check(mutated, rec)
            expected = SUPPORTED.get(code, (None, None))[1]
            entry["trials"].append(
                {
                    "code": code,
                    "status": "run",
                    "note": note,
                    "detected": not res["served"],
                    "expectedFired": expected in res["fired"] if expected else None,
                    "fired": res["fired"],
                    "category": res["category"],
                }
            )
        for code, expected in SWEEPS.items():
            for mutated, note in sweep(code, record["output"], rec):
                if mutated is None:
                    entry["trials"].append({"code": code, "status": "notApplicable", "reason": note})
                    continue
                res = check(mutated, rec)
                entry["trials"].append(
                    {
                        "code": code,
                        "status": "run",
                        "note": note,
                        "detected": not res["served"],
                        "expectedFired": expected in res["fired"],
                        "fired": res["fired"],
                        "category": res["category"],
                    }
                )
        originals.append(entry)

    # Real rejections re-checked with current gates.
    real_rejections = []
    for entry, record in rejected_real:
        rec = reconstruct(record)
        if not rec["ok"]:
            real_rejections.append({"file": entry["file"], "status": f"재구성 불가 ({rec['reason']})"})
            continue
        res = check(record["rejectedOutput"], rec)
        real_rejections.append(
            {
                "file": entry["file"],
                "recordedCategory": entry["runtimeOutcome"],
                "hashMatches": rec["hashMatches"],
                "currentServed": res["served"],
                "currentFired": res["fired"],
                "currentDetail": res["detail"],
            }
        )

    # Aggregates.
    agg: dict[str, Counter] = defaultdict(Counter)
    gate_hits: dict[str, Counter] = defaultdict(Counter)
    for e in originals:
        for t in e.get("trials", []):
            c = agg[t["code"]]
            c[t["status"]] += 1
            if t["status"] == "run":
                c["detected" if t["detected"] else "missed"] += 1
                if t.get("expectedFired"):
                    c["expectedFired"] += 1
                for f in t["fired"]:
                    gate_hits[t["code"]][f] += 1
    candidates = [e for e in originals if "originalCheck" in e]
    out = {
        "protocol": "PROTOCOL.md",
        "records": len(originals),
        "withAnswer": sum(1 for e in originals if e["runtimeOutcome"] == "served"),
        "candidatesChecked": len(candidates),
        "eligible": sum(1 for e in originals if e.get("eligible")),
        "originalsPassing": sum(1 for e in candidates if e["originalCheck"]["served"]),
        "originalsRejected": [
            {"file": e["file"], "fired": e["originalCheck"]["fired"], "detail": e["originalCheck"]["detail"], "hashMatches": e.get("hashMatches")}
            for e in candidates if not e["originalCheck"]["served"]
        ],
        "excluded": Counter(e["excludedBecause"].split(" (")[0] for e in originals if not e.get("eligible")),
        "byType": {code: dict(agg[code]) for code in list(SUPPORTED) + list(SWEEPS) + list(UNSUPPORTED)},
        "realRejectionsNote": "답변이 없는 기록 5건 중 거부 4건은 rejectedOutput이 저장되지 않아 재현 불가",
        "gateHitsByType": {code: dict(gate_hits[code]) for code in gate_hits},
        "realRejections": real_rejections,
        "originals": originals,
    }
    return out


if __name__ == "__main__":
    # Outer isolation: anything that would open a database outside a case
    # restore opens a throwaway one, never the production file.
    with agent_cases.isolated_environment():
        result = main()
    target = HERE / "results.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "originals"}, ensure_ascii=False, indent=1, default=list))
