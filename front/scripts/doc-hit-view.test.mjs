// node --experimental-strip-types --test scripts/doc-hit-view.test.mjs  (npm run test:docview)
// 공식 문서 구획의 표시 규칙(docHitView.ts)과 근거 출처 분류(evidenceSource.ts).
// 고정 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  filterHits,
  hitFilterCounts,
  splitInputs,
  usageStages,
} from '../src/features/run-detail/docHitView.ts'
import {
  countEvidenceSources,
  evidenceSourceOf,
  isDocEvidence,
} from '../src/features/run-detail/evidenceSource.ts'

const usage = (over = {}) => ({
  returnedBySearch: true,
  selectedForAgent: null,
  inAgentInput: null,
  readByModel: null,
  citedInAnswer: null,
  ...over,
})
const values = (stages) => Object.fromEntries(stages.map((s) => [s.key, s.value]))

test('usageStages: Run 상세 검색 — 첫 단계만 있고 나머지는 "기록 없음"(아니오로 바꾸지 않음)', () => {
  const stages = usageStages(usage(), false)
  assert.deepEqual(values(stages), {
    returned: '예',
    candidate: '기록 없음',
    input: '기록 없음',
    read: '기록 없음',
    cited: '기록 없음',
  })
  assert.deepEqual(
    stages.map((s) => s.label),
    ['검색 결과에 나타남', 'Agent 입력 후보', '요청 입력에 포함', '모델이 읽음', '답변 인용'],
  )
})

test('usageStages: 요청이 있었는데 인용 값이 null이면 "확인 불가"', () => {
  const stages = usageStages(usage({ selectedForAgent: true, inAgentInput: true }), true)
  assert.equal(values(stages).cited, '확인 불가')
  assert.equal(stages.find((s) => s.key === 'cited').state, 'none')
})

test('usageStages: 인용 확인 · 아니오 · 후보 제외', () => {
  const cited = usageStages(
    usage({ selectedForAgent: true, inAgentInput: true, citedInAnswer: true }),
    true,
  )
  assert.deepEqual(values(cited), {
    returned: '예',
    candidate: '예',
    input: '예',
    read: '기록 없음',
    cited: '확인됨',
  })
  assert.equal(cited.find((s) => s.key === 'cited').state, 'yes')
  const excluded = usageStages(
    usage({ selectedForAgent: false, inAgentInput: false, citedInAnswer: false }),
    true,
  )
  assert.deepEqual(values(excluded), {
    returned: '예',
    candidate: '아니오',
    input: '아니오',
    read: '기록 없음',
    cited: '아니오',
  })
  assert.equal(usageStages(usage({ returnedBySearch: false }), false)[0].value, '아니오')
})

const hit = (id, over) => ({ evidenceId: id, usage: usage(over) })
const HITS = [
  hit('doc:a', { selectedForAgent: true, inAgentInput: true, citedInAnswer: true }),
  hit('manual:b', { selectedForAgent: true, inAgentInput: true, citedInAnswer: false }),
  hit('manual:c', { selectedForAgent: false, inAgentInput: false, citedInAnswer: false }),
  hit('manual:d', {}),
]

test('filterHits: true인 것만 남기고 순서를 지킨다. null은 포함하지 않는다', () => {
  assert.deepEqual(filterHits(HITS, 'all').map((h) => h.evidenceId), ['doc:a', 'manual:b', 'manual:c', 'manual:d'])
  assert.deepEqual(filterHits(HITS, 'inAgentInput').map((h) => h.evidenceId), ['doc:a', 'manual:b'])
  assert.deepEqual(filterHits(HITS, 'cited').map((h) => h.evidenceId), ['doc:a'])
  assert.deepEqual(hitFilterCounts(HITS), { all: 4, inAgentInput: 2, cited: 1 })
  assert.deepEqual(hitFilterCounts([]), { all: 0, inAgentInput: 0, cited: 0 })
})

test('filterHits: 입력 배열을 바꾸지 않는다', () => {
  const before = HITS.map((h) => h.evidenceId)
  filterHits(HITS, 'all').reverse()
  assert.deepEqual(HITS.map((h) => h.evidenceId), before)
})

test('splitInputs: 반환 문서 유무로 나누고 각 쪽의 원래 순서를 지킨다. 빠지는 입력이 없다', () => {
  const inputs = [{ inputId: 'i1' }, { inputId: 'i2' }, { inputId: 'i3' }, { inputId: 'i4' }]
  const counts = { i1: 0, i2: 6, i3: 0, i4: 1 }
  const { withHits, withoutHits } = splitInputs(inputs, (id) => counts[id])
  assert.deepEqual(withHits.map((i) => i.inputId), ['i2', 'i4'])
  assert.deepEqual(withoutHits.map((i) => i.inputId), ['i1', 'i3'])
  assert.equal(withHits.length + withoutHits.length, inputs.length)
})

test('evidenceSourceOf: prefix로만 나눈다', () => {
  for (const ref of ['run:status', 'lim:x', 'step:00_input_validation']) {
    assert.equal(evidenceSourceOf(ref), 'record', ref)
  }
  // 관측과 그 code의 일반 설명을 함께 가리키는 id(2026-11-21)
  for (const ref of ['dx:MULTIQC_MISSING', 'fail:required_tools']) {
    assert.equal(evidenceSourceOf(ref), 'mixed', ref)
  }
  for (const ref of ['doc:htslib-provides-tabix', 'manual:bcftools-manual#view#00']) {
    assert.equal(evidenceSourceOf(ref), 'doc', ref)
    assert.equal(isDocEvidence(ref), true, ref)
  }
  for (const ref of ['src:a', 'concept:b', 'term:c']) assert.equal(evidenceSourceOf(ref), 'knowledge', ref)
  for (const ref of ['artifact:x', 'nocolon', ':x', 'doc:', '']) {
    assert.equal(evidenceSourceOf(ref), 'other', ref)
    assert.equal(isDocEvidence(ref), false, ref)
  }
})

test('countEvidenceSources: 고정 순서, 0건 제외, 같은 id는 한 번', () => {
  assert.deepEqual(
    countEvidenceSources(['doc:a', 'fail:x', 'run:status', 'fail:x', 'term:t', 'weird']),
    [
      { source: 'record', count: 1 },
      { source: 'mixed', count: 1 },
      { source: 'doc', count: 1 },
      { source: 'knowledge', count: 1 },
      { source: 'other', count: 1 },
    ],
  )
  assert.deepEqual(countEvidenceSources([]), [])
})
