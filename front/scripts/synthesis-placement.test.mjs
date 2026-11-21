// node --experimental-strip-types --test scripts/synthesis-placement.test.mjs  (npm run test:placement)
// AI 문장의 위치 배분(src/features/run-detail/synthesisPlacement.ts).
// 합성 응답만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  numberStatements,
  pick,
  placeStatements,
  statementNumber,
} from '../src/features/run-detail/synthesisPlacement.ts'

const REGISTERED_DX = new Set(['MULTIQC_MISSING', 'NM_MD_REPAIRED', 'UNCOVERED_TARGETS'])
const REGISTERED_FAIL = new Set(['required_tools', 'resource_bundle'])
const STEPS = ['00_input_validation', '01_raw_qc', '04_processing', '06_variant_calling']

const s = (statement, ...evidenceRefs) => ({ statement, evidenceRefs })
const synth = (parts = {}) => ({
  importantFindings: [],
  limitations: [],
  nextChecks: [],
  uncertainties: [],
  ...parts,
})

function input(synthesis, over = {}) {
  return {
    synthesis,
    failures: [{ code: 'required_tools', stepId: '00_input_validation' }],
    diagnostics: [{ code: 'NM_MD_REPAIRED', stepId: '04_processing' }],
    shownDiagnosticCodes: ['NM_MD_REPAIRED'],
    limitationCodes: ['NO_ANALYSIS_OUTPUT'],
    stepIds: STEPS,
    isRegisteredDiagnostic: (c) => REGISTERED_DX.has(c),
    isRegisteredFailure: (c) => REGISTERED_FAIL.has(c),
    ...over,
  }
}

/** 모든 문장은 statements에 정확히 한 번 있고, 붙거나 unplaced 중 정확히 한쪽이다. */
function assertComplete(p, total) {
  assert.deepEqual(p.statements.map((x) => x.number), Array.from({ length: total }, (_, i) => i + 1))
  const placed = new Set([...p.byFailure.values(), ...p.byDiagnostic.values(), ...p.byLimitation.values(), ...p.byStep.values()].flat())
  const unplaced = new Set(p.unplaced.map((u) => u.number))
  for (const n of placed) assert.ok(!unplaced.has(n), `#${n} is both placed and unplaced`)
  assert.equal(placed.size + unplaced.size, total)
  assert.equal(p.placedCount, placed.size)
}

test('번호는 응답 순서(묶음 순서 → 묶음 안 순서)이고 패널이 같은 번호를 찾는다', () => {
  const sy = synth({
    importantFindings: [s('a', 'run:status'), s('b', 'run:status')],
    nextChecks: [s('c', 'run:status')],
    uncertainties: [s('d', 'run:status')],
  })
  const numbered = numberStatements(sy)
  assert.deepEqual(numbered.map((x) => [x.number, x.group, x.index]), [
    [1, 'importantFindings', 0], [2, 'importantFindings', 1], [3, 'nextChecks', 0], [4, 'uncertainties', 0],
  ])
  assert.equal(statementNumber(numbered, 'nextChecks', 0), 3)
  assert.equal(statementNumber(numbered, 'limitations', 0), null)
})

test('정상: 실패·진단·제한·단계 id가 하나로 확인되면 그 위치에 붙는다', () => {
  const sy = synth({
    importantFindings: [
      s('도구가 없어 멈췄다', 'fail:required_tools'),
      s('NM 보정', 'dx:NM_MD_REPAIRED'),
    ],
    limitations: [s('산출물 없음', 'lim:NO_ANALYSIS_OUTPUT')],
    nextChecks: [s('정렬 단계 확인', 'step:04_processing')],
  })
  const p = placeStatements(input(sy))
  assert.deepEqual(p.byFailure.get('required_tools'), [1])
  assert.deepEqual(p.byDiagnostic.get('NM_MD_REPAIRED'), [2])
  assert.deepEqual(p.byLimitation.get('NO_ANALYSIS_OUTPUT'), [3])
  // 실패·진단의 단계는 backend가 기록한 발생 위치에서만 온다.
  assert.deepEqual(p.byStep.get('00_input_validation'), [1])
  assert.deepEqual(p.byStep.get('04_processing'), [2, 4])
  assert.equal(p.unplaced.length, 0)
  assertComplete(p, 4)
})

test('근거가 여러 개면 확인된 위치마다 같은 번호를 참조한다(복제·충돌 없음)', () => {
  const sy = synth({ importantFindings: [s('둘 다', 'fail:required_tools', 'dx:NM_MD_REPAIRED', 'src:x')] })
  const p = placeStatements(input(sy))
  assert.deepEqual(p.byFailure.get('required_tools'), [1])
  assert.deepEqual(p.byDiagnostic.get('NM_MD_REPAIRED'), [1])
  assert.equal(pick(p, p.byFailure.get('required_tools'))[0], pick(p, p.byDiagnostic.get('NM_MD_REPAIRED'))[0])
  assert.equal(p.placedCount, 1)
  assertComplete(p, 1)
})

