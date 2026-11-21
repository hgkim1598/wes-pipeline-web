// node --experimental-strip-types --test scripts/fact-applicability.test.mjs  (npm run test:facts)
// 실행 장부·문장 적용 판정의 화면 반영(factApplicability.ts, stepView.ts).
// 고정 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  applyWithheld,
  executionByStep,
  occurrenceKey,
  withLedger,
  withheldByOccurrence,
} from '../src/features/run-detail/factApplicability.ts'
import { isNotRun, isUndetermined } from '../src/features/run-detail/stepView.ts'

// 00에서 멈춘 실행(2026-11-21 결함 재현 형태). 값은 backend 응답 모양 그대로.
const STOPPED_AT_00 = {
  diagnostics: [{ code: 'MULTIQC_MISSING', actualStepId: '00_input_validation' }],
  executionLedger: {
    stepsKnown: true,
    steps: [
      { stepId: '00_input_validation', execution: 'ranFailed', basis: '단계 문서의 상태가 failed입니다.' },
      { stepId: '01_raw_qc', execution: 'notRunAfterFailure', basis: '앞 단계가 실패로 끝나 이 단계는 시작되지 않았습니다.' },
      { stepId: '02_preprocessing', execution: 'unknown', basis: '판단할 수 없습니다.' },
    ],
  },
  knowledgeDecisions: [
    { section: 'diagnostics', index: 0, part: 'meaning', withheld: false, reason: null },
    { section: 'diagnostics', index: 0, part: 'grounding.scope.2', withheld: true, reason: '원본 품질 검사(01_raw_qc) 단계: 앞 단계 실패로 실행 안 됨' },
    { section: 'diagnostics', index: 0, part: 'impact', withheld: true, reason: '원본 품질 검사(01_raw_qc) 단계: 앞 단계 실패로 실행 안 됨' },
  ],
}

test('장부: 단계별 실행 사실을 붙이고, 장부에 없는 단계는 그대로 둔다', () => {
  const ledger = executionByStep(STOPPED_AT_00)
  const steps = withLedger(
    [{ stepId: '00_input_validation', status: 'failed' }, { stepId: '01_raw_qc', status: 'pending' }, { stepId: '09_x', status: 'pending' }],
    ledger,
  )
  assert.equal(steps[1].execution, 'notRunAfterFailure')
  assert.match(steps[1].executionBasis, /시작되지 않았습니다/)
  assert.equal(steps[2].execution, undefined)
})

test('장부가 없거나 단계 목록이 없으면 빈 Map — 예전 규칙으로 돌아간다', () => {
  assert.equal(executionByStep(undefined).size, 0)
  assert.equal(executionByStep({ diagnostics: [] }).size, 0)
  assert.equal(executionByStep({ diagnostics: [], executionLedger: { stepsKnown: false, steps: [] } }).size, 0)
})

test('isNotRun: 장부가 있으면 장부만 본다', () => {
  // 예전 규칙: 끝난 실행의 pending = 실행 안 됨
  assert.equal(isNotRun('pending', true), true)
  // 장부가 판정 불가라고 하면 실행 안 됨이 아니다(취소 시점 진행 중 단계 등)
  assert.equal(isNotRun('pending', true, 'unknown'), false)
  assert.equal(isUndetermined('unknown'), true)
  assert.equal(isNotRun('pending', true, 'notRunCancelled'), true)
  assert.equal(isNotRun('pending', false, 'waiting'), false)
  // 문서가 있는 단계는 장부가 있어도 실행 안 됨이 아니다
  assert.equal(isNotRun('completed', true, 'ranCompleted'), false)
})

test('보류: 화면이 쓰는 meaning·impact만 (단계, code)에 붙는다', () => {
  const withheld = withheldByOccurrence(STOPPED_AT_00)
  const entry = withheld.get(occurrenceKey('00_input_validation', 'MULTIQC_MISSING'))
  assert.ok(entry)
  assert.match(entry.impact, /01_raw_qc/)
  assert.equal(entry.meaning, undefined) // meaning은 applicable
  assert.equal(withheld.size, 1)
})

test('보류 정보는 /results 경로로 모은 진단에도 같은 키로 붙는다', () => {
  const d = { stepId: '00_input_validation', code: 'MULTIQC_MISSING', impact: 'Per-lane FastQC still runs' }
  const other = { stepId: '01_raw_qc', code: 'MULTIQC_MISSING', impact: 'x' }
  const collection = {
    byStep: new Map([['00_input_validation', [d]], ['01_raw_qc', [other]]]),
    unattributed: [],
    all: [d, other],
  }
  const out = applyWithheld(collection, withheldByOccurrence(STOPPED_AT_00))
  assert.ok(out.all[0].withheld?.impact)
  assert.equal(out.all[1].withheld, undefined) // 같은 code라도 다른 단계면 따로
  assert.ok(out.byStep.get('00_input_validation')[0].withheld?.impact)
  // 원래 값은 바꾸지 않는다
  assert.equal(d.withheld, undefined)
})

test('보류할 것이 없으면 같은 객체', () => {
  const collection = { byStep: new Map(), unattributed: [], all: [] }
  assert.equal(applyWithheld(collection, new Map()), collection)
})
