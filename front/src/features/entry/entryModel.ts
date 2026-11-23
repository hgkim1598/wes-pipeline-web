/*
  진입 화면이 보여 주는 값. 모두 실제 출처에서 온다 — 지어낸 숫자·예시 결과 없음.

    파이프라인 지도   config/knowledge/wes_steps.json(단계 의미) + stepPlan.ts(웹 계획)
    최근 실행         GET /api/jobs (backend가 최신순으로 준다. 다시 정렬하지 않는다)

  React·경로 별칭을 쓰지 않는다: scripts/entry-model.test.mjs가 node로 직접 읽는다.
*/

import { webStepPlan } from '../../registries/stepPlan.ts'
import type { StepPlanKind } from '../../registries/stepPlan.ts'

export interface StepSource {
  stepId: string
  label: string
  tools: string[]
}

export interface PipelineNode {
  stepId: string
  /** `03_alignment` -> `03`. 접두 숫자가 없으면 빈 문자열. */
  ordinal: string
  label: string
  /** 실제 도구 이름(canonical). 도구를 실행하지 않는 단계는 빈 문자열. */
  tools: string
  plan: StepPlanKind
  note: string | null
}

/** shared knowledge 순서 그대로. 웹 계획에 없는 단계도 빼지 않고 그렇다고 표시한다. */
export function pipelineMap(steps: readonly StepSource[]): PipelineNode[] {
  return steps.map((step) => {
    const plan = webStepPlan(step.stepId)
    const ordinal = /^(\d+)_/.exec(step.stepId)?.[1] ?? ''
    return {
      stepId: step.stepId,
      ordinal,
      label: step.label,
      tools: step.tools.join(' · '),
      plan: plan.kind,
      note: plan.note,
    }
  })
}

export interface RunsDigest<T> {
  total: number
  /** queued·running. 모르는 상태는 진행 중으로 세지 않는다(status.ts와 같은 규칙). */
  active: number
  recent: T[]
}

const ACTIVE = new Set(['queued', 'running'])

export function runsDigest<T extends { status: string }>(jobs: readonly T[], limit = 5): RunsDigest<T> {
  return {
    total: jobs.length,
    active: jobs.filter((job) => ACTIVE.has(job.status)).length,
    recent: jobs.slice(0, Math.max(0, limit)),
  }
}
