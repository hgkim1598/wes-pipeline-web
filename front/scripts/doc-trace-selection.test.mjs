// node --experimental-strip-types --test scripts/doc-trace-selection.test.mjs  (npm run test:trace)
// 문서 구획의 자동 이동 규칙(src/features/run-detail/docTraceSelection.ts, 개발판단기록 29장).
// 합성 목록만 쓴다. 서버·브라우저·네트워크 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { newLinkedAgentSearch, seenFrom } from '../src/features/run-detail/docTraceSelection.ts'

const JOB = 'job-a'
const user = (id) => ({ searchId: id, purpose: 'userRequest', agentRequest: null })
const linked = (id) => ({ searchId: id, purpose: 'agentRequest', agentRequest: { outcome: 'noAnswer' } })
const unlinked = (id) => ({ searchId: id, purpose: 'agentRequest', agentRequest: null })

test('재현 순서: 사용자 검색 선택 → AI 요청 → 새 연결 Agent 검색으로 이동', () => {
  const before = [user('u1')]
  const after = [linked('a1'), user('u1')]
  assert.equal(newLinkedAgentSearch(seenFrom(JOB, before), JOB, after), 'a1')
})

test('첫 목록에서는 이동하지 않는다(기본 표시 유지)', () => {
  assert.equal(newLinkedAgentSearch(null, JOB, [linked('a1'), user('u1')]), null)
})

test('다른 Run의 목록과 비교하지 않는다', () => {
  assert.equal(newLinkedAgentSearch(seenFrom('job-b', []), JOB, [linked('a1')]), null)
})

test('사용자 검색이 새로 생긴 것은 이동 사유가 아니다', () => {
  assert.equal(newLinkedAgentSearch(seenFrom(JOB, [user('u1')]), JOB, [user('u2'), user('u1')]), null)
})

test('요청 기록이 연결되지 않은 Agent 검색으로는 이동하지 않는다', () => {
  assert.equal(newLinkedAgentSearch(seenFrom(JOB, [user('u1')]), JOB, [unlinked('a1'), user('u1')]), null)
})

test('이미 본 기록만 있는 갱신은 사용자가 고른 과거 기록을 유지한다', () => {
  const runs = [linked('a2'), linked('a1'), user('u1')]
  assert.equal(newLinkedAgentSearch(seenFrom(JOB, runs), JOB, runs), null)
})

test('새 연결 검색이 여럿이면 가장 최근 것(목록 앞쪽)', () => {
  const before = [user('u1')]
  const after = [linked('a2'), unlinked('a1'), linked('a0'), user('u1')]
  assert.equal(newLinkedAgentSearch(seenFrom(JOB, before), JOB, after), 'a2')
})

test('요청 실패(검색이 생기지 않음): 이동하지 않는다', () => {
  const runs = [user('u1')]
  assert.equal(newLinkedAgentSearch(seenFrom(JOB, runs), JOB, runs), null)
})
