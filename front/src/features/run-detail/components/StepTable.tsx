import { ChevronRight } from 'lucide-react'

import type { StepState } from '@/features/run-detail/api'
import { describeStepStatus, isStepProblem } from '@/features/run-detail/stepStatus'
import { formatDuration } from '@/features/runs/time'
import { describeStep, stepOrdinal } from '@/registries/steps'
import { cx } from '@/lib/cx'

/*
  단계 표.

  시안 근거 (docs/design/pipeline-tab.html · 단계 목록)
    1px 테두리 컨테이너 · 행마다 하단 1px ink-100 · 행 좌측 1px 상태 rule
    열: mono tag(고정) / 이름 / 부제 / 소요시간(mono, 우측) / note / chevron
    선택된 행은 옅은 배경, 실패 행은 failure rule
    상태 문구가 있으면 이름 아래 caption 한 줄

  배지 대신 mono tag를 쓴다 — 8행에 알약을 8개 늘어놓으면 표의 밀도가 깨진다
  (CLAUDE.md 23장의 "상태마다 알약 badge를 여기저기 남발").

  좌측 rule은 1px이다. 시안의 두꺼운 accent bar는 CLAUDE.md 24장이 금지하므로
  선의 두께가 아니라 색으로만 구분한다.

  선택 상태를 스스로 갖지 않는다. 부모가 selectedStepId를 소유하므로 상세를
  레일에서 보여주든 드로어로 바꾸든 이 표는 그대로다.
*/

const RULE_CLASS: Record<string, string> = {
  idle: 'border-l-border',
  running: 'border-l-fill-running',
  success: 'border-l-fill-success',
  warning: 'border-l-fill-warning',
  failure: 'border-l-fill-failure',
  cancelled: 'border-l-fill-skip',
}

const TAG_CLASS: Record<string, string> = {
  idle: 'text-text-muted',
  running: 'text-status-running-fg',
  success: 'text-status-success-fg',
  warning: 'text-status-warning-fg',
  failure: 'text-status-failure-fg',
  cancelled: 'text-text-muted',
}

export interface StepTableProps {
  steps: StepState[]
  /** 지금 실행 중인 단계. backend의 currentStep. */
  currentStepId: string | null
  selectedStepId: string | null
  onSelect: (stepId: string) => void
}

export function StepTable({
  steps,
  currentStepId,
  selectedStepId,
  onSelect,
}: StepTableProps) {
  return (
    <ul className="overflow-hidden rounded-md border border-border bg-surface">
      {steps.map((step) => {
        const view = describeStepStatus(step.status)
        const definition = describeStep(step.stepId)
        const selected = step.stepId === selectedStepId
        const isCurrent = step.stepId === currentStepId
        // messages는 skip 사유·경고 요약 등 backend가 준 문장이다. 첫 줄만
        // 표에 두고 전체는 상세에서 본다.
        const note = step.messages[0]

        return (
          <li
            key={step.stepId}
            className={cx(
              'border-b border-border-subtle border-l last:border-b-0',
              RULE_CLASS[view.tone] ?? 'border-l-border',
              selected && 'bg-brand-faint',
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(step.stepId)}
              aria-current={selected ? 'true' : undefined}
              className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-brand-faint focus-visible:[outline-offset:-2px]"
            >
              <span
                className={cx(
                  'w-24 flex-none font-mono text-data font-medium',
                  TAG_CLASS[view.tone] ?? 'text-text-muted',
                )}
              >
                {view.tag}
              </span>

              <span className="flex min-w-0 flex-1 basis-full items-baseline gap-x-2 md:basis-auto">
                <span className="flex-none font-mono text-caption text-text-muted">
                  {stepOrdinal(step.stepId)}
                </span>
                <span
                  className={cx(
                    'min-w-0 truncate text-body',
                    isCurrent || isStepProblem(step.status)
                      ? 'font-medium text-text-strong'
                      : 'text-text',
                  )}
                >
                  {definition.label}
                </span>
                {definition.tool ? (
                  <span className="hidden min-w-0 truncate text-small text-text-muted lg:block">
                    {definition.tool}
                  </span>
                ) : null}
              </span>

              <span className="flex-none font-mono text-data text-text-muted">
                {/*
                  0초는 "0초"가 아니라 아직 기록되지 않은 것일 수 있다.
                  pending 단계는 항상 0이므로 대시로 둔다.
                */}
                {step.elapsedSeconds > 0 ? formatDuration(step.elapsedSeconds) : '—'}
              </span>

              {isCurrent ? (
                <span className="flex-none text-caption text-status-running-fg">
                  진행 중
                </span>
              ) : null}

              <ChevronRight
                size={12}
                strokeWidth={1.5}
                aria-hidden="true"
                className="flex-none text-ink-400"
              />

              {note ? (
                <span className="basis-full pl-24 text-caption text-text-muted">
                  {note}
                </span>
              ) : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
