/*
  GET /api/jobs 의 계약.

  근거
    backend/app/schemas.py   JobListItem · JobListResponse
    backend/app/api/jobs.py  list_jobs()

  backend는 정렬된 목록을 준다(created_at DESC, job_id DESC). frontend에서
  다시 정렬하지 않는다 — 순서는 backend의 계약이고, 여기서 흉내 내면 두 곳이
  어긋났을 때 어느 쪽이 옳은지 알 수 없게 된다.

  filtering · search · pagination 파라미터는 없다. backend가 의도적으로 두지
  않았고 화면에도 해당 조작이 없다.
*/

import { z } from 'zod'

import { ApiError, getJson } from '@/api/client'

export const JOBS_PATH = '/api/jobs'

/**
 * 한 건의 실행.
 *
 * status를 literal union으로 좁히지 않았다. backend의 JobStatus는 지금
 * queued|running|completed|completed_with_warnings|failed|cancelled 여섯
 * 개지만(backend/app/schemas.py), 그 목록을 schema로 강제하면 backend가
 * 상태를 하나 추가한 순간 **목록 전체**가 "응답을 읽지 못함"이 된다.
 * 한 행의 상태 어휘를 모르는 것과 응답을 못 읽는 것은 다른 문제이고
 * 사용자에게 필요한 조치도 다르다. 모르는 상태의 처리는 status.ts가 맡는다.
 *
 * 같은 이유로 runMode도 문자열로 받는다.
 *
 * nullable은 값이 null일 수 있다는 뜻이지 키가 없어도 된다는 뜻이 아니다.
 * 여기 선언한 필드는 모두 backend JobListItem의 정식 응답 필드이므로
 * (backend/app/schemas.py), 키 자체가 사라진 응답은 값 없음이 아니라 계약
 * 불일치다. default로 조용히 메우지 않는다 — safeParse가 실패해
 * ApiError(kind='malformed')로 드러나는 것이 맞다.
 *
 * sampleId는 migration 이전 row에서 실제로 null이 올 수 있다
 * (backend/app/schemas.py의 주석). 그 null을 runId 등으로 대체하지 않는다 —
 * 없는 정보를 채우는 순간 화면이 거짓말을 한다.
 *
 * step 수도 backend가 항상 주는 필드다. 키 누락은 마찬가지로 계약 불일치이며
 * 0으로 보정하지 않는다. 다만 정수로 들어온 뒤의 범위는 검증하지 않는다.
 * 음수 같은 값이 오면 목록 전체를 실패시키는 대신 표시 단계에서 방어한다
 * (StepProgress).
 */
export const JobListItemSchema = z.object({
  jobId: z.string(),
  runId: z.string(),
  status: z.string(),
  sampleId: z.string().nullable(),
  profileId: z.string(),
  captureKitId: z.string().nullable(),
  runMode: z.string(),
  createdAt: z.string(),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  error: z.string().nullable(),
  plannedStepCount: z.number().int(),
  completedStepCount: z.number().int(),
})

export type JobListItem = z.infer<typeof JobListItemSchema>

export const JobListResponseSchema = z.object({
  jobs: z.array(JobListItemSchema),
})

export type JobListResponse = z.infer<typeof JobListResponseSchema>

export async function fetchJobList(signal?: AbortSignal): Promise<JobListResponse> {
  const payload = await getJson(JOBS_PATH, { signal })

  const parsed = JobListResponseSchema.safeParse(payload)
  if (!parsed.success) {
    // 계약 불일치를 조용히 넘기면 화면은 "실행 0건"으로 보인다.
    // 아직 없는 것과 읽지 못한 것은 구분해야 한다.
    throw new ApiError('실행 목록 응답이 예상한 형식과 다릅니다.', {
      kind: 'malformed',
      detail: z.prettifyError(parsed.error),
      cause: parsed.error,
    })
  }

  return parsed.data
}
