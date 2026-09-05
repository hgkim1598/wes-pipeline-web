import { ChevronLeft, Ban } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/Button'
import { CopyableId } from '@/components/ui/CopyableId'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { RunTape } from '@/components/ui/RunTape'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { JobState } from '@/features/run-detail/api'
import { PollingStatus } from '@/features/run-detail/components/PollingStatus'
import { toTapeCells } from '@/features/run-detail/tape'
import type { JobListItem } from '@/features/runs/api'
import { describeJobStatus, isTerminalStatus } from '@/features/runs/status'
import { durationBetween, formatTimestamp } from '@/features/runs/time'
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
}

export function RunHeader({
  job,
  listItem,
  polling,
  onCancel,
  isCancelling,
  cancelError,
}: RunHeaderProps) {
  const [confirmingCancel, setConfirmingCancel] = useState(false)

  const status = describeJobStatus(job.status)
  const terminal = isTerminalStatus(job.status)
  const completed = job.steps.filter(
    (step) => step.status !== 'pending' && step.status !== 'running',
  ).length
  const currentLabel = job.currentStep ? describeStep(job.currentStep).label : null
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
        <div className="flex min-w-0 flex-col gap-3">
          <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
            {job.profileId}
            {sample ? (
              <>
                <span className="px-2 text-ink-400">·</span>
                <code className="text-h1">{sample}</code>
              </>
            ) : null}
          </h1>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <div className="min-w-0 flex-1 basis-64">
              <RunTape size="md" cells={toTapeCells(job)} />
            </div>
          </div>

          <p className="text-body text-text">
            {currentLabel ? (
              <>
                <span className="font-medium text-text-strong">{currentLabel}</span>
                <span className="px-2 text-ink-400">·</span>
              </>
            ) : null}
            <span className="font-mono text-data">
              {completed}/{job.steps.length}
            </span>
            단계
            {elapsed ? (
              <>
                <span className="px-2 text-ink-400">·</span>
                {elapsed} 소요
              </>
            ) : null}
          </p>

          <p className="text-small text-text-muted">
            {[
              job.runMode === 'full' ? '전체 분석 모드' : null,
              job.runMode === 'check_only' ? '사전 점검 모드' : null,
              job.runMode !== 'full' && job.runMode !== 'check_only'
                ? `실행 모드 ${job.runMode}`
                : null,
              listItem?.captureKitId ?? null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>

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

      {cancelError ? (
        <MessageBlock tone="danger" role="alert" title="취소 요청이 실패했습니다">
          서버가 요청을 처리하지 못했습니다. 실행은 계속되고 있을 수 있으니 상태를
          확인해 주세요.
        </MessageBlock>
      ) : null}
    </div>
  )
}
