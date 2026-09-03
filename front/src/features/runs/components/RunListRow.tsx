import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'

import { StatusBadge } from '@/components/ui/StatusBadge'
import type { JobListItem } from '@/features/runs/api'
import { StepProgress } from '@/features/runs/components/StepProgress'
import { describeJobStatus } from '@/features/runs/status'
import { formatTimestamp } from '@/features/runs/time'

/*
  실행 목록의 한 행.

  시안 근거 (docs/design/remaining-screens.html · RUN LIST)
    행 padding 16 · 열 gap 16 · 하단 1px 구분선 · 우측 chevron
    상태 132 / 샘플 96 / 진행 120 / 시각 88 (px)
    행 전체가 하나의 클릭 대상이다.

  시안과 다르게 한 것

    · 시안의 summary("6/8단계 · 1시간 18분")에서 경과 시간을 뺐다. 목록
      응답에 elapsed가 없고, createdAt/startedAt으로 계산한 값은 서버 시계가
      아니라 브라우저 시계 기준이라 실제와 어긋난다.
    · 시안의 sub("GRCh38 · IDT xGen Exome Hyb Panel v2")는 mock이다. assembly는
      목록 응답에 없고 capture kit은 이름이 아니라 ID로만 온다. 실제로 오는 값
      (실행 모드 · capture kit ID · run ID)으로 다시 구성했다.
    · 좁은 화면에서는 한 줄 배치를 유지할 수 없어 상태·시각이 위, 본문과 진행이
      아래로 접힌다. 375px 시안과 같은 구조다.

  중첩 금지: 행 전체가 이미 링크이므로 안에 버튼이나 다른 링크를 넣지 않는다.
*/

/**
 * backend의 실행 모드 값(backend/app/config.py RUN_MODE_CHOICES).
 * 모르는 값이면 원문을 그대로 보여준다. 없는 의미를 지어내지 않는다.
 */
const RUN_MODE_LABEL: Record<string, string> = {
  check_only: '사전 점검',
  full: '전체 분석',
}

export interface RunListRowProps {
  job: JobListItem
}

export function RunListRow({ job }: RunListRowProps) {
  const status = describeJobStatus(job.status)
  const createdAt = formatTimestamp(job.createdAt)
  const runModeLabel = RUN_MODE_LABEL[job.runMode] ?? job.runMode

  return (
    <li className="border-b border-border-subtle last:border-b-0">
      <Link
        to={`/runs/${encodeURIComponent(job.jobId)}`}
        /*
          목록 컨테이너가 overflow-hidden이라 기본 포커스 링(바깥 2px)이
          첫 행과 마지막 행에서 잘린다. 링을 지우는 대신 안쪽으로 넣는다.
        */
        className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 text-text no-underline hover:bg-brand-faint focus-visible:[outline-offset:-2px] md:flex-nowrap"
      >
        {/*
          시안의 상태 열은 132px 고정이지만 min-width로 둔다. backend가 모르는
          상태를 보내면 배지 문구가 원문 그대로라 길어질 수 있고, 그때 고정폭은
          옆 열을 덮는다. 열이 조금 어긋나는 편이 글자가 겹치는 것보다 낫다.
        */}
        <span className="order-1 flex-none md:min-w-33">
          <StatusBadge tone={status.tone} size="sm">
            {status.label}
          </StatusBadge>
        </span>

        {/* 좁은 화면에서는 상태 배지와 같은 줄 오른쪽 끝으로 간다. */}
        <span className="order-2 ml-auto flex-none text-small text-text-muted md:order-4 md:ml-0 md:w-22 md:text-right">
          <span className="sr-only">제출 </span>
          {createdAt ? (
            <time dateTime={createdAt.machine} title={createdAt.full}>
              {createdAt.display}
            </time>
          ) : (
            <span title={job.createdAt}>—</span>
          )}
        </span>

        <div className="order-3 flex min-w-0 basis-full flex-col gap-1 md:order-2 md:flex-1 md:basis-auto">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-3">
            {job.sampleId ? (
              <code className="flex-none font-medium text-text-strong md:min-w-24">
                {job.sampleId}
              </code>
            ) : (
              /*
                sampleId는 column이 생기기 전에 만들어진 실행에서 null이다.
                runId로 대신 채우지 않는다 — 없는 정보를 채우면 사용자는
                그것을 샘플 이름으로 읽는다.
              */
              <span className="flex-none text-small text-text-muted md:min-w-24">
                샘플 정보 없음
              </span>
            )}
            <span
              className="min-w-0 flex-1 truncate text-body text-text"
              title={job.profileId}
            >
              {job.profileId}
            </span>
          </div>

          <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-caption text-text-muted">
            <span>{runModeLabel}</span>
            <span aria-hidden="true">·</span>
            <span>{job.captureKitId ?? 'capture kit 미지정'}</span>
            <span aria-hidden="true">·</span>
            <code className="min-w-0 truncate text-caption">{job.runId}</code>
          </p>

          {/*
            실패 사유는 backend가 준 문자열 그대로다. 목록에서는 문제가 있다는
            사실과 첫 줄만 보여주고, 전문은 실행 상세에서 다룬다.
          */}
          {job.error ? (
            <p
              className="truncate text-caption text-status-failure-fg"
              title={job.error}
            >
              {job.error}
            </p>
          ) : null}
        </div>

        <div className="order-4 basis-full md:order-3 md:w-30 md:basis-auto">
          <StepProgress
            completedStepCount={job.completedStepCount}
            plannedStepCount={job.plannedStepCount}
            tone={status.tone}
          />
        </div>

        <ChevronRight
          size={16}
          strokeWidth={1.5}
          aria-hidden="true"
          className="order-5 hidden flex-none text-ink-400 md:block"
        />
      </Link>
    </li>
  )
}
