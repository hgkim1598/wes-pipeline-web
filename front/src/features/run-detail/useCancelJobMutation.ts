/*
  실행 취소.

  retry를 두지 않는다. 부작용이 있는 요청이고, backend는 이미 끝난 job에도 204를
  주므로(api/jobs.py cancel_job) 실패했다면 재시도가 아니라 원인을 봐야 한다.

  성공 후 상세와 목록을 함께 무효화한다. POSIX에서 취소는 main.sh가 trap으로
  기록하므로 상태가 즉시 바뀌지 않을 수 있다 — 그래서 폴링이 이어서 확인하고,
  여기서는 즉시 한 번 다시 읽는 것으로 충분하다.
*/

import { useMutation, useQueryClient } from '@tanstack/react-query'

import { cancelJob } from '@/features/run-detail/api'
import { runDetailKey } from '@/features/run-detail/queries'
import { runListQueryKey } from '@/features/runs/useRunListQuery'

export function useCancelJobMutation(jobId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => cancelJob(jobId),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: runDetailKey(jobId) })
      void queryClient.invalidateQueries({ queryKey: runListQueryKey })
    },
  })
}
