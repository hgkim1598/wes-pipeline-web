/*
  Diagnostic(진단 사건) — 화면 어휘.

  ── 이 파일이 소유하는 것 ───────────────────────────────────────────────

  **표시(presentation)뿐이다.**

    kind                      severity + resolution을 합친 표시용 한 축
    "자동 복구"/"확인 필요"/…   사용자에게 보이는 라벨

  진단의 **의미**(severity · resolution · title · meaning · relatedSteps ·
  status)는 이 파일에 없다. 저장소 최상위의

    config/knowledge/wes_diagnostics.json

  이 canonical source이고, backend도 같은 파일을 읽는다. 여기서
  severity나 resolution을 다시 상수로 적지 않는다 — 사본이 생기면
  `steps.ts`의 tool처럼 언젠가 어긋난다.

  로딩·검증은 registries/knowledge.ts가 맡는다.

  ── 두 축을 합치지 않는다 ──────────────────────────────────────────────

  severity(확인이 필요한가)와 resolution(파이프라인이 이미 해결했는가)은
  서로 다른 질문이다. NM_MD_REPAIRED는 "확인 불필요"이면서 동시에
  "복구 완료"이고, DBSNP_NOT_CONFIGURED는 "확인 불필요"이지만 복구할
  대상이 아니다. 하나의 enum으로 만들면 이 차이가 사라진다.

  두 축은 shared source에서 분리된 채로 오고, describeDiagnostic()이 표시
  직전에 한 번만 합친다. 사용자는 축이 둘이라는 사실을 몰라도 된다.

  ── severity 분류의 근거는 어디에 있나 ─────────────────────────────────

  각 code의 severity는 main.sh가 그 자리에 적어 둔 impact 문장을 근거로
  정했다. 그 판단 근거는 JSON에 주석을 달 수 없으므로
  local-context/WES_AI_DIAGNOSTIC_AGENT_CONTEXT.md에 보존한다. 예:

    DBSNP_NOT_CONFIGURED
      impact: "Variant records will carry no rsID; the calls themselves are
               unaffected"                              script/main.sh:3802
      → 분석 결과에 영향 없음 → info
*/

import type {
  DiagnosticKnowledge,
  DiagnosticResolution,
  DiagnosticSeverity,
} from '@/registries/knowledge'
import { diagnosticKnowledge } from '@/registries/knowledge'

export type { DiagnosticSeverity, DiagnosticResolution }

/**
 * 알 수 없는 code의 기본값.
 *
 * attention으로 둔다. 모르는 사건을 "참고"로 낮추면 실제 문제가 조용히
 * 묻힌다. 반대 방향의 실수(참고 사항이 확인 필요로 보이는 것)가 훨씬 낫다.
 *
 * title이 비어 있으면 호출부가 backend의 원문 message를 제목 자리에 쓴다 —
 * 의미를 지어내지 않고, 최소한 서버가 말한 것은 보여준다.
 */
const UNKNOWN: DiagnosticKnowledge = {
  code: '',
  severity: 'attention',
  resolution: null,
  relatedSteps: [],
  status: 'active',
  title: '',
  meaning: '',
}

/** 사용자에게 보이는 한 가지 구분. 위 두 축을 여기서 한 번만 합친다. */
export type DiagnosticKind = 'repaired' | 'attention' | 'note' | 'failure'

export interface DiagnosticView {
  severity: DiagnosticSeverity
  resolution: DiagnosticResolution
  title: string
  meaning: string
  kind: DiagnosticKind
  /** "자동 복구" · "확인 필요" · "참고" · "실패". 색 없이도 읽히는 유일한 단서. */
  label: string
}

const KIND_LABEL: Record<DiagnosticKind, string> = {
  repaired: '자동 복구',
  attention: '확인 필요',
  note: '참고',
  failure: '실패',
}

function toView(knowledge: DiagnosticKnowledge): DiagnosticView {
  const kind: DiagnosticKind =
    knowledge.resolution === 'repaired'
      ? 'repaired'
      : knowledge.severity === 'attention'
        ? 'attention'
        : 'note'
  return {
    severity: knowledge.severity,
    resolution: knowledge.resolution,
    title: knowledge.title,
    meaning: knowledge.meaning,
    kind,
    label: KIND_LABEL[kind],
  }
}

/**
 * code -> 표시 어휘.
 *
 * shared knowledge에 없는 code도 화면을 세우지 않는다.
 */
export function describeDiagnostic(code: string): DiagnosticView {
  return toView(diagnosticKnowledge(code) ?? UNKNOWN)
}

/** 실패는 knowledge를 거치지 않는다. code와 무관하게 항상 실패다. */
export function describeFailure(): DiagnosticView {
  return {
    severity: 'attention',
    resolution: null,
    title: '',
    meaning: '',
    kind: 'failure',
    label: KIND_LABEL.failure,
  }
}
