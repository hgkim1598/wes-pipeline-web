// node --experimental-strip-types --test scripts/eval-compare.test.mjs  (npm run test:compare)
// A/B 비교 지표 집계(compareMetrics.ts). 고정 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  armMetrics,
  diffChunks,
  evaluateCriteria,
  lineDiff,
  median,
  modelsByArm,
} from '../src/features/eval-compare/compareMetrics.ts'

const answerScores = ({ nonRun = 0, causes = 4 } = {}) => ({
  measured: true,
  claimCount: 5,
  nonRunClaims: nonRun,
  execContradictions: 0,
  detectorHits: [],
  wrongCauseCandidates: [],
  requiredCauses: { mentioned: causes, required: 4, byCause: {} },
})

// backend(contract.evaluation_of)가 보내는 모양 그대로
const EVALUATION = {
  served: { outcome: 'served', category: null, answerProduced: true, exclusion: null, countsForGate: true, countsForContent: true, integrityChecked: true },
  gateRejected: { outcome: 'gateRejected', category: 'runFactMismatch', answerProduced: true, exclusion: null, countsForGate: true, countsForContent: true, integrityChecked: true },
  timeout: { outcome: 'providerError', category: 'timeout', answerProduced: false, exclusion: 'providerError', countsForGate: false, countsForContent: false, integrityChecked: true },
  integrity: { outcome: 'served', category: null, answerProduced: true, exclusion: 'integrity', countsForGate: false, countsForContent: false, integrityChecked: true },
}

const call = (arm, repeat, code, kind = 'served', { nonRun = 0, duration = 1000, models = ['model-x'] } = {}) => {
  const scored = kind === 'served' || kind === 'integrity'
  return {
    callId: `${arm}${repeat}`,
    attempt: 1,
    attempts: 1,
    arm,
    case: 'real_b94559',
    repeat,
    seq: 1,
    blindCode: code,
    mock: false,
    startedAt: 't',
    models,
    toolUse: { openedStepIds: [] },
    privacyOk: true,
    evaluation: EVALUATION[kind],
    integrity: { ok: kind !== 'integrity', checks: {}, notInCallPathImported: [] },
    durationMs: duration,
    wallMs: duration + 100,
    scores: {
      served: scored ? answerScores({ nonRun }) : { measured: false },
      rejected: kind === 'gateRejected' ? answerScores({ nonRun }) : { measured: false },
    },
  }
}

const CRITERIA = [
  { id: 'S1', metric: 'nonRunClaims', rule: 'B_total == 0', source: 'human', label: '' },
  { id: 'S3', metric: 'supportedClaims', rule: 'B_rate >= A_rate - 0.05', source: 'human', label: '' },
  { id: 'S8', metric: 'gateRejected', rule: 'B_rate <= A_rate', source: 'auto', label: '' },
  { id: 'S9', metric: 'latency', rule: 'B_median < A_median * 1.2', source: 'auto', label: '' },
  { id: 'SX', metric: 'latency', rule: 'something new', source: 'auto', label: '' },
]

const detail = (calls, { grades = {}, unblinded = false, mock = false, plan } = {}) => ({
  mock,
  protocol: {
    cases: [{ case: 'real_b94559', label: 'b94559', synthetic: false, facts: { steps: [], requiredCauses: [1, 2, 3, 4], notes: [] } }],
    successCriteria: CRITERIA,
  },
  blind: { unblinded, unblindedAt: null, gradable: calls.length, graded: Object.keys(grades).length, gradedAfterUnblind: 0 },
  plan:
    plan ??
    calls.map((c) => ({ callId: c.callId, case: c.case, arm: c.arm, repeat: c.repeat, seq: 1, state: 'recorded', outcome: c.evaluation.outcome, attempts: 1, history: [] })),
  calls,
  grades,
})

