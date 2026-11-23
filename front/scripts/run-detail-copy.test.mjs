// node --experimental-strip-types --test scripts/run-detail-copy.test.mjs  (npm run test:copy)
// "없음"을 말하는 문구가 실행 상태와 맞는가(emptyStateCopy.ts).
// 고정 값만 쓴다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  artifactsNotReadyCopy,
  failureLead,
  failureLeadText,
} from '../src/features/run-detail/emptyStateCopy.ts'

test('산출물 409: 실행 중이면 "아직", 끝났으면 앞으로도 생기지 않는다고 말한다', () => {
  const running = artifactsNotReadyCopy(true)
  assert.match(running.title, /아직/)
  assert.match(running.body, /단계가 끝날 때마다/)

  const ended = artifactsNotReadyCopy(false)
  assert.doesNotMatch(ended.title + ended.body, /아직|끝날 때마다/)
  assert.match(ended.body, /실행이 끝났/)
})

test('실패 카드: 구조화된 실패가 있으면 "아래 항목"', () => {
  assert.equal(failureLead(1, null), 'items')
  assert.equal(failureLead(2, 'raw text'), 'items') // 원문이 있어도 항목이 기준
  assert.match(failureLeadText('items', false) ?? '', /아래 항목에서/)
})

test('실패 카드: 원문만 있으면 "아래 항목"이라고 하지 않는다', () => {
  assert.equal(failureLead(0, 'main.sh exited with code 1'), 'rawOnly')
  for (const precheck of [false, true]) {
    const text = failureLeadText('rawOnly', precheck) ?? ''
    assert.doesNotMatch(text, /아래 항목/)
    assert.match(text, /구조화된 기록이 없습니다/)
    assert.match(text, /오류 원문/)
  }
})

test('실패 카드: 실패가 없으면(공백 원문 포함) 첫 문장도 없다', () => {
  assert.equal(failureLead(0, null), 'none')
  assert.equal(failureLead(0, '   '), 'none')
  assert.equal(failureLeadText('none', false), null)
})

// --- 다음 행동(nextActions.ts) -------------------------------------------
import { helpPathLabel, nextActions } from '../src/features/run-detail/nextActions.ts'

test('다음 행동: 준비 안내가 먼저, 같은 경로·같은 단계는 한 번만', () => {
  const help = { required_tools: '/help/setup#tools', resource_bundle: '/help/setup#resources' }
  const actions = nextActions(
    [
      { code: 'required_tools', actualStepId: '00_input_validation' },
      { code: 'resource_bundle', actualStepId: '00_input_validation' },
      { code: 'required_tools', actualStepId: '00_input_validation' },
    ],
    (code) => help[code],
  )
  assert.deepEqual(actions, [
    { kind: 'help', path: '/help/setup#tools', label: '프로그램 준비 방법 보기' },
    { kind: 'help', path: '/help/setup#resources', label: '참조 데이터 준비 방법 보기' },
    { kind: 'step', stepId: '00_input_validation' },
  ])
})

test('다음 행동: 미등록 code·귀속 단계 없음이면 만들지 않는다 (없는 기능을 지어내지 않는다)', () => {
  assert.deepEqual(nextActions([{ code: 'UNKNOWN', actualStepId: null }], () => undefined), [])
  assert.deepEqual(nextActions([], () => '/x'), [])
  assert.equal(helpPathLabel('/help/setup#tools'), '프로그램 준비 방법 보기')
})

import { resultsNotReadyCopy } from '../src/features/run-detail/emptyStateCopy.ts'

test('결과 409: 끝난 실행은 "아직"이라 하지 않고, 바로 위 안내를 두고 다른 탭으로만 보내지 않는다', () => {
  const ended = resultsNotReadyCopy(true)
  assert.doesNotMatch(ended.title + ended.body, /아직/)
  assert.match(ended.body, /위쪽 안내/)
  const running = resultsNotReadyCopy(false)
  assert.match(running.title, /아직/)
  assert.match(running.body, /0건이라는 뜻이 아닙니다/)
})

// --- 위치 문장·카드 제목(runPosition.ts, emptyStateCopy.attentionHeading) ---
import { describePosition } from '../src/features/run-detail/runPosition.ts'
import { attentionHeading } from '../src/features/run-detail/emptyStateCopy.ts'

const label = (id) => `L(${id})`

test('위치: 실패 → 멈춘 단계, 실행 중 → 다음 단계, 끝난 완료 실행은 "기록 없음"이 아니다', () => {
  const failed = describePosition(
    { status: 'failed', currentStep: null, steps: [{ stepId: 'a', status: 'failed' }, { stepId: 'b', status: 'pending' }] },
    label,
  )
  assert.deepEqual(failed, { headline: 'L(a)에서 멈춤', detail: '이후 1단계는 실행되지 않았습니다' })

  const running = describePosition(
    { status: 'running', currentStep: 'b', steps: [{ stepId: 'a', status: 'completed' }, { stepId: 'b', status: 'running' }, { stepId: 'c', status: 'pending' }] },
    label,
  )
  assert.deepEqual(running, { headline: 'L(b) 진행 중', detail: '다음: L(c)' })

  // 단계 기록 일부가 없는 완료(경고) 실행. 실행됐다/안 됐다를 지어내지 않는다.
  const done = describePosition(
    { status: 'completed_with_warnings', currentStep: null, steps: [{ stepId: 'a', status: 'pending' }, { stepId: 'b', status: 'completed' }] },
    label,
  )
  assert.equal(done.headline, '실행이 끝났습니다')
  assert.match(done.detail, /1단계는 단계 기록이 남지 않았습니다/)
  assert.doesNotMatch(done.detail, /실행되지 않았/)

  assert.equal(describePosition({ status: 'queued', currentStep: null, steps: [] }, label).headline, '시작 대기 중')
})

test('카드 제목: 확인 필요가 0이면 "확인이 필요한"이라고 말하지 않는다', () => {
  assert.equal(attentionHeading(true, false, 0).tone, 'failure')
  assert.match(attentionHeading(true, true, 0).title, /시작하기 전/)
  assert.deepEqual(attentionHeading(false, false, 2), { title: '확인이 필요한 사항이 있습니다', tone: 'warning' })
  const note = attentionHeading(false, false, 0)
  assert.equal(note.tone, 'note')
  assert.doesNotMatch(note.title, /확인이 필요/)
})

test('위치: 중단된 실행(failed, 실패 단계 없음)·취소는 "기록 없음"·"실행되지 않았습니다"라고 하지 않는다', () => {
  const interrupted = describePosition(
    { status: 'failed', currentStep: null, steps: [{ stepId: 'a', status: 'completed' }, { stepId: 'b', status: 'pending' }] },
    label,
  )
  assert.equal(interrupted.headline, '실행이 중단되었습니다')
  assert.doesNotMatch(interrupted.headline + interrupted.detail, /기록 없음|L\(b\)/) // 단계 이름을 지어내지 않는다

  const cancelled = describePosition(
    { status: 'cancelled', currentStep: null, steps: [{ stepId: 'a', status: 'completed' }, { stepId: 'b', status: 'pending' }] },
    label,
  )
  assert.equal(cancelled.detail, '1단계는 완료 기록이 없습니다')
})
