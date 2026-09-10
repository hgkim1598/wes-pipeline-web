"""Run one or more eval cases against the real model, then score them.

    python -m evals.run_eval --case full
    python -m evals.run_eval --case all --record-baseline --yes

The only code in this repository that can spend subscription usage outside a
user's own request. `pytest` never reaches it: pytest.ini sets
`testpaths = app/tests`, and this file is not there.

What it does per case
---------------------

    fixture (RunExplanation)  ->  build_payload  ->  provider  ->  evaluators

`build_payload` runs *here*, not at fixture time. That is deliberate: the
privacy allowlist and the concept selection execute on every eval, so a
regression in either shows up as an eval failure rather than being frozen into
a stored payload.

Cost safety
-----------

Nothing new is invented. The provider's own gates still apply -- an API key in
the environment refuses the call, a non-subscription auth method refuses it,
`--bare` is never used, there is no API fallback and no automatic retry. This
script adds one thing on top: it says out loud how many calls it is about to
make and asks first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config
from app.services.explanation.deterministic import RunExplanation
from app.services.explanation.llm import contract, prompt, synthesis

from . import evaluators

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
EXPECTATIONS = HERE / "expectations"
BASELINES = HERE / "baselines"

CASES = {
    "full": "full_completed_with_warnings",
    "precheck": "precheck_failed",
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _knowledge_hash() -> str:
    """All four canonical knowledge files, so a knowledge edit is visible."""
    parts = []
    for path in sorted(config.KNOWLEDGE_DIR.glob("*.json")):
        parts.append(path.name)
        parts.append(path.read_text(encoding="utf-8"))
    return _hash("".join(parts))


def privacy_check(fixture: dict[str, Any]) -> evaluators.CheckResult:
    """Does the payload derived from this fixture leak the sample canary?

    Free -- no model call -- so both the live path and `--rescore` run it.
    The fixture keeps a fake sample name precisely so this can be observed;
    if it ever appears in the payload, the allowlist regressed.
    """
    payload, _allowed = contract.build_payload(RunExplanation.model_validate(fixture))
    blob = json.dumps(payload, ensure_ascii=False)
    leaked = [n for n in ("EVAL_SAMPLE_CANARY", "EVAL_SAMPLE") if n in blob]
    if leaked:
        return evaluators.CheckResult(
            name="payload-privacy",
            outcome="fail",
            detail=f"fixture canary가 payload에 유입: {leaked}",
        )
    return evaluators.CheckResult(
        name="payload-privacy", outcome="pass", detail="검체 식별자가 payload에 없음"
    )


def load_case(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    expectations = json.loads(
        (EXPECTATIONS / f"{name}.json").read_text(encoding="utf-8")
    )
    return fixture, expectations


def evaluate(name: str) -> dict[str, Any]:
    """One case: build payload, call the model once, score the result."""
    fixture, expectations = load_case(name)
    explanation = RunExplanation.model_validate(fixture)

    payload, allowed = contract.build_payload(explanation)

    result = synthesis.build_run_synthesis(explanation).model_dump()
    report = evaluators.run_expectations(expectations, fixture, result, payload)
    report.results.insert(0, privacy_check(fixture))

    provenance = result.get("provenance") or {}
    return {
        "case": name,
        "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provenance.get("provider"),
        "models": provenance.get("models"),
        "durationMs": provenance.get("durationMs"),
        "configuredModel": config.SYNTHESIS_MODEL,
        "promptHash": _hash(prompt.CONSTRAINTS),
        "knowledgeHash": _knowledge_hash(),
        "schemaHash": _hash(json.dumps(contract.SYNTHESIS_JSON_SCHEMA, sort_keys=True)),
        "allowedRefCount": len(allowed),
        "evaluation": report.to_json(),
        # 사람이 채운다. 자동으로 pass를 넣지 않는다.
        "humanReview": {
            "reviewedBy": None,
            "verdict": None,
            "notes": None,
            "items": [
                {"name": r.name, "question": r.detail, "verdict": None}
                for r in report.results
                if r.kind == "human"
            ],
        },
        "available": result.get("available"),
        "errorCategory": result.get("errorCategory"),
        "output": result.get("synthesis"),
    }


def print_report(record: dict[str, Any]) -> None:
    print(f"\n=== {record['case']} ===")
    print(f"  model      {record.get('models')}")
    print(f"  duration   {record.get('durationMs')} ms")
    print(f"  available  {record.get('available')} {record.get('errorCategory') or ''}")
    for row in record["evaluation"]["results"]:
        mark = {"pass": "PASS", "fail": "FAIL", "needs_review": "REVIEW"}[row["outcome"]]
        print(f"  [{mark:6}] {row['name']:44} {row['detail'][:60]}")
    print(
        f"  deterministic: "
        f"{'PASSED' if record['evaluation']['deterministicPassed'] else 'FAILED'}"
        f" · human items: {len(record['humanReview']['items'])}"
    )


def rescore(names: list[str], *, record: bool) -> int:
    """Re-evaluate stored baselines. No model call."""
    failed = 0
    for name in names:
        matches = sorted(BASELINES.glob(f"*_{name}_*.json"))
        if not matches:
            print(f"{name}: baseline이 없습니다.")
            continue
        path = matches[-1]
        stored = json.loads(path.read_text(encoding="utf-8"))
        fixture, expectations = load_case(name)
        result = {
            "available": stored.get("available"),
            "errorCategory": stored.get("errorCategory"),
            "synthesis": stored.get("output"),
        }
        payload, _ = contract.build_payload(RunExplanation.model_validate(fixture))
        report = evaluators.run_expectations(expectations, fixture, result, payload)
        report.results.insert(0, privacy_check(fixture))
        stored["evaluation"] = report.to_json()
        stored["rescoredAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print_report(stored)
        if record:
            path.write_text(
                json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  baseline 갱신 -> {path.name} (모델 호출 없음)")
        if not report.ok:
            failed += 1
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[*sorted(CASES), "all"], required=True)
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="결과를 evals/baselines/ 에 저장한다",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="저장된 baseline의 출력을 다시 채점한다. 모델을 호출하지 않는다",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="비대화형 실행. 이 플래그 없이는 확인을 요구한다",
    )
    args = parser.parse_args()

    names = list(CASES.values()) if args.case == "all" else [CASES[args.case]]

    if args.rescore:
        # evaluator를 고쳤을 때 쓴다. 모델 출력은 그대로 두고 채점만 다시 한다 --
        # 내 채점 버그 때문에 구독 사용량을 또 쓸 이유가 없다.
        return rescore(names, record=args.record_baseline)

    print("이 명령은 Claude Max 구독 사용량을 소비합니다.")
    print(f"  case {len(names)}개 · case당 1회 호출 · 총 {len(names)}회")
    print(f"  model: {config.SYNTHESIS_MODEL or 'CLI 기본값'}")
    print("  자동 재시도 없음. 실패하면 그대로 보고합니다.")
    if not args.yes:
        answer = input("계속할까요? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("취소했습니다. 호출하지 않았습니다.")
            return 1

    records = []
    for name in names:
        record = evaluate(name)
        print_report(record)
        records.append(record)

        if args.record_baseline:
            BASELINES.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            model = (record.get("configuredModel") or "default").replace("/", "-")
            # promptHash를 파일명에 넣는다. 같은 날 같은 모델로 prompt만 바꿔
            # 다시 돌리면 **이전 baseline을 덮어쓰게 되는데**, 그 파일이 바로
            # 비교 기준이다. 무엇이 이 결과를 만들었는지가 이름에 있어야 한다.
            target = BASELINES / f"{stamp}_{name}_{model}_{record['promptHash']}.json"
            target.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  baseline -> {target.name}")

    failed = [r for r in records if not r["evaluation"]["deterministicPassed"]]
    print(
        f"\n{len(records)}개 case · deterministic 실패 {len(failed)}개 · "
        "human 항목은 사람이 검토해야 합니다."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
