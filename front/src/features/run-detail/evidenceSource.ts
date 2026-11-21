/*
  근거 id → 출처 종류 (실행 기록 · 공식 문서 · 등록된 지식).

  화면에서 "이 문장이 무엇에 기대는가"를 한눈에 구분하려고 쓴다. 기준은
  backend가 발급한 id의 prefix뿐이다(registries/evidence.ts 머리 주석).

    record     run · lim · step               이 Run이 남긴 기록에서 나온 것
    mixed      dx · fail                      이 Run의 기록 + 그 code의 일반 설명
    doc        doc · manual                    공식 문서 발췌·매뉴얼 구간
    knowledge  src · concept · term            저장소에 등록된 일반 지식
    other      그 밖의 prefix                  해석하지 않는다(raw로 보인다)

  `mixed`(2026-11-21): dx·fail id 하나가 이 실행의 관측(원문 message)과 그
  code의 일반 지식(meaning·grounding)을 함께 가리킨다. "이 Run의 기록"으로만
  세면 일반 설명에 기댄 문장이 관측처럼 읽힌다. id는 바꾸지 않고 표시만
  나눈다 — 일반 설명 중 이 실행에 해당하지 않는 문장은 backend가 모델 입력에서
  이미 뺐다(applicability.py).

  `doc`은 "이런 실패가 일반적으로 무엇을 뜻하는가"의 근거이지 이 Run에서 일어난
  일의 근거가 아니다. 그래서 record와 섞어 세지 않는다.

  React·import 없이 순수 함수로 둔다(node --test로 검증).
*/

export type EvidenceSource = 'record' | 'mixed' | 'doc' | 'knowledge' | 'other'

export const EVIDENCE_SOURCES: readonly EvidenceSource[] = [
  'record',
  'mixed',
  'doc',
  'knowledge',
  'other',
]

const BY_PREFIX: Record<string, EvidenceSource> = {
  run: 'record',
  dx: 'mixed',
  fail: 'mixed',
  lim: 'record',
  step: 'record',
  doc: 'doc',
  manual: 'doc',
  src: 'knowledge',
  concept: 'knowledge',
  term: 'knowledge',
}

export function evidenceSourceOf(ref: string): EvidenceSource {
  const separator = ref.indexOf(':')
  if (separator <= 0 || separator === ref.length - 1) return 'other'
  return BY_PREFIX[ref.slice(0, separator)] ?? 'other'
}

/** 출처별 건수. 같은 id를 두 번 인용해도 한 번만 센다. 건수 0인 출처는 빠진다. */
export function countEvidenceSources(
  refs: readonly string[],
): { source: EvidenceSource; count: number }[] {
  const counts = new Map<EvidenceSource, number>()
  for (const ref of new Set(refs)) {
    const source = evidenceSourceOf(ref)
    counts.set(source, (counts.get(source) ?? 0) + 1)
  }
  return EVIDENCE_SOURCES.filter((source) => counts.has(source)).map((source) => ({
    source,
    count: counts.get(source) ?? 0,
  }))
}

/** 공식 문서 영역의 결과와 대조할 수 있는 id인가(doc · manual). */
export function isDocEvidence(ref: string): boolean {
  return evidenceSourceOf(ref) === 'doc'
}
