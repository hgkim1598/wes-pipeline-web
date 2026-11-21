import { ChevronRight, Clock } from 'lucide-react'

import { DiagnosticCounts } from '@/components/ui/DiagnosticNote'
import type { StatusTone } from '@/components/ui/StatusBadge'
import type { StepState } from '@/features/run-detail/api'
import { AiNoteCount } from '@/features/run-detail/components/AiNote'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import { byPriority, needsAttention } from '@/features/run-detail/diagnostics'
import { stepStatusDisplay } from '@/features/run-detail/stepDisplay'
import { stepIcon } from '@/features/run-detail/stepIcons'
import { isNotRun } from '@/features/run-detail/stepView'
import { formatDuration } from '@/features/runs/time'
import { describeStep, stepOrdinal } from '@/registries/steps'
import { cx } from '@/lib/cx'

/*
  파이프라인 워크스페이스의 단계 목록 (개발판단기록 40 · 41장).

  ── 2026-11-20 승인 시안 반영 ──────────────────────────────────────────

  목록이 화면의 약 60%를 쓰고, 행마다 단계 아이콘 · 번호 · 이름 · 단계 설명
  (registries/steps의 purpose — 이 Run의 결과가 아니라 단계의 성질) · 상태 ·
  소요 시간 · 펼침 표시를 둔다. 실패한 단계는 옅은 실패 배경과 테두리로
  강조한다. 선택된 행은 1px 브랜드 테두리(실패 행은 실패 테두리)다. glow는
  쓰지 않는다.

  ── 상태 ──────────────────────────────────────────────────────────────

  아이콘 + 글자 + 색. 끝난 실행에서 시작되지 않은 단계는 "실행 안 됨"이며
  완료로 쓰지 않는다(stepView.ts). warning은 "완료"이고 경고는 아래 진단 줄이
  말한다.

  ── 클릭 대상 ─────────────────────────────────────────────────────────

  button은 머리 부분(아이콘·번호·이름·설명·상태·시간)만 감싼다. 진단 건수·AI
  해설 건수는 button 밖에 둔다 — 버튼 이름이 문단 몇 개가 되지 않게.
*/

/**
 * 상세 패널의 DOM id. 목록의 각 행과 진행 표시가 aria-controls로 가리킨다.
 */
export const STEP_DETAIL_PANEL_ID = 'step-detail-panel'

const PILL_CLASS: Record<StatusTone, string> = {
  idle: 'bg-status-idle-bg text-status-idle-fg',
  running: 'bg-status-running-bg text-status-running-fg',
  success: 'bg-status-success-bg text-status-success-fg',
  // warning도 사용자에게는 완료다. 성공과 같은 색을 쓴다.
  warning: 'bg-status-success-bg text-status-success-fg',
  failure: 'bg-status-failure-bg text-status-failure-fg',
  cancelled: 'bg-status-cancelled-bg text-status-cancelled-fg',
}

export interface StepTableProps {
  /** `execution`은 backend 장부 값(factApplicability.withLedger). 없으면 예전 규칙. */
  steps: (StepState & { execution?: string })[]
  /** 지금 실행 중인 단계. backend의 currentStep. */
  currentStepId: string | null
  selectedStepId: string | null
  /** 실행이 끝났는가. 끝난 실행의 pending은 "실행 안 됨"이다. */
  terminal: boolean
  /** stepId -> 진단. 실행이 끝나기 전에는 비어 있다(diagnostics.ts 참고). */
  diagnosticsByStep: Map<string, RunDiagnostic[]>
  onSelect: (stepId: string) => void
  /** stepId -> 그 단계에 확인 가능하게 연결된 AI 해설 수. 문장은 상세 패널에 있다. */
  aiNoteCountByStep?: ReadonlyMap<string, number>
}

