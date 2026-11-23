/*
  실패 카드의 "다음 행동" 목록 (2026-11-23, 개발판단기록 53장).

  다크 Overview 시안(ref 1)은 "핵심 문제 · 근거 · 다음 행동"을 서로 다른 블록으로
  나눈다. 이전 실패 카드는 준비 안내 버튼이 실패 설명 바로 밑에 붙어 있어서
  "무엇이 잘못됐나"와 "무엇을 하면 되나"가 한 덩어리로 읽혔다.

  다음 행동은 **이 실행의 기록에서만** 만든다. 시안의 "재실행"·"로그 내보내기"
  같은 버튼은 backend에 없는 기능이라 만들지 않는다.

    1. 준비 안내   등록된 실패 code의 helpPath(registries/failures.ts). 같은
                  경로는 한 번만.
    2. 근거 보기   실패가 귀속된 단계(actualStepId)의 파이프라인 상세. 같은
                  단계는 한 번만. 귀속 단계가 없으면 만들지 않는다.

  React·경로 별칭을 쓰지 않는다: scripts/run-detail-copy.test.mjs가 node로
  직접 읽는다. code → helpPath 해석은 호출하는 쪽이 넘긴다.
*/

export type NextAction =
  | { kind: 'help'; path: string; label: string }
  | { kind: 'step'; stepId: string }

export interface FailureRef {
  code: string
  actualStepId: string | null
}

/** 준비 안내 경로의 버튼 이름. 경로의 조각(#tools)이 무엇을 안내하는지 말한다. */
export function helpPathLabel(path: string): string {
  return path.endsWith('#tools') ? '프로그램 준비 방법 보기' : '참조 데이터 준비 방법 보기'
}

export function nextActions(
  failures: readonly FailureRef[],
  helpPathOf: (code: string) => string | undefined,
): NextAction[] {
  const help: NextAction[] = []
  const steps: NextAction[] = []
  const seenPaths = new Set<string>()
  const seenSteps = new Set<string>()
  for (const failure of failures) {
    const path = helpPathOf(failure.code)
    if (path && !seenPaths.has(path)) {
      seenPaths.add(path)
      help.push({ kind: 'help', path, label: helpPathLabel(path) })
    }
    if (failure.actualStepId && !seenSteps.has(failure.actualStepId)) {
      seenSteps.add(failure.actualStepId)
      steps.push({ kind: 'step', stepId: failure.actualStepId })
    }
  }
  // 고칠 방법이 먼저, 기록을 더 보는 것이 그다음이다.
  return [...help, ...steps]
}
