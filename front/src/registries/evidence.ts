/*
  evidenceRef id → 사람이 읽는 이름.

  ── id는 어디서 오나 ────────────────────────────────────────────────────

  backend가 AI에게 payload를 만들면서 발급한다
  (`services/explanation/llm/contract.py build_payload`). 모델은 이 문자열만
  인용할 수 있고, 인용한 id가 발급되지 않은 것이면 응답 전체가 폐기된다.
  즉 여기 도착하는 id는 **backend가 실제로 준 것**이다.

    dx:<code>        이번 실행이 낸 진단
    fail:<code>      이번 실행이 낸 실패
    lim:<code>       결정론적 범위 제한
    src:<id>         인용된 출처
    concept:<id>     해석 개념
    run:<section>    실행 자체의 사실 (status · checkSummary · coverage 등)

  ── 이름을 지어내지 않는다 `[설계판단]` ─────────────────────────────────

  각 prefix의 이름은 **이미 있는 canonical source**에서 가져온다.

    dx      wes_diagnostics.json  title
    fail    wes_failures.json     title
    src     wes_sources.json      title
    concept wes_concepts.json     label

  `lim:`과 `run:`만 이 파일이 이름을 갖는다. 그 둘은 knowledge 파일의 항목이
  아니라 **payload의 구획 이름**이어서 canonical source가 존재하지 않는다.
  backend가 그 구획을 만들 때 쓴 이름을 그대로 옮긴 것이며, 새로운 도메인
  지식이 아니다.

  등록되지 않은 id는 **번역하지 않는다.** `known: false`로 돌려주고 호출부가
  raw id를 그대로 보여준다 — 억지로 그럴듯한 이름을 만들면 사용자가 근거를
  대조할 수 없게 된다.
*/

import {
  conceptKnowledge,
  diagnosticKnowledge,
  failureKnowledge,
  sourceKnowledge,
} from '@/registries/knowledge'

export interface EvidenceView {
  /** 사람이 읽는 이름. `known`이 false면 raw id가 그대로 들어온다. */
  label: string
  /** 어떤 종류의 근거인가. 목록에서 묶어 보여줄 때 쓴다. */
  group: '이 실행의 기록' | '등록된 지식' | '참고 자료' | '알 수 없음'
  known: boolean
  /** 항상 원본 id. 기술 정보에서 그대로 보여준다. */
  id: string
}

/*
  payload 구획 이름. backend build_payload가 만든 구획과 1:1이다.
  새 구획이 생기면 여기 없는 id가 도착하고, 그때는 raw로 표시된다.
*/
const RUN_SECTION_LABEL: Record<string, string> = {
  status: '이 실행의 상태',
  checkSummary: '검증 결과 요약',
  coverage: '커버리지 측정값',
  variantCalling: '변이 검출 결과',
  intendedUse: '결과의 사용 범위',
}

/* 결정론적 limitation code. backend deterministic._limitations와 짝이다. */
const LIMITATION_LABEL: Record<string, string> = {
  NO_ANALYSIS_OUTPUT: '분석 산출물이 없다는 기록',
  UNFILTERED_VARIANTS: '변이에 필터가 적용되지 않았다는 기록',
  MEDIAN_NOT_MEASURED: '깊이 중앙값을 측정하지 않았다는 기록',
  INTENDED_USE: '결과의 사용 범위',
  RUN_IN_PROGRESS: '실행이 끝나지 않았다는 기록',
}

export function describeEvidenceRef(ref: string): EvidenceView {
  const separator = ref.indexOf(':')
  if (separator < 0) return unknown(ref)

  const prefix = ref.slice(0, separator)
  const key = ref.slice(separator + 1)

  switch (prefix) {
    case 'dx': {
      const entry = diagnosticKnowledge(key)
      return entry
        ? { label: entry.title, group: '등록된 지식', known: true, id: ref }
        : unknown(ref)
    }
    case 'fail': {
      const entry = failureKnowledge(key)
      return entry
        ? { label: entry.title, group: '등록된 지식', known: true, id: ref }
        : unknown(ref)
    }
    case 'concept': {
      const entry = conceptKnowledge(key)
      return entry
        ? { label: entry.label, group: '등록된 지식', known: true, id: ref }
        : unknown(ref)
    }
    case 'src': {
      const entry = sourceKnowledge(key)
      return entry
        ? { label: entry.title, group: '참고 자료', known: true, id: ref }
        : unknown(ref)
    }
    case 'lim': {
      const label = LIMITATION_LABEL[key]
      return label
        ? { label, group: '이 실행의 기록', known: true, id: ref }
        : unknown(ref)
    }
    case 'run': {
      const label = RUN_SECTION_LABEL[key]
      return label
        ? { label, group: '이 실행의 기록', known: true, id: ref }
        : unknown(ref)
    }
    default:
      return unknown(ref)
  }
}

function unknown(ref: string): EvidenceView {
  return { label: ref, group: '알 수 없음', known: false, id: ref }
}
