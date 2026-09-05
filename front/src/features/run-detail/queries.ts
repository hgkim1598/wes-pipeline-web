/*
  Run 상세의 query 정책 한 곳.

  polling 간격과 정지 조건을 화면마다 흩어 두면 어떤 화면은 영원히 서버를
  두드리고 어떤 화면은 너무 일찍 멈춘다. 그래서 네 query의 정책을 이 파일에 모은다.

  query key는 계층적이다. ['runs']가 목록의 key이므로(features/runs/useRunListQuery)
  ['runs', jobId]는 그 prefix 아래에 들어가고, invalidateQueries({queryKey:['runs']})
  하나로 목록과 상세를 함께 무효화할 수 있다. 기존 key를 바꾸지 않았다.

  SSE를 쓰지 않는 이유: GET /api/jobs/{id}/stream은 의도적으로 404이고
  (backend/app/api/jobs.py job_stream), backend에 이벤트 소스가 없다. main.sh가
  파일에 상태를 쓰고 backend가 읽는 구조라 polling이 계약과 일치한다. 나중에
  바뀌어도 교체 지점은 이 파일 하나다.
*/

import { useQuery } from '@tanstack/react-query'

import type { JobState } from '@/features/run-detail/api'
import {
  fetchArtifacts,
  fetchJobState,
  fetchResults,
  fetchStepDetail,
} from '@/features/run-detail/api'
import { isStepRunning } from '@/features/run-detail/stepStatus'
import { isTerminalStatus } from '@/features/runs/status'

/** 실행 중 job 상세. CLAUDE.md 13장과 시안의 "3초 폴링". */
const DETAIL_INTERVAL_MS = 3000

/**
 * 산출물은 더 느리게 본다. 실행 중에도 개수가 늘긴 하지만(CLAUDE.md 14장)
 * 3초마다 확인해야 할 값은 아니고, artifact_reader가 매번 매니페스트와
 * 파일 시스템을 읽는다.
 */
const ARTIFACTS_INTERVAL_MS = 10000

export const runDetailKey = (jobId: string) => ['runs', jobId] as const
export const stepDetailKey = (jobId: string, stepId: string) =>
  ['runs', jobId, 'steps', stepId] as const
export const resultsKey = (jobId: string) => ['runs', jobId, 'results'] as const
export const artifactsKey = (jobId: string) =>
  ['runs', jobId, 'artifacts'] as const

/**
 * Job 상세 + 3초 polling.
 *
 * refetchInterval을 함수로 주는 것이 핵심이다. 값으로 주면 terminal에 도달한
 * 뒤에도 다음 렌더까지 한 번 더 요청하고, 상태가 바뀌는 순간을 화면이 스스로
 * 판단하지 못한다.
 *
 * retry: 1 — 목록(retry:false)과 다르다. 폴링 중 한 번의 실패로 화면 전체를
 * 오류로 바꾸는 것은 과하다. 실패가 이어지면 PollingStatus가 "연결 끊김"으로
 * 알리고 마지막 성공 데이터는 남는다.
 */
export function useJobDetailQuery(jobId: string) {
  return useQuery({
    queryKey: runDetailKey(jobId),
    queryFn: ({ signal }) => fetchJobState(jobId, signal),
    retry: 1,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === undefined) return DETAIL_INTERVAL_MS
      return isTerminalStatus(status) ? false : DETAIL_INTERVAL_MS
    },
  })
}

/**
 * 선택한 단계의 상세.
 *
 * enabled로 감싼 이유: 이 endpoint는 step 문서 + metrics + artifacts를 읽으므로
 * (backend/app/api/steps.py의 설명) 열지도 않은 단계까지 미리 받을 이유가 없다.
 *
 * 끝난 단계의 문서는 더 이상 바뀌지 않으므로 polling하지 않는다. 실행 중인
 * 단계만 3초로 따라간다.
 */
export function useStepDetailQuery(
  jobId: string,
  stepId: string | null,
  stepStatus: string | undefined,
) {
  return useQuery({
    queryKey: stepDetailKey(jobId, stepId ?? ''),
    queryFn: ({ signal }) => fetchStepDetail(jobId, stepId as string, signal),
    enabled: stepId !== null,
    retry: 1,
    refetchInterval:
      stepStatus !== undefined && isStepRunning(stepStatus)
        ? DETAIL_INTERVAL_MS
        : false,
  })
}

/**
 * 결과.
 *
 * 실행이 끝나기 전에는 409(아직 준비되지 않음)가 정상 응답이다. 그것을 반복
 * 요청하지 않도록 terminal일 때만 enabled로 둔다. 실행 중에는 화면이 "결과는
 * 실행이 끝나면 제공됩니다"를 보여준다 — 오류가 아니다.
 *
 * staleTime을 길게 두는 이유: terminal 이후 결과 문서는 변하지 않는다.
 */
export function useResultsQuery(jobId: string, jobStatus: string | undefined) {
  const terminal = jobStatus !== undefined && isTerminalStatus(jobStatus)
  return useQuery({
    queryKey: resultsKey(jobId),
    queryFn: ({ signal }) => fetchResults(jobId, signal),
    enabled: terminal,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

/**
 * 산출물.
 *
 * 결과와 달리 실행 중에도 조회한다. CLAUDE.md 14장이 "실행 중 artifact 개수는
 * /artifacts 응답을 기준으로" 하라고 정했고, 실제로 단계가 끝날 때마다 늘어난다.
 * 아직 아무것도 없으면 409가 오고, 그것도 정상 상태로 다룬다.
 */
export function useArtifactsQuery(jobId: string, jobStatus: string | undefined) {
  const terminal = jobStatus !== undefined && isTerminalStatus(jobStatus)
  return useQuery({
    queryKey: artifactsKey(jobId),
    queryFn: ({ signal }) => fetchArtifacts(jobId, signal),
    retry: false,
    refetchInterval: terminal ? false : ARTIFACTS_INTERVAL_MS,
  })
}

/** 상세 응답에서 한 단계의 상태를 찾는다. 없으면 undefined. */
export function findStepStatus(
  job: JobState | undefined,
  stepId: string | null,
): string | undefined {
  if (!job || !stepId) return undefined
  return job.steps.find((step) => step.stepId === stepId)?.status
}
