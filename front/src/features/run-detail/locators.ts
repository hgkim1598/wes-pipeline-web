/*
  AI 설명 문장 안의 내부 locator를 사람이 읽는 이름으로.

  ── 무엇이 문제인가 ─────────────────────────────────────────────────────

  shared knowledge의 `grounding.checks[].locator`는 `{kind, id}`이고, backend가
  prompt에 `look_at: "metric:markdup_validation"` 형태로 넣는다. 모델은 그
  문자열을 자기 문장에 그대로 인용한다. 실제 출력:

      "metric:markdup_validation에서 NM/MD 보정 전 ValidateSamFile 분류 결과를..."

  사용자에게 `metric:`은 아무 의미가 없다.

  ── 이름을 지어내지 않는다 `[설계판단]` ─────────────────────────────────

  regex로 그럴듯한 한국어를 만들어 붙이지 않는다. **id가 실제 source에서
  해석될 때만** 바꾼다.

      artifact:<kind>          이 실행의 artifact displayName (/artifacts 응답)
      stepFile:<stepId>/<file> 단계 이름 (wes_steps.json) + 파일명
      metric:<id>              해석할 source가 없다 → 그대로 둔다
      check:<id>               해석할 source가 없다 → 그대로 둔다

  `metric`과 `check`는 파이프라인 내부 식별자이고 어느 canonical 파일에도
  사람이 읽는 이름이 없다. 여기서 사전을 새로 만들면 그것은 knowledge를
  frontend에 하드코딩하는 일이 되고, main.sh가 이름을 바꾸면 조용히 어긋난다.
  **번역할 수 없는 것은 원문 그대로 두는 편이 낫다** — 사용자가 로그·문서와
  대조할 수는 있다.

  ── 문장을 다시 쓰지 않는다 ─────────────────────────────────────────────

  모델의 문장 구조는 건드리지 않는다. **정확히 일치하는 토큰만** 치환한다.
  치환 전 원문은 호출부가 기술 정보에 그대로 보존한다.
*/

import { stepKnowledge } from '@/registries/knowledge'

/** kind 접두사가 붙은 locator 토큰. 공백·한글 조사 앞에서 끊긴다. */
const LOCATOR_TOKEN = /\b(artifact|stepFile|metric|check):([A-Za-z0-9_./-]+)/g

export interface LocatorResolver {
  /** artifact kind -> displayName. 이 실행의 /artifacts 응답에서 만든다. */
  artifactLabels: Map<string, string>
}

/**
 * 하나의 locator 토큰을 사람이 읽는 이름으로. 해석할 수 없으면 null.
 *
 * null은 실패가 아니라 정상적인 답이다 — 호출부는 원문을 그대로 남긴다.
 */
export function resolveLocator(
  kind: string,
  id: string,
  resolver: LocatorResolver,
): string | null {
  if (kind === 'artifact') {
    return resolver.artifactLabels.get(id) ?? null
  }
  if (kind === 'stepFile') {
    const slash = id.indexOf('/')
    if (slash < 0) return null
    const step = stepKnowledge(id.slice(0, slash))
    if (!step) return null
    // 단계 이름 + 파일명. 경로 전체를 그대로 쓰면 다시 기술 표현이 된다.
    const file = id.slice(slash + 1).split('/').pop()
    return file ? `${step.label} 단계의 ${file}` : step.label
  }
  // metric · check: 해석할 canonical source가 없다.
  return null
}

/**
 * 문장 안의 알려진 locator 토큰만 사람 말로 바꾼 문자열.
 *
 * 바뀐 것이 없으면 입력과 동일한 문자열이 돌아온다 — 호출부가 그것으로
 * "치환이 일어났는지"를 판단할 수 있다.
 */
export function humanizeLocators(
  statement: string,
  resolver: LocatorResolver,
): string {
  return statement.replace(LOCATOR_TOKEN, (whole, kind: string, id: string) => {
    const label = resolveLocator(kind, id, resolver)
    return label ?? whole
  })
}

/**
 * 응답의 artifact 목록에서 kind -> displayName 표를 만든다.
 *
 * `/artifacts`는 아직 준비되지 않았을 때 409(NotReady)를 준다. 그때는 빈
 * 표이고, 치환이 일어나지 않아 원문이 그대로 남는다 — 정상 동작이다.
 */
export function artifactLabelMap(
  data: { artifacts: { kind: string; displayName: string }[] } | undefined,
): Map<string, string> {
  const map = new Map<string, string>()
  for (const artifact of data?.artifacts ?? []) {
    // 같은 kind가 여러 건일 수 있다(FastQC R1/R2). 먼저 온 것을 대표로 쓴다.
    if (!map.has(artifact.kind)) map.set(artifact.kind, artifact.displayName)
  }
  return map
}
