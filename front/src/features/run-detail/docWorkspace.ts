/*
  공식 문서 워크스페이스(목록 + 상세 패널)의 규칙 — 순수 함수만.

  1. 목록 순서(orderedHits)
     입력 순서(서버가 준 순서) → 같은 입력 안에서는 관계(등록 해설 → 같은 명령
     구간 → 다른 명령 구간 → 일반 구간 → 그 밖) → 순위. 화면이 순서를 새로
     매기지 않고 저장된 값으로만 정렬한다.

  2. 선택(resolveHit)
     URL의 `doc`(evidenceId)과 `input`(inputId)으로 찾는다. 같은 문서가 두
     입력에서 반환될 수 있어 inputId가 있으면 둘 다 맞는 것을 먼저 고른다.
     없으면 보이는 목록의 첫 문서.

  3. 검색 기록 고르기(runForEvidence)
     AI 설명의 근거에서 문서로 이동할 때, 지금 고른 검색 기록에 그 문서가
     없으면 그 문서를 가진 가장 최근 기록을 고른다. 어디에도 없으면 null —
     없는 문서를 있는 것처럼 고르지 않는다.

  4. 단계별 건수(stageCounts)
     검색 결과 → Agent 입력 후보 → 요청 입력 → 답변 인용. 그 단계 값이 모든
     문서에서 null이면 건수 대신 null(기록 없음)이다. 0건과 기록 없음을 섞지
     않는다. "모델이 읽음"은 어디에도 기록되지 않으므로 세지 않는다.

  React·import 없이 둔다(node --test, scripts/workspace-view.test.mjs).
*/

export interface HitLike {
  inputId: string
  evidenceId: string
  relation: string
  rank: number
  corpus: string
  usage: {
    returnedBySearch: boolean
    selectedForAgent: boolean | null
    inAgentInput: boolean | null
    citedInAnswer: boolean | null
  }
}

export const RELATION_ORDER: readonly string[] = [
  'filedUnderCauseKind',
  'sameCommandSection',
  'otherCommandSection',
  'generalSection',
  // 분류되지 않은 문장의 표현으로 추정한 종류의 해설(개발판단기록 62장). 가장 약한 관계라 마지막이다.
  'suggestedByWording',
]

function relationIndex(relation: string): number {
  const at = RELATION_ORDER.indexOf(relation)
  return at === -1 ? RELATION_ORDER.length : at
}

/** 목록에 쓰는 문서 하나의 키. 같은 evidenceId가 입력마다 다시 나올 수 있다. */
export function hitKey(hit: { inputId: string; corpus: string; rank: number }): string {
  return `${hit.inputId}|${hit.corpus}|${hit.rank}`
}

export function orderedHits<H extends HitLike>(
  inputIds: readonly string[],
  hits: readonly H[],
): H[] {
  const inputAt = (id: string) => {
    const at = inputIds.indexOf(id)
    return at === -1 ? inputIds.length : at
  }
  return hits
    .map((hit, original) => ({ hit, original }))
    .sort(
      (a, b) =>
        inputAt(a.hit.inputId) - inputAt(b.hit.inputId) ||
        relationIndex(a.hit.relation) - relationIndex(b.hit.relation) ||
        a.hit.rank - b.hit.rank ||
        a.original - b.original,
    )
    .map((entry) => entry.hit)
}

export function resolveHit<H extends HitLike>(
  hits: readonly H[],
  evidenceId: string | null,
  inputId: string | null,
): H | null {
  if (evidenceId) {
    const exact = inputId
      ? hits.find((h) => h.evidenceId === evidenceId && h.inputId === inputId)
      : undefined
    const byId = exact ?? hits.find((h) => h.evidenceId === evidenceId)
    if (byId) return byId
  }
  return hits[0] ?? null
}

export interface RunLike {
  searchId: string
  hits: readonly { evidenceId: string }[]
}

/** `runs`는 최신순. 고른 기록에 있으면 그대로, 아니면 가진 가장 최근 기록. */
export function runForEvidence(
  runs: readonly RunLike[],
  preferredSearchId: string | null,
  evidenceId: string,
): string | null {
  const preferred = runs.find((r) => r.searchId === preferredSearchId)
  if (preferred?.hits.some((h) => h.evidenceId === evidenceId)) return preferred.searchId
  return runs.find((r) => r.hits.some((h) => h.evidenceId === evidenceId))?.searchId ?? null
}

export interface StageCounts {
  returned: number
  candidate: number | null
  input: number | null
  cited: number | null
}

function countTrue(values: readonly (boolean | null)[]): number | null {
  if (values.length === 0 || values.every((v) => v === null)) return null
  return values.filter((v) => v === true).length
}

export function stageCounts(hits: readonly HitLike[]): StageCounts {
  return {
    returned: hits.filter((h) => h.usage.returnedBySearch).length,
    candidate: countTrue(hits.map((h) => h.usage.selectedForAgent)),
    input: countTrue(hits.map((h) => h.usage.inAgentInput)),
    cited: countTrue(hits.map((h) => h.usage.citedInAnswer)),
  }
}

/** 이 단계의 실패로 검색된 문서 수. 검색 기록이 없으면 null. */
export function hitsForStep(
  run: { inputs: readonly { inputId: string; stepId: string }[]; hits: readonly { inputId: string }[] } | undefined,
  stepId: string,
): number | null {
  if (!run) return null
  const ids = new Set(run.inputs.filter((i) => i.stepId === stepId).map((i) => i.inputId))
  return run.hits.filter((h) => ids.has(h.inputId)).length
}
