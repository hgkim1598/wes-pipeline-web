/*
  GET /api/health 의 계약.

  근거는 backend/app/main.py의 health() 하나뿐이다. 필드 이름을 frontend에서
  바꾸지 않는다 — 화면에 보이는 라벨은 한국어여도, 계약 키는 backend가 쓰는
  이름 그대로 유지해야 두 쪽을 대조할 수 있다.

  z.object는 모르는 키를 버린다. backend가 필드를 추가해도 이 화면은 깨지지
  않고, 반대로 여기 선언한 필드가 사라지면 즉시 malformed로 드러난다.
*/

import { z } from 'zod'

import { ApiError, getJson } from '@/api/client'

export const HEALTH_PATH = '/api/health'

/**
 * status와 runMode를 literal/enum으로 좁히지 않았다.
 *
 * backend는 지금 status에 "ok"만, runMode에 check_only|full만 쓰지만
 * (backend/app/config.py의 RUN_MODE_CHOICES), 그 값을 schema로 강제하면
 * 예상 밖의 값이 왔을 때 "backend가 비정상"이 아니라 "응답을 못 읽음"으로
 * 보고된다. 어느 쪽인지는 화면이 판단할 문제라서 문자열로 받는다.
 */
export const HealthResponseSchema = z.object({
  status: z.string(),
  runMode: z.string(),
  pipelineScript: z.string(),
  pipelineScriptPresent: z.boolean(),
  captureKitRegistryPresent: z.boolean(),
  referenceConfigured: z.boolean(),
})

export type HealthResponse = z.infer<typeof HealthResponseSchema>

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const payload = await getJson(HEALTH_PATH, { signal })

  const parsed = HealthResponseSchema.safeParse(payload)
  if (!parsed.success) {
    // 조용히 넘기지 않는다. 계약 불일치는 network 오류와 다른 문제이고,
    // 다른 조치를 요구한다.
    throw new ApiError('백엔드 응답이 예상한 형식과 다릅니다.', {
      kind: 'malformed',
      detail: z.prettifyError(parsed.error),
      cause: parsed.error,
    })
  }

  return parsed.data
}
