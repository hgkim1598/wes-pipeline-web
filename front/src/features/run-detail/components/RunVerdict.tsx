import { ChevronRight, CircleCheck, OctagonX, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'

import type { JobState, Results, StepState } from '@/features/run-detail/api'
import type { RunIssueCounts } from '@/features/run-detail/components/RunHeader'
import { PipelineStepper } from '@/features/run-detail/components/PipelineStepper'
import { describePosition as positionOf } from '@/features/run-detail/runPosition'
import type { JobListItem } from '@/features/runs/api'
import { durationBetween } from '@/features/runs/time'
import { formatCount } from '@/lib/number'
import { describeStep } from '@/registries/steps'

/*
  개요 탭의 첫 면 (2026-11-23 UI 정리, 개발판단기록 63장).

  이전에는 같은 무게의 네 칸 카드(지금 위치 · 진행 · 문제 · 실행 조건)와
  별도의 단계 띠 카드가 위에 있고, 실제 측정값(평균 깊이·변이 후보 수)은
  화면 아래쪽 결과 블록에서야 나왔다. 보고서처럼 "이 실행은 어떻게 끝났고
  무엇을 쟀나"를 한 면에서 먼저 말하도록 세 줄로 묶었다.

    1. 판정 줄   멈춘 위치·끝난 상태(runPosition) + 실패·확인 필요 건수(글자+아이콘)
                 오른쪽에 실행 조건(모드 · 소요 · 캡처 키트)
    2. 측정 줄   /results가 값을 줄 때만. 숫자와 단위만 쓰고 충분/부족 같은
                 판단어는 붙이지 않는다(CoverageSection과 같은 원칙). 변이 수는
                 필터 적용 여부를 숫자 옆에 같이 쓴다 — 그 숫자의 정의다.
    3. 단계 줄   PipelineStepper(파이프라인 탭과 같은 component). 진행 비율은
                 실행 중일 때만 "남은 시간이 아님"을 덧붙인다.

  카드 안의 카드를 만들지 않는다: 한 면에 1px 구분선으로 줄을 나눈다.
*/

export interface RunVerdictProps {
  job: JobState
  listItem: JobListItem | undefined
  issues: RunIssueCounts
  results: Results | undefined
  steps: (StepState & { execution?: string })[]
  selectedStepId: string | null
  terminal: boolean
  runPath: string
  onSelectStep: (stepId: string) => void
}

const RUN_MODE_LABEL: Record<string, string> = {
  full: '전체 분석',
  check_only: '사전 점검',
}

/** 20X가 있으면 그것을, 없으면 측정 줄에 breadth를 넣지 않는다. 키는 mosdepth가 정한다. */
const HEADLINE_BREADTH_KEY = '20X'

export function RunVerdict({
  job,
  listItem,
  issues,
  results,
  steps,
  selectedStepId,
  terminal,
  runPath,
  onSelectStep,
}: RunVerdictProps) {
  const position = positionOf(job, (stepId) => describeStep(stepId).label)
  const elapsed = durationBetween(job.startedAt, job.finishedAt)
  const completed = job.steps.filter(
    (step) => step.status !== 'pending' && step.status !== 'running',
  ).length
  const total = job.steps.length
  const measurements = results ? collectMeasurements(results) : []

  return (
    <section
      aria-labelledby="run-verdict-heading"
      className="flex flex-col divide-y divide-border-subtle rounded-lg border border-border bg-surface shadow-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3 px-5 py-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 id="run-verdict-heading" className="text-h3 font-semibold text-text-strong">
            {position.headline}
          </h2>
          {position.detail ? <p className="text-small text-text-muted">{position.detail}</p> : null}
          <IssueLine issues={issues} />
        </div>
        <dl className="grid flex-none grid-cols-[auto_auto] gap-x-4 gap-y-1 text-small">
          <dt className="text-text-muted">실행 조건</dt>
          <dd className="text-text-strong">{RUN_MODE_LABEL[job.runMode] ?? job.runMode}</dd>
          {elapsed ? (
            <>
              <dt className="text-text-muted">소요</dt>
              <dd className="font-mono text-text-strong">{elapsed}</dd>
            </>
          ) : null}
          {listItem?.captureKitId ? (
            <>
              <dt className="text-text-muted">캡처 키트</dt>
              <dd className="font-mono text-text-strong">{listItem.captureKitId}</dd>
            </>
          ) : null}
        </dl>
      </div>

      {measurements.length > 0 ? (
        <dl
          aria-label="이 실행에서 측정된 값"
          className="grid grid-cols-2 gap-y-4 px-5 py-4 md:grid-cols-4"
        >
          {measurements.map((m) => (
            <div key={m.term} className="flex min-w-0 flex-col gap-1 md:not-first:border-l md:not-first:border-border-subtle md:not-first:pl-5">
              <dt className="text-caption text-text-muted">{m.term}</dt>
              <dd className="flex flex-col">
                <span className="font-mono text-h2 font-semibold tracking-tight text-text-strong">
                  {m.value}
                  {m.unit ? <span className="pl-0.5 text-body font-normal text-text-muted">{m.unit}</span> : null}
                </span>
                {m.note ? <span className="text-caption text-text-muted">{m.note}</span> : null}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {steps.length > 0 ? (
        <div className="flex flex-col gap-3 px-5 py-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="text-small text-text">
              <span className="font-mono font-semibold text-text-strong">
                {completed}/{total}
              </span>{' '}
              단계 끝남
              {!terminal ? (
                <span className="text-text-muted"> · 완료 비율이며 남은 시간이 아닙니다</span>
              ) : null}
            </p>
            <Link
              to={`${runPath}/pipeline`}
              className="inline-flex min-h-6 items-center gap-1 text-small text-text-muted no-underline hover:text-brand hover:underline"
            >
              단계별 상세 보기
              <ChevronRight size={14} strokeWidth={1.5} aria-hidden="true" />
            </Link>
          </div>
          <PipelineStepper
            steps={steps}
            selectedStepId={selectedStepId}
            terminal={terminal}
            onSelect={onSelectStep}
            controlsDetail={false}
          />
        </div>
      ) : null}
    </section>
  )
}

function IssueLine({ issues }: { issues: RunIssueCounts }) {
  if (issues.failures === 0 && issues.attention === 0) {
    return (
      <p className="flex items-center gap-1.5 text-small text-text">
        <CircleCheck size={15} strokeWidth={1.75} aria-hidden="true" className="text-text-muted" />
        기록된 실패·확인 필요 없음
        {issues.notes > 0 ? <span className="text-text-muted"> · 참고·자동 처리 {issues.notes}건</span> : null}
      </p>
    )
  }
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-small">
      {issues.failures > 0 ? (
        <span className="inline-flex items-center gap-1.5 font-medium text-status-failure-fg">
          <OctagonX size={15} strokeWidth={1.75} aria-hidden="true" />
          실패 {issues.failures}
        </span>
      ) : null}
      {issues.attention > 0 ? (
        <span className="inline-flex items-center gap-1.5 font-medium text-status-warning-fg">
          <TriangleAlert size={15} strokeWidth={1.75} aria-hidden="true" />
          확인 필요 {issues.attention}
        </span>
      ) : null}
      {issues.notes > 0 ? <span className="text-text-muted">참고·자동 처리 {issues.notes}</span> : null}
    </p>
  )
}

interface Measurement {
  term: string
  value: string
  unit?: string
  note?: string
}

/** 응답에 값이 있는 것만. null은 칸을 만들지 않는다(— 칸을 늘어놓지 않는다). */
function collectMeasurements(results: Results): Measurement[] {
  const out: Measurement[] = []
  const cov = results.coverage
  if (cov) {
    if (cov.meanTargetDepth !== null) {
      out.push({ term: '평균 타깃 깊이', value: cov.meanTargetDepth.toFixed(2), unit: '×' })
    }
    const breadth = cov.breadth[HEADLINE_BREADTH_KEY]
    if (breadth !== undefined) {
      out.push({ term: `${HEADLINE_BREADTH_KEY} 이상 염기`, value: breadth.toFixed(2), unit: '%' })
    }
    if (cov.zeroCoverageBasesPct !== null) {
      out.push({ term: '0× 염기', value: cov.zeroCoverageBasesPct.toFixed(2), unit: '%' })
    }
  }
  const vc = results.variantCalling
  if (vc && vc.rawVariantRecords !== null) {
    out.push({
      term: vc.filteringApplied ? '변이 기록' : '변이 후보 기록',
      value: formatCount(vc.rawVariantRecords),
      note: vc.filteringApplied ? '필터 적용' : '필터 적용 전',
    })
  }
  return out
}
