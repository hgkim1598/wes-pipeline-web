/*
  Run 상세 계약 4종.

  근거: backend/app/schemas.py
    JobStateResponse      GET /api/jobs/{id}
    StepDetailResponse    GET /api/jobs/{id}/steps/{stepId}
    JobResultsResponse    GET /api/jobs/{id}/results
    ArtifactListResponse  GET /api/jobs/{id}/artifacts

  세 가지 규칙을 이 파일 전체에 적용한다.

  1. status·runMode·stepId 같은 어휘는 z.string()으로 받는다. backend가 값을
     하나 추가한 순간 화면 전체가 "응답을 읽지 못함"이 되는 것을 막는다.
     모르는 값의 처리는 stepStatus.ts와 registries/steps.ts가 맡는다.

  2. nullable 필드에 default를 두지 않는다. 여기 선언한 필드는 모두 정식 응답
     필드이므로 키 누락은 값 없음이 아니라 계약 불일치다(features/runs/api.ts와
     같은 정책).

  3. metrics는 통과시킨다. 키가 pipeline의 metric 식별자이고 main.sh에
     step_metric이 추가될 때 frontend가 따라 바뀌어서는 안 된다.
     ⚠️ 첫 full 실행 결과를 아직 본 적이 없으므로 의미·단위를 지어내지 않고
        키/값을 그대로 표시한다.
*/

import { z } from 'zod'

import { ApiError, getJson, postJson } from '@/api/client'
import { JOBS_PATH } from '@/features/runs/api'

/** 아직 준비되지 않은 응답(409)을 오류와 구분하기 위한 표식. */
export const NOT_READY = 'notReady' as const

export interface NotReady {
  state: typeof NOT_READY
  /** backend가 준 사유. 사용자에게 그대로 보여줄 수 있다. */
  reason: string | null
}

export function isNotReady<T>(value: T | NotReady): value is NotReady {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as NotReady).state === NOT_READY
  )
}

function parse<T>(schema: z.ZodType<T>, payload: unknown, message: string): T {
  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new ApiError(message, {
      kind: 'malformed',
      detail: z.prettifyError(parsed.error),
      cause: parsed.error,
    })
  }
  return parsed.data
}

/*
  409는 오류가 아니다.

  /results와 /artifacts는 실행이 아직 그 문서를 만들지 않았을 때 409를 준다
  (backend/app/api/results.py). 그것을 실패로 처리하면 화면이 "결과 0건" 또는
  빨간 오류를 보여주는데, 사실은 "아직"이다. 둘을 구분하는 것이 이 함수다.
*/
async function readOrNotReady<T>(
  path: string,
  schema: z.ZodType<T>,
  message: string,
  signal?: AbortSignal,
): Promise<T | NotReady> {
  try {
    const payload = await getJson(path, { signal })
    return parse(schema, payload, message)
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      return { state: NOT_READY, reason: error.detail }
    }
    throw error
  }
}

// --- GET /api/jobs/{id} -----------------------------------------------------

export const StepStateSchema = z.object({
  stepId: z.string(),
  /** pending·running은 backend가 계획에서 유도한 값이다. 디스크에는 없다. */
  status: z.string(),
  elapsedSeconds: z.number(),
  messages: z.array(z.string()),
})

export type StepState = z.infer<typeof StepStateSchema>

export const JobStateSchema = z.object({
  jobId: z.string(),
  runId: z.string(),
  profileId: z.string(),
  status: z.string(),
  /** 완료 단계 비율(%). 시간 진행률이 아니다. */
  progress: z.number(),
  steps: z.array(StepStateSchema),
  logTail: z.array(z.string()),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  error: z.string().nullable(),
  runMode: z.string(),
  /** main.sh의 원래 어휘. 화면에서는 보조 정보로만 쓴다. */
  pipelineStatus: z.string().nullable(),
  currentStep: z.string().nullable(),
  unsupportedOptions: z.array(z.string()),
})

export type JobState = z.infer<typeof JobStateSchema>

export function jobPath(jobId: string): string {
  return `${JOBS_PATH}/${encodeURIComponent(jobId)}`
}

