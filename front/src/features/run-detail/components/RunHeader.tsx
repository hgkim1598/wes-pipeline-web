import { ChevronLeft, Ban } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/Button'
import { CopyableId } from '@/components/ui/CopyableId'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { RunTape } from '@/components/ui/RunTape'
import type { RunTapeCell } from '@/components/ui/RunTape'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { JobState } from '@/features/run-detail/api'
import { PollingStatus } from '@/features/run-detail/components/PollingStatus'
import { describeStepStatus } from '@/features/run-detail/stepStatus'
import { toTapeCells } from '@/features/run-detail/tape'
import type { JobListItem } from '@/features/runs/api'
import { describeJobStatus, isTerminalStatus } from '@/features/runs/status'
import { durationBetween, formatDuration, formatTimestamp } from '@/features/runs/time'
import { describeStep } from '@/registries/steps'

/*
  Run 헤더.

  시안 근거 (docs/design/pipeline-tab.html · Run 헤더)
    ‹ 실행 목록 / 제목(display) / 배지 + RunTape(md) /
    "변이 검출 · 6/8단계 · 1시간 18분 경과" / 메타 한 줄 /
    mono run id + 복사 / 시작 시각 / "3초 전 갱신" / 우측 [분석 취소]
    상태 변형 V1~V4의 요약 문구 형태를 그대로 따랐다.

  시안과 다른 점 두 가지.

  1. 경과 시간을 실행 중에는 표시하지 않는다. 시안의 "1시간 18분 경과"는
     브라우저 시계로 startedAt과의 차이를 계산해야 나오는 값이고, 서버 시계와
     어긋나면 사용자가 확인할 수 없는 오차가 생긴다. terminal이면 서버가 준
     startedAt/finishedAt의 차이를 쓴다(둘 다 서버 값이라 정확하다).
  2. sampleId·captureKitId는 GET /api/jobs/{id}에 없다(backend/app/schemas.py의
     JobStateResponse). 목록 응답에는 있으므로 그 행을 함께 받아 채운다.
     없으면 표시하지 않는다 — 지어내지 않는다.
*/

export interface RunHeaderProps {
  job: JobState
  /** 목록 응답의 같은 job. sampleId·captureKitId·createdAt의 출처. */
  listItem: JobListItem | undefined
  polling: {
    updatedAt: number
    failureCount: number
    isFetching: boolean
  }
  onCancel: () => void
  isCancelling: boolean
  cancelError: unknown
  /**
   * 이 실행의 문제 건수. 페이지가 AttentionSection에 넘기는 것과 같은 출처에서
   * 센다 — 요약 띠와 본문의 숫자가 달라지면 안 된다.
   */
  issues: RunIssueCounts
}

export interface RunIssueCounts {
  failures: number
  attention: number
  /** 참고·자동 처리. 할 일은 아니지만 있었던 일이다. */
  notes: number
}

