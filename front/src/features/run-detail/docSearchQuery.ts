import { useQuery } from '@tanstack/react-query'

import { fetchDocSearches } from '@/features/run-detail/api'
import { runDetailKey } from '@/features/run-detail/queries'

/*
  공식 문서 검색 기록(GET, 모델 호출 없음, polling 없음).

  공식 문서 탭과 파이프라인 상세 패널("이 단계의 실패로 검색된 문서 n건")이
  같은 기록을 읽는다. 같은 query key라 요청은 한 번이다. AI 설명 요청이 끝나면
  useRunSynthesis가 이 key를 무효화한다(['runs', id, 'doc-search']).
*/
export const docSearchKey = (jobId: string) => [...runDetailKey(jobId), 'doc-search'] as const

export function useDocSearchHistory(jobId: string) {
  return useQuery({
    queryKey: docSearchKey(jobId),
    queryFn: ({ signal }) => fetchDocSearches(jobId, signal),
    staleTime: Infinity,
  })
}
