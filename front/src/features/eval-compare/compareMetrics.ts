/*
  A/B 비교 지표 집계 — 순수 함수(node --test로 검증, scripts/eval-compare.test.mjs).

  판정은 backend가 한다
  - 호출 결과(served / gateRejected / providerError / unclassified)와 "무엇에
    세어지는가"(countsForGate · countsForContent · exclusion)는 backend가
    evals/ab_compare/contract.py로 정해 보낸다. 여기서는 그 값을 세기만 한다.
    record.available 같은 원본 값으로 다시 판정하지 않는다 — 첫 판에서 그렇게
    해서 provider 시간 초과가 "Gate 거부"로 집계됐다.

  규칙
  - 분자와 분모를 함께 돌려준다. 빠진 호출은 이유별로 센다(excluded).
  - 자동(고정 문형 검출)과 사람 채점을 다른 값으로 둔다.
  - 채점이 없으면 "미평가"다. 0으로 채우지 않는다. 일부만 있으면 "부분"이다.
  - 내용 지표의 단위는 "모델이 낸 답변"이다(Gate가 거부한 답변 포함).
  - Gate 지표의 분모는 "답변을 받은 호출"이다. provider 실패는 Gate 판정이
    아니므로 분자에도 분모에도 넣지 않고 따로 센다. 응답 시간도 답변을 받은
    호출만 쓴다(시간 초과 300초가 중앙값에 섞이지 않게).
  - 블라인드 해제 전에는 사람 채점을 집계하지 않는다(backend가 보내지도 않는다).
  - 모의 실험은 성공 기준을 판정하지 않는다.
  - 반복 몇 번의 결과다. 통계적 유의성 판정을 만들지 않는다.
*/

import type { CallSummary, Criterion, Exclusion, ExperimentDetail, Grade } from './api'

export type Arm = 'A' | 'B'
export type MetricStatus = 'measured' | 'partial' | 'unmeasured'

export interface MetricValue {
  status: MetricStatus
  /** 합계·중앙값·비율. 미평가면 null. */
  value: number | null
  numerator: number | null
  denominator: number | null
  /** 이 값이 몇 개 답변·호출에서 나왔는가. */
  basis: number
  /** 계획대로 모두 있었다면의 basis. */
  expected: number
  unit: string
  /** 미평가·부분인 이유를 사람이 읽을 말로. */
  note?: string
}

export type ExclusionCounts = Record<Exclusion | 'notRecorded', number>

export interface ArmMetrics {
  planned: number
  /** 답변을 받은 호출(served + gateRejected, 제외 사유 없음). */
  answered: number
  /** 채점·자동 점수를 낼 답변 텍스트가 있는 호출. */
  contentAnswers: number
  excluded: ExclusionCounts
  auto: Record<'nonRunClaims' | 'execContradictions' | 'requiredCauses' | 'wrongCauses', MetricValue>
  human: Record<
    'nonRunClaims' | 'execContradictions' | 'supportedClaims' | 'requiredCauses' | 'wrongCauses' | 'understanding' | 'usefulness',
    MetricValue
  >
  exact: Record<'gateRejected' | 'latency' | 'providerErrors', MetricValue>
  /** 사람 채점: 판단 불가로 표시된 주장 수(분모에는 들어가고 분자에는 들어가지 않는다). */
  undeterminedClaims: number | null
  /** 블라인드 해제 뒤에 저장된 채점 수. */
  nonBlindGrades: number
}

export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/** 모델이 낸 답변의 자동 점수: 제공된 답변, 없으면 Gate가 거부한 답변. */
export function answerScoresOf(call: Pick<CallSummary, 'scores'>) {
  if (call.scores.served.measured) return call.scores.served
  if (call.scores.rejected.measured) return call.scores.rejected
  return null
}

function value(
  status: MetricStatus,
  v: number | null,
  basis: number,
  expected: number,
  unit: string,
  numerator: number | null = v,
  denominator: number | null = null,
  note?: string,
): MetricValue {
  return { status, value: v, numerator, denominator, basis, expected, unit, ...(note ? { note } : {}) }
}

function statusOf(basis: number, expected: number): MetricStatus {
  if (basis === 0 || expected === 0) return 'unmeasured'
  return basis < expected ? 'partial' : 'measured'
}

export function callsFor(detail: ExperimentDetail, arm: Arm, caseName: string | null): CallSummary[] {
  return detail.calls.filter((c) => c.arm === arm && (caseName === null || c.case === caseName))
}

export const EXCLUSION_LABEL: Record<keyof ExclusionCounts, string> = {
  notRecorded: '아직 결과 없음',
  providerError: 'provider 실패',
  unclassified: '분류 불가',
  privacy: '식별자 검사 걸림',
  integrity: '사후 무결성 실패',
  integrityUnchecked: '사후 무결성 미확인(이전 형식)',
}

