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
    # 아래 둘은 /results가 409다. core_summary.json이 없으므로 step 문서에서
    # 사실을 모은다 -- run_context가 같은 상황에서 하는 것과 같다.
    "execfailed": {
        "jobId": "wes-20260904-172826-68aa20",
        "file": "execution_failed.json",
        "api": "http://127.0.0.1:8000",
    },
    "inprogress": {
        "jobId": "wes-20260906-234444-eed8e3",
        "file": "in_progress.json",
        "api": "http://127.0.0.1:8000",
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


# 조립된 failure code 안의 검체 이름 조각. `sort_order_DEMO_WES.L001`처럼
# main.sh가 실행 값으로 만든 code에는 검체 이름이 박혀 있다.
#
# 비우지 않고 canary로 바꾼다 -- code가 **조립되었다**는 성질(open set)이
# 유지돼야 하고, 그 code는 evidence id로도 쓰이므로 fixture 안에서 일관돼야
# 한다. 그리고 이 문자열이 언젠가 payload에 나타나면 privacy 검사가 잡는다.
def scrub_composed_code(code: str, sample: str | None) -> str:
    """조립 code 안의 검체 이름만 canary로 바꾼다. 구조는 그대로 둔다."""
    if not sample or sample not in code:
        return code
    return code.replace(sample, CANARY_SAMPLE)


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


def build_explanation_from_steps(
    job: dict[str, Any], step_docs: dict[str, dict[str, Any]], sample: str | None
):
    """`/results`가 없는 실행. step 문서에서 사실을 모은다.

    `run_context`의 같은 분기를 그대로 옮긴 것이 아니라 **의미를 맞춘** 것이다.
    그쪽은 run 디렉터리의 step 문서를 파일로 읽고, 여기는 같은 문서를
    `/api/jobs/{id}/steps/{stepId}`로 읽는다. 소스가 HTTP라 helper를 그대로
    재사용할 수는 없다.

    맞춰야 하는 의미는 셋이다.

      contextKind   terminal이면 failed, 아니면 in_progress
      resultsAvailable  항상 False
      coverage · variantCalling · optionalSteps · intendedUse
                    전부 비운다. 파이프라인이 만든 적이 없고, 빈 껍데기를
                    넣으면 "측정했는데 없었다"로 읽힌다

    `analysisOutputProduced`는 **건드리지 않는다.** 기본값 None이 맞다 --
    "산출물이 없다"가 아니라 "여기서는 알 수 없다"이다. False로 바꾸면
    NO_ANALYSIS_OUTPUT limitation이 잘못 생긴다.
    """
    warnings: list[run_context.RunWarning] = []
    failures: list[run_context.RunFailure] = []
    for step in job.get("steps", []):
        doc = step_docs.get(step["stepId"])
        if not doc:
            continue
        for item in doc.get("failures", []):
            failures.append(
                run_context.RunFailure(
                    stepId=step["stepId"],
                    code=scrub_composed_code(item.get("code", ""), sample),
                    message=item.get("message", ""),
                )
            )
        for item in doc.get("warnings", []):
            warnings.append(
                run_context.RunWarning(
                    stepId=step["stepId"],
                    code=item.get("code", ""),
                    message=item.get("message", ""),
                    impact=item.get("impact", ""),
                    canContinue=item.get("canContinue", False),
                )
            )

    terminal = job["status"] in ("failed", "cancelled")
    context = run_context.RunDiagnosticContext(
        contextKind="failed" if terminal else "in_progress",
        resultsAvailable=False,
        resultsUnavailableReason="the run has not produced core_summary.json",
        identity=run_context.RunIdentity(
            jobId=SCRUBBED["jobId"],
            runId=SCRUBBED["runId"],
            sampleId=SCRUBBED["sampleId"],
            profileId=job["profileId"],
            captureKitId=None,
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
            # analysisOutputProduced는 설정하지 않는다. 위 docstring 참고.
        ),
        steps=[
            run_context.RunStepState(
                stepId=s["stepId"],
                status=s["status"],
                elapsedSeconds=s.get("elapsedSeconds", 0),
            )
            for s in job.get("steps", [])
        ],
        checks=[],
        warnings=warnings,
        failures=failures,
        coverage=None,
        variantCalling=None,
        optionalSteps={},
        intendedUse=None,
        sources={"warnings": "step documents", "failures": "step documents"},
    )
    return deterministic.build_run_explanation(context)


# 저장 전에 반드시 없어야 하는 것. 하나라도 걸리면 파일을 쓰지 않는다.
FORBIDDEN = (
    "SRR2962669",
    "DEMO_WES",
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

    try:
        results = _get(api, f"/api/jobs/{job_id}/results")
    except SystemExit:
        results = None

    if results and results.get("resultType"):
        explanation = build_explanation(job, results)
        source = "/results"
    else:
        # core_summary.json이 없는 실행. 끝난 step의 문서만 읽는다 --
        # pending·running은 문서 자체가 없다.
        sample = None
        step_docs: dict[str, dict[str, Any]] = {}
        for step in job.get("steps", []):
            if step["status"] in ("pending", "running"):
                continue
            try:
                step_docs[step["stepId"]] = _get(
                    api, f"/api/jobs/{job_id}/steps/{step['stepId']}"
                )
            except SystemExit:
                continue
        # 조립 code에서 지울 검체 이름은 목록 응답이 갖고 있다.
        for row in _get(api, "/api/jobs").get("jobs", []):
            if row.get("jobId") == job_id:
                sample = row.get("sampleId")
        explanation = build_explanation_from_steps(job, step_docs, sample)
        source = "step documents"

    payload = explanation.model_dump()
    scrub_variant_calling(payload)

    blob = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    assert_clean(blob)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    target = FIXTURES / case["file"]
    target.write_text(blob + "\n", encoding="utf-8")

    print(f"wrote {target.relative_to(Path(__file__).resolve().parent.parent)}")
    print(f"  source      {api} · {job_id} · {source}")
    print(f"  contextKind {explanation.contextKind} · status {explanation.status}")
    print(f"  diagnostics {[d.code for d in explanation.diagnostics]}")
    print(f"  failures    {[f.code for f in explanation.failures]}")
    print(f"  limitations {[l.code for l in explanation.limitations]}")
    print(f"  bytes       {len(blob)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
