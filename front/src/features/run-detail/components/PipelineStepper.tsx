import { Activity, Ban, Check, CircleHelp, X } from 'lucide-react'

import type { StepState } from '@/features/run-detail/api'
import { stepStatusDisplay } from '@/features/run-detail/stepDisplay'
import { isNotRun, isUndetermined } from '@/features/run-detail/stepView'
import { STEP_DETAIL_PANEL_ID } from '@/features/run-detail/components/StepTable'
import { describeStep, stepOrdinal } from '@/registries/steps'
import { cx } from '@/lib/cx'

/*
  가로 단계 진행 표시 (2026-11-20 승인 시안, 헤더의 단계 띠를 파이프라인 탭으로 옮김).

  점 하나가 단계 하나다. 상태는 점의 모양(채움·아이콘)과 아래 글자(화면 낭독기용
  sr-only 포함)로 말한다 — 색 하나로 구분하지 않는다. 시작되지 않은 단계는
  빈 원이고, 끝난 실행이면 "실행 안 됨"이다(stepView.ts).

  점을 누르면 그 단계를 선택한다(목록과 같은 선택, URL ?step=).
*/
export function PipelineStepper({
  steps,
  selectedStepId,
  terminal,
  onSelect,
}: {
  /** `execution`은 backend 장부 값(factApplicability.withLedger). 없으면 예전 규칙. */
  steps: (StepState & { execution?: string })[]
  selectedStepId: string | null
  terminal: boolean
  onSelect: (stepId: string) => void
}) {
  return (
    <div className="overflow-x-auto pb-1">
      <ol aria-label="단계 진행" className="flex min-w-[36rem] items-start">
        {steps.map((step, index) => {
          const display = stepStatusDisplay(step.status, terminal, step.execution)
          const selected = step.stepId === selectedStepId
          const prevDone =
            index > 0 && ['completed', 'warning', 'failed'].includes(steps[index - 1].status)
          return (
            <li key={step.stepId} className="relative flex flex-1 flex-col items-center">
              {index > 0 ? (
                <span
                  aria-hidden="true"
                  className={cx(
                    'absolute top-3 right-1/2 left-[-50%] h-px',
                    prevDone ? 'bg-ink-300' : 'bg-border',
                  )}
                />
              ) : null}
              <button
                type="button"
                onClick={() => onSelect(step.stepId)}
                aria-current={selected ? 'step' : undefined}
                aria-controls={STEP_DETAIL_PANEL_ID}
                className="relative flex flex-col items-center gap-1 rounded-md px-1 pb-1 focus-visible:[outline-offset:-2px]"
              >
                <Dot
                  status={step.status}
                  notRun={isNotRun(step.status, terminal, step.execution)}
                  undetermined={isUndetermined(step.execution)}
                />
                <span className="font-mono text-caption text-text-muted">
                  {stepOrdinal(step.stepId)}
                </span>
                <span
                  className={cx(
                    'rounded-sm px-1.5 text-center text-caption whitespace-nowrap',
                    selected
                      ? step.status === 'failed'
                        ? 'bg-status-failure-bg font-medium text-status-failure-fg'
                        : 'bg-brand-selected font-medium text-text-strong'
                      : 'text-text',
                  )}
                >
                  {describeStep(step.stepId).label}
                </span>
                <span className="sr-only">{display.label}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Dot({
  status,
  notRun,
  undetermined,
}: {
  status: string
  notRun: boolean
  undetermined: boolean
}) {
  const base = 'relative z-10 flex size-6 items-center justify-center rounded-pill'
  if (undetermined) {
    // 기록으로 판정할 수 없는 단계. 끝난 실행에 running으로 남은 단계도 여기다.
    return (
      <span className={cx(base, 'border-2 border-dashed border-ink-300 bg-surface text-text-muted')}>
        <CircleHelp size={12} strokeWidth={2} aria-hidden="true" />
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className={cx(base, 'bg-fill-failure text-surface')}>
        <X size={14} strokeWidth={2.5} aria-hidden="true" />
      </span>
    )
  }
  if (status === 'completed' || status === 'warning') {
    return (
      <span className={cx(base, 'bg-fill-success text-surface')}>
        <Check size={14} strokeWidth={2.5} aria-hidden="true" />
      </span>
    )
  }
  if (status === 'running') {
    return (
      <span className={cx(base, 'border-2 border-fill-running bg-surface text-status-running-fg')}>
        <Activity size={12} strokeWidth={2} aria-hidden="true" />
      </span>
    )
  }
  if (status === 'skipped') {
    return (
      <span className={cx(base, 'bg-fill-skip text-surface')}>
        <Ban size={12} strokeWidth={2} aria-hidden="true" />
      </span>
    )
  }
  // 대기 중 · 실행 안 됨: 빈 원. 실행 안 됨은 점선으로 구분한다.
  return (
    <span
      className={cx(
        base,
        'border-2 bg-surface',
        notRun ? 'border-dashed border-ink-300' : 'border-ink-300',
      )}
    />
  )
}