// 기본은 완료된 채점(backend가 complete: true로 보낸 것). 미완료는 complete: false로 따로 만든다.
const grade = (code, { nonRun = 0, verdicts = ['supported'], understanding = 4, blind = true, complete = true } = {}) => ({
  code,
  complete,
  grader: 'u',
  savedAt: 't',
  blind,
  claims: verdicts.map((verdict, index) => ({
    section: 'importantFindings',
    index,
    verdict,
    source: 'record',
    nonRunClaim: index < nonRun,
    execContradiction: false,
    unsupportedCause: false,
  })),
  requiredCauses: { a: true, b: true, c: false, d: true },
  understanding,
  usefulness: 3,
  notes: '',
})

const ALL_ANSWERED = [
  call('A', 1, 'X01', 'served', { nonRun: 2, duration: 1000 }),
  call('A', 2, 'X02', 'gateRejected', { nonRun: 1, duration: 3000 }),
  call('B', 1, 'X03', 'served', { duration: 1100 }),
  call('B', 2, 'X04', 'served', { duration: 1300 }),
]

test('median', () => {
  assert.equal(median([]), null)
  assert.equal(median([3, 1, 2]), 2)
  assert.equal(median([1, 2, 3, 4]), 2.5)
})

test('provider 실패는 Gate 거부의 분자·분모와 응답 시간에 들어가지 않는다 (H1)', () => {
  const calls = [
    call('A', 1, 'X01', 'served', { duration: 1000 }),
    call('A', 2, 'X02', 'timeout', { duration: 300000 }),
    call('A', 3, 'X05', 'gateRejected', { duration: 2000 }),
  ]
  const a = armMetrics(detail(calls, { unblinded: true }), 'A', null) // Gate 결과는 해제 뒤에만 온다(H3)
  assert.deepEqual([a.exact.gateRejected.numerator, a.exact.gateRejected.denominator], [1, 2])
  assert.equal(a.exact.gateRejected.value, 0.5)
  assert.equal(a.exact.latency.value, 1500) // 300000 ms 시간 초과가 섞이지 않는다
  assert.deepEqual([a.exact.providerErrors.numerator, a.exact.providerErrors.denominator], [1, 3])
  assert.equal(a.excluded.providerError, 1)
  assert.equal(a.answered, 2)
  assert.equal(a.exact.gateRejected.status, 'partial')
  assert.match(a.exact.gateRejected.note, /provider 실패 1/)
})

test('자동 값: 거부된 답변도 모델 답변으로 세고, 제외된 호출은 이유별로 센다', () => {
  const calls = [...ALL_ANSWERED, call('B', 3, 'X06', 'integrity')]
  const b = armMetrics(detail(calls, { unblinded: true }), 'B', null)
  assert.equal(b.contentAnswers, 2)
  assert.equal(b.excluded.integrity, 1)
  const a = armMetrics(detail(calls, { unblinded: true }), 'A', null)
  assert.equal(a.auto.nonRunClaims.value, 3)
  assert.equal(a.auto.nonRunClaims.status, 'measured')
  assert.deepEqual([a.auto.requiredCauses.numerator, a.auto.requiredCauses.denominator], [8, 8])
})

test('기록되지 않은 계획 호출은 "아직 결과 없음"으로 센다', () => {
  const plan = [
    { callId: 'A1', case: 'real_b94559', arm: 'A', repeat: 1, seq: 1, state: 'recorded', outcome: 'served', attempts: 1, history: [] },
    { callId: 'A2', case: 'real_b94559', arm: 'A', repeat: 2, seq: 2, state: 'uncertain', outcome: null, attempts: 1, history: [] },
  ]
  const a = armMetrics(detail([call('A', 1, 'X01')], { plan }), 'A', null)
  assert.equal(a.excluded.notRecorded, 1)
  assert.equal(a.planned, 2)
})

test('블라인드 해제 전에는 사람 지표를 집계하지 않는다', () => {
  const grades = { X03: grade('X03'), X04: grade('X04') }
  const before = armMetrics(detail(ALL_ANSWERED, { grades, unblinded: false }), 'B', null)
  for (const key of Object.keys(before.human)) {
    assert.equal(before.human[key].status, 'unmeasured', key)
    assert.equal(before.human[key].value, null, key)
  }
  assert.match(before.human.nonRunClaims.note, /블라인드/)
  const after = armMetrics(detail(ALL_ANSWERED, { grades, unblinded: true }), 'B', null)
  assert.equal(after.human.nonRunClaims.status, 'measured')
})