export function exclusionSummary(excluded: ExclusionCounts): string {
  return (Object.keys(EXCLUSION_LABEL) as (keyof ExclusionCounts)[])
    .filter((k) => excluded[k] > 0)
    .map((k) => `${EXCLUSION_LABEL[k]} ${excluded[k]}`)
    .join(' · ')
}

export function armMetrics(detail: ExperimentDetail, arm: Arm, caseName: string | null): ArmMetrics {
  const calls = callsFor(detail, arm, caseName)
  const planItems = detail.plan.filter((p) => p.arm === arm && (caseName === null || p.case === caseName))
  const planned = planItems.length
  const byId = new Map(calls.map((c) => [c.callId, c]))

  const excluded: ExclusionCounts = {
    notRecorded: 0,
    providerError: 0,
    unclassified: 0,
    privacy: 0,
    integrity: 0,
    integrityUnchecked: 0,
  }
  for (const item of planItems) {
    const call = byId.get(item.callId)
    if (item.state !== 'recorded' || !call) excluded.notRecorded++
    else if (call.evaluation.exclusion) excluded[call.evaluation.exclusion]++
  }
  const gateCalls = calls.filter((c) => c.evaluation.countsForGate)
  const content = calls
    .filter((c) => c.evaluation.countsForContent)
    .map((c) => ({ call: c, s: answerScoresOf(c) }))
    .filter((x): x is { call: CallSummary; s: NonNullable<ReturnType<typeof answerScoresOf>> } => x.s !== null)
  const nContent = content.length
  const missing = exclusionSummary(excluded)

  const sum = (pick: (s: (typeof content)[number]['s']) => number) => content.reduce((acc, x) => acc + pick(x.s), 0)
  const autoStatus = statusOf(nContent, planned)
  const autoNote = autoStatus === 'measured' ? undefined : missing || undefined
  const auto = {
    nonRunClaims: value(autoStatus, nContent ? sum((s) => s.nonRunClaims ?? 0) : null, nContent, planned, '건', undefined, null, autoNote),
    execContradictions: value(autoStatus, nContent ? sum((s) => s.execContradictions ?? 0) : null, nContent, planned, '건', undefined, null, autoNote),
    requiredCauses: nContent
      ? value(
          autoStatus,
          sum((s) => s.requiredCauses?.mentioned ?? 0),
          nContent,
          planned,
          '개',
          sum((s) => s.requiredCauses?.mentioned ?? 0),
          sum((s) => s.requiredCauses?.required ?? 0),
          autoNote,
        )
      : value('unmeasured', null, 0, planned, '개', null, null, autoNote),
    wrongCauses: value(autoStatus, nContent ? sum((s) => s.wrongCauseCandidates?.length ?? 0) : null, nContent, planned, '건', undefined, null, autoNote),
  }

  // --- 사람 채점 (blind code로 묶인다; 해제 전에는 backend가 보내지 않는다) ---
  const blindNote = detail.blind.unblinded ? undefined : '블라인드 채점 중 — 해제 후 집계'
  const graded = (detail.blind.unblinded ? content : [])
    .map((x) => ({ ...x, g: x.call.blindCode ? (detail.grades[x.call.blindCode] as Grade | undefined) : undefined }))
    .filter((x): x is typeof x & { g: Grade } => x.g !== undefined)
  const nGraded = graded.length
  const hStatus = statusOf(nGraded, planned)
  const hNote = blindNote ?? (hStatus === 'measured' ? undefined : missing || undefined)
  const flagSum = (key: 'nonRunClaim' | 'execContradiction' | 'unsupportedCause') =>
    graded.reduce((acc, x) => acc + x.g.claims.filter((c) => c[key]).length, 0)
  const judged = graded.flatMap((x) => x.g.claims.filter((c) => c.verdict !== null))
  const supported = judged.filter((c) => c.verdict === 'supported').length
  const undetermined = judged.filter((c) => c.verdict === 'undetermined').length
  // "선택 안 함"(null)은 판정하지 않은 것이다. 분모에서 빼고, 못 말한 것으로 세지 않는다.
  const causeAnswers = graded.map((x) => Object.values(x.g.requiredCauses).filter((v) => v !== null))
  const causeTrue = causeAnswers.reduce((acc, v) => acc + v.filter((x) => x === true).length, 0)
  const causeTotal = causeAnswers.reduce((acc, v) => acc + v.length, 0)
  const scoreValue = (key: 'understanding' | 'usefulness') => {
    const xs = graded.map((x) => x.g[key]).filter((v): v is number => typeof v === 'number')
    return value(statusOf(xs.length, planned), median(xs), xs.length, planned, '점 (중앙값)', null, null, hNote)
  }
  const human = {
    nonRunClaims: value(hStatus, nGraded ? flagSum('nonRunClaim') : null, nGraded, planned, '건', undefined, null, hNote),
    execContradictions: value(hStatus, nGraded ? flagSum('execContradiction') : null, nGraded, planned, '건', undefined, null, hNote),
    supportedClaims: judged.length
      ? value(hStatus, supported / judged.length, nGraded, planned, '비율', supported, judged.length, hNote)
      : value('unmeasured', null, nGraded, planned, '비율', null, null, hNote),
    requiredCauses: causeTotal
      ? value(hStatus, causeTrue, nGraded, planned, '개', causeTrue, causeTotal, hNote)
      : value('unmeasured', null, 0, planned, '개', null, null, hNote),
    wrongCauses: value(hStatus, nGraded ? flagSum('unsupportedCause') : null, nGraded, planned, '건', undefined, null, hNote),
    understanding: scoreValue('understanding'),
    usefulness: scoreValue('usefulness'),
  }

  // --- 정확히 잰 값 ---
  const nGate = gateCalls.length
  const gateStatus = statusOf(nGate, planned)
  const gateNote = gateStatus === 'measured' ? undefined : missing || undefined
  const rejected = gateCalls.filter((c) => c.evaluation.outcome === 'gateRejected').length
  const durations = gateCalls.map((c) => c.durationMs).filter((v): v is number => typeof v === 'number')
  const providerErrors = calls.filter((c) => c.evaluation.outcome === 'providerError').length
  const recorded = calls.length
  const exact = {
    gateRejected: nGate
      ? value(gateStatus, rejected / nGate, nGate, planned, '비율', rejected, nGate, gateNote)
      : value('unmeasured', null, 0, planned, '비율', null, null, gateNote),
    latency: value(statusOf(durations.length, planned), median(durations), durations.length, planned, 'ms (중앙값)', null, null, gateNote),
    providerErrors: recorded
      ? value(statusOf(recorded, planned), providerErrors, recorded, planned, '회', providerErrors, recorded)
      : value('unmeasured', null, 0, planned, '회', null, null),
  }

  return {
    planned,
    answered: nGate,
    contentAnswers: nContent,
    excluded,
    auto,
    human,
    exact,
    undeterminedClaims: judged.length ? undetermined : null,
    nonBlindGrades: graded.filter((x) => x.g.blind === false).length,
  }
}

