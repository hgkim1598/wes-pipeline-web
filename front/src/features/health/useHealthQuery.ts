/*
  health query.

  기본 동작에서 두 가지만 바꿨다.

  retry: false
    React Query 기본값은 3회 재시도 + 지수 backoff다. 이 화면의 목적이
    "지금 backend에 닿는가"를 알려주는 것인데, backend가 꺼져 있으면
    기본값에서는 오류가 보이기까지 수 초가 걸리고 그동안 loading으로 보인다.
    상태를 늦게, 부정확하게 전달하게 되므로 끈다.

  staleTime: 0 (기본값 유지)
    화면에 들어올 때마다 다시 확인한다. health는 캐시해서 좋을 값이 아니다.

  polling(refetchInterval)은 넣지 않았다. 주기적 확인이 필요한 제품 요구가
  아직 없고, 근거 없는 반복 호출을 만들지 않는다. 새로고침은 화면의 명시적인
  "다시 확인" 동작으로만 일어난다.
*/

import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from '@/features/health/api'

export const healthQueryKey = ['health'] as const

export function useHealthQuery() {
  return useQuery({
    queryKey: healthQueryKey,
    queryFn: ({ signal }) => fetchHealth(signal),
    retry: false,
  })
}
