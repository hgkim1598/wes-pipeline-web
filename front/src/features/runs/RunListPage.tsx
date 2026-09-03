import { Inbox, RefreshCw } from 'lucide-react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { JOBS_PATH } from '@/features/runs/api'
import type { JobListItem } from '@/features/runs/api'
import { RunListRow } from '@/features/runs/components/RunListRow'
import { useRunListQuery } from '@/features/runs/useRunListQuery'

/*
  실행 목록 — GET /api/jobs.

  이 서버가 기록한 모든 실행을 보여준다. 시안(remaining-screens.html)의
  "이 목록은 이 브라우저에만 저장됩니다"는 localStorage 기반이던 과거 설계의
  문구다. 지금의 출처는 FastAPI + SQLite이므로 그 문장을 쓰지 않는다.

  시안에 있는 "새 분석" 버튼도 두지 않았다. 제출 화면이 아직 없어서 눌러도
  갈 곳이 없고, 없는 기능을 있는 것처럼 보이게 하지 않는다(CLAUDE.md 35장).
  화면이 생기는 단계에서 이 자리에 들어온다.

  검색·필터·정렬·페이지네이션도 없다. backend에 해당 파라미터가 없고
  (backend/app/api/jobs.py list_jobs), 조작만 먼저 만들면 동작하지 않는
  컨트롤이 된다.
*/

export function RunListPage() {
  const { data, error, isPending, isFetching, refetch } = useRunListQuery()
  const jobs = data?.jobs

  return (
    <main className="mx-auto flex max-w-app flex-col gap-6 px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
            실행 목록
          </h1>
          {jobs ? (
            <p className="text-caption text-text-muted">
              이 서버에 기록된 분석 실행{' '}
              <span className="font-mono text-data text-text">
                {jobs.length}
              </span>
              건
            </p>
          ) : null}
        </div>

        {/* 오류·빈 상태는 각자 자기 자리에 조치 버튼을 갖는다. 여기서는 중복을 만들지 않는다. */}
        {jobs && jobs.length > 0 ? (
          <Button
            variant="secondary"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
            {isFetching ? '확인 중' : '다시 확인'}
          </Button>
        ) : null}
      </div>

      {isPending ? (
        <MessageBlock tone="info" role="status" title="목록을 불러오는 중입니다">
          <code>{JOBS_PATH}</code> 응답을 기다리고 있습니다.
        </MessageBlock>
      ) : null}

      {error ? <RunListError error={error} onRetry={() => void refetch()} /> : null}

      {jobs ? <RunList jobs={jobs} onRefresh={() => void refetch()} /> : null}
    </main>
  )
}

function RunList({
  jobs,
  onRefresh,
}: {
  jobs: JobListItem[]
  onRefresh: () => void
}) {
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={<Inbox size={32} strokeWidth={1.5} aria-hidden="true" />}
        title="아직 실행한 분석이 없습니다"
        description={
          <>
            서버에 기록된 분석 실행이 없습니다. 분석을 제출하면 이 목록에
            나타납니다. 제출 화면은 아직 준비 중입니다.
          </>
        }
        action={
          <Button variant="secondary" onClick={onRefresh}>
            <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
            다시 확인
          </Button>
        }
      />
    )
  }

  return (
    <ul className="overflow-hidden rounded-md border border-border bg-surface">
      {jobs.map((job) => (
        <RunListRow key={job.jobId} job={job} />
      ))}
    </ul>
  )
}

interface ErrorView {
  summary: string
  hint: string
  detail: string | null
}

/*
  ApiError.kind별로 사용자가 할 수 있는 조치가 다르다. 세 경우를 하나의
  "불러오지 못했습니다"로 뭉치면 아무도 다음 행동을 알 수 없다.
  기술 상세는 남기되 시각적 우선순위를 낮춘다.
*/
function describeError(error: unknown): ErrorView {
  if (error instanceof ApiError) {
    if (error.kind === 'network') {
      return {
        summary: '요청이 backend에 도달하지 못했습니다.',
        hint: 'FastAPI 서버가 실행 중인지 확인한 뒤 다시 시도하세요. 서버가 꺼져 있어도 이전에 실행한 분석 기록은 사라지지 않습니다.',
        detail: error.detail,
      }
    }
    if (error.kind === 'http') {
      return {
        summary: `backend가 HTTP ${error.status}로 응답했습니다.`,
        hint: '서버는 살아 있지만 목록 요청을 처리하지 못했습니다. 목록이 비어 있다는 뜻이 아닙니다. 서버 로그를 확인하세요.',
        detail: error.detail,
      }
    }
    return {
      summary: '응답을 읽었지만 예상한 형식이 아닙니다.',
      hint: `frontend가 아는 계약과 backend 응답이 어긋났습니다. 실행이 없는 것과는 다른 문제입니다. 아래 상세와 backend의 ${JOBS_PATH} 응답 모델을 대조하세요.`,
      detail: error.detail,
    }
  }
  return {
    summary: '알 수 없는 오류가 발생했습니다.',
    hint: '브라우저 개발자 도구의 Network / Console 탭을 확인하세요.',
    detail: error instanceof Error ? error.message : String(error),
  }
}

function RunListError({
  error,
  onRetry,
}: {
  error: unknown
  onRetry: () => void
}) {
  const { summary, hint, detail } = describeError(error)

  return (
    <MessageBlock
      tone="danger"
      role="alert"
      title="실행 목록을 불러오지 못했습니다"
      action={
        <Button variant="primary" onClick={onRetry}>
          <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
          다시 시도
        </Button>
      }
    >
      <div className="flex flex-col gap-2">
        <p>{summary}</p>
        <p>{hint}</p>
        {detail ? (
          <code className="break-all text-text-muted">{detail}</code>
        ) : null}
      </div>
    </MessageBlock>
  )
}
