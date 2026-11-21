/*
  AI 종합 설명 패널과 각 항목 옆 AI 해설이 함께 쓰는 값.

  component 파일에서 상수·함수를 함께 export하면 fast refresh가 그 파일을
  다시 불러야 해서 여기로 모았다.
*/

import { humanizeLocators } from '@/features/run-detail/locators'
import type { LocatorResolver } from '@/features/run-detail/locators'
import type { PlacedStatement } from '@/features/run-detail/synthesisPlacement'

/** 상태 줄의 "전체 설명으로" 이동 대상. */
export const SYNTHESIS_PANEL_ID = 'ai-synthesis-panel'

/** 패널 안 문장 하나의 id. 각 항목의 AI 해설이 이 id로 이동한다. */
export function statementAnchorId(number: number): string {
  return `ai-statement-${number}`
}

/*
  backend가 모델의 응답을 받은 뒤 검사에서 거부한 category.

  backend/app/services/explanation/llm/synthesis.py의 검사 단계 이름이며,
  backend 테스트(test_every_error_category_has_a_curated_message)의 domain
  집합과 같다. 사용자 문구는 여기서 만들지 않는다 — 제목만 "모델을 쓸 수
  없었다"와 "모델이 쓴 설명을 버렸다"로 구분한다. 모르는 category는 일반
  제목으로 간다.
*/
export const GATE_REJECTIONS: ReadonlySet<string> = new Set([
  'invalidSynthesis',
  'unknownEvidenceRef',
  'unsupportedNumber',
  'internalFieldName',
  'runFactMismatch',
  'evidenceMismatch',
  'sensitiveOutput',
  'docEvidenceMisuse',
])

/**
 * 각 항목 옆 AI 해설이 패널과 **같은 문자열**을 보이게 한다. 패널은
 * nextChecks에만 locator 치환을 하므로(FoldSection) 같은 규칙을 쓴다.
 */
export function shownStatement(item: PlacedStatement, locators: LocatorResolver): string {
  return item.group === 'nextChecks'
    ? humanizeLocators(item.statement, locators)
    : item.statement
}

/**
 * AI 설명 탭의 그 문장으로 이동한다(접힌 묶음은 연다).
 *
 * AI 설명은 2026-11-20부터 탭이라 지금 화면에 없을 수 있다. 요청만 알리고
 * 페이지(RunDetailPage)가 `/ai`로 옮긴 뒤 그 문장을 보여 준다.
 */
export function revealStatement(number: number): void {
  window.dispatchEvent(new CustomEvent<number>(OPEN_STATEMENT_EVENT, { detail: number }))
}

/** AI 설명 탭에서 이 문장을 보여 달라는 요청(detail: 문장 번호). */
export const OPEN_STATEMENT_EVENT = 'wes:open-statement'

/** 공식 문서 탭의 상세 패널 id(DocEvidenceSection). AI 근거에서 이동해 오는 대상. */
export const DOC_DETAIL_PANEL_ID = 'doc-detail-panel'

/**
 * AI 문장의 근거(doc:·manual:)를 공식 문서 탭에서 연다.
 *
 * 공식 문서는 탭이라(2026-11-20) 지금 화면에 없을 수 있다. 그래서 요청만
 * 알리고, 페이지(RunDetailPage)가 `/docs?doc=<id>`로 이동한다. 탭은 그 문서를
 * 가진 검색 기록을 고르고 거르기를 풀어 상세 패널에 연다. 어느 기록에도 없으면
 * "이 문서가 검색 기록에 없습니다"라고 말한다 — 없는 결과를 있는 것처럼
 * 강조하지 않는다.
 */
export function revealDocEvidence(evidenceId: string): void {
  window.dispatchEvent(new CustomEvent<string>(OPEN_DOC_EVIDENCE_EVENT, { detail: evidenceId }))
}

/** 공식 문서 탭에서 이 근거를 열어 달라는 요청(detail: evidenceId). */
export const OPEN_DOC_EVIDENCE_EVENT = 'wes:open-doc-evidence'

/**
 * 요소로 이동한다. 접힌 묶음(details) 안에 있으면 먼저 연다 — 닫힌 details
 * 안의 요소로는 스크롤해도 보이지 않는다. 대상이 details면 그것도 연다.
 */
export function revealElement(target: HTMLElement | null, block: ScrollLogicalPosition): void {
  if (!target) return
  let node: HTMLElement | null = target
  while (node) {
    if (node instanceof HTMLDetailsElement) node.open = true
    node = node.parentElement
  }
  target.scrollIntoView({ block })
  target.focus({ preventScroll: true })
}
