import { useEffect, useRef } from 'react'
import { Activity, Ban, Check, CircleHelp, X } from 'lucide-react'

import type { StepState } from '@/features/run-detail/api'
import { stepStatusDisplay } from '@/features/run-detail/stepDisplay'
import { isNotRun, isUndetermined } from '@/features/run-detail/stepView'
import { STEP_DETAIL_PANEL_ID } from '@/features/run-detail/components/StepTable'
import { describeStep, stepOrdinal } from '@/registries/steps'
import { cx } from '@/lib/cx'
import { revealScrollLeft } from '@/lib/scrollReveal'

/*
  가로 단계 진행 표시 (2026-11-20 승인 시안, 헤더의 단계 띠를 파이프라인 탭으로 옮김).

  점 하나가 단계 하나다. 상태는 점의 모양(채움·아이콘)과 아래 글자(화면 낭독기용
  sr-only 포함)로 말한다 — 색 하나로 구분하지 않는다. 시작되지 않은 단계는
  빈 원이고, 끝난 실행이면 "실행 안 됨"이다(stepView.ts).

  점을 누르면 그 단계를 선택한다(목록과 같은 선택, URL ?step=).

  개요 탭에서도 같은 띠를 쓴다(2026-11-23, ref 1의 "어디서 멈췄나" 띠). 거기서는
  점을 누르면 파이프라인 탭의 그 단계로 간다 — 같은 화면에 상세 패널이 없으므로
  `controlsDetail={false}`로 aria-controls를 빼고, 실제 선택이 아닌 강조이므로
  aria-current도 쓰지 않는다.

  좁은 화면(md 48rem 미만 — tokens.css에 sm 구간이 없다, 2026-11-23 · 개발판단기록 54장). 예전에는 띠에 36rem 최소
  폭이 있어 390px에서 뒤쪽 단계가 가로 스크롤 밖에 숨었고, 스크롤할 수 있다는
  단서도 없었다(gradient 페이드는 CLAUDE.md 23장 금지). 이제 md 미만에서는
  최소 폭을 없애고 점·번호만 그린다 — 8단계가 모두 한 줄에 보인다. 단계 이름은
  버튼의 화면 낭독기용 글자로 남고, 강조 단계의 이름·상태는 띠 아래 한 줄로
  보인다. md 이상에서는 예전과 같다.

  넓은 화면에서도 컨테이너가 띠보다 좁으면 가로 스크롤이 생긴다. 다른 곳에서
  단계를 고르면 그 점이 보이도록 컨테이너의 scrollLeft만 맞춘다(scrollReveal.ts —
  페이지 세로 스크롤은 건드리지 않고, 이미 보이면 그대로 둔다).
*/
export function PipelineStepper({
  steps,
  selectedStepId,
  terminal,
  onSelect,
  controlsDetail = true,
}: {
  /** `execution`은 backend 장부 값(factApplicability.withLedger). 없으면 예전 규칙. */
  steps: (StepState & { execution?: string })[]
  selectedStepId: string | null
  terminal: boolean
  onSelect: (stepId: string) => void
  /** 같은 화면에 단계 상세 패널이 있는가(파이프라인 탭). 개요 탭은 false. */
  controlsDetail?: boolean
}) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller || !selectedStepId) return
    const item = scroller.querySelector<HTMLElement>(
      `[data-step-id="${CSS.escape(selectedStepId)}"]`,
    )
    if (!item) return
    scroller.scrollLeft = revealScrollLeft(
      scroller.scrollLeft,
      scroller.clientWidth,
      item.offsetLeft,
      item.offsetWidth,
    )
  }, [selectedStepId])

  const emphasized = steps.find((s) => s.stepId === selectedStepId)
  const emphasizedDisplay = emphasized
    ? stepStatusDisplay(emphasized.status, terminal, emphasized.execution)
    : null

  return (
    <div className="flex flex-col gap-2">
      {/* relative: 항목의 offsetLeft가 이 컨테이너 기준이 되게 한다(스크롤 맞춤). */}
      <div ref={scrollerRef} className="relative overflow-x-auto pb-1">
        <ol aria-label="단계 진행" className="flex items-start md:min-w-[36rem]">
          {steps.map((step, index) => {
            const display = stepStatusDisplay(step.status, terminal, step.execution)
            const selected = step.stepId === selectedStepId
            const prevDone =
              index > 0 && ['completed', 'warning', 'failed'].includes(steps[index - 1].status)
            return (
              <li
                key={step.stepId}
                data-step-id={step.stepId}
                className="relative flex min-w-0 flex-1 flex-col items-center"
              >
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
                  aria-current={selected && controlsDetail ? 'step' : undefined}
                  aria-controls={controlsDetail ? STEP_DETAIL_PANEL_ID : undefined}
                  className="relative flex flex-col items-center gap-1 rounded-md px-1 pb-1 focus-visible:[outline-offset:-2px]"
                >
                  <Dot
                    status={step.status}
                    notRun={isNotRun(step.status, terminal, step.execution)}
                    undetermined={isUndetermined(step.execution)}
                  />
                  <span
                    className={cx(
                      'font-mono text-caption',
                      // 좁은 화면에서는 이름이 없으므로 강조 단계의 번호가 선택 표시다.
                      selected ? 'font-semibold text-text-strong md:font-normal md:text-text-muted' : 'text-text-muted',
                    )}
                  >
                    {stepOrdinal(step.stepId)}
                  </span>
                  <span className="sr-only md:hidden">{describeStep(step.stepId).label}</span>
                  <span
                    className={cx(
                      'hidden rounded-sm px-1.5 text-center text-caption whitespace-nowrap md:inline-block',
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
      {/*
        좁은 화면 전용: 강조 단계의 이름·상태. 버튼이 이미 같은 내용을 화면 낭독기에
        주므로 aria-hidden이다.
      */}
      {emphasized && emphasizedDisplay ? (
        <p aria-hidden="true" className="flex items-baseline gap-2 text-small md:hidden">
          <span className="font-mono text-caption text-text-muted">{stepOrdinal(emphasized.stepId)}</span>
          <span className="font-medium text-text-strong">{describeStep(emphasized.stepId).label}</span>
          <span className="text-text-muted">{emphasizedDisplay.label}</span>
        </p>
      ) : null}
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
