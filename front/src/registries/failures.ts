/*
  실패 code → 화면 어휘.

  ── 이 파일이 더 이상 소유하지 않는 것 ─────────────────────────────────

  title·meaning은 여기 있었다. 지금은 `config/knowledge/wes_failures.json`에
  있고 이 파일은 그것을 읽는다.

  옮긴 이유는 소비자가 둘이 됐기 때문이다. 다음 단계의 설명 계층은 backend에
  있고, 같은 실패를 설명하려면 같은 문장이 필요하다. 여기 남겨 두면 backend가
  두 번째 사본을 만들게 되고, 그것은 `steps.ts`의 tool metadata가 실제
  파이프라인과 갈라졌던 것과 정확히 같은 결함이다.

  ── 여기 남은 것 ───────────────────────────────────────────────────────

  `helpPath`뿐이다. 앱 내부 route는 화면의 사정이고 backend에는 의미가 없다.
  shared knowledge에 넣으면 knowledge가 frontend 라우팅을 알게 된다.

  ── 닫힌 집합이 아니다 ─────────────────────────────────────────────────

  main.sh는 일부 failure code를 실행 값으로 조립한다 — 관찰된 것 중에
  `sort_order_DEMO_WES.L001`, `alignment_${unit}`이 있다. 그래서 진단 code처럼
  전수 등록이 불가능하고, 미등록 code는 결함이 아니라 정상이다.
  그때는 backend가 준 원문을 그대로 보여준다.

  ── 근거 ────────────────────────────────────────────────────────────────

  두 code 모두 main.sh의 리터럴 문자열이다.

    required_tools    script/main.sh  step_check_fail "required_tools"
    resource_bundle   script/main.sh  step_check_fail "resource_bundle"

  각 문장의 출처는 shared knowledge의 evidence.sourceIds가 갖고 있고,
  backend loader가 그 id들이 실제로 존재하는지 검증한다.
*/

import { failureKnowledge } from '@/registries/knowledge'

/**
 * 준비 안내 페이지의 해당 절. 확실히 연결되는 것만 둔다.
 * 없으면 화면에 "해결 방법" 링크를 그리지 않는다.
 */
const HELP_PATH: Record<string, string> = {
  required_tools: '/help/setup#tools',
  resource_bundle: '/help/setup#resources',
}

export interface FailureView {
  /** 등록된 code인가. false면 title·meaning을 읽지 말 것. */
  known: boolean
  /** 한 줄 제목. 사용자가 먼저 읽는 문장이다. */
  title: string
  /** 이 검사가 무엇을 확인했는지. 원인 추론이 아니다. */
  meaning: string
  helpPath?: string
}

/**
 * code -> 표시 어휘.
 *
 * 미등록 code는 `known: false`로 돌려주고 title·meaning을 비운다.
 * 호출부는 그때 backend가 준 원문을 제목 자리에 쓴다 — 의미를 지어내지 않고,
 * 최소한 서버가 말한 것은 보여준다.
 */
export function describeFailureCode(code: string): FailureView {
  const entry = failureKnowledge(code)
  if (!entry) return { known: false, title: '', meaning: '' }
  return {
    known: true,
    title: entry.title,
    meaning: entry.meaning,
    helpPath: HELP_PATH[code],
  }
}