export function RunHeader({
  job,
  listItem,
  polling,
  onCancel,
  isCancelling,
  cancelError,
  issues,
}: RunHeaderProps) {
  const [confirmingCancel, setConfirmingCancel] = useState(false)

  const status = describeJobStatus(job.status)
  const terminal = isTerminalStatus(job.status)
  const completed = job.steps.filter(
    (step) => step.status !== 'pending' && step.status !== 'running',
  ).length
  const position = describePosition(job)
  const elapsed = durationBetween(job.startedAt, job.finishedAt)
  const started = formatTimestamp(job.startedAt)
  const sample = listItem?.sampleId ?? null

  return (
    <div className="flex flex-col gap-4 border-b border-border pb-6">
      <Link
        to="/runs"
        className="inline-flex min-h-6 items-center gap-1 self-start text-small text-text-muted no-underline hover:text-text hover:underline"
      >
        <ChevronLeft size={12} strokeWidth={1.5} aria-hidden="true" />
        실행 목록
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
              {job.profileId}
              {sample ? (
                <>
                  <span className="px-2 text-ink-400">·</span>
                  <code className="text-h1">{sample}</code>
                </>
              ) : null}
            </h1>
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <CopyableId value={job.runId} />
            {started ? (
              <span className="text-caption text-text-muted">
                <time dateTime={started.machine} title={started.full}>
                  {started.display}
                </time>{' '}
                시작
              </span>
            ) : null}
            <PollingStatus
              active={!terminal}
              updatedAt={polling.updatedAt}
              failureCount={polling.failureCount}
              isFetching={polling.isFetching}
            />
          </div>
        </div>

        {/*
          취소는 진행 중일 때만 보여준다. backend는 끝난 job에도 204를 주지만
          (api/jobs.py cancel_job) 누를 수 있는 버튼이 아무 일도 하지 않는 것은
          잘못된 안내다.
        */}
        {!terminal ? (
          <div className="flex flex-none flex-col items-end gap-2">
            {confirmingCancel ? (
              <div className="flex flex-col items-end gap-2">
                <span className="text-small text-text">
                  실행을 취소하면 되돌릴 수 없습니다.
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setConfirmingCancel(false)}
                  >
                    유지
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      setConfirmingCancel(false)
                      onCancel()
                    }}
                    disabled={isCancelling}
                  >
                    <Ban size={16} strokeWidth={1.5} aria-hidden="true" />
                    취소 확인
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                variant="danger"
                onClick={() => setConfirmingCancel(true)}
                disabled={isCancelling}
              >
                <Ban size={16} strokeWidth={1.5} aria-hidden="true" />
                {isCancelling ? '취소 요청 중' : '분석 취소'}
              </Button>
            )}
          </div>
        ) : null}
      </div>

      {/*
        실행 요약 띠 `[설계판단 2026-11-17]`

        시연에서 "지금 어디까지 왔고 무엇이 문제인가"를 한 줄로 말할 수 있게
        흩어져 있던 사실을 한 표면에 모은다. KPI 카드 네 장이 아니라 하나의
        표면 안의 정의 목록(dl)이다 — 값은 모두 backend 응답에서 오고, 없는
        값은 칸을 비우지 않고 "기록 없음"이라고 말한다.

        분석 모드와 캡처 키트는 **다른 필드**다 `[코드근거]`. runMode는
        full|check_only, captureKitId는 캡처 키트 registry 식별자라 라벨을 따로
        붙인다(이전에 `·`로 이어 붙여 모드의 일부처럼 읽혔다).
      */}
      <dl className="grid grid-cols-1 rounded-md border border-border bg-surface sm:grid-cols-2 lg:grid-cols-4">
        <Fact term="지금 위치">
          <span className="text-body font-medium text-text-strong">
            {position.headline}
          </span>
          {position.detail ? (
            <span className="text-caption text-text-muted">{position.detail}</span>
          ) : null}
        </Fact>
        <Fact term="진행">
          <span className="text-body text-text-strong">
            <span className="font-mono text-data">
              {completed} / {job.steps.length}
            </span>{' '}
            단계 끝남
          </span>
          <span className="text-caption text-text-muted">
            완료 비율이며 남은 시간이 아닙니다
          </span>
        </Fact>
        <Fact term="문제">
          <span className="text-body text-text-strong">
            {issues.failures > 0 || issues.attention > 0 ? (
              <>
                <span className={issues.failures > 0 ? 'text-status-failure-fg' : undefined}>
                  실패 {issues.failures}
                </span>
                <span className="px-1.5 text-ink-400">·</span>
                <span className={issues.attention > 0 ? 'text-status-warning-fg' : undefined}>
                  확인 필요 {issues.attention}
                </span>
              </>
            ) : (
              '기록된 실패·확인 필요 없음'
            )}
          </span>
          {issues.notes > 0 ? (
            <span className="text-caption text-text-muted">
              참고·자동 처리 {issues.notes}건
            </span>
          ) : null}
        </Fact>
        <Fact term="실행 조건">
          <span className="text-body text-text-strong">
            {job.runMode === 'full'
              ? '전체 분석'
              : job.runMode === 'check_only'
                ? '사전 점검'
                : job.runMode}
            {elapsed ? (
              <span className="text-text-muted">
                <span className="px-1.5 text-ink-400">·</span>
                {elapsed} 소요
              </span>
            ) : null}
          </span>
          {listItem?.captureKitId ? (
            <span className="text-caption text-text-muted">
              캡처 키트{' '}
              <span className="font-mono text-text">{listItem.captureKitId}</span>
            </span>
          ) : null}
        </Fact>
      </dl>

      {/*
        단계 띠(lg, 라벨 + 상태). 헤더의 띠를 md(라벨 없음)에서 lg로 올렸다.
        색 띠만으로는 "어느 단계가 빨간가"를 읽을 수 없어 시연에서 매번 표를
        내려가 봐야 했다. 아래 단계 표는 설명·상세 진입을 맡고, 이 띠는 위치만
        말한다.
      */}
      <RunTape size="lg" cells={tapeCells(job)} />

      {cancelError ? (
        <MessageBlock tone="danger" role="alert" title="취소 요청이 실패했습니다">
          서버가 요청을 처리하지 못했습니다. 실행은 계속되고 있을 수 있으니 상태를
          확인해 주세요.
        </MessageBlock>
      ) : null}
    </div>
  )
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    /*
      칸 사이 구분선. 1열은 아래선, 2열(sm)은 왼쪽 칸 오른선 + 윗줄 아래선,
      4열(lg)은 마지막 칸을 뺀 오른선만.
    */
    <div className="flex min-w-0 flex-col gap-1 border-border-subtle px-4 py-3 not-last:border-b sm:odd:border-r sm:nth-last-[-n+2]:border-b-0 lg:border-b-0 lg:not-last:border-r">

      <dt className="text-caption font-medium tracking-wide-kr text-text-muted">{term}</dt>
      <dd className="flex min-w-0 flex-col gap-0.5">{children}</dd>
    </div>
  )
}

