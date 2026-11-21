// node --experimental-strip-types --test scripts/workspace-view.test.mjs  (npm run test:workspace)
// 파이프라인 단계 선택(stepView.ts)과 공식 문서 워크스페이스 규칙(docWorkspace.ts).
// 고정 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  defaultStepId,
  isNotRun,
  resolveStepId,
} from '../src/features/run-detail/stepView.ts'
import {
  hitKey,
  hitsForStep,
  orderedHits,
  resolveHit,
  runForEvidence,
  stageCounts,
} from '../src/features/run-detail/docWorkspace.ts'

const s = (stepId, status) => ({ stepId, status })
const FAILED_AT_FIRST = [s('00', 'failed'), s('01', 'pending'), s('02', 'pending')]

test('defaultStepId: 실패 → 실행 중 → 경고 → 첫 단계', () => {
  assert.equal(defaultStepId(FAILED_AT_FIRST, null), '00')
  assert.equal(defaultStepId([s('00', 'completed'), s('01', 'running'), s('02', 'pending')], '01'), '01')
  assert.equal(defaultStepId([s('00', 'completed'), s('01', 'running')], null), '01')
  assert.equal(defaultStepId([s('00', 'completed'), s('01', 'warning')], null), '01')
  assert.equal(defaultStepId([s('00', 'completed'), s('01', 'completed')], null), '00')
  assert.equal(defaultStepId([], null), null)
  // 계획에 없는 currentStep은 쓰지 않는다
  assert.equal(defaultStepId([s('00', 'completed')], 'zz'), '00')
})

test('resolveStepId: URL 값이 계획에 있을 때만 그대로', () => {
  assert.equal(resolveStepId('02', FAILED_AT_FIRST, null), '02')
  assert.equal(resolveStepId('nope', FAILED_AT_FIRST, null), '00')
  assert.equal(resolveStepId(null, FAILED_AT_FIRST, null), '00')
})

test('isNotRun: 끝난 실행의 pending만 "실행 안 됨". 실행 중이면 대기 중', () => {
  assert.equal(isNotRun('pending', true), true)
  assert.equal(isNotRun('pending', false), false)
  for (const status of ['completed', 'warning', 'failed', 'skipped', 'running']) {
    assert.equal(isNotRun(status, true), false, status)
  }
})

const usage = (over = {}) => ({
  returnedBySearch: true,
  selectedForAgent: null,
  inAgentInput: null,
  citedInAnswer: null,
  ...over,
})
const h = (inputId, evidenceId, relation, rank, over, corpus = 'manual') => ({
  inputId, evidenceId, relation, rank, corpus, usage: usage(over),
})

test('orderedHits: 입력 순서 → 관계 순서 → 순위, 빠지는 문서 없음', () => {
  const hits = [
    h('in-2', 'manual:z', 'generalSection', 1),
    h('in-3', 'manual:b', 'sameCommandSection', 2),
    h('in-3', 'doc:a', 'filedUnderCauseKind', 1, {}, 'curated'),
    h('in-3', 'manual:c', 'sameCommandSection', 1),
    h('in-3', 'manual:x', 'unknownRelation', 1),
  ]
  const ordered = orderedHits(['in-1', 'in-3', 'in-2'], hits)
  assert.deepEqual(ordered.map((x) => x.evidenceId), ['doc:a', 'manual:c', 'manual:b', 'manual:x', 'manual:z'])
  assert.equal(ordered.length, hits.length)
  // 입력 배열을 바꾸지 않는다
  assert.equal(hits[0].evidenceId, 'manual:z')
})

test('resolveHit: evidenceId+inputId → evidenceId → 첫 문서 → null', () => {
  const hits = [h('in-1', 'doc:a', 'x', 1), h('in-2', 'doc:a', 'x', 1), h('in-2', 'manual:b', 'x', 2)]
  assert.equal(resolveHit(hits, 'doc:a', 'in-2'), hits[1])
  assert.equal(resolveHit(hits, 'doc:a', null), hits[0])
  assert.equal(resolveHit(hits, 'doc:a', 'in-9'), hits[0])
  assert.equal(resolveHit(hits, 'missing', null), hits[0])
  assert.equal(resolveHit([], 'doc:a', null), null)
  assert.notEqual(hitKey(hits[0]), hitKey(hits[1]))
})

test('runForEvidence: 고른 기록 우선, 없으면 가진 최근 기록, 어디에도 없으면 null', () => {
  const runs = [
    { searchId: 'new', hits: [{ evidenceId: 'doc:a' }] },
    { searchId: 'old', hits: [{ evidenceId: 'doc:a' }, { evidenceId: 'manual:b' }] },
  ]
  assert.equal(runForEvidence(runs, 'old', 'doc:a'), 'old')
  assert.equal(runForEvidence(runs, 'new', 'manual:b'), 'old')
  assert.equal(runForEvidence(runs, null, 'doc:a'), 'new')
  assert.equal(runForEvidence(runs, 'new', 'manual:zz'), null)
})

test('stageCounts: 모두 null인 단계는 null(기록 없음), 0건과 구분', () => {
  const userSearch = [h('i', 'a', 'x', 1), h('i', 'b', 'x', 2)]
  assert.deepEqual(stageCounts(userSearch), { returned: 2, candidate: null, input: null, cited: null })
  const agent = [
    h('i', 'a', 'x', 1, { selectedForAgent: true, inAgentInput: true, citedInAnswer: true }),
    h('i', 'b', 'x', 2, { selectedForAgent: true, inAgentInput: true, citedInAnswer: false }),
    h('i', 'c', 'x', 3, { selectedForAgent: false, inAgentInput: false, citedInAnswer: false }),
  ]
  assert.deepEqual(stageCounts(agent), { returned: 3, candidate: 2, input: 2, cited: 1 })
  const rejected = [h('i', 'a', 'x', 1, { selectedForAgent: true, inAgentInput: true, citedInAnswer: null })]
  assert.deepEqual(stageCounts(rejected), { returned: 1, candidate: 1, input: 1, cited: null })
  assert.deepEqual(stageCounts([]), { returned: 0, candidate: null, input: null, cited: null })
})

test('hitsForStep: 그 단계 입력의 문서만, 검색 기록이 없으면 null', () => {
  const run = {
    inputs: [{ inputId: 'i1', stepId: '00' }, { inputId: 'i2', stepId: '03' }],
    hits: [{ inputId: 'i1' }, { inputId: 'i1' }, { inputId: 'i2' }],
  }
  assert.equal(hitsForStep(run, '00'), 2)
  assert.equal(hitsForStep(run, '03'), 1)
  assert.equal(hitsForStep(run, '05'), 0)
  assert.equal(hitsForStep(undefined, '00'), null)
})
