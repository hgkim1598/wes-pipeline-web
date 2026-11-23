import {
  Ban,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/Button'
import { CopyableId } from '@/components/ui/CopyableId'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { JobState } from '@/features/run-detail/api'
import { PollingStatus } from '@/features/run-detail/components/PollingStatus'
import { describePosition as positionOf } from '@/features/run-detail/runPosition'
import type { ConnectionState } from '@/features/run-detail/runDetailPolicy'
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

  2026-11-20 (개발판단기록 41장): 승인된 밝은 시안대로 헤더를 줄였다 — 경로 ·
  상태 · 제목 · run id · 시작 시각 · 소요 시간 · 멈춘 위치와 문제 건수 한 줄.
  네 칸 요약은 개요 탭으로(2026-11-23 RunVerdict로 대체), 단계 띠는 파이프라인 탭의 진행 표시로
  옮겼다. 시안의 공유·내보내기·다시 실행 버튼은 없는 기능이라 만들지 않았다.

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
    connection: ConnectionState
  }
  onCancel: () => void
  isCancelling: boolean
  cancelError: unknown
  /**
   * 이 실행의 문제 건수. 페이지가 AttentionSection에 넘기는 것과 같은 출처에서
   * 센다 — 요약 띠와 본문의 숫자가 달라지면 안 된다.
   */
  issues: RunIssueCounts
  /**
   * "어디서 멈췄고 문제가 몇 건인가" 한 줄. 개요 탭은 바로 아래 판정 면(RunVerdict)이
   * 같은 문장을 말하므로 false다 — 같은 사실이 위아래로 두 번 보였다.
   */
  showPositionLine?: boolean
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
  showPositionLine = true,
}: RunHeaderProps) {
  const [confirmingCancel, setConfirmingCancel] = useState(false)

  const status = describeJobStatus(job.status)
  const terminal = isTerminalStatus(job.status)
  const position = describePosition(job)
  const elapsed = durationBetween(job.startedAt, job.finishedAt)
  const started = formatTimestamp(job.startedAt)
  const created = started ? null : formatTimestamp(listItem?.createdAt ?? null)
  const sample = listItem?.sampleId ?? null
  // 경로 표시의 짧은 이름: run id의 마지막 조각. 전체 id는 아래 복사 칸에 있다.
  const shortId = job.runId.split('-').at(-1) || job.runId

  return (
    <header className="flex flex-col gap-3">
      <nav aria-label="현재 위치" className="flex items-center gap-1.5 text-small text-text-muted">
        <Link
          to="/runs"
          className="inline-flex min-h-6 items-center gap-1 text-text-muted no-underline hover:text-text hover:underline"
        >
          <ChevronLeft size={12} strokeWidth={1.5} aria-hidden="true" />
          실행 목록
        </Link>
        <ChevronRight size={12} strokeWidth={1.5} aria-hidden="true" className="text-ink-400" />
        <span className="font-mono text-text-strong">{shortId}</span>
      </nav>

      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <h1 className="min-w-0 text-h2 font-semibold tracking-tight [overflow-wrap:anywhere] text-text-strong">
              {job.profileId}
              {sample ? (
                <>
                  <span className="px-2 text-ink-400">·</span>
                  <code className="text-h2">{sample}</code>
                </>
              ) : null}
            </h1>
          </div>

          {/* 실제 값만. 없는 값은 칸을 만들지 않는다. */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-small text-text-muted">
            <CopyableId value={job.runId} />
            {started ? (
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays size={14} strokeWidth={1.5} aria-hidden="true" />
                <time dateTime={started.machine} title={started.full}>
                  {started.display}
                </time>
                시작
              </span>
            ) : created ? (
              /* 시작 시각이 기록되지 않은 실행(예: 사전 점검에서 멈춤)은 등록 시각만 있다. 시작으로 쓰지 않는다. */
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays size={14} strokeWidth={1.5} aria-hidden="true" />
                <time dateTime={created.machine} title={created.full}>
                  {created.display}
                </time>
                등록 · 시작 시각 기록 없음
              </span>
            ) : null}
            {elapsed ? (
              <span className="inline-flex items-center gap-1.5">
                <Clock size={14} strokeWidth={1.5} aria-hidden="true" />
                {elapsed} 소요
              </span>
            ) : null}
            <PollingStatus
              active={!terminal}
              updatedAt={polling.updatedAt}
              connection={polling.connection}
            />
          </div>

          {/*
            개요 밖의 탭에서도 "어디서 멈췄고 문제가 몇 건인가"가 보이게 한 줄로
            둔다. 개요 탭은 RunVerdict가 같은 말을 하므로 숨긴다(showPositionLine).
          */}
          {showPositionLine ? (
            <p className="flex flex-wrap items-baseline gap-x-2 text-small">
              <span className="font-medium text-text-strong">{position.headline}</span>
              {position.detail ? <span className="text-text-muted">{position.detail}</span> : null}
              {issues.failures > 0 || issues.attention > 0 ? (
                <span className="text-text-muted">
                  ·{' '}
                  <span className={issues.failures > 0 ? 'font-medium text-status-failure-fg' : undefined}>
                    실패 {issues.failures}
                  </span>{' '}
                  ·{' '}
                  <span className={issues.attention > 0 ? 'font-medium text-status-warning-fg' : undefined}>
                    확인 필요 {issues.attention}
                  </span>
                </span>
              ) : null}
            </p>
          ) : null}
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
    </header>
  )
}

/** 위치 문장(runPosition.ts)에 단계 이름 registry를 붙인다. */
function describePosition(job: JobState) {
  return positionOf(job, (stepId) => describeStep(stepId).label)
}
