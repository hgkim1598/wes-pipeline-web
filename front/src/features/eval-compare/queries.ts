/*
  A/B 비교 화면의 query. 저장된 결과만 읽으므로 polling하지 않는다.
  retry: false — 기능이 꺼진 서버(404)를 몇 초 동안 "불러오는 중"으로 보이지 않게.
*/

import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api/client'

import { fetchBlind, fetchCall, fetchExperiment, fetchExperiments, fetchPayloads } from './api'

export const evalCompareKey = ['eval-compare'] as const

export function useExperiments() {
  return useQuery({
    queryKey: [...evalCompareKey, 'list'],
    queryFn: ({ signal }) => fetchExperiments(signal),
    retry: false,
  })
}

/**
 * 사이드바 항목: 이 서버가 비교 기능을 켰는가. 꺼져 있거나 다른 PC면(404)
 * 항목을 그리지 않는다. 토큰이 없거나(401) 서버에 토큰이 설정되지 않은(503)
 * 경우는 기능이 있는 것이므로 항목을 그리고, 화면에서 토큰을 묻는다.
 */
export function useEvalCompareAvailable(): boolean {
  const query = useQuery({
    queryKey: [...evalCompareKey, 'list'],
    queryFn: ({ signal }) => fetchExperiments(signal),
    retry: false,
    staleTime: 60_000,
  })
  const status = query.error instanceof ApiError ? query.error.status : undefined
  return query.isSuccess || status === 401 || status === 503
}

export function useExperiment(id: string) {
  return useQuery({
    queryKey: [...evalCompareKey, id],
    queryFn: ({ signal }) => fetchExperiment(id, signal),
    retry: false,
  })
}

export function useCall(id: string, callId: string | null) {
  return useQuery({
    queryKey: [...evalCompareKey, id, 'call', callId],
    queryFn: ({ signal }) => fetchCall(id, callId as string, signal),
    enabled: callId !== null,
    retry: false,
  })
}

export function usePayloads(id: string, caseName: string, enabled: boolean) {
  return useQuery({
    queryKey: [...evalCompareKey, id, 'payloads', caseName],
    queryFn: ({ signal }) => fetchPayloads(id, caseName, signal),
    enabled,
    retry: false,
  })
}

export function useBlind(id: string) {
  return useQuery({
    queryKey: [...evalCompareKey, id, 'blind'],
    queryFn: ({ signal }) => fetchBlind(id, signal),
    retry: false,
  })
}
