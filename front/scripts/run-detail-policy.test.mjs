// node --experimental-strip-types --test scripts/run-detail-policy.test.mjs  (npm run test:policy)
// Run 상세의 조회 정책(runDetailPolicy.ts): 언제 다시 읽고, 언제 멈추고, 끝나는
// 순간 무엇을 다시 읽고, 일시적 실패를 어떻게 표시하는가.
// 고정 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  connectionState,
  dependentEnabled,
  dependentInterval,
  detailInterval,
  justSettled,
  runPhase,
  shouldRetryDetail,
} from '../src/features/run-detail/runDetailPolicy.ts'

const MS = 3000
const phase = (status, terminal, errorStatus = null) => runPhase({ status, terminal, errorStatus })

test('runPhase: 받은 상세가 있으면 그것이 기준이고, 이후의 실패는 단계를 바꾸지 않는다', () => {
  assert.equal(phase('running', false), 'active')
  assert.equal(phase('failed', true), 'terminal')
  // 폴링 중 일시적 실패(react-query는 data를 남긴다) — 여전히 active
  assert.equal(phase('running', false, 500), 'active')
  assert.equal(phase('running', false, null), 'active')
})

test('runPhase: 받은 적 없을 때 404는 missing, 그 밖의 실패·첫 로딩은 pending', () => {
  assert.equal(phase(undefined, false, 404), 'missing')
  assert.equal(phase(undefined, false, 500), 'pending')
  assert.equal(phase(undefined, false, null), 'pending')
})

test('없는 실행(404)은 상세도 딸린 query도 다시 묻지 않는다', () => {
  assert.equal(detailInterval('missing', MS), false)
  assert.equal(dependentEnabled('missing'), false)
  assert.equal(dependentInterval('missing', MS), false)
  assert.equal(shouldRetryDetail(0, 404), false)
})

test('첫 응답 전: 상세는 다시 묻고(일시적 실패에서 회복), 딸린 query는 기다린다', () => {
  assert.equal(detailInterval('pending', MS), MS)
  assert.equal(dependentEnabled('pending'), false)
  assert.equal(shouldRetryDetail(0, 500), true)
  assert.equal(shouldRetryDetail(0, null), true)
  assert.equal(shouldRetryDetail(1, 500), false)
})

test('실행 중에는 모두 따라가고, 끝나면 모두 멈춘다', () => {
  assert.equal(detailInterval('active', MS), MS)
  assert.equal(dependentEnabled('active'), true)
  assert.equal(dependentInterval('active', MS), MS)

  assert.equal(detailInterval('terminal', MS), false)
  assert.equal(dependentEnabled('terminal'), true) // 끝난 실행의 설명·산출물은 읽는다
  assert.equal(dependentInterval('terminal', MS), false)
})

test('justSettled: 실행 중 → 끝남 전환에서만 마지막 갱신을 한다', () => {
  assert.equal(justSettled('active', 'terminal'), true)
  // 처음부터 끝난 실행을 연 경우 — 첫 응답이 이미 끝난 뒤의 것
  assert.equal(justSettled('pending', 'terminal'), false)
  assert.equal(justSettled('terminal', 'terminal'), false)
  assert.equal(justSettled('active', 'active'), false)
  assert.equal(justSettled('pending', 'missing'), false)
})

test('connectionState: 실패는 다음 성공까지 끊김으로 남는다', () => {
  assert.equal(connectionState({ isError: false, failureCount: 0, isFetching: false }), 'live')
  assert.equal(connectionState({ isError: false, failureCount: 0, isFetching: true }), 'refreshing')
  // 재시도 중
  assert.equal(connectionState({ isError: false, failureCount: 1, isFetching: true }), 'disconnected')
  // 재시도를 다 쓴 뒤 다음 폴링이 시작되면 failureCount는 0이 되지만 실패 상태는 남는다
  assert.equal(connectionState({ isError: true, failureCount: 0, isFetching: true }), 'disconnected')
  assert.equal(connectionState({ isError: true, failureCount: 0, isFetching: false }), 'disconnected')
})

// --- 단계 띠 스크롤 맞춤(lib/scrollReveal.ts) ------------------------------
import { revealScrollLeft } from '../src/lib/scrollReveal.ts'

test('스크롤 맞춤: 이미 보이면 그대로, 왼쪽 밖이면 왼쪽 끝, 오른쪽 밖이면 오른쪽 끝에 맞춘다', () => {
  // 보이는 폭 300, 지금 0~300이 보인다.
  assert.equal(revealScrollLeft(0, 300, 100, 50), 0) // 다 보임 → 사용자가 둔 위치 유지
  assert.equal(revealScrollLeft(0, 300, 500, 60), 260) // 오른쪽 밖 → 항목 오른쪽 끝 = 보이는 오른쪽 끝
  assert.equal(revealScrollLeft(400, 300, 100, 50), 100) // 왼쪽 밖 → 항목 왼쪽 끝
  assert.equal(revealScrollLeft(0, 300, 280, 60), 40) // 걸쳐 있음 → 전부 보이게
  assert.equal(revealScrollLeft(0, 30, 100, 50), 100) // 항목이 폭보다 넓음 → 시작을 보인다
})
