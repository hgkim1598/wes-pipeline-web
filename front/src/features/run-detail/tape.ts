/*
  steps[] -> RunTape 셀.

  backend 어휘와 표시의 경계다. RunTape는 tone만 받고 step status를 모른다 —
  StatusBadge와 같은 정책이며, 그래서 이 변환이 component 밖에 있다.

  헤더(md, 라벨 없음)와 파이프라인 탭(lg, 라벨 + 소요시간)이 같은 함수를 쓰고
  withLabels로만 갈린다. 두 곳이 서로 다른 상태 색을 보여주는 일이 없어야 한다.
*/

import type { RunTapeCell } from '@/components/ui/RunTape'
import type { JobState } from '@/features/run-detail/api'
import { describeStepStatus } from '@/features/run-detail/stepStatus'
import { formatDuration } from '@/features/runs/time'
import { describeStep } from '@/registries/steps'

export function toTapeCells(job: JobState, withLabels = false): RunTapeCell[] {
  return job.steps.map((step) => {
    const view = describeStepStatus(step.status)
    const definition = describeStep(step.stepId)
    return {
      id: step.stepId,
      tone: view.tone,
      label: withLabels ? definition.label : undefined,
      meta:
        withLabels && step.elapsedSeconds > 0
          ? formatDuration(step.elapsedSeconds)
          : undefined,
      current: step.stepId === job.currentStep,
      // 색만으로 상태를 전달하지 않는다. md는 라벨이 없으므로 이 문장이 유일한
      // 대체 텍스트다.
      ariaLabel: `${definition.label}, ${view.label}${
        step.elapsedSeconds > 0 ? `, ${formatDuration(step.elapsedSeconds)}` : ''
      }`,
    }
  })
}
