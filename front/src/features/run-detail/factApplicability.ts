/*
  실행 사실(장부)과 설명 문장의 적용 판정을 화면 값으로 옮긴다 — 순수 함수만.

  ── 왜 (2026-11-21) ─────────────────────────────────────────────────────

  00_input_validation에서 멈춘 실행에서 MULTIQC_MISSING의 일반 설명
  "개별 FastQC 리포트는 정상적으로 생성되었습니다"가 화면에 보였다. 01_raw_qc는
  시작되지 않았다. 설명 문장은 code마다 하나로 쓰여 있어, 그 문장이 전제하는
  단계 실행을 이 실행의 기록과 대조한 곳이 없었다.

  backend가 대조한다(run_ledger.py · applicability.py). 이 모듈은 그 결과를
  받아 쓰기만 하고 다시 판정하지 않는다 — 규칙이 두 벌이 되지 않게.

  ── 단계 상태 ───────────────────────────────────────────────────────────

  장부가 있으면 장부가 이긴다. 끝난 실행의 pending을 "실행 안 됨"으로 쓰던
  예전 규칙(stepView.isNotRun)은 취소 시점에 진행 중이던 단계와 기록이 빠진
  단계까지 "실행 안 됨"으로 썼다. 장부는 그 둘을 `unknown`(판정 불가)으로 둔다.
  장부가 없는 응답(이전 backend)이면 예전 규칙을 그대로 쓴다.

  ── 보류된 문장 ─────────────────────────────────────────────────────────

  화면의 의미 문장은 registry(같은 knowledge 파일)에서, 영향 문장은 실행
  기록에서 온다. 판정은 explanation의 진단 순서(index)에 붙어 오므로, 그
  진단의 (단계, code)로 바꿔 /results 경로의 진단에도 붙인다.

  React·import 없이 둔다(node --test, scripts/fact-applicability.test.mjs).
*/

export interface LedgerStepLike {
  stepId: string
  execution: string
  basis: string
}

export interface ExplanationLike {
  diagnostics: { code: string; actualStepId: string | null }[]
  executionLedger?: { stepsKnown: boolean; steps: LedgerStepLike[] }
  knowledgeDecisions?: {
    section: string
    index: number
    part: string
    withheld: boolean
    reason: string | null
  }[]
}

// 상태 이름의 표시 해석(실행 안 됨 / 판정 불가)은 stepView.ts 한 곳에 있다.

export interface StepExecution {
  execution: string
  basis: string
}

/** stepId -> 장부의 실행 사실. 장부가 없거나 단계 목록이 없으면 빈 Map. */
export function executionByStep(
  explanation: ExplanationLike | undefined,
): Map<string, StepExecution> {
  const out = new Map<string, StepExecution>()
  const ledger = explanation?.executionLedger
  if (!ledger || !ledger.stepsKnown) return out
  for (const step of ledger.steps) {
    out.set(step.stepId, { execution: step.execution, basis: step.basis })
  }
  return out
}

/** 단계 목록에 장부 값을 붙인다. 장부에 없는 단계는 그대로 둔다. */
export function withLedger<T extends { stepId: string }>(
  steps: readonly T[],
  ledger: ReadonlyMap<string, StepExecution>,
): (T & { execution?: string; executionBasis?: string })[] {
  return steps.map((step) => {
    const fact = ledger.get(step.stepId)
    return fact ? { ...step, execution: fact.execution, executionBasis: fact.basis } : step
  })
}

export interface Withheld {
  /** 일반 설명(meaning)을 뺀 이유. */
  meaning?: string
  /** 파이프라인 고정 영향 문구를 뺀 이유. */
  impact?: string
}

const NO_REASON = '이 실행의 기록으로 확인되지 않습니다.'

export function occurrenceKey(stepId: string | null, code: string): string {
  return `${stepId ?? 'run'}|${code}`
}

/** "(단계)|(code)" -> 이 실행에서 뺀 문장과 이유. */
export function withheldByOccurrence(
  explanation: ExplanationLike | undefined,
): Map<string, Withheld> {
  const out = new Map<string, Withheld>()
  if (!explanation?.knowledgeDecisions) return out
  for (const d of explanation.knowledgeDecisions) {
    if (!d.withheld || d.section !== 'diagnostics') continue
    // 화면이 쓰는 두 부분만. grounding 문장은 화면에 없고, recordedMeaning은
    // 저장된 이전 문장이라 화면(registry의 현재 문장)과 관계없다.
    const field = d.part === 'meaning' ? 'meaning' : d.part === 'impact' ? 'impact' : null
    if (field === null) continue
    const item = explanation.diagnostics[d.index]
    if (!item) continue
    const key = occurrenceKey(item.actualStepId, item.code)
    const entry = out.get(key) ?? {}
    entry[field] = d.reason ?? NO_REASON
    out.set(key, entry)
  }
  return out
}

/** 진단 목록에 보류 정보를 붙인다. 붙일 것이 없으면 같은 객체를 돌려준다. */
export function applyWithheld<
  D extends { stepId: string | null; code: string },
  C extends { byStep: Map<string, D[]>; unattributed: D[]; all: D[] },
>(collection: C, withheld: ReadonlyMap<string, Withheld>): C {
  if (withheld.size === 0) return collection
  const mark = (d: D): D => {
    const found = withheld.get(occurrenceKey(d.stepId, d.code))
    return found ? { ...d, withheld: found } : d
  }
  const byStep = new Map<string, D[]>()
  for (const [stepId, items] of collection.byStep) byStep.set(stepId, items.map(mark))
  return {
    ...collection,
    byStep,
    unattributed: collection.unattributed.map(mark),
    all: collection.all.map(mark),
  }
}
