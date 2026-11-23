import { ChevronRight } from 'lucide-react'

import { DiagnosticCounts } from '@/components/ui/DiagnosticNote'
import type { StatusTone } from '@/components/ui/StatusBadge'
import type { StepState } from '@/features/run-detail/api'
import { AiNoteCount } from '@/features/run-detail/components/AiNote'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import { byPriority, needsAttention } from '@/features/run-detail/diagnostics'
import { stepStatusDisplay } from '@/features/run-detail/stepDisplay'
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

  button은 머리 부분(번호·이름·상태·시간)만 감싼다. 진단 건수·AI 해설 건수는
  button 밖에 둔다 — 버튼 이름이 문단 몇 개가 되지 않게.

  ── 2026-11-23 장부형으로 정리 (개발판단기록 63장) ─────────────────────

  행마다 둥근 카드 · 단계 아이콘 타일 · 두 줄 설명이 있어 여덟 단계가 화면
  두 개 높이를 썼고, 설명은 이 Run의 사실이 아니라 단계의 성질이라 매번 같았다.
  행을 1px 구분선으로 나눈 장부로 바꾸고 설명은 상세 패널("이 단계에서 확인하는
  내용")에만 둔다. 선택 행은 옅은 브랜드 배경 + 1px 안쪽 테두리(왼쪽 막대 아님),
  실패 행은 옅은 실패 배경이다. 소요 시간은 줄바꿈하지 않고, 옆의 막대는 이
  Run에서 가장 오래 걸린 단계 대비 비율이다 — 서버가 준 elapsedSeconds만 쓰며
  진행률이나 남은 시간이 아니다.
*/

/**
 * 상세 패널의 DOM id. 목록의 각 행과 진행 표시가 aria-controls로 가리킨다.
 */
export const STEP_DETAIL_PANEL_ID = 'step-detail-panel'

/** 상태 글자색. 아이콘 + 글자 + 색을 함께 쓴다 — 색만으로 말하지 않는다. */
const STATUS_TEXT: Record<StatusTone, string> = {
  idle: 'text-text-muted',
  running: 'text-status-running-fg',
  success: 'text-status-success-fg',
  // "완료 (경고)"는 끝난 단계다. 경고 색은 아이콘·글자와 아래 진단 줄이 말한다.
  warning: 'text-status-warning-fg',
  failure: 'text-status-failure-fg',
  cancelled: 'text-status-cancelled-fg',
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
  const longest = Math.max(0, ...steps.map((step) => step.elapsedSeconds))
  return (
    <ul className="flex flex-col divide-y divide-border-subtle border-y border-border-subtle">
      {steps.map((step) => {
        const display = stepStatusDisplay(step.status, terminal, step.execution)
        const StatusIcon = display.icon
        const definition = describeStep(step.stepId)
        const selected = step.stepId === selectedStepId
        const isCurrent = step.stepId === currentStepId
        const notRun = isNotRun(step.status, terminal, step.execution)
        const failed = step.status === 'failed'
        const diagnostics = [...(diagnosticsByStep.get(step.stepId) ?? [])].sort(byPriority)
        // 진단을 아직 구조화해서 받지 못한 동안(실행 중)의 대체 표시. 중립으로 둔다.
        const rawNote = diagnostics.length === 0 ? step.messages[0] : undefined
        const aiCount = aiNoteCountByStep?.get(step.stepId) ?? 0
        const hasDuration = step.elapsedSeconds > 0
        const duration = hasDuration ? formatDuration(step.elapsedSeconds) : '—'
        const share = hasDuration && longest > 0 ? step.elapsedSeconds / longest : 0
        const hasNotes = diagnostics.length > 0 || Boolean(rawNote) || aiCount > 0

        return (
          <li
            key={step.stepId}
            className={cx(
              failed && 'bg-status-failure-bg',
              selected && (failed ? 'ring-1 ring-fill-failure ring-inset' : 'bg-brand-faint ring-1 ring-brand ring-inset'),
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(step.stepId)}
              aria-current={selected ? 'true' : undefined}
              aria-controls={STEP_DETAIL_PANEL_ID}
              className={cx(
                'grid min-h-11 w-full grid-cols-[2rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1 px-3 text-left focus-visible:[outline-offset:-2px] md:grid-cols-[2rem_minmax(0,1fr)_auto]',
                hasNotes ? 'pt-2.5 pb-1' : 'py-2.5',
                !selected && !failed && 'hover:bg-sunken',
              )}
            >
              <span className="font-mono text-caption text-text-muted">{stepOrdinal(step.stepId)}</span>

              <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <span
                  className={cx(
                    'min-w-0 text-body',
                    notRun ? 'text-text' : 'text-text-strong',
                    (selected || isCurrent || failed || needsAttention(diagnostics)) && 'font-semibold',
                  )}
                >
                  {definition.label}
                </span>
                {isCurrent && !terminal ? (
                  <span className="text-caption text-status-running-fg">현재 단계</span>
                ) : null}
              </span>

              {/* 좁은 화면: 상태·시간은 이름 아래 줄(둘째 열)로 내려간다. */}
              <span className="col-start-2 flex items-center gap-3 md:col-start-auto">
                <span
                  className={cx(
                    'inline-flex w-24 items-center gap-1 text-small font-medium whitespace-nowrap',
                    STATUS_TEXT[display.tone],
                  )}
                >
                  <StatusIcon size={14} strokeWidth={1.75} aria-hidden="true" className="flex-none" />
                  {display.label}
                </span>
                {/* 시간이 없는 단계(실행 안 됨·0초)는 빈 막대를 그리지 않는다 — 0으로 읽힌다. */}
                <span aria-hidden="true" className="hidden w-16 md:block">
                  {share > 0 ? (
                    <span className="block h-1.5 overflow-hidden rounded-sm bg-ink-100">
                      <span
                        className="block h-full rounded-sm bg-ink-400"
                        style={{ width: `${Math.max(4, Math.round(share * 100))}%` }}
                      />
                    </span>
                  ) : null}
                </span>
                {/* 폭 고정 — 행마다 시간의 x좌표가 같아야 세로로 훑어 읽힌다. 0초는 대시. */}
                <span className="ml-auto w-20 text-right font-mono text-data whitespace-nowrap text-text-muted tabular-nums">
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

            {hasNotes ? (
              <div className="flex flex-col gap-1 pr-3 pb-2.5 pl-[3rem]">
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
