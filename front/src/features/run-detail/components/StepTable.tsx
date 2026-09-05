import { ChevronRight } from 'lucide-react'

import { DiagnosticNote } from '@/components/ui/DiagnosticNote'
import type { StepState } from '@/features/run-detail/api'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import { byPriority, needsAttention } from '@/features/run-detail/diagnostics'
import { describeStepStatus } from '@/features/run-detail/stepStatus'
import { formatDuration } from '@/features/runs/time'
import { describeStep, stepOrdinal } from '@/registries/steps'
import { cx } from '@/lib/cx'

/*
  단계 목록.

  시안 근거 (docs/design/pipeline-tab.html · 단계 목록)
    1px 테두리 컨테이너 · 행마다 하단 1px ink-100 · 행 좌측 상태 rule
    선택된 행은 옅은 배경

  ── 시안·이전 구현과 달라진 점, 그리고 이유 ────────────────────────────

  1. 상태를 왼쪽 mono TAG 열(COMPLETED / RUNNING)에서 오른쪽 한국어 텍스트로
     옮겼다. 104px 대문자 영문 태그가 행마다 왼쪽 끝에 서 있으면 사용자가
     가장 먼저 읽는 것이 단계 이름이 아니라 상태 어휘가 된다. 사용자가
     알아야 할 큰 상태는 "완료 / 진행 중 / 실패"뿐이고, 그것은 이름 옆에
     조용히 있으면 된다.

  2. 각 행에 단계 설명(purpose)을 한 줄 둔다. registries/steps.ts가 갖는
     Layer 1이며, 이번 Run의 결과가 아니라 단계의 성질이다. 실제 측정값과
     구분되도록 색과 크기를 낮춰 둔다.

  3. 진단(경고·복구·참고·실패)을 행 안에 펼친다. 이전에는 messages[0]만
     회색 caption 한 줄로 보여줘서, core step의 실패와 단순 안내가 같은
     회색으로 나왔다. 무엇이 문제이고 무엇이 참고인지가 목록에서 바로
     읽혀야 한다.

  진단은 상태와 다른 축이다. 한 단계는 "완료"이면서 동시에 "확인 필요 1건"일
  수 있다. 그래서 상태 텍스트 하나에 그것을 합치지 않는다.

  ── 클릭 대상 ─────────────────────────────────────────────────────────

  button은 머리줄 하나만 감싼다. 설명과 진단까지 button 안에 넣으면 스크린
  리더가 읽는 이름이 문단 몇 개가 되고, 무엇을 누르는 것인지 알 수 없게
  된다. 대신 button 끝에 "상세"라는 보이는 라벨을 둬서 무엇이 열리는지
  예측할 수 있게 했다 — 행 전체가 이유 없이 눌리는 화면을 만들지 않는다.
*/

/**
 * 상세 레일의 DOM id.
 *
 * 표의 각 행과 레일은 서로 다른 곳에 렌더링되므로 aria-controls로 연결한다.
 * 한 페이지에 레일은 하나뿐이라 상수 하나로 충분하다.
 */
export const STEP_DETAIL_PANEL_ID = 'step-detail-panel'

/** 행 좌측 1px rule. 시안은 3px이지만 CLAUDE.md 24장이 두꺼운 accent bar를 금지한다. */
const RULE_CLASS: Record<string, string> = {
  idle: 'border-l-border',
  running: 'border-l-fill-running',
  success: 'border-l-fill-success',
  warning: 'border-l-fill-warning',
  failure: 'border-l-fill-failure',
  cancelled: 'border-l-fill-skip',
}

const STATUS_TEXT_CLASS: Record<string, string> = {
  idle: 'text-text-muted',
  running: 'text-status-running-fg',
  success: 'text-status-success-fg',
  // warning도 사용자에게는 완료다. 성공과 같은 색을 쓴다.
  warning: 'text-status-success-fg',
  failure: 'text-status-failure-fg',
  cancelled: 'text-text-muted',
}

export interface StepTableProps {
  steps: StepState[]
  /** 지금 실행 중인 단계. backend의 currentStep. */
  currentStepId: string | null
  selectedStepId: string | null
  /** stepId -> 진단. 실행이 끝나기 전에는 비어 있다(diagnostics.ts 참고). */
  diagnosticsByStep: Map<string, RunDiagnostic[]>
  onSelect: (stepId: string) => void
}

