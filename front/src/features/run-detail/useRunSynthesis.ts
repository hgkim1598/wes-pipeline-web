import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { createSynthesis } from '@/features/run-detail/api'
import type { SynthesisResult } from '@/features/run-detail/api'

/*
  AI 종합 설명 요청 — 한 페이지에 하나.

  이전에는 RunSynthesisPanel 안에 있었다. 이제 페이지가 가지고, 패널·상태
  줄·각 항목의 AI 해설이 **같은 응답 하나**를 읽는다. 위치마다 따로 요청하면
  서로 다른 답변이 한 화면에 섞인다.

  호출 정책은 그대로다(RunSynthesisPanel 머리말):
    - mutation이다. 누를 때만 실행되고 mount·focus로 스스로 실행되지 않는다.
    - 재시도하지 않는다. 사용량을 사용자 모르게 반복해서 쓰지 않는다.
    - 끝나면 문서 검색 목록을 다시 읽는다(GET, 모델 호출 아님).

  응답은 저장하지 않는다(서버 비저장 원칙). 이 페이지가 열려 있는 동안만
  있고, 새로고침하면 사라진다.

  ── 다른 Run으로 이동했을 때 ───────────────────────────────────────────

  `/runs/a` → `/runs/b`로 가도 같은 페이지 component가 재사용되어 mutation
  상태가 남는다. 요청한 jobId를 변수로 넘기고, 지금 jobId와 같을 때만
  결과로 내보낸다. 다른 Run의 설명이 이 Run 옆에 붙지 않게 한다.
*/

export interface RunSynthesisState {
  /** 이 Run에 대한 응답. 다른 Run의 응답이거나 아직 없으면 undefined. */
  result: SynthesisResult | undefined
  isPending: boolean
  /** 요청 자체가 실패(연결·HTTP·형식). 200 + available:false와 다르다. */
  error: unknown
  isError: boolean
  /** 이 요청을 시작한 시각(ms). 경과 시간 표시용 client 값이다. */
  startedAt: number | null
  request: () => void
}

export function useRunSynthesis(jobId: string): RunSynthesisState {
  /*
    시작 시각은 요청을 시작한 이벤트가 기록한다(effect 안 setState 금지,
    oxlint set-state-in-effect). RunSynthesisPanel에서 옮겨 왔다.
  */
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (id: string) => createSynthesis(id),
    onMutate: () => setStartedAt(Date.now()),
    retry: false,
    onSettled: (_data, _error, id) => {
      void queryClient.invalidateQueries({ queryKey: ['runs', id, 'doc-search'] })
    },
  })

  const mine = mutation.variables === jobId
  return {
    result: mine ? mutation.data : undefined,
    isPending: mine && mutation.isPending,
    error: mine ? mutation.error : null,
    isError: mine && mutation.isError,
    startedAt: mine ? startedAt : null,
    request: () => mutation.mutate(jobId),
  }
}