export async function fetchJobState(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobState> {
  const payload = await getJson(jobPath(jobId), { signal })
  return parse(JobStateSchema, payload, '실행 상세 응답이 예상한 형식과 다릅니다.')
}

export async function cancelJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<void> {
  // 204를 돌려주므로 본문을 읽지 않는다. backend는 이미 끝난 job에도 204를
  // 주므로(api/jobs.py cancel_job) 경합 상황에서 오류가 되지 않는다.
  await postJson(`${jobPath(jobId)}/cancel`, null, { signal })
}

// --- 공통 하위 모델 ---------------------------------------------------------

export const CheckResultSchema = z.object({
  name: z.string(),
  /** main.sh는 PASS / WARN / FAIL 대문자로 쓴다. */
  status: z.string(),
  detail: z.string(),
})

export type CheckResult = z.infer<typeof CheckResultSchema>

export const PipelineWarningSchema = z.object({
  stepId: z.string().nullable(),
  code: z.string(),
  message: z.string(),
  impact: z.string(),
  canContinue: z.boolean(),
})

export type PipelineWarning = z.infer<typeof PipelineWarningSchema>

export const PipelineFailureSchema = z.object({
  stepId: z.string().nullable(),
  code: z.string(),
  message: z.string(),
})

export type PipelineFailure = z.infer<typeof PipelineFailureSchema>

export const ArtifactEntrySchema = z.object({
  fileId: z.string(),
  stepId: z.string(),
  kind: z.string(),
  displayName: z.string(),
  /** 항상 run 디렉터리 기준 상대경로다. 서버 절대경로는 응답에 없다. */
  relativePath: z.string(),
  sizeBytes: z.number().nullable(),
  sha256: z.string().nullable(),
  downloadable: z.boolean(),
  description: z.string(),
  available: z.boolean(),
})

export type ArtifactEntry = z.infer<typeof ArtifactEntrySchema>

// --- GET /api/jobs/{id}/steps/{stepId} --------------------------------------

export const StepIOSchema = z.object({
  type: z.string(),
  path: z.string(),
})

export const StepDetailSchema = z.object({
  jobId: z.string(),
  runId: z.string(),
  stepId: z.string(),
  status: z.string(),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  elapsedSeconds: z.number(),
  exitCode: z.number().nullable(),
  inputs: z.array(StepIOSchema),
  outputs: z.array(StepIOSchema),
  validation: z.object({
    status: z.string(),
    results: z.array(CheckResultSchema),
  }),
  /** pipeline의 metric 식별자 -> 값. 해석하지 않고 그대로 표시한다. */
  metrics: z.record(z.string(), z.unknown()),
  artifacts: z.array(ArtifactEntrySchema),
  warnings: z.array(PipelineWarningSchema),
  failures: z.array(PipelineFailureSchema),
  /** main.sh gate_next_step()의 판단. 실패 진단에 쓴다. */
  nextStepReady: z.boolean(),
})

export type StepDetail = z.infer<typeof StepDetailSchema>

export async function fetchStepDetail(
  jobId: string,
  stepId: string,
  signal?: AbortSignal,
): Promise<StepDetail> {
  const payload = await getJson(
    `${jobPath(jobId)}/steps/${encodeURIComponent(stepId)}`,
    { signal },
  )
  return parse(StepDetailSchema, payload, '단계 상세 응답이 예상한 형식과 다릅니다.')
}

// --- GET /api/jobs/{id}/results ---------------------------------------------

export const ResultsSchema = z.object({
  jobId: z.string(),
  runId: z.string(),
  resultType: z.string(),
  /** --check-only 실행은 항상 false. 산출물이 존재하지 않는다. */
  analysisOutputProduced: z.boolean(),
  status: z.string(),
  pipelineStatus: z.string().nullable(),
  schemaVersion: z.string().nullable(),
  sample: z.string().nullable(),
  elapsedSeconds: z.number().nullable(),
  checks: z.array(CheckResultSchema),
  warnings: z.array(PipelineWarningSchema),
  failures: z.array(PipelineFailureSchema),
  inputSummary: z
    .object({
      sample: z.string().nullable(),
      laneCount: z.number().nullable(),
      assembly: z.string().nullable(),
      contigStyle: z.string().nullable(),
      bundleId: z.string().nullable(),
      captureKitId: z.string().nullable(),
      captureKitMode: z.string().nullable(),
      targetBedSha256: z.string().nullable(),
      coverageBedSha256: z.string().nullable(),
    })
    .nullable(),
  /*
    커버리지는 **두 가지 다른 측정**을 담고 있다. 섞어 읽으면 안 된다.

      염기 단위   thresholds.bed.gz — 각 depth 이상인 실제 염기 수.
                  breadth와 zeroCoverage*가 여기 속한다.
                  "target이 실제로 얼마나 덮였나"의 정직한 답이다.

      구간 단위   regions.bed.gz — interval마다 평균 depth 하나.
                  lowMeanDepth*와 fullyUncovered*가 여기 속한다.

    평균 depth가 0보다 큰 interval도 그 안에 0X 염기를 가질 수 있으므로
    basesInFullyUncoveredIntervalsPct는 항상 zeroCoverageBasesPct 이하이고,
    둘은 서로를 대신할 수 없다. 화면에서도 두 그룹을 분리해 보여준다.
  */
  coverage: z
    .object({
      meanTargetDepth: z.number().nullable(),
      targetNonoverlapBases: z.number().nullable(),
      /** 깊이 라벨 -> target 염기 비율. 키는 mosdepth --thresholds가 정한다. */
      breadth: z.record(z.string(), z.number()),

      // 염기 단위
      /** 1X에 한 번도 도달하지 못한 target 염기 수. 옛 run은 null일 수 있다. */
      zeroCoverageBases: z.number().nullable(),
      zeroCoverageBasesPct: z.number().nullable(),

      // 구간 단위
      lowMeanDepthThresholdX: z.number().nullable(),
      lowMeanDepthIntervals: z.number().nullable(),
      basesInLowMeanDepthIntervals: z.number().nullable(),
      basesInLowMeanDepthIntervalsPct: z.number().nullable(),
      /** interval 전체의 평균 depth가 0인 구간. 0X 염기 비율과 다른 값이다. */
      fullyUncoveredIntervals: z.number().nullable(),
      basesInFullyUncoveredIntervals: z.number().nullable(),
      basesInFullyUncoveredIntervalsPct: z.number().nullable(),

      /** 항상 null. mosdepth가 --no-per-base로 실행되어 산출되지 않는다. */
      medianTargetDepth: z.null(),
      medianNote: z.string().nullable(),
    })
    .nullable(),
  variantCalling: z
    .object({
      sample: z.string().nullable(),
      assembly: z.string().nullable(),
      rawVariantRecords: z.number().nullable(),
      filteringApplied: z.boolean(),
      coreEndpoint: z.string(),
      rawVcfRelative: z.string().nullable(),
      gvcfRelative: z.string().nullable(),
    })
    .nullable(),
  optionalSteps: z.record(z.string(), z.string()),
  /** 이 실행에서 실제로 렌더링할 수 있는 결과 view id. */
  availableViews: z.array(z.string()),
  artifactCount: z.number(),
  intendedUse: z.string().nullable(),
})

export type Results = z.infer<typeof ResultsSchema>

export async function fetchResults(
  jobId: string,
  signal?: AbortSignal,
): Promise<Results | NotReady> {
  return readOrNotReady(
    `${jobPath(jobId)}/results`,
    ResultsSchema,
    '결과 응답이 예상한 형식과 다릅니다.',
    signal,
  )
}

// --- GET /api/jobs/{id}/artifacts -------------------------------------------

export const ArtifactListSchema = z.object({
  jobId: z.string(),
  artifactCount: z.number(),
  manifestPresent: z.boolean(),
  /*
    ⚠️ 이 값은 화면에 표시하지 않는다.
    main.sh가 finalization이 자기 산출물을 등록하기 전에 manifest를 쓰기 때문에
    full 실행에서는 구조적으로 false가 된다(backend/app/schemas.py의 주석,
    CLAUDE.md 15장). 사용자에게 오류로 보이면 안 된다.
  */
  manifestConsistent: z.boolean(),
  /** 잘못된 항목이라 제외된 개수. 0보다 크면 사용자에게 알린다. */
  suppressedCount: z.number(),
  artifacts: z.array(ArtifactEntrySchema),
})

export type ArtifactList = z.infer<typeof ArtifactListSchema>

export async function fetchArtifacts(
  jobId: string,
  signal?: AbortSignal,
): Promise<ArtifactList | NotReady> {
  return readOrNotReady(
    `${jobPath(jobId)}/artifacts`,
    ArtifactListSchema,
    '산출물 응답이 예상한 형식과 다릅니다.',
    signal,
  )
}

/**
 * 다운로드 URL.
 *
 * fetch로 본문을 받아 Blob을 만들지 않는다. 수 GB짜리 BAM을 메모리에 올릴 수
 * 없고, 브라우저가 이미 잘하는 일이다. 평범한 링크로 두어 다시 시도·이어받기를
 * 브라우저에 맡긴다.
 */
export function artifactDownloadUrl(jobId: string, fileId: string): string {
  return `${jobPath(jobId)}/artifacts/${encodeURIComponent(fileId)}/download`
}
