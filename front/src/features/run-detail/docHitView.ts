/*
  공식 문서 구획의 표시 규칙 — 순수 함수만 (DocEvidenceSection).

  1. 문서 하나의 사용 단계(usageStages)
     저장된 usage 값을 단계별 표시 값으로 옮긴다. 값의 문구는 이전 화면
     (UsageLine)과 같다: 예 · 아니오 · 기록 없음 · 확인됨 · 확인 불가.
     null을 "아니오"로 바꾸지 않는다 — 기록이 없다는 것과 아니라는 것은 다르다.

  2. 결과 거르기(filterHits)
     전체 · 요청 입력에 포함 · 답변 인용 확인. 값이 true인 것만 남긴다.
     화면이 고르는 것이지 데이터를 바꾸는 것이 아니다.

  3. 입력 나누기(splitInputs)
     반환된 문서가 있는 입력과 없는 입력. 각 쪽은 원래 순서를 지킨다.

  React·import 없이 둔다(node --test, scripts/doc-hit-view.test.mjs).
*/

export interface UsageLike {
  returnedBySearch: boolean
  selectedForAgent: boolean | null
  inAgentInput: boolean | null
  readByModel: boolean | null
  citedInAnswer: boolean | null
}

/** yes: 그 단계에 도달함 · no: 도달하지 않음 · none: 기록 없음/확인 불가 */
export type StageState = 'yes' | 'no' | 'none'

export interface UsageStage {
  key: 'returned' | 'candidate' | 'input' | 'read' | 'cited'
  label: string
  value: string
  state: StageState
}

function yesNo(value: boolean | null): { value: string; state: StageState } {
  if (value === null) return { value: '기록 없음', state: 'none' }
  return value ? { value: '예', state: 'yes' } : { value: '아니오', state: 'no' }
}

/**
 * 문서 하나가 어느 단계까지 기록되었는가.
 *
 * `hasAgentRequest`: 이 검색이 AI 설명 요청과 연결되어 있는가. 요청이 있었는데
 * 인용 값이 null이면 "답변이 없거나 거부되어 확인할 수 없음"이므로 "확인 불가",
 * 요청이 없으면 "기록 없음"이다.
 */
export function usageStages(usage: UsageLike, hasAgentRequest: boolean): UsageStage[] {
  const cited: { value: string; state: StageState } =
    usage.citedInAnswer === null
      ? { value: hasAgentRequest ? '확인 불가' : '기록 없음', state: 'none' }
      : usage.citedInAnswer
        ? { value: '확인됨', state: 'yes' }
        : { value: '아니오', state: 'no' }
  return [
    {
      key: 'returned',
      label: '검색 결과에 나타남',
      ...(usage.returnedBySearch
        ? { value: '예', state: 'yes' as const }
        : { value: '아니오', state: 'no' as const }),
    },
    { key: 'candidate', label: 'Agent 입력 후보', ...yesNo(usage.selectedForAgent) },
    { key: 'input', label: '요청 입력에 포함', ...yesNo(usage.inAgentInput) },
    { key: 'read', label: '모델이 읽음', ...yesNo(usage.readByModel) },
    { key: 'cited', label: '답변 인용', ...cited },
  ]
}

export type HitFilter = 'all' | 'inAgentInput' | 'cited'

export function filterHits<H extends { usage: UsageLike }>(
  hits: readonly H[],
  filter: HitFilter,
): H[] {
  if (filter === 'inAgentInput') return hits.filter((hit) => hit.usage.inAgentInput === true)
  if (filter === 'cited') return hits.filter((hit) => hit.usage.citedInAnswer === true)
  return [...hits]
}

export function hitFilterCounts(hits: readonly { usage: UsageLike }[]): Record<HitFilter, number> {
  return {
    all: hits.length,
    inAgentInput: filterHits(hits, 'inAgentInput').length,
    cited: filterHits(hits, 'cited').length,
  }
}

export function splitInputs<I extends { inputId: string }>(
  inputs: readonly I[],
  hitCount: (inputId: string) => number,
): { withHits: I[]; withoutHits: I[] } {
  const withHits: I[] = []
  const withoutHits: I[] = []
  for (const input of inputs) {
    if (hitCount(input.inputId) > 0) withHits.push(input)
    else withoutHits.push(input)
  }
  return { withHits, withoutHits }
}