test('모호: 같은 code가 두 단계에 기록되면 진단에도 단계에도 붙이지 않는다', () => {
  const sy = synth({ importantFindings: [s('MultiQC 없음', 'dx:MULTIQC_MISSING')] })
  const p = placeStatements(input(sy, {
    diagnostics: [
      { code: 'MULTIQC_MISSING', stepId: '00_input_validation' },
      { code: 'MULTIQC_MISSING', stepId: '01_raw_qc' },
    ],
    shownDiagnosticCodes: ['MULTIQC_MISSING', 'MULTIQC_MISSING'],
  }))
  assert.equal(p.byDiagnostic.size, 0)
  assert.equal(p.byStep.size, 0)
  assert.deepEqual(p.unplaced, [{ number: 1, reasons: ['ambiguousTarget'] }])
})

test('모호: 화면 목록에서만 두 번 나타나도 붙이지 않는다', () => {
  const sy = synth({ importantFindings: [s('x', 'dx:NM_MD_REPAIRED')] })
  const p = placeStatements(input(sy, { shownDiagnosticCodes: ['NM_MD_REPAIRED', 'NM_MD_REPAIRED'] }))
  assert.deepEqual(p.unplaced, [{ number: 1, reasons: ['ambiguousTarget'] }])
})

test('모호: 같은 실패 code가 두 번이면 붙이지 않는다', () => {
  const sy = synth({ importantFindings: [s('x', 'fail:required_tools')] })
  const p = placeStatements(input(sy, {
    failures: [{ code: 'required_tools', stepId: null }, { code: 'required_tools', stepId: null }],
  }))
  assert.equal(p.byFailure.size, 0)
  assert.deepEqual(p.unplaced[0].reasons, ['ambiguousTarget'])
})

test('발생 위치가 기록되지 않은 진단(사전 점검)은 진단에만 붙고 단계에는 붙지 않는다', () => {
  const sy = synth({ importantFindings: [s('MultiQC', 'dx:MULTIQC_MISSING')] })
  const p = placeStatements(input(sy, {
    diagnostics: [{ code: 'MULTIQC_MISSING', stepId: null }],
    shownDiagnosticCodes: ['MULTIQC_MISSING'],
  }))
  assert.deepEqual(p.byDiagnostic.get('MULTIQC_MISSING'), [1])
  assert.equal(p.byStep.size, 0)
})

test('누락·미확인: 없는 code, 미등록 code, 없는 단계, 화면에 없는 진단은 붙이지 않는다', () => {
  const sy = synth({
    importantFindings: [
      s('없는 진단', 'dx:UNCOVERED_TARGETS'),
      s('미등록 실패', 'fail:sort_order_x'),
      s('없는 단계', 'step:09_report'),
      s('없는 제한', 'lim:UNFILTERED_VARIANTS'),
    ],
  })
  const p = placeStatements(input(sy, {
    failures: [{ code: 'sort_order_x', stepId: '04_processing' }],
    // 설명 응답에는 있지만 실패 카드 목록에는 없다.
    diagnostics: [{ code: 'UNCOVERED_TARGETS', stepId: '06_variant_calling' }],
    shownDiagnosticCodes: [],
  }))
  assert.equal(p.placedCount, 0)
  assert.deepEqual(p.unplaced.map((u) => u.reasons), [
    ['unconfirmedTarget'], ['unconfirmedTarget'], ['unconfirmedTarget'], ['unconfirmedTarget'],
  ])
  assertComplete(p, 4)
})

test('위치를 가리키지 않는 근거(run:·doc:·manual:·src:)만 있으면 noTargetRef', () => {
  const sy = synth({
    importantFindings: [s('상태', 'run:status'), s('커버리지', 'run:coverage')],
    nextChecks: [s('문서', 'doc:x', 'manual:m#1')],
    uncertainties: [s('개념', 'concept:y', 'term:z')],
  })
  const p = placeStatements(input(sy))
  assert.equal(p.placedCount, 0)
  assert.ok(p.unplaced.every((u) => u.reasons.length === 1 && u.reasons[0] === 'noTargetRef'))
  assertComplete(p, 4)
})

test('형식이 깨진 id는 무시하고, 하나라도 확인되면 그 위치에 붙는다', () => {
  const sy = synth({ importantFindings: [s('x', 'dx:', ':NM', 'nocolon', 'dx:NM_MD_REPAIRED')] })
  const p = placeStatements(input(sy))
  assert.deepEqual(p.byDiagnostic.get('NM_MD_REPAIRED'), [1])
  assert.equal(p.unplaced.length, 0)
})

test('빈 답변은 빈 배분이다', () => {
  const p = placeStatements(input(synth()))
  assert.equal(p.statements.length, 0)
  assert.equal(p.placedCount, 0)
  assert.equal(p.unplaced.length, 0)
  assert.deepEqual(pick(p, undefined), [])
})

test('같은 문장이 같은 위치를 두 번 인용해도 한 번만 붙는다', () => {
  const sy = synth({ importantFindings: [s('x', 'dx:NM_MD_REPAIRED', 'step:04_processing')] })
  const p = placeStatements(input(sy))
  assert.deepEqual(p.byStep.get('04_processing'), [1])
})
