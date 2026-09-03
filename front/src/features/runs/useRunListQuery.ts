/*
  실행 목록 query.

  retry: false
    health query와 같은 이유다(features/health/useHealthQuery.ts). 기본값인
    3회 재시도는 backend가 꺼져 있을 때 오류가 보이기까지 수 초를 loading으로
    보내게 만든다. 목록 화면에서 그 시간은 "비어 있는 것처럼" 읽힌다.

  polling은 넣지 않았다.
    CLAUDE.md 13장의 3초 polling은 실행 **하나**의 상태를 따라가는 규칙이고,
    그 화면은 아직 없다. 목록 전체를 주기적으로 다시 읽어야 한다는 제품 요구는
    아직 확인되지 않았으므로 근거 없는 반복 호출을 만들지 않는다. 갱신은
    화면의 명시적인 "다시 확인"과 React Query의 기본 focus refetch로 한다.
*/

import { useQuery } from '@tanstack/react-query'

import { fetchJobList } from '@/features/runs/api'

export const runListQueryKey = ['runs'] as const

export function useRunListQuery() {
  return useQuery({
    queryKey: runListQueryKey,
    queryFn: ({ signal }) => fetchJobList(signal),
    retry: false,
  })
}