/** 두 경로가 실제로 받은 모델 ID. 별칭(sonnet)이 같다고 같은 모델로 보지 않는다. */
export function modelsByArm(detail: ExperimentDetail): { A: string[]; B: string[]; differ: boolean } {
  const of = (arm: Arm) =>
    [...new Set(detail.calls.filter((c) => c.arm === arm && c.evaluation.countsForGate).flatMap((c) => c.models ?? []))].sort()
  const A = of('A')
  const B = of('B')
  return { A, B, differ: A.length > 0 && B.length > 0 && A.join('|') !== B.join('|') }
}

// --- 사전 고정 성공 기준 ---------------------------------------------------

export type CriterionStatus = 'met' | 'notMet' | 'unmeasured' | 'mock'

export interface CriterionResult {
  criterion: Criterion
  status: CriterionStatus
  reason: string
}

function metricFor(m: ArmMetrics, c: Criterion): MetricValue | null {
  const key = c.metric
  if (key === 'gateRejected' || key === 'latency' || key === 'providerErrors') return m.exact[key]
  if (c.source === 'human' && key in m.human) return m.human[key as keyof ArmMetrics['human']]
  if (c.source === 'auto' && key in m.auto) return m.auto[key as keyof ArmMetrics['auto']]
  return null
}

/**
 * 프로토콜 규칙 문자열을 그대로 해석한다. 아는 형태만 계산하고, 모르는 형태는
 * 미평가로 둔다(새 규칙을 추측해서 판정하지 않는다).
 *
 * 판정 전제(프로토콜 evaluationRule): 계획한 모든 호출이 답변을 받았고 제외
 * 사유가 없어야 한다. provider 실패·불확실·제외 호출이 하나라도 있으면 어떤
 * 기준도 판정하지 않는다.
 */