export function StepTable({
  steps,
  currentStepId,
  selectedStepId,
  terminal,
  diagnosticsByStep,
  onSelect,
  aiNoteCountByStep,
}: StepTableProps) {
  return (
    <ul className="flex flex-col gap-2">
      {steps.map((step) => {
        const display = stepStatusDisplay(step.status, terminal, step.execution)
        const StatusIcon = display.icon
        const StepIcon = stepIcon(step.stepId)
        const definition = describeStep(step.stepId)
        const selected = step.stepId === selectedStepId
        const isCurrent = step.stepId === currentStepId
        const notRun = isNotRun(step.status, terminal, step.execution)
        const failed = step.status === 'failed'
        const diagnostics = [...(diagnosticsByStep.get(step.stepId) ?? [])].sort(byPriority)
        // 진단을 아직 구조화해서 받지 못한 동안(실행 중)의 대체 표시. 중립으로 둔다.
        const rawNote = diagnostics.length === 0 ? step.messages[0] : undefined
        const aiCount = aiNoteCountByStep?.get(step.stepId) ?? 0
        const duration = step.elapsedSeconds > 0 ? formatDuration(step.elapsedSeconds) : '—'
        const pill = (
          <span
            className={cx(
              'inline-flex items-center gap-1 rounded-pill px-2.5 py-0.5 text-small font-medium whitespace-nowrap',
              PILL_CLASS[display.tone],
            )}
          >
            <StatusIcon size={13} strokeWidth={1.75} aria-hidden="true" className="flex-none" />
            {display.label}
          </span>
        )

        return (
          <li
            key={step.stepId}
            className={cx(
              'rounded-lg border',
              failed ? 'border-status-failure-bd bg-status-failure-bg' : 'border-border bg-surface',
              selected && (failed ? 'border-fill-failure shadow-card' : 'border-brand bg-brand-faint shadow-card'),
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(step.stepId)}
              aria-current={selected ? 'true' : undefined}
              aria-controls={STEP_DETAIL_PANEL_ID}
              className={cx(
                'grid w-full grid-cols-[2.25rem_minmax(0,1fr)_auto] items-center gap-x-3 rounded-lg px-3 text-left focus-visible:[outline-offset:-2px] md:px-4',
                diagnostics.length > 0 || rawNote || aiCount > 0 ? 'pt-3 pb-1.5' : 'py-3',
                !selected && !failed && 'hover:bg-brand-faint',
              )}
            >
              <span
                aria-hidden="true"
                className={cx(
                  'flex size-9 items-center justify-center rounded-md border',
                  failed
                    ? 'border-status-failure-bd bg-surface text-status-failure-fg'
                    : notRun
                      ? 'border-border-subtle bg-sunken text-text-muted'
                      : 'border-border-subtle bg-sunken text-text',
                )}
              >
                <StepIcon size={18} strokeWidth={1.5} />
              </span>

              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="flex items-baseline gap-2">
                  <span className="flex-none font-mono text-caption text-text-muted">
                    {stepOrdinal(step.stepId)}
                  </span>
                  <span
                    className={cx(
                      'min-w-0 text-body',
                      notRun ? 'text-text' : 'text-text-strong',
                      (selected || isCurrent || failed || needsAttention(diagnostics)) &&
                        'font-semibold',
                    )}
                  >
                    {definition.label}
                  </span>
                  {isCurrent && !terminal ? (
                    <span className="text-caption text-status-running-fg">현재 단계</span>
                  ) : null}
                </span>
                {definition.purpose ? (
                  <span className="line-clamp-2 text-small text-text-muted">
                    {definition.purpose}
                  </span>
                ) : null}
                {/* 좁은 화면: 상태와 시간을 설명 아래에 둔다. */}
                <span className="mt-1 flex items-center gap-3 md:hidden">
                  {pill}
                  <span className="inline-flex items-center gap-1 font-mono text-caption text-text-muted">
                    <Clock size={12} strokeWidth={1.5} aria-hidden="true" />
                    {duration}
                  </span>
                </span>
              </span>

              <span className="flex items-center gap-3">
                <span className="hidden md:inline-flex">{pill}</span>
                {/* 폭 고정 — 행마다 시간의 x좌표가 같아야 세로로 훑어 읽힌다. 0초는 대시. */}
                <span className="hidden w-16 items-center justify-end gap-1 font-mono text-data text-text-muted md:inline-flex">
                  <Clock size={12} strokeWidth={1.5} aria-hidden="true" />
                  {duration}
                </span>
                <ChevronRight
                  size={16}
                  strokeWidth={1.5}
                  aria-hidden="true"
                  className={selected ? 'text-brand' : 'text-ink-400'}
                />
              </span>
            </button>

            {diagnostics.length > 0 || rawNote || aiCount > 0 ? (
              <div className="flex flex-col gap-1 pr-4 pb-3 pl-[3.75rem] md:pl-[4.25rem]">
                <DiagnosticCounts diagnostics={diagnostics} />
                {rawNote ? <p className="text-caption text-text-muted">{rawNote}</p> : null}
                {/* AI 해설은 표시만. 문장은 상세 패널에 있다. */}
                <AiNoteCount count={aiCount} />
              </div>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
