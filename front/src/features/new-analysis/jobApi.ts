/*
  POST /api/jobs 의 계약.

  근거: backend/app/schemas.py CreateJobRequest / CreateJobResponse,
        backend/app/api/jobs.py create_job()

  요청 형태는 backend가 읽는 그대로다.

    { profileId, captureKitId, options, samples: [{ sampleId, files: {r1, r2} }] }

  samples가 배열인 것은 backend의 계약이다. 지금 backend는 원소가 정확히
  하나일 때만 받고, 둘 이상이면 400으로 거절한다(create_job의 명시적 검사).
  그래서 화면은 샘플 하나만 보내지만, 이 함수는 "샘플 하나"를 하드코딩하지
  않고 배열을 만들어 보낸다. 나중에 여러 샘플을 각각의 Job으로 제출하게 되면
  이 함수를 샘플마다 호출하면 된다.

  runMode는 요청에 없다. backend가 서버 설정(config.RUN_MODE)을 쓰기 때문에
  화면이 보낼 값이 아니다.
*/

import { z } from 'zod'

import { ApiError, postJson } from '@/api/client'
import { JOBS_PATH } from '@/features/runs/api'

const CreateJobResponseSchema = z.object({
  jobId: z.string(),
})

export interface CreateJobInput {
  profileId: string
  captureKitId: string
  sampleId: string
  /** slotId → 업로드 토큰. 값은 POST /api/uploads/{id}/complete가 준 것 그대로다. */
  files: Record<string, string>
}

export async function createJob(
  input: CreateJobInput,
  signal?: AbortSignal,
): Promise<string> {
  const payload = await postJson(
    JOBS_PATH,
    {
      profileId: input.profileId,
      captureKitId: input.captureKitId,
      // 서버가 실제로 해석하는 옵션만 보낸다. capture kit은 위 필드로 이미
      // 전달되고, assembly는 서버 bundle에 고정이며, run_acmg는 이 서버의
      // InterVar 지원 여부를 확인할 방법이 아직 없다. 보내지 않는 편이
      // 정확하다 — 무시될 값을 보내면 unsupportedOptions에만 쌓인다.
      options: {},
      samples: [{ sampleId: input.sampleId, files: input.files }],
    },
    { signal },
  )

  const parsed = CreateJobResponseSchema.safeParse(payload)
  if (!parsed.success) {
    throw new ApiError('분석 생성 응답이 예상한 형식과 다릅니다.', {
      kind: 'malformed',
      detail: z.prettifyError(parsed.error),
      cause: parsed.error,
    })
  }

  return parsed.data.jobId
}
