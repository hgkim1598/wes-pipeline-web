/*
  실행 목록 query.

  retry: false
    health query와 같은 이유다(features/health/useHealthQuery.ts). 기본값인
    3회 재시도는 backend가 꺼져 있을 때 오류가 보이기까지 수 초를 loading으로
    보내게 만든다. 목록 화면에서 그 시간은 "비어 있는 것처럼" 읽힌다.

  polling: 진행 중인 실행이 있을 때만 5초.
    상세(3초)보다 느린 이유는 비용이다. list_jobs()는 행마다 run 상태 문서를
    읽으므로(backend/app/api/jobs.py) 목록 한 번이 파일 N개 읽기다. 목록에서
    필요한 정확도는 "곧 바뀐다"까지이고, 초 단위 추적은 상세 화면이 한다.

    전부 terminal이면 멈춘다. 더 이상 바뀔 값이 없는데 두드릴 이유가 없다.
*/

import { useQuery } from '@tanstack/react-query'

import { fetchJobList } from '@/features/runs/api'
import { isTerminalStatus } from '@/features/runs/status'

export const runListQueryKey = ['runs'] as const

const LIST_INTERVAL_MS = 5000

export function useRunListQuery() {
  return useQuery({
    queryKey: runListQueryKey,
    queryFn: ({ signal }) => fetchJobList(signal),
    retry: false,
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs
      if (jobs === undefined) return false
      const hasActive = jobs.some((job) => !isTerminalStatus(job.status))
      return hasActive ? LIST_INTERVAL_MS : false
    },
  })
}
