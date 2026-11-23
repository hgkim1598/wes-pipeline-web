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

  언제 멈추고, 끝나는 순간 무엇을 다시 읽고, 404·일시적 실패를 어떻게 보는지는
  runDetailPolicy.ts(순수 함수, 테스트 있음)가 정한다. 여기서는 그 결정을
  react-query 옵션으로 옮기기만 한다. 딸린 query는 상세가 정한 RunPhase를
  받는다 — 각자 status 문자열을 해석하지 않는다.
*/

import { useEffect, useRef } from 'react'
import type { Query } from '@tanstack/react-query'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import type { JobState } from '@/features/run-detail/api'
import {
  fetchArtifacts,
  fetchExplanation,
  fetchJobState,
  fetchResults,
  fetchStepDetail,
} from '@/features/run-detail/api'
import type { RunPhase } from '@/features/run-detail/runDetailPolicy'
import {
  dependentEnabled,
  dependentInterval,
  detailInterval,
  justSettled,
  runPhase,
  shouldRetryDetail,
} from '@/features/run-detail/runDetailPolicy'
import { isStepRunning } from '@/features/run-detail/stepStatus'
import { isTerminalStatus } from '@/features/runs/status'
import { runListQueryKey } from '@/features/runs/useRunListQuery'

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

/** 실패의 HTTP status. ApiError가 아니거나 HTTP 응답이 없었으면 null. */
export function errorStatusOf(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null
}

/** 상세 query의 현재 값으로 RunPhase를 정한다. 페이지와 refetchInterval이 같이 쓴다. */
export function phaseOf(job: JobState | undefined, error: unknown): RunPhase {
  return runPhase({
    status: job?.status,
    terminal: job ? isTerminalStatus(job.status) : false,
    errorStatus: errorStatusOf(error),
  })
}

/**
 * Job 상세 + 3초 polling.
 *
 * refetchInterval을 함수로 주는 것이 핵심이다. 값으로 주면 terminal에 도달한
 * 뒤에도 다음 렌더까지 한 번 더 요청하고, 상태가 바뀌는 순간을 화면이 스스로
 * 판단하지 못한다. 404(없는 실행)도 멈춘다.
 *
 * retry: 404가 아니면 1회 — 목록(retry:false)과 다르다. 폴링 중 한 번의 실패로
 * 화면 전체를 오류로 바꾸지 않는다. 받은 값이 있으면 페이지는 그 값을 남기고
 * PollingStatus가 "연결 끊김 · 마지막 성공 시각 기준"을 계속 보여 준다.
 */
export function useJobDetailQuery(jobId: string) {
  return useQuery({
    queryKey: runDetailKey(jobId),
    queryFn: ({ signal }) => fetchJobState(jobId, signal),
    retry: (failureCount, error) => shouldRetryDetail(failureCount, errorStatusOf(error)),
    refetchInterval: (query: Query<JobState>) =>
      detailInterval(phaseOf(query.state.data, query.state.error), DETAIL_INTERVAL_MS),
  })
}

/**
 * 실행이 방금 끝나면(active → terminal) 딸린 query를 한 번 다시 읽는다.
 *
 * 설명·산출물·단계 상세는 terminal을 본 렌더에서 폴링을 멈추므로, 마지막
 * 응답은 끝나기 전의 것이다(runDetailPolicy.justSettled). 상세 자신은 방금
 * 받았으므로 제외하고, 목록의 상태 배지도 함께 갱신한다.
 */
export function useRefreshOnSettle(jobId: string, phase: RunPhase) {
  const queryClient = useQueryClient()
  const previous = useRef<{ jobId: string; phase: RunPhase }>({ jobId, phase })
  useEffect(() => {
    const before = previous.current
    previous.current = { jobId, phase }
    if (before.jobId !== jobId || !justSettled(before.phase, phase)) return
    void queryClient.invalidateQueries({
      queryKey: runDetailKey(jobId),
      predicate: (query) => query.queryKey.length > runDetailKey(jobId).length,
    })
    /*
      exact: 목록 key ['runs']는 모든 Run query의 앞부분이라, exact 없이 무효화하면
      방금 받은 상세(['runs', jobId])와 다른 Run의 query까지 다시 읽었다
      (2026-11-23 리뷰). 목록 하나만 다시 읽는다.
    */
    void queryClient.invalidateQueries({ queryKey: runListQueryKey, exact: true })
  }, [jobId, phase, queryClient])
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
    /*
      단계 상태가 key에 들어간다. 단계가 끝나는 순간(running → completed ·
      failed) 폴링은 멈추는데, 마지막 응답은 끝나기 전의 것이다. 상태가 바뀌면
      key가 바뀌어 끝난 뒤의 문서를 새로 읽는다. 앞부분이 stepDetailKey 그대로라
      prefix 무효화(useRefreshOnSettle)도 그대로 닿는다.
    */
    queryKey: [...stepDetailKey(jobId, stepId ?? ''), stepStatus ?? null] as const,
    queryFn: ({ signal }) => fetchStepDetail(jobId, stepId as string, signal),
    enabled: stepId !== null,
    retry: 1,
    // 같은 단계의 상태만 바뀐 경우 새 응답이 올 때까지 앞 값을 보여 준다.
    // 다른 단계로 옮긴 경우에는 남기지 않는다 — 엉뚱한 단계의 내용이 된다.
    // 다른 Run의 같은 단계도 마찬가지다: 페이지는 :jobId가 바뀌어도 다시 마운트되지
    // 않으므로 jobId까지 같아야 앞 값을 쓴다(2026-11-23 리뷰).
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === jobId && previousQuery.queryKey[3] === stepId
        ? previous
        : undefined,
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
export function useResultsQuery(jobId: string, phase: RunPhase) {
  return useQuery({
    queryKey: resultsKey(jobId),
    queryFn: ({ signal }) => fetchResults(jobId, signal),
    enabled: phase === 'terminal',
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
export function useArtifactsQuery(jobId: string, phase: RunPhase) {
  return useQuery({
    queryKey: artifactsKey(jobId),
    queryFn: ({ signal }) => fetchArtifacts(jobId, signal),
    enabled: dependentEnabled(phase),
    retry: false,
    refetchInterval: dependentInterval(phase, ARTIFACTS_INTERVAL_MS),
  })
}

/**
 * 결정적 실행 설명.
 *
 * /results와 달리 **실패한 실행에서도 200**이므로 enabled 조건을 두지 않는다.
 * 오히려 실패한 실행이 이 응답이 가장 필요한 경우다 — /results가 409라
 * 다른 출처가 없다.
 *
 * 실행 중에는 진단이 늘어날 수 있으므로 job 상세와 같은 주기로 따라가고,
 * terminal에 도달하면 멈춘다(끝나는 순간의 마지막 갱신은 useRefreshOnSettle).
 * 서버 계산은 파일 읽기뿐이라 LLM 호출 같은 비용이 없다.
 */
export const explanationKey = (jobId: string) =>
  ['runs', jobId, 'explanation'] as const

export function useExplanationQuery(jobId: string, phase: RunPhase) {
  return useQuery({
    queryKey: explanationKey(jobId),
    queryFn: ({ signal }) => fetchExplanation(jobId, signal),
    enabled: dependentEnabled(phase),
    retry: 1,
    refetchInterval: dependentInterval(phase, DETAIL_INTERVAL_MS),
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
