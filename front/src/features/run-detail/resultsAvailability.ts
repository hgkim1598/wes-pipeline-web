/*
  결과 탭을 보여줄지, 어느 탭으로 시작할지.

  ── status로 판단하지 않는다 `[설계판단]` ───────────────────────────────

  "failed면 결과 탭을 숨긴다"는 규칙은 틀린다. 03_alignment에서 멈춘 실행과
  사전 점검에서 멈춘 실행은 둘 다 `failed`지만, 앞의 것은 정렬까지의 산출물이
  남아 있을 수 있고 뒤의 것은 아무것도 만들지 않는다. status는 "어떻게
  끝났는가"이지 "보여줄 결과가 있는가"가 아니다.

  그래서 응답이 실제로 무엇을 담고 있는지로 판단한다.

    409(NotReady)                        결과 문서 자체가 없다
    analysisOutputProduced === false     +  coverage·variantCalling 모두 없음
                                         → 측정값이 하나도 없다

  두 번째 조건에서 coverage/variantCalling을 함께 보는 것이 핵심이다.
  `analysisOutputProduced`만으로 끊으면, core가 완료되지 못했지만 커버리지까지는
  측정한 실행에서 실제로 있는 숫자를 숨기게 된다.

  ── 아직 끝나지 않은 실행 ───────────────────────────────────────────────

  숨기지 않는다. 결과는 "없는" 것이 아니라 "아직"이고, ResultsView가 그 문구를
  이미 구분해서 보여준다(CLAUDE.md 14장). 숨겼다가 완료 시점에 탭이 나타나면
  탭 줄이 흔들린다.
*/

import type { NotReady, Results } from '@/features/run-detail/api'
import { isNotReady } from '@/features/run-detail/api'

export const RUN_TABS = [
  { id: 'results', label: '결과' },
  { id: 'pipeline', label: '파이프라인' },
  { id: 'files', label: '파일' },
] as const

export type TabId = (typeof RUN_TABS)[number]['id']

/**
 * 결과 탭에 보여줄 것이 있는가.
 *
 * `undefined`는 "아직 모른다"이며 숨기지 않는다. 로딩 중에 탭이 사라졌다가
 * 다시 나타나는 것이 빈 탭보다 나쁘다.
 */
export function hasResultsContent(
  data: Results | NotReady | undefined,
  terminal: boolean,
): boolean {
  if (!terminal) return true
  if (data === undefined) return true
  // 결과 문서가 없다. precheck 실패 대부분이 여기에 해당한다.
  if (isNotReady(data)) return false
  if (data.analysisOutputProduced) return true
  // 산출물은 없지만 측정값이 남아 있을 수 있다. 있으면 보여준다.
  return data.coverage !== null || data.variantCalling !== null
}

/**
 * 처음 열었을 때 어느 탭인가.
 *
 * "탭을 보여줄까"와 "거기서 시작할까"는 다른 질문이다. 정렬까지 가고 실패한
 * 실행에는 커버리지가 남아 있어 결과 탭을 **보여주지만**, 그 사용자가 먼저
 * 묻는 것은 "무엇이 나왔나"가 아니라 "어디서 멈췄나"다. 그래서 시작 탭은
 * 산출물이 실제로 만들어진 실행에서만 결과다.
 *
 *   완료 + 산출물 있음   결과       "무엇이 나왔나"
 *   실패 (부분 결과 포함) 파이프라인  "어디서 멈췄나"
 *   진행 중 / queued     파이프라인  "어디까지 갔나"
 */
export function defaultTab(
  data: Results | NotReady | undefined,
  terminal: boolean,
): TabId {
  if (!terminal) return 'pipeline'
  if (data === undefined || isNotReady(data)) return 'pipeline'
  // 부분 결과가 있어도 산출물이 없으면 실패한 실행이다. 과정부터 보여준다.
  return data.analysisOutputProduced ? 'results' : 'pipeline'
}

/**
 * URL의 탭 세그먼트를 실제로 존재하는 탭으로 해석한다.
 *
 * `/runs/{id}/results`를 직접 열었는데 그 실행에 결과가 없을 수 있다 —
 * 링크를 공유했거나, 이전에 열어 둔 주소이거나. 그때 빈 패널을 그리지 않고
 * 존재하는 탭으로 접는다. 어느 탭도 유효하지 않은 경우는 없다(파이프라인과
 * 파일은 항상 있다).
 */
export function resolveTab(
  raw: string | undefined,
  data: Results | NotReady | undefined,
  terminal: boolean,
): TabId {
  const requested = RUN_TABS.find((tab) => tab.id === raw)?.id
  if (!requested) return defaultTab(data, terminal)
  if (requested === 'results' && !hasResultsContent(data, terminal)) {
    return 'pipeline'
  }
  return requested
}

/** 실제로 그릴 탭 목록. 결과가 없는 실행에서는 결과 탭이 빠진다. */
export function visibleTabs(
  data: Results | NotReady | undefined,
  terminal: boolean,
): readonly { id: TabId; label: string }[] {
  if (hasResultsContent(data, terminal)) return RUN_TABS
  return RUN_TABS.filter((tab) => tab.id !== 'results')
}
