import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createSynthesis,
  deleteSynthesisAnswer,
  getSynthesisAnswer,
  listSynthesisAnswers,
} from '@/features/run-detail/api'
import type {
  StoredAnswer,
  StoredAnswerList,
  SynthesisResult,
} from '@/features/run-detail/api'
import { chooseSynthesisView, storedAsResult } from '@/features/run-detail/synthesisView'
import type { SynthesisSource } from '@/features/run-detail/synthesisView'

export type { SynthesisSource }

/*
  AI 종합 설명 요청 — 한 페이지에 하나.

  이전에는 RunSynthesisPanel 안에 있었다. 이제 페이지가 가지고, 패널·상태
  줄·각 항목의 AI 해설이 **같은 응답 하나**를 읽는다. 위치마다 따로 요청하면
  서로 다른 답변이 한 화면에 섞인다.

  호출 정책은 그대로다(RunSynthesisPanel 머리말):
    - mutation이다. 누를 때만 실행되고 mount·focus로 스스로 실행되지 않는다.
    - 재시도하지 않는다. 사용량을 사용자 모르게 반복해서 쓰지 않는다.
    - 끝나면 문서 검색 목록과 저장된 설명 목록을 다시 읽는다(GET, 모델 호출 아님).

  ── 저장된 설명 (개발판단기록 66장) ─────────────────────────────────────

  서버가 저장을 켜 두었으면(WES_SYNTHESIS_STORE_ANSWERS=1) 게이트를 통과한
  설명이 Run마다 v1, v2…로 남는다. 화면에 보이는 설명을 고르는 순서는
  synthesisView.ts에 있다(고른 버전 > 방금 받은 응답 > 저장된 최신 버전).

  목록과 버전 조회는 GET이고 모델을 부르지 않는다. 저장이 꺼진 서버는
  `storing: false`와 빈 목록을 주고, 그때는 예전처럼 화면에만 있다.

  ── 다른 Run으로 이동했을 때 ───────────────────────────────────────────

  `/runs/a` → `/runs/b`로 가도 같은 페이지 component가 재사용되어 mutation
  상태가 남는다. 요청한 jobId를 변수로 넘기고, 지금 jobId와 같을 때만
  결과로 내보낸다. 고른 버전도 jobId와 함께 기억해 다른 Run에 붙지 않게 한다.
*/

export interface SynthesisHistory {
  /** 저장 목록. 아직 못 읽었거나 실패하면 undefined. */
  list: StoredAnswerList | undefined
  listError: unknown
  /** 화면의 설명에 해당하는 저장 버전 번호. 저장본과 연결되지 않으면 null. */
  viewingVersion: number | null
  viewing: StoredAnswer | undefined
  viewingError: unknown
  /** 사용자가 기록에서 직접 고른 버전. 고르지 않았으면 null(= 기본 순서). */
  selectedVersion: number | null
  select: (version: number | null) => void
  remove: (version: number) => void
  /** 지우는 중인 버전. */
  removing: number | null
  removeError: unknown
}

export interface RunSynthesisState {
  /** 화면에 보일 설명. 이 Run의 것이 아니거나 아직 없으면 undefined. */
  result: SynthesisResult | undefined
  source: SynthesisSource | null
  isPending: boolean
  /** 요청 자체가 실패(연결·HTTP·형식). 200 + available:false와 다르다. */
  error: unknown
  isError: boolean
  /** 이 요청을 시작한 시각(ms). 경과 시간 표시용 client 값이다. */
  startedAt: number | null
  request: () => void
  history: SynthesisHistory
}

export function useRunSynthesis(jobId: string): RunSynthesisState {
  /*
    시작 시각은 요청을 시작한 이벤트가 기록한다(effect 안 setState 금지,
    oxlint set-state-in-effect). RunSynthesisPanel에서 옮겨 왔다.
  */
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [selection, setSelection] = useState<{ jobId: string; version: number } | null>(null)
  const queryClient = useQueryClient()
  const answersKey = ['runs', jobId, 'synthesis-answers'] as const

  const mutation = useMutation({
    mutationFn: (id: string) => createSynthesis(id),
    onMutate: () => {
      setStartedAt(Date.now())
      // 새로 요청하면 고른 버전을 놓고 방금 받을 응답을 본다.
      setSelection(null)
    },
    retry: false,
    onSettled: (_data, _error, id) => {
      void queryClient.invalidateQueries({ queryKey: ['runs', id, 'doc-search'] })
      void queryClient.invalidateQueries({ queryKey: ['runs', id, 'synthesis-answers'] })
    },
  })

  const list = useQuery({
    queryKey: answersKey,
    queryFn: ({ signal }) => listSynthesisAnswers(jobId, signal),
  })

  const mine = mutation.variables === jobId
  const fresh = mine ? mutation.data : undefined
  const selectedVersion = selection?.jobId === jobId ? selection.version : null
  const { viewingVersion, prefer } = chooseSynthesisView({
    selectedVersion,
    fresh,
    latestVersion: list.data?.latestVersion ?? null,
  })

  const viewing = useQuery({
    queryKey: [...answersKey, viewingVersion],
    queryFn: ({ signal }) => getSynthesisAnswer(jobId, viewingVersion ?? 0, signal),
    enabled: viewingVersion !== null,
  })
  const viewingAnswer = viewingVersion !== null ? viewing.data : undefined

  const removal = useMutation({
    mutationFn: (version: number) => deleteSynthesisAnswer(jobId, version),
    retry: false,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: answersKey })
    },
  })

  const result: SynthesisResult | undefined =
    prefer === 'fresh' ? fresh : storedAsResult(viewingAnswer)
  const source: SynthesisSource | null = result ? prefer : null

  return {
    result,
    source,
    isPending: mine && mutation.isPending,
    error: mine ? mutation.error : null,
    isError: mine && mutation.isError,
    startedAt: mine ? startedAt : null,
    request: () => mutation.mutate(jobId),
    history: {
      list: list.data,
      listError: list.error,
      viewingVersion,
      viewing: viewingAnswer,
      viewingError: viewingVersion !== null ? viewing.error : null,
      selectedVersion,
      select: (version) => setSelection(version === null ? null : { jobId, version }),
      remove: (version) => removal.mutate(version),
      removing: removal.isPending ? (removal.variables ?? null) : null,
      removeError: removal.error,
    },
  }
}
