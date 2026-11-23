// node --experimental-strip-types --test scripts/entry-model.test.mjs  (npm run test:entry)
// 진입 화면의 파이프라인 지도·최근 실행(entryModel.ts), 웹 실행 계획(stepPlan.ts),
// 실행 목록 상태 요약(summary.ts).
// 고정 값과 저장소 파일만 읽는다. 서버·브라우저·네트워크·모델 호출 없음.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { pipelineMap, runsDigest } from '../src/features/entry/entryModel.ts'
import { summarizeStatuses } from '../src/features/runs/summary.ts'
import { OPTIONAL_STEP_IDS, webStepPlan } from '../src/registries/stepPlan.ts'

const ROOT = new URL('../../', import.meta.url)
const read = (rel) => readFileSync(new URL(rel, ROOT), 'utf8')

test('stepPlan의 선택 단계는 main.sh의 OPTIONAL_STEPS와 같다', () => {
  const line = /^OPTIONAL_STEPS=\(([^)]*)\)/m.exec(read('script/main.sh'))
  assert.ok(line, 'main.sh에 OPTIONAL_STEPS가 없다')
  assert.deepEqual([...OPTIONAL_STEP_IDS].sort(), line[1].trim().split(/\s+/).sort())
})

test('웹 제출에서 08·10은 꺼져 있고 11만 run_acmg로 켜진다(config_builder.py)', () => {
  const builder = read('backend/app/services/config_builder.py')
  assert.match(builder, /"filtering":\s*False/)
  assert.match(builder, /"annotation":\s*False/)
  assert.match(builder, /"run_acmg":\s*"optional_steps\.intervar"/)
  assert.equal(webStepPlan('08_filtering').kind, 'notOnWeb')
  assert.equal(webStepPlan('10_annotation').kind, 'notOnWeb')
  assert.equal(webStepPlan('11_intervar').kind, 'conditional')
  assert.deepEqual(webStepPlan('03_alignment'), { kind: 'core', note: null })
})

test('파이프라인 지도는 shared knowledge의 모든 단계를 순서대로 담는다', () => {
  const doc = JSON.parse(read('config/knowledge/wes_steps.json'))
  const nodes = pipelineMap(doc.steps)
  assert.deepEqual(nodes.map((n) => n.stepId), doc.steps.map((s) => s.stepId))
  const intervar = nodes.find((n) => n.stepId === '11_intervar')
  assert.equal(intervar.plan, 'conditional')
  assert.match(intervar.note, /InterVar/)
  const first = nodes[0]
  assert.equal(first.ordinal, '00')
  assert.equal(first.tools, '') // 도구를 실행하지 않는 단계
  assert.equal(nodes.find((n) => n.stepId === '03_alignment').tools, 'bwa · samtools')
})

test('최근 실행: backend 순서를 지키고, 진행 중은 queued·running만 센다', () => {
  const jobs = [
    { id: 1, status: 'running' },
    { id: 2, status: 'queued' },
    { id: 3, status: 'failed' },
    { id: 4, status: 'mystery' },
    { id: 5, status: 'completed' },
    { id: 6, status: 'completed' },
  ]
  const digest = runsDigest(jobs, 3)
  assert.equal(digest.total, 6)
  assert.equal(digest.active, 2)
  assert.deepEqual(digest.recent.map((j) => j.id), [1, 2, 3])
  assert.deepEqual(runsDigest([], 5), { total: 0, active: 0, recent: [] })
})

test('상태 요약: 주의 순서, 없는 상태는 만들지 않고, 모르는 상태는 원문으로 맨 뒤', () => {
  const summary = summarizeStatuses([
    { status: 'completed' },
    { status: 'failed' },
    { status: 'mystery' },
    { status: 'running' },
    { status: 'failed' },
  ])
  assert.deepEqual(
    summary.map((s) => [s.status, s.count, s.label]),
    [
      ['running', 1, '분석 중'],
      ['failed', 2, '실패'],
      ['completed', 1, '완료'],
      ['mystery', 1, 'mystery'],
    ],
  )
  assert.deepEqual(summarizeStatuses([]), [])
})
