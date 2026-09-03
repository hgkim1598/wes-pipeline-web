/*
  분석 제출 mutation.

  성공하면 실행 목록 query를 무효화한다. /runs로 이동했을 때 방금 만든 Job이
  이미 캐시된 예전 목록에 가려지지 않게 하기 위해서다. 목록 화면 코드는
  건드리지 않는다 — 필요한 연결은 query key 하나뿐이다.

  retry는 두지 않는다. 이 요청은 부작용이 있다(Job 생성 + worker queue 투입).
  응답을 못 받았다는 이유로 자동으로 다시 보내면 같은 분석이 두 번 실행될 수
  있다. 재시도는 사용자가 명시적으로 한다.
*/

import { useMutation, useQueryClient } from '@tanstack/react-query'

import type { CreateJobInput } from '@/features/new-analysis/jobApi'
import { createJob } from '@/features/new-analysis/jobApi'
import { runListQueryKey } from '@/features/runs/useRunListQuery'

export function useCreateJobMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateJobInput) => createJob(input),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runListQueryKey })
    },
  })
}