export function StepTable({
  steps,
  currentStepId,
  selectedStepId,
  diagnosticsByStep,
  onSelect,
}: StepTableProps) {
  return (
    <ul className="overflow-hidden rounded-md border border-border bg-surface">
      {steps.map((step) => {
        const view = describeStepStatus(step.status)
        const definition = describeStep(step.stepId)
        const selected = step.stepId === selectedStepId
        const isCurrent = step.stepId === currentStepId
        const diagnostics = [...(diagnosticsByStep.get(step.stepId) ?? [])].sort(
          byPriority,
        )
        /*
          진단을 아직 구조화해서 받지 못한 동안(실행 중)의 대체 표시.
          backend가 준 문장을 그대로 한 줄 보여주되 중립적으로 둔다 —
          "확인 필요"인지 "참고"인지 단정하지 않는다.
        */
        const rawNote = diagnostics.length === 0 ? step.messages[0] : undefined

        return (
          <li
            key={step.stepId}
            className={cx(
              'border-b border-border-subtle border-l last:border-b-0',
              RULE_CLASS[view.tone] ?? 'border-l-border',
              selected && 'bg-brand-faint',
            )}
          >
            {/*
              머리줄 — 이름과 상태. 사용자가 가장 먼저 읽는 줄이자 클릭 대상.

              aria-controls로 이 버튼이 무엇을 여는지 알린다. 레일은 이 표 밖에
              있으므로 그것이 없으면 "펼쳐짐"이라는 상태만 들리고 무엇이
              펼쳐졌는지는 알 수 없다.
            */}
            <button
              type="button"
              onClick={() => onSelect(step.stepId)}
              aria-expanded={selected}
              aria-controls={STEP_DETAIL_PANEL_ID}
              className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-4 pt-3 text-left hover:bg-brand-faint focus-visible:[outline-offset:-2px]"
            >
              <span className="flex-none font-mono text-caption text-text-muted">
                {stepOrdinal(step.stepId)}
              </span>
              <span
                className={cx(
                  'min-w-0 text-body text-text-strong',
                  (isCurrent || needsAttention(diagnostics)) && 'font-medium',
                )}
              >
                {definition.label}
              </span>

              <span className="ml-auto flex flex-none items-baseline gap-3">
                {/*
                  폭을 고정한다. "53초"와 "29분 07초"가 섞이면 행마다 상태
                  텍스트의 x좌표가 달라져 세로로 훑어 읽기 어렵다.
                  0초는 "0초"가 아니라 아직 기록되지 않은 것일 수 있으므로
                  대시로 둔다.
                */}
                <span className="w-20 text-right font-mono text-data text-text-muted">
                  {step.elapsedSeconds > 0
                    ? formatDuration(step.elapsedSeconds)
                    : '—'}
                </span>
                <span
                  className={cx(
                    'text-body',
                    STATUS_TEXT_CLASS[view.tone] ?? 'text-text-muted',
                  )}
                >
                  {/*
                    step status가 warning이어도 사용자에게는 "완료"다.
                    경고의 존재는 아래 진단 줄이 말하므로, 큰 상태에 괄호를
                    덧붙이면 같은 정보를 두 번 다르게 말하게 된다.
                  */}
                  {step.status === 'warning' ? '완료' : view.label}
                </span>
                <span className="flex items-center gap-0.5 text-small text-text-muted">
                  상세
                  <ChevronRight
                    size={14}
                    strokeWidth={1.5}
                    aria-hidden="true"
                    className={selected ? 'text-brand' : 'text-ink-400'}
                  />
                </span>
              </span>
            </button>

            {/*
              registry가 모르는 단계이고 이번 실행에서 아무 일도 없었다면
              그릴 것이 없다. 빈 div에 padding만 남기지 않는다.
            */}
            {definition.purpose || diagnostics.length > 0 || rawNote ? (
              <div className="flex flex-col gap-3 px-4 pt-1 pb-3">
                {/* Layer 1 — 이 단계가 무엇을 왜 하는지. Run과 무관한 설명. */}
                {definition.purpose ? (
                  <p className="max-w-prose text-small text-text-muted">
                    {definition.purpose}
                  </p>
                ) : null}

                {/* Layer 2 — 이번 Run에서 실제로 있었던 일. */}
                {diagnostics.map((diagnostic) => (
                  <DiagnosticNote
                    key={diagnostic.key}
                    diagnostic={diagnostic}
                    compact
                  />
                ))}

                {rawNote ? (
                  <p className="text-caption text-text-muted">{rawNote}</p>
                ) : null}
              </div>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