test('일부 답변만 채점이 완료되면 partial, 판단 불가는 분모에만 들어간다', () => {
  const grades = { X03: grade('X03', { verdicts: ['supported', 'undetermined'] }) }
  const b = armMetrics(detail(ALL_ANSWERED, { grades, unblinded: true }), 'B', null)
  assert.equal(b.human.supportedClaims.status, 'partial')
  assert.deepEqual([b.human.supportedClaims.numerator, b.human.supportedClaims.denominator], [1, 2])
  assert.equal(b.undeterminedClaims, 1)
  assert.deepEqual([b.human.requiredCauses.numerator, b.human.requiredCauses.denominator], [3, 4])
  // 미완료 채점(complete: false)은 채점 안 한 답변과 같다
  const unfinished = { X03: grade('X03', { verdicts: ['supported', null], complete: false }) }
  const u = armMetrics(detail(ALL_ANSWERED, { grades: unfinished, unblinded: true }), 'B', null)
  assert.equal(u.human.supportedClaims.status, 'unmeasured')
})

test('모의 실험은 어떤 성공 기준도 판정하지 않는다 (M4)', () => {
  const results = evaluateCriteria(detail(ALL_ANSWERED, { mock: true, unblinded: true }))
  assert.ok(results.every((r) => r.status === 'mock'))
})

test('provider 실패가 하나라도 남아 있으면 자동 기준도 판정하지 않는다', () => {
  const calls = [...ALL_ANSWERED.slice(0, 3), call('B', 2, 'X04', 'timeout')]
  const results = Object.fromEntries(evaluateCriteria(detail(calls)).map((r) => [r.criterion.id, r]))
  assert.equal(results.S8.status, 'unmeasured')
  assert.match(results.S8.reason, /provider 실패 1/)
})

test('모든 호출이 답변을 받으면 해제 뒤 자동 기준을 판정하고, 사람 기준은 채점이 끝나야 판정한다', () => {
  const blinded = evaluateCriteria(detail(ALL_ANSWERED))
  assert.ok(blinded.every((r) => r.status === 'unmeasured')) // 해제 전에는 자동 기준도 판정하지 않는다(H3)
  const results = Object.fromEntries(evaluateCriteria(detail(ALL_ANSWERED, { unblinded: true })).map((r) => [r.criterion.id, r.status]))
  assert.equal(results.S1, 'unmeasured')
  assert.equal(results.S3, 'unmeasured')
  assert.equal(results.S8, 'met') // B 0/2 <= A 1/2
  assert.equal(results.S9, 'met') // 1200 < 2000*1.2
  assert.equal(results.SX, 'unmeasured') // 모르는 규칙은 추측하지 않는다
})

test('모두 채점되면 사람 기준도 판정하고, 비블라인드 채점은 이유에 밝힌다', () => {
  const grades = {
    X01: grade('X01', { nonRun: 1 }),
    X02: grade('X02'),
    X03: grade('X03', { nonRun: 1, blind: false }),
    X04: grade('X04'),
  }
  const results = Object.fromEntries(evaluateCriteria(detail(ALL_ANSWERED, { grades, unblinded: true })).map((r) => [r.criterion.id, r]))
  assert.equal(results.S1.status, 'notMet')
  assert.match(results.S1.reason, /B 1/)
  assert.match(results.S1.reason, /블라인드 해제 뒤 채점 1건/)
  assert.equal(results.S3.status, 'met')
})

test('계획보다 기록이 적으면 판정하지 않는다', () => {
  const d = detail(ALL_ANSWERED)
  d.plan.push({ callId: 'B3', case: 'real_b94559', arm: 'B', repeat: 3, seq: 9, state: 'planned', outcome: null, attempts: 0, history: [] })
  const results = Object.fromEntries(evaluateCriteria(d).map((r) => [r.criterion.id, r]))
  assert.equal(results.S8.status, 'unmeasured')
  assert.match(results.S8.reason, /아직 결과 없음 1/)
})

