"""Build an eval fixture from a real run's structured API responses.

    python -m evals.generate_fixture --case full  --api http://127.0.0.1:8000
    python -m evals.generate_fixture --case precheck --api http://127.0.0.1:8011

What it copies, and what it refuses to
--------------------------------------

Two small JSON documents:

    GET /api/jobs/{id}            job state
    GET /api/jobs/{id}/results    ~3 KB

Nothing else. No BAM, VCF, FASTQ, run directory, artifact contents or log tail
-- the run stays where it is. The Full Run lives on a VM whose deployed release
predates `/explanation`, so the responses are fed through the *local*
deterministic layer instead of asking that server to build the explanation.
That is the same path the 2026-09-09 validation used.

Why RunExplanation and not the LLM payload
------------------------------------------

The payload is what `build_payload` produces, and `build_payload` is the most
frequently changed layer in this subsystem -- privacy allowlist, concepts,
knowledgeStatus all landed there. Freezing its output would bake today's
behaviour into the fixture and hide exactly the regressions worth catching.

Storing the explanation means every eval run re-derives the payload, so the
privacy allowlist and concept selection actually execute each time.

Identity is scrubbed, and it is safe to scrub
---------------------------------------------

`build_payload` reads exactly one identity field: `runMode`. Verified by
reading it, not assumed. So jobId / runId / sampleId / profileId /
captureKitId can be replaced with fixed placeholders and the derived payload is
byte-identical -- while the fixture stops carrying a sample identifier into
git.

No number is typed by a person. Every value comes from the API response.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.services.explanation import deterministic, run_context

FIXTURES = Path(__file__).resolve().parent / "fixtures"

CASES = {
    "full": {
        "jobId": "wes-20260907-014650-fcb1c2",
        "file": "full_completed_with_warnings.json",
        "api": "http://127.0.0.1:8000",
    },
    "precheck": {
        "jobId": "wes-20260813-170053-8eccbb",
        "file": "precheck_failed.json",
        "api": "http://127.0.0.1:8011",
    },
}

# 스크럽 후 값. build_payload가 읽지 않는 필드만 바꾼다.
SCRUBBED = {
    "jobId": "eval-job",
    "runId": "eval-run",
    "sampleId": "EVAL_SAMPLE",
}

# `variantCalling`도 검체 이름을 들고 있다 -- `sample`과, 그 이름이 박힌 두 경로.
# `build_payload`의 allowlist(_VARIANT_FIELDS)가 셋 다 제외하므로 바꿔도 payload는
# 동일하다.
#
# 지우지 않고 **canary로 바꾼다.** 이 문자열이 언젠가 payload에 나타나면
# allowlist가 뚫린 것이고, run_eval의 privacy 확인이 바로 잡는다. 비워 두면
# 그 회귀를 볼 방법이 없다.
CANARY_SAMPLE = "EVAL_SAMPLE_CANARY"


def scrub_variant_calling(payload: dict[str, Any]) -> None:
    """검체 이름과 그 이름이 든 경로를 canary로 바꾼다. 구조는 그대로 둔다."""
    variant = payload.get("variantCalling")
    if not variant:
        return
    if variant.get("sample"):
        variant["sample"] = CANARY_SAMPLE
    for key in ("rawVcfRelative", "gvcfRelative"):
        value = variant.get(key)
        if value:
            # 디렉터리 구조는 남기고 파일명만 바꾼다 -- 경로 모양 자체는 사실이다.
            head, _, tail = value.rpartition("/")
            suffix = tail.split(".", 1)[1] if "." in tail else ""
            variant[key] = f"{head}/{CANARY_SAMPLE}.{suffix}" if head else tail


def _get(api: str, path: str) -> dict[str, Any]:
    url = f"{api.rstrip('/')}{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"{url} 를 읽지 못했습니다: {exc}") from exc


def build_explanation(job: dict[str, Any], results: dict[str, Any]):
    """Assemble the context from API responses, then run the real explanation.

    The reader layer (`run_context.build_run_diagnostic_context`) is bypassed
    because it needs the run directory, which is on the VM. Everything below it
    -- the deterministic layer that the eval is actually about -- is the real
    code.
    """
    summary = results.get("inputSummary") or {}
    context = run_context.RunDiagnosticContext(
        contextKind="full" if results["resultType"] == "full" else "precheck",
        resultsAvailable=True,
        resultsUnavailableReason=None,
        identity=run_context.RunIdentity(
            jobId=SCRUBBED["jobId"],
            runId=SCRUBBED["runId"],
            sampleId=SCRUBBED["sampleId"],
            profileId=job["profileId"],
            captureKitId=summary.get("captureKitId"),
            runMode=job["runMode"],
        ),
        outcome=run_context.RunOutcome(
            status=job["status"],
            pipelineStatus=job.get("pipelineStatus"),
            progress=job.get("progress", 0),
            currentStep=job.get("currentStep"),
            startedAt=job.get("startedAt"),
            finishedAt=job.get("finishedAt"),
            error=job.get("error"),
            analysisOutputProduced=results.get("analysisOutputProduced"),
            elapsedSeconds=results.get("elapsedSeconds"),
        ),
        steps=[
            run_context.RunStepState(
                stepId=s["stepId"],
                status=s["status"],
                elapsedSeconds=s.get("elapsedSeconds", 0),
            )
            for s in job.get("steps", [])
        ],
        checks=[run_context.RunCheck(**c) for c in results.get("checks", [])],
        warnings=[run_context.RunWarning(**w) for w in results.get("warnings", [])],
        failures=[run_context.RunFailure(**f) for f in results.get("failures", [])],
        coverage=(
            run_context.RunCoverage(**results["coverage"])
            if results.get("coverage")
            else None
        ),
        variantCalling=(
            run_context.RunVariantCalling(**results["variantCalling"])
            if results.get("variantCalling")
            else None
        ),
        optionalSteps=results.get("optionalSteps") or {},
        intendedUse=results.get("intendedUse"),
        sources={"checks": "result_reader", "warnings": "result_reader"},
    )
    return deterministic.build_run_explanation(context)


# 저장 전에 반드시 없어야 하는 것. 하나라도 걸리면 파일을 쓰지 않는다.
FORBIDDEN = (
    "SRR2962669",
    "/home/",
    "C:\\Users",
    "C:/Users",
    "vboxuser",
    "logTail",
    "run_dir",
    "wes-20260907",
    "wes-20260813",
)


def assert_clean(blob: str) -> None:
    hits = [needle for needle in FORBIDDEN if needle in blob]
    if hits:
        raise SystemExit(f"fixture에 남으면 안 되는 값: {hits}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(CASES), required=True)
    parser.add_argument("--api", help="기본값은 case별 backend")
    args = parser.parse_args()

    case = CASES[args.case]
    api = args.api or case["api"]
    job_id = case["jobId"]

    job = _get(api, f"/api/jobs/{job_id}")
    results = _get(api, f"/api/jobs/{job_id}/results")
    if results.get("resultType") is None:
        raise SystemExit("결과 문서가 없어 fixture를 만들 수 없습니다.")

    explanation = build_explanation(job, results)
    payload = explanation.model_dump()
    scrub_variant_calling(payload)

    blob = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    assert_clean(blob)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    target = FIXTURES / case["file"]
    target.write_text(blob + "\n", encoding="utf-8")

    print(f"wrote {target.relative_to(Path(__file__).resolve().parent.parent)}")
    print(f"  source      {api} · {job_id}")
    print(f"  contextKind {explanation.contextKind} · status {explanation.status}")
    print(f"  diagnostics {[d.code for d in explanation.diagnostics]}")
    print(f"  failures    {[f.code for f in explanation.failures]}")
    print(f"  limitations {[l.code for l in explanation.limitations]}")
    print(f"  bytes       {len(blob)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