export function evaluateCriteria(detail: ExperimentDetail): CriterionResult[] {
  if (detail.mock) {
    return detail.protocol.successCriteria.map((criterion) => ({
      criterion,
      status: 'mock',
      reason: '모의 실험 — 모델 답변이 아니므로 판정하지 않습니다.',
    }))
  }
  const a = armMetrics(detail, 'A', null)
  const b = armMetrics(detail, 'B', null)
  const planned = a.planned + b.planned
  const answered = a.answered + b.answered
  const incomplete =
    answered < planned
      ? `계획 ${planned}회 중 답변 ${answered}회 (${exclusionSummary(sumExcluded(a.excluded, b.excluded))}). 모든 호출이 답변을 받아야 판정합니다.`
      : null
  return detail.protocol.successCriteria.map((criterion) => {
    if (incomplete) return { criterion, status: 'unmeasured', reason: incomplete }
    if (criterion.source === 'human' && !detail.blind.unblinded) {
      return { criterion, status: 'unmeasured', reason: '블라인드 채점을 마치고 해제한 뒤 판정합니다.' }
    }
    const ma = metricFor(a, criterion)
    const mb = metricFor(b, criterion)
    if (!ma || !mb) return { criterion, status: 'unmeasured', reason: '이 지표를 계산할 수 없습니다.' }
    if (ma.status !== 'measured' || mb.status !== 'measured' || ma.value === null || mb.value === null) {
      const why = criterion.source === 'human' ? '모든 답변의 사람 채점이 끝나야 판정합니다.' : '모든 답변의 자동 점수가 있어야 판정합니다.'
      return { criterion, status: 'unmeasured', reason: why }
    }
    const A = ma.value
    const B = mb.value
    let ok: boolean | null = null
    switch (criterion.rule) {
      case 'B_total == 0':
        ok = B === 0
        break
      case 'B_total <= A_total':
        ok = B <= A
        break
      case 'B_total >= A_total':
        ok = B >= A
        break
      case 'B_rate >= A_rate - 0.05':
        ok = B >= A - 0.05
        break
      case 'B_rate <= A_rate':
        ok = B <= A
        break
      case 'B_median >= A_median - 0.5':
        ok = B >= A - 0.5
        break
      case 'B_median < A_median * 1.2':
        ok = B < A * 1.2
        break
    }
    if (ok === null) return { criterion, status: 'unmeasured', reason: `해석하지 않는 규칙: ${criterion.rule}` }
    const nonBlind = criterion.source === 'human' && a.nonBlindGrades + b.nonBlindGrades > 0
    const suffix = nonBlind ? ` · 블라인드 해제 뒤 채점 ${a.nonBlindGrades + b.nonBlindGrades}건 포함` : ''
    return { criterion, status: ok ? 'met' : 'notMet', reason: `A ${describe(ma)} · B ${describe(mb)}${suffix}` }
  })
}

function sumExcluded(a: ExclusionCounts, b: ExclusionCounts): ExclusionCounts {
  const out = { ...a }
  for (const key of Object.keys(out) as (keyof ExclusionCounts)[]) out[key] = a[key] + b[key]
  return out
}

function describe(v: MetricValue): string {
  if (v.value === null) return '—'
  if (v.unit === '비율' && v.numerator !== null && v.denominator !== null) {
    return `${v.numerator}/${v.denominator} (${Math.round(v.value * 100)}%)`
  }
  return formatNumber(v.value)
}

export function formatNumber(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

// --- 모델 입력(payload) 줄 단위 차이 ------------------------------------------

export interface DiffLine {
  kind: 'same' | 'add' | 'del'
  text: string
}

/** LCS 기반 줄 차이. payload는 수백 줄이라 O(n·m)으로 충분하다. */
export function lineDiff(a: readonly string[], b: readonly string[]): DiffLine[] {
  const n = a.length
  const m = b.length
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i] })
      i++
      j++
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      out.push({ kind: 'del', text: a[i++] })
    } else {
      out.push({ kind: 'add', text: b[j++] })
    }
  }
  while (i < n) out.push({ kind: 'del', text: a[i++] })
  while (j < m) out.push({ kind: 'add', text: b[j++] })
  return out
}

export type DiffChunk = { kind: 'lines'; lines: DiffLine[] } | { kind: 'skip'; count: number }

/** 바뀐 줄 앞뒤 `context`줄만 남기고 나머지는 "n줄 같음"으로 접는다. */
export function diffChunks(diff: readonly DiffLine[], context = 3): DiffChunk[] {
  const keep = new Array<boolean>(diff.length).fill(false)
  diff.forEach((line, index) => {
    if (line.kind === 'same') return
    for (let k = Math.max(0, index - context); k <= Math.min(diff.length - 1, index + context); k++) keep[k] = true
  })
  const chunks: DiffChunk[] = []
  let index = 0
  while (index < diff.length) {
    if (keep[index]) {
      const lines: DiffLine[] = []
      while (index < diff.length && keep[index]) lines.push(diff[index++])
      chunks.push({ kind: 'lines', lines })
    } else {
      let count = 0
      while (index < diff.length && !keep[index]) {
        count++
        index++
      }
      chunks.push({ kind: 'skip', count })
    }
  }
  return chunks
}

export function prettyLines(value: unknown): string[] {
  return JSON.stringify(value, null, 2).split('\n')
}
