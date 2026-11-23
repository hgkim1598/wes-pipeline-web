// node --experimental-strip-types --test scripts/synthesis-view.test.mjs  (npm run test:synthview)
// 화면에 보일 AI 설명을 고르는 규칙(src/features/run-detail/synthesisView.ts, 개발판단기록 66장).
// 합성 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음. 여기의 문장은 실제 Claude 응답이 아니다.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { chooseSynthesisView, storedAsResult } from '../src/features/run-detail/synthesisView.ts'

const BODY = {
  summary: '합성 요약(테스트용, 모델 응답 아님).',
  importantFindings: [{ statement: '합성 문장.', evidenceRefs: ['run:status'] }],
  limitations: [],
  nextChecks: [],
  uncertainties: [],
}
const PROVENANCE = {
  provider: 'claude-code-cli',
  models: ['synthetic-model'],
  generatedAt: '2026-11-23T00:00:00+00:00',
  contextKind: 'completedFull',
  runStatus: 'completed',
  durationMs: null,
}
const fresh = (storedVersion) => ({
  available: true,
  synthesis: BODY,
  provenance: PROVENANCE,
  errorCategory: null,
  errorMessage: null,
  storedVersion,
})
const stored = (version, synthesis = BODY) => ({
  version,
  createdAt: '2026-11-23T00:00:00+00:00',
  models: ['synthetic-model'],
  contractVersion: 'run-synthesis/1',
  status: 'served',
  deleted: synthesis === null,
  supersedesVersion: version > 1 ? version - 1 : null,
  inputDigest: '000000000000',
  inputChangedFromPrevious: version > 1 ? false : null,
  recordChanged: false,
  docSearchLinked: false,
  contextKind: 'completedFull',
  runStatus: 'completed',
  synthesis,
  provenance: PROVENANCE,
  docEvidence: [],
  citedDocIds: [],
  citationsOutsidePayload: [],
})

test('새로고침 뒤: 방금 받은 응답이 없으면 저장된 최신 버전을 본다', () => {
  assert.deepEqual(chooseSynthesisView({ selectedVersion: null, fresh: undefined, latestVersion: 3 }), {
    viewingVersion: 3,
    prefer: 'stored',
  })
})

test('저장이 꺼졌거나 저장본이 없으면 볼 버전이 없다', () => {
  assert.deepEqual(chooseSynthesisView({ selectedVersion: null, fresh: undefined, latestVersion: null }), {
    viewingVersion: null,
    prefer: 'stored',
  })
})

test('방금 받은 응답이 저장됐으면 그 버전과 연결하고, 응답 자체를 보인다', () => {
  assert.deepEqual(chooseSynthesisView({ selectedVersion: null, fresh: fresh(4), latestVersion: 3 }), {
    viewingVersion: 4,
    prefer: 'fresh',
  })
})

test('방금 받은 응답이 저장되지 않았으면 다른 버전과 연결하지 않는다', () => {
  // 목록의 최신(v3)은 이 응답이 아니다. 시각으로 짐작해 붙이지 않는다.
  for (const storedVersion of [null, undefined]) {
    assert.deepEqual(
      chooseSynthesisView({ selectedVersion: null, fresh: fresh(storedVersion), latestVersion: 3 }),
      { viewingVersion: null, prefer: 'fresh' },
    )
  }
})

test('기록에서 고른 버전이 방금 받은 응답보다 우선한다', () => {
  assert.deepEqual(chooseSynthesisView({ selectedVersion: 1, fresh: fresh(4), latestVersion: 4 }), {
    viewingVersion: 1,
    prefer: 'stored',
  })
})

test('저장본은 버전 번호를 단 응답이 되고, 본문이 지워진 버전은 응답이 없다', () => {
  const result = storedAsResult(stored(2))
  assert.equal(result.available, true)
  assert.equal(result.storedVersion, 2)
  assert.deepEqual(result.synthesis, BODY)
  assert.equal(result.errorCategory, null)
  assert.equal(storedAsResult(stored(1, null)), undefined)
  assert.equal(storedAsResult(undefined), undefined)
})
