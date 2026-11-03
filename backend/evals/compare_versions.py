"""A/B comparison of stored eval records, on one common basis. Never calls a model.

    python -m evals.compare_versions --a <record>... --b <record>...
                                     [--out report.json] [--blind sheet.md --blind-key key.json]

Each side is a list of baseline file names (under evals/baselines) or paths. The
two sides were generated with different prompt/knowledge versions; this script
does not judge them by the checker each side was written against. Every answer
is re-scored here with BOTH rule versions (explanation_checks_v1 and _v2), so a
difference between A and B is a difference in the answers, not in the checker.

What it reports, per record and per side:
  - promptHash / knowledgeHash / models: which inputs produced the answer
    (a side that mixes hashes is flagged -- it is not one version)
  - durationMs / numTurns as recorded; token usage is not recorded by run_eval,
    so it is reported as unavailable rather than estimated
  - the stored deterministic evaluation (numbers-preserved, evidence checks, ...)
    exactly as recorded -- this script does not re-run it
  - output length: characters and statement count per group
  - explanation-quality counts and the warning/measurement/hard-phrase findings
    under rules v1 and v2

What it does not do: decide which side is better. The counts are checker output
(REVIEW means "a person should look"), and a few records per side are not a
measurement. --blind writes a sheet with the answers under shuffled labels for a
person to read; the key that maps labels back to A/B goes to a separate file.

Output files are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import explanation_quality as q

RULES = ("1", "2")
GROUPS = ("summary", "importantFindings", "limitations", "nextChecks", "uncertainties")
_WATCHED_RULE_PREFIXES = ("warning-", "measurement-meaning", "hard-wording:", "field-translation:")


def _resolve(name: str) -> Path:
    path = Path(name)
    if path.is_file():
        return path
    candidate = q.BASELINES / name
    if candidate.is_file():
        return candidate
    raise SystemExit(f"기록을 찾을 수 없습니다: {name}")


def _length(output: dict[str, Any]) -> dict[str, Any]:
    chars = 0
    statements: dict[str, int] = {}
    for group in GROUPS:
        value = output.get(group)
        if isinstance(value, str):
            chars += len(value)
            statements[group] = 1 if value else 0
        elif isinstance(value, list):
            texts = [item.get("statement", "") for item in value if isinstance(item, dict)]
            chars += sum(len(t) for t in texts)
            statements[group] = len(texts)
        else:
            statements[group] = 0
    return {"characters": chars, "statements": statements, "statementTotal": sum(statements.values())}


def _deterministic(record: dict[str, Any]) -> dict[str, Any]:
    evaluation = record.get("evaluation") or {}
    outcomes = {r.get("name"): r.get("outcome") for r in evaluation.get("results", [])}
    return {"passed": evaluation.get("deterministicPassed"), "outcomes": outcomes}


def _watched(block: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"verdict": f["verdict"], "rule": f["rule"], "unit": f["unit"], "subject": f["subject"]}
        for f in block["findings"]
        # internal findings carry the check in `rule`; fact findings in `subject`
        if str(f["rule"]).startswith(_WATCHED_RULE_PREFIXES)
        or str(f["subject"]).startswith(_WATCHED_RULE_PREFIXES)
    ]


def score_record(path: Path, payloads: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    record = json.loads(path.read_text(encoding="utf-8"))
    case = record.get("case")
    trace = record.get("trace") or {}
    row: dict[str, Any] = {
        "file": path.name,
        "case": case,
        "variant": record.get("variant"),
        "promptHash": record.get("promptHash"),
        "knowledgeHash": record.get("knowledgeHash"),
        "models": record.get("models"),
        "durationMs": record.get("durationMs"),
        "numTurns": trace.get("numTurns"),
        "usage": "not recorded",
        "deterministic": _deterministic(record),
        "hasOutput": bool(record.get("output")),
    }
    output = record.get("output")
    if not output:
        return row
    if case not in payloads:
        payloads[case] = q._payload_for_case(case) if isinstance(case, str) else None
    payload = payloads[case]
    expectations_path = q.EXPECTATIONS / f"{case}.json"
    expectations = (
        json.loads(expectations_path.read_text(encoding="utf-8")) if expectations_path.is_file() else None
    )
    row["length"] = _length(output)
    row["payloadAvailable"] = payload is not None
    row["quality"] = {}
    for rules in RULES:
        block = q.evaluate_record(expectations, payload, output, rules=rules)
        if block is None:
            continue
        row["quality"][f"v{rules}"] = {"counts": block["counts"], "watched": _watched(block)}
    return row


def _side_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    with_output = [r for r in rows if r["hasOutput"]]
    hashes = sorted({(r["promptHash"], r["knowledgeHash"]) for r in rows}, key=str)
    summary: dict[str, Any] = {
        "records": len(rows),
        "withOutput": len(with_output),
        "promptKnowledgeHashes": [list(h) for h in hashes],
        "mixedVersions": len(hashes) > 1,
        "cases": sorted({str(r["case"]) for r in rows}),
        "deterministicPassed": sum(1 for r in rows if r["deterministic"]["passed"] is True),
        "durationMs": [r["durationMs"] for r in rows],
        "characters": [r["length"]["characters"] for r in with_output],
        "statementTotal": [r["length"]["statementTotal"] for r in with_output],
    }
    for rules in RULES:
        key = f"v{rules}"
        totals: dict[str, Counter[str]] = {}
        for r in with_output:
            for category, verdicts in r.get("quality", {}).get(key, {}).get("counts", {}).items():
                totals.setdefault(category, Counter()).update(verdicts)
        summary[f"qualityCounts_{key}"] = {c: dict(v) for c, v in totals.items()}
    return summary


def _blind_sheet(sides: dict[str, list[Path]], seed: int) -> tuple[str, dict[str, str]]:
    items = [(side, path) for side, paths in sides.items() for path in paths]
    rng = random.Random(seed)
    rng.shuffle(items)
    key: dict[str, str] = {}
    lines = [
        "# 블라인드 비교 시트",
        "",
        "답변 순서와 라벨은 무작위입니다. A/B 대응표는 별도 파일에 있으니 다 읽기 전에 열지 마세요.",
        "",
    ]
    for index, (side, path) in enumerate(items, start=1):
        label = f"X{index:02d}"
        key[label] = f"{side}:{path.name}"
        output = json.loads(path.read_text(encoding="utf-8")).get("output")
        lines += [f"## {label}", ""]
        if not output:
            lines += ["(출력 없음)", ""]
            continue
        for group in GROUPS:
            value = output.get(group)
            if isinstance(value, str):
                lines += [f"**{group}**", "", value, ""]
            elif isinstance(value, list) and value:
                lines += [f"**{group}**", ""]
                lines += [f"- {item.get('statement', '')}" for item in value if isinstance(item, dict)]
                lines += [""]
    return "\n".join(lines), key


def _write_new(path: Path, text: str) -> None:
    if path.exists():
        raise SystemExit(f"이미 있는 파일은 덮어쓰지 않습니다: {path}")
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", nargs="+", required=True, help="A 쪽 기록")
    parser.add_argument("--b", nargs="+", required=True, help="B 쪽 기록")
    parser.add_argument("--out", type=Path, help="JSON 보고서 (새 파일만)")
    parser.add_argument("--blind", type=Path, help="블라인드 시트 markdown (새 파일만)")
    parser.add_argument("--blind-key", type=Path, help="블라인드 라벨 대응표 JSON (새 파일만)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    if (args.blind is None) != (args.blind_key is None):
        parser.error("--blind 와 --blind-key 는 함께 지정합니다")

    sides = {"A": [_resolve(n) for n in args.a], "B": [_resolve(n) for n in args.b]}
    payloads: dict[str, dict[str, Any] | None] = {}
    rows = {side: [score_record(p, payloads) for p in paths] for side, paths in sides.items()}
    report = {
        "note": "공통 기준(rules v1·v2 모두)으로 다시 채점한 결과. 어느 쪽이 낫다는 판정이 아니다.",
        "sides": {side: {"summary": _side_summary(r), "records": r} for side, r in rows.items()},
    }

    sys.stdout.reconfigure(encoding="utf-8")
    for side, r in rows.items():
        s = report["sides"][side]["summary"]
        flag = "  ⚠ 한 쪽에 여러 버전이 섞여 있음" if s["mixedVersions"] else ""
        print(f"== {side}: 기록 {s['records']} (출력 {s['withOutput']}) hash {s['promptKnowledgeHashes']}{flag}")
        print(f"   결정론 평가 통과 {s['deterministicPassed']}/{s['records']}  durationMs {s['durationMs']}")
        print(f"   글자수 {s['characters']}  문장수 {s['statementTotal']}")
        for rules in RULES:
            print(f"   rules v{rules}: {s[f'qualityCounts_v{rules}']}")
        for row in r:
            if not row["hasOutput"]:
                print(f"   - {row['file']}: 출력 없음")
                continue
            print(f"   - {row['file']}")
            for w in row["quality"].get("v2", {}).get("watched", []):
                print(f"       v2 {w['verdict']:6} {w['subject']:34} {w['rule']}")

    if args.out:
        _write_new(args.out, json.dumps(report, ensure_ascii=False, indent=2))
    if args.blind and args.blind_key:
        sheet, key = _blind_sheet(sides, args.seed)
        _write_new(args.blind, sheet)
        _write_new(args.blind_key, json.dumps(key, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