test('두 경로의 실제 모델 ID가 다르면 알린다', () => {
  const same = modelsByArm(detail(ALL_ANSWERED))
  assert.equal(same.differ, false)
  const calls = [call('A', 1, 'X01', 'served', { models: ['m-1'] }), call('B', 1, 'X02', 'served', { models: ['m-2'] })]
  assert.equal(modelsByArm(detail(calls)).differ, true)
})

test('lineDiff · diffChunks', () => {
  const a = ['{', '  "x": 1,', '  "y": 2,', '  "z": 3', '}']
  const b = ['{', '  "x": 1,', '  "y": 5,', '  "z": 3', '}']
  const diff = lineDiff(a, b)
  assert.deepEqual(
    diff.filter((l) => l.kind !== 'same').map((l) => `${l.kind}${l.text.trim()}`),
    ['del"y": 2,', 'add"y": 5,'],
  )
  assert.equal(diff.filter((l) => l.kind !== 'add').length, a.length)
  const chunks = diffChunks(diff, 0)
  assert.deepEqual(chunks.map((c) => c.kind), ['skip', 'lines', 'skip'])
  assert.deepEqual(diffChunks(lineDiff(a, a)), [{ kind: 'skip', count: a.length }])
})

// --- 독립 리뷰 지적(2026-11-22) -------------------------------------------------

test('H2: 미완료 채점(판정 안 한 문장·선택 안 한 원인·점수 없음)은 채점 완료로 세지 않는다', () => {
  const done = (code) => ({ ...grade(code), requiredCauses: { a: true, b: true, c: false, d: true }, complete: true })
  const unfinished = {
    ...grade('X04', { verdicts: ['supported', null] }),
    requiredCauses: { a: true, b: null, c: null, d: null },
    understanding: null,
    complete: false,
  }
  const grades = { X01: done('X01'), X02: done('X02'), X03: done('X03'), X04: unfinished }
  const d = detail(ALL_ANSWERED, { grades, unblinded: true })
  const b = armMetrics(d, 'B', null)
  assert.notEqual(b.human.supportedClaims.status, 'measured')
  assert.notEqual(b.human.requiredCauses.status, 'measured')
  const results = Object.fromEntries(evaluateCriteria(d).map((r) => [r.criterion.id, r]))
  assert.equal(results.S3.status, 'unmeasured')
  assert.equal(results.S1.status, 'unmeasured')
})

test('H3: 해제 전 응답에는 답변·Gate 파생 값이 없고, 지표·기준은 판정하지 않는다', () => {
  // backend가 해제 전에 보내는 모양: 답변을 받은 호출은 outcome "answered", 파생 값은 null
  const blinded = (arm, repeat, kind = 'answered') => ({
    ...call(arm, repeat, null, 'served'),
    blindCode: null,
    models: null,
    toolUse: null,
    durationMs: null,
    wallMs: null,
    scores: null,
    evaluation:
      kind === 'answered'
        ? // countsForContent도 null: false면 "답이 파싱 안 된 Gate 거부"라서 해제 전에는 보내지 않는다(H3 2차)
          { outcome: 'answered', category: null, answerProduced: null, exclusion: null, countsForGate: true, countsForContent: null, integrityChecked: true }
        : EVALUATION.timeout,
  })
  const calls = [blinded('A', 1), blinded('A', 2), blinded('B', 1), blinded('B', 2, 'timeout')]
  const d = detail(calls)
  const a = armMetrics(d, 'A', null)
  assert.equal(a.exact.gateRejected.status, 'unmeasured')
  assert.equal(a.exact.latency.status, 'unmeasured')
  assert.equal(a.auto.nonRunClaims.status, 'unmeasured')
  const b = armMetrics(d, 'B', null)
  assert.deepEqual([b.exact.providerErrors.numerator, b.exact.providerErrors.denominator], [1, 2]) // 실행 상태는 보인다
  const allAnswered = detail(calls.slice(0, 3).concat([blinded('B', 2)]))
  assert.ok(evaluateCriteria(allAnswered).every((r) => r.status === 'unmeasured'))
})
