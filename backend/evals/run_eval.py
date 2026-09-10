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
    "execfailed": "execution_failed",
    "inprogress": "in_progress",
}

# fixture가 검체 이름 자리에 넣어 둔 값. payload에 나타나면 allowlist가 뚫린
# 것이다 -- 단 조립 failure code 안은 예외다(privacy_check 참고).
CANARY = "EVAL_SAMPLE_CANARY"

# 모델을 부르지 않기로 한 case와 그 이유. provider 실패와 구분해서 기록한다.
SKIP_MODEL = {
    "in_progress": (
        "제품 UI가 미완료 실행의 synthesis를 막는다(§32). 모델에 가는 사실이 "
        "3개뿐이고, 이 Run은 stale/orphan이라 model baseline 기준으로 적합하지 "
        "않다. in_progress 계약 회귀는 deterministic 검사로 충분하다."
    ),
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

    One occurrence is legitimate `[설계판단]`
    ---------------------------------------

    main.sh composes some failure codes from run values, and the sample name
    ends up *inside the code*: `sort_order_DEMO_WES.L001`. That code is the
    failure's identity and its evidence id -- the model has to cite
    `fail:sort_order_EVAL_SAMPLE_CANARY.L001`, so the canary must reach the
    payload there.

    That is not the same thing as leaking `variantCalling.sample`. So the
    codes that carry it are subtracted first, and the canary is then forbidden
    everywhere else. A blanket substring check would fail Case C for doing
    exactly what it is supposed to do.
    """
    payload, _allowed = contract.build_payload(RunExplanation.model_validate(fixture))
    blob = json.dumps(payload, ensure_ascii=False)

    # 조립 failure code 안의 canary는 정당하다. 그 자리만 지우고 나머지를 본다.
    allowed_here = [
        row.get("code", "")
        for row in payload.get("failures", [])
        if CANARY in row.get("code", "")
    ]
    remainder = blob
    for code in allowed_here:
        remainder = remainder.replace(code, "")

    leaked = [n for n in (CANARY, "EVAL_SAMPLE") if n in remainder]
    if leaked:
        return evaluators.CheckResult(
            name="payload-privacy",
            outcome="fail",
            detail=f"fixture canary가 payload에 유입: {leaked}",
        )
    detail = "검체 식별자가 payload에 없음"
    if allowed_here:
        detail += f" (조립 code {len(allowed_here)}건은 evidence id로 허용)"
    return evaluators.CheckResult(
        name="payload-privacy", outcome="pass", detail=detail
    )


def load_case(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    expectations = json.loads(
        (EXPECTATIONS / f"{name}.json").read_text(encoding="utf-8")
    )
    return fixture, expectations


def evaluate(name: str) -> dict[str, Any]:
    """One case: build payload, call the model once, score the result.

    A case listed in SKIP_MODEL is evaluated without calling anything. Its
    record says `invocationStatus: skipped` with a reason -- deliberately not
    running is not the same state as a provider failing, and a report that
    conflated them would make a decision look like an outage.
    """
    fixture, expectations = load_case(name)
    explanation = RunExplanation.model_validate(fixture)

    payload, allowed = contract.build_payload(explanation)
    skipped = SKIP_MODEL.get(name)

    if skipped:
        result = {"available": False, "errorCategory": None, "synthesis": None}
        report = evaluators.run_expectations(
            expectations, fixture, result, payload, model_invoked=False
        )
    else:
        result = synthesis.build_run_synthesis(explanation).model_dump()
        report = evaluators.run_expectations(expectations, fixture, result, payload)
    report.results.insert(0, privacy_check(fixture))

    provenance = result.get("provenance") or {}
    return {
        "invocationStatus": "skipped" if skipped else "invoked",
        "invocationSkippedReason": skipped,
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
    if record.get("invocationStatus") == "skipped":
        # 실패가 아니라 의도적 미실행이다. 헤더에서부터 구분한다.
        print("  model      호출하지 않음 (skipped)")
        print(f"  이유       {record.get('invocationSkippedReason')}")
    else:
        print(f"  model      {record.get('models')}")
        print(f"  duration   {record.get('durationMs')} ms")
        print(
            f"  available  {record.get('available')} "
            f"{record.get('errorCategory') or ''}"
        )
    for row in record["evaluation"]["results"]:
        mark = {
            "pass": "PASS",
            "fail": "FAIL",
            "needs_review": "REVIEW",
            "not_run": "SKIP",
        }[row["outcome"]]
        print(f"  [{mark:6}] {row['name']:44} {row['detail'][:60]}")
    if record.get("invocationStatus") == "skipped":
        # "PASSED"라고 쓰면 출력을 채점해서 통과한 것처럼 읽힌다. 실제로는
        # 계약 검사만 돌았다.
        checked = [
            r for r in record["evaluation"]["results"] if r["outcome"] != "not_run"
        ]
        print(
            f"  계약 검사만 수행: {len(checked)}건 통과 · "
            f"출력 채점 {len(record['evaluation']['results']) - len(checked)}건 미실행"
        )
    else:
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
        # A baseline recorded as `skipped` has no model output, and rescoring it
        # as if it did turns "we never called" into "the provider failed" -- the
        # one distinction this record exists to keep. Carry the status forward.
        invoked = stored.get("invocationStatus") != "skipped"
        report = evaluators.run_expectations(
            expectations, fixture, result, payload, model_invoked=invoked
        )
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

    calling = [n for n in names if n not in SKIP_MODEL]
    print("이 명령은 Claude Max 구독 사용량을 소비합니다.")
    print(
        f"  case {len(names)}개 중 {len(calling)}개 호출 · 총 {len(calling)}회"
    )
    for n in names:
        if n in SKIP_MODEL:
            print(f"  (skip) {n} : 모델을 호출하지 않습니다")
    print(f"  model: {config.SYNTHESIS_MODEL or 'CLI 기본값'}")
    print("  자동 재시도 없음. 실패하면 그대로 보고합니다.")
    if not calling:
        print("  호출할 case가 없습니다. 확인 없이 진행합니다.")
    if calling and not args.yes:
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