/**
 * "지금 어디인가"를 한 문장으로.
 *
 * 실패한 실행은 currentStep이 null이라 이전 헤더는 "1/8단계"만 보여주고 어디서
 * 멈췄는지 말하지 않았다. 단계 상태에서 직접 찾는다 — backend가 준 값만 쓴다.
 */
function describePosition(job: JobState): { headline: string; detail: string | null } {
  const steps = job.steps
  const failed = steps.find((step) => step.status === 'failed')
  const waiting = steps.filter((step) => step.status === 'pending').length

  if (failed) {
    return {
      headline: `${describeStep(failed.stepId).label}에서 멈춤`,
      detail: waiting > 0 ? `이후 ${waiting}단계는 실행되지 않았습니다` : null,
    }
  }
  if (job.currentStep) {
    const index = steps.findIndex((step) => step.stepId === job.currentStep)
    const next = index >= 0 ? steps[index + 1] : undefined
    return {
      headline: `${describeStep(job.currentStep).label} 진행 중`,
      detail: next ? `다음: ${describeStep(next.stepId).label}` : '마지막 단계입니다',
    }
  }
  if (job.status === 'queued') {
    return { headline: '시작 대기 중', detail: null }
  }
  if (job.status === 'cancelled') {
    return { headline: '취소됨', detail: waiting > 0 ? `${waiting}단계는 실행되지 않았습니다` : null }
  }
  if (steps.length > 0 && waiting === 0) {
    return { headline: '모든 단계가 끝났습니다', detail: null }
  }
  return { headline: '기록 없음', detail: null }
}

/** lg 띠 셀. 라벨 아래에 상태를 글자로 적는다 — 색만으로 상태를 말하지 않는다. */
function tapeCells(job: JobState): RunTapeCell[] {
  return toTapeCells(job, true).map((cell, index) => {
    const step = job.steps[index]
    const view = describeStepStatus(step.status)
    return {
      ...cell,
      meta:
        step.elapsedSeconds > 0
          ? `${view.label} · ${formatDuration(step.elapsedSeconds)}`
          : view.label,
    }
  })
}
