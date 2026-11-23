import type { StoredAnswer, SynthesisResult } from '@/features/run-detail/api'

/*
  화면에 보일 AI 설명을 고르는 규칙 (개발판단기록 66장). useRunSynthesis가 쓴다.

    1. 기록에서 고른 버전   사용자가 고른 것이 가장 우선이다
    2. 방금 받은 응답       이 화면에서 요청한 것. 저장됐으면 그 버전과 연결한다
    3. 저장된 최신 버전     본문이 남아 있는 가장 높은 번호

  React와 네트워크 없이 시험할 수 있게 hook 밖에 둔다
  (scripts/synthesis-view.test.mjs).
*/

export type SynthesisSource = 'fresh' | 'stored'

export interface SynthesisViewInput {
  selectedVersion: number | null
  /** 이 화면에서 받은 응답. 없으면 undefined. */
  fresh: SynthesisResult | undefined
  /** 서버 목록의 latestVersion. 목록을 못 읽었으면 null. */
  latestVersion: number | null
}

export interface SynthesisViewChoice {
  /** 조회할 저장 버전. 저장본과 연결되지 않으면 null. */
  viewingVersion: number | null
  /** 화면이 쓸 응답의 출처. 저장본 쪽은 그 버전을 읽어야 결과가 생긴다. */
  prefer: 'fresh' | 'stored'
}

export function chooseSynthesisView({
  selectedVersion,
  fresh,
  latestVersion,
}: SynthesisViewInput): SynthesisViewChoice {
  if (selectedVersion !== null) return { viewingVersion: selectedVersion, prefer: 'stored' }
  if (fresh) return { viewingVersion: fresh.storedVersion ?? null, prefer: 'fresh' }
  return { viewingVersion: latestVersion, prefer: 'stored' }
}

/** 저장본을 화면이 쓰는 응답 모양으로. 본문이 지워졌거나 아직 없으면 undefined. */
export function storedAsResult(answer: StoredAnswer | undefined): SynthesisResult | undefined {
  if (!answer || answer.synthesis === null) return undefined
  return {
    available: true,
    synthesis: answer.synthesis,
    provenance: answer.provenance,
    errorCategory: null,
    errorMessage: null,
    storedVersion: answer.version,
  }
}
