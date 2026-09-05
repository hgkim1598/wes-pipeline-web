import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { TabsList, TabsPanel, TabsRoot, TabsTab } from '@/components/ui/Tabs'
import { DiagnosticList } from '@/components/ui/DiagnosticNote'
import { ArtifactsView } from '@/features/run-detail/components/ArtifactsView'
import { DeveloperDetails } from '@/features/run-detail/components/DeveloperDetails'
import { LogPanel } from '@/features/run-detail/components/LogPanel'
import { ResultsView } from '@/features/run-detail/components/ResultsView'
import { RunHeader } from '@/features/run-detail/components/RunHeader'
import { StepDetailRail } from '@/features/run-detail/components/StepDetailRail'
import {
  STEP_DETAIL_PANEL_ID,
  StepTable,
} from '@/features/run-detail/components/StepTable'
import { collectDiagnostics } from '@/features/run-detail/diagnostics'
import {
  findStepStatus,
  useArtifactsQuery,
  useJobDetailQuery,
  useResultsQuery,
  useStepDetailQuery,
} from '@/features/run-detail/queries'
import { useCancelJobMutation } from '@/features/run-detail/useCancelJobMutation'
import { useRunListQuery } from '@/features/runs/useRunListQuery'
import { isTerminalStatus } from '@/features/runs/status'
import { formatTimestamp } from '@/features/runs/time'
import { describeStep } from '@/registries/steps'

/*
  실행 상세 — Analysis Workspace.

  시안 근거 (docs/design/pipeline-tab.html)
    Run 헤더 · 탭바 · 좌 본문 + 우 400px sticky 레일 · 로그 · 하단 RUO 문구.
    계층을 shadow가 아니라 1px 선과 surface/paper 배경으로 만든다.

  이 파일의 책임은 조립뿐이다. 쿼리 정책은 queries.ts, 표시는 components/,
  어휘는 registries/steps.ts와 stepStatus.ts에 있다. 탭이 늘어도 이 파일은
  거의 커지지 않는다.

  탭은 URL 경로 세그먼트다(/runs/:jobId/:tab). 뒤로가기·앞으로가기·새로고침·
  링크 공유가 모두 동작하고, 시안의 워크스페이스 구조와 같다.

  ⚠️ 목록 query를 함께 읽는다. sampleId·captureKitId·createdAt이
  GET /api/jobs/{id}에 없기 때문이다(JobStateResponse). 목록은 이미 캐시되어
  있는 경우가 많고, 없으면 한 번 받아온다.
*/

const TABS = [
  { id: 'pipeline', label: '파이프라인' },
  { id: 'results', label: '결과' },
  { id: 'files', label: '파일' },
] as const

type TabId = (typeof TABS)[number]['id']

const DEFAULT_TAB: TabId = 'pipeline'

function parseTab(raw: string | undefined): TabId {
  return TABS.some((tab) => tab.id === raw) ? (raw as TabId) : DEFAULT_TAB
}

export function RunDetailPage() {
  const { jobId = '', tab } = useParams<{ jobId: string; tab?: string }>()
  const navigate = useNavigate()

  const activeTab = parseTab(tab)
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)

  const detail = useJobDetailQuery(jobId)
  const job = detail.data
  const terminal = job ? isTerminalStatus(job.status) : false

  // 목록에서 이 job의 행을 찾는다. 상세 응답에 없는 필드의 출처다.
  const list = useRunListQuery()
  const listItem = list.data?.jobs.find((item) => item.jobId === jobId)

  const stepStatus = findStepStatus(job, selectedStepId)
  const step = useStepDetailQuery(jobId, selectedStepId, stepStatus)
  const results = useResultsQuery(jobId, job?.status)
  const artifacts = useArtifactsQuery(jobId, job?.status)
  const cancel = useCancelJobMutation(jobId)

  if (detail.isPending) {
    return (
      <Shell>
        <MessageBlock tone="info" role="status" title="실행 정보를 불러오는 중입니다">
          <code>/api/jobs/{jobId}</code> 응답을 기다리고 있습니다.
        </MessageBlock>
      </Shell>
    )
  }

  if (detail.error || !job) {
    return (
      <Shell>
        <RunDetailError error={detail.error} onRetry={() => void detail.refetch()} />
      </Shell>
    )
  }

  const currentStepLabel = job.currentStep
    ? describeStep(job.currentStep).label
    : null

  /*
    진단을 단계별로 배분한다. 출처와 실행 중 동작은 diagnostics.ts에 설명이
    있다. 계획된 단계 목록을 함께 넘기는 것은 --check-only 실행의 귀속
    때문이다.
  */
  const diagnostics = collectDiagnostics(
    results.data,
    job.steps.map((s) => s.stepId),
  )

  return (
    <Shell wide>
      <RunHeader
        job={job}
        listItem={listItem}
        polling={{
          updatedAt: detail.dataUpdatedAt,
          failureCount: detail.failureCount,
          isFetching: detail.isFetching,
        }}
        onCancel={() => cancel.mutate()}
        isCancelling={cancel.isPending}
        cancelError={cancel.error}
      />

      {/*
        실행 전체의 실패는 탭과 무관하게 항상 보여야 한다. 어느 탭에 있든
        "무엇이 잘못됐는지"가 화면에서 사라지면 안 된다.
      */}
      {job.error ? (
        <MessageBlock
          tone={job.status === 'cancelled' ? 'info' : 'danger'}
          title={
            job.status === 'cancelled'
              ? '이 실행은 취소되었습니다'
              : `${failedStepLabel(job) ?? '실행'}에서 중단되었습니다`
          }
        >
          <div className="flex flex-col gap-2">
            <p className="whitespace-pre-wrap">{job.error}</p>
            {job.pipelineStatus ? (
              <code className="text-text-muted">
                pipeline status: {job.pipelineStatus}
              </code>
            ) : null}
          </div>
        </MessageBlock>
      ) : null}

      {job.unsupportedOptions.length > 0 ? (
        <MessageBlock
          tone="warning"
          title="이 서버가 적용하지 않은 요청 옵션이 있습니다"
        >
          <code>{job.unsupportedOptions.join(', ')}</code>
        </MessageBlock>
      ) : null}

      <TabsRoot
        value={activeTab}
        onValueChange={(next) => {
          navigate(`/runs/${encodeURIComponent(jobId)}/${next}`)
        }}
      >
        <TabsList>
          {TABS.map((item) => (
            <TabsTab key={item.id} value={item.id}>
              {item.label}
            </TabsTab>
          ))}
        </TabsList>

        <TabsPanel value="pipeline">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-6">
            <div className="flex min-w-0 flex-1 flex-col gap-10">
              {/*
                시안에는 여기에 라벨이 붙은 lg RunTape가 하나 더 있었지만
                뺐다. 바로 아래 표가 같은 8단계를 이름·상태·소요시간까지
                포함해 보여주고, 헤더에도 md 띠가 이미 있다. 한 화면에 같은
                정보를 세 번 그리는 것은 UI chrome이지 정보가 아니다.
              */}
              <section className="flex flex-col gap-4">
                <SectionHeader
                  eyebrow="PIPELINE"
                  title="단계별 진행"
                  meta={`${job.steps.length}단계 계획`}
                />
                <StepTable
                  steps={job.steps}
                  currentStepId={job.currentStep}
                  selectedStepId={selectedStepId}
                  diagnosticsByStep={diagnostics.byStep}
                  onSelect={(stepId) =>
                    setSelectedStepId((prev) =>
                      prev === stepId ? null : stepId,
                    )
                  }
                />
              </section>

              {/*
                어느 단계에도 귀속되지 않은 진단. backend가 stepId를 주지
                않은 경우이며(diagnostics.ts 참고) 버리지 않고 여기서 보여준다.
              */}
              {diagnostics.unattributed.length > 0 ? (
                <section className="flex flex-col gap-4">
                  <SectionHeader
                    title="실행 전반의 확인 사항"
                    meta={`${diagnostics.unattributed.length}건`}
                  />
                  <DiagnosticList diagnostics={diagnostics.unattributed} />
                </section>
              ) : null}

              <LogPanel lines={job.logTail} />

              {/*
                실행 조건 — Layer 3.

                이전에는 12행 KV 표가 로그 바로 아래 같은 크기로 펼쳐져 있었다.
                거기에는 `상태: completed_with_warnings`, `pipeline 상태`,
                `완료 단계 비율`처럼 backend 내부 어휘가 그대로 들어 있었는데,
                그 값들은 이미 헤더가 사람이 읽는 말로 전달하고 있다. 같은 것을
                두 번, 한 번은 내부 표현으로 보여주면 사용자가 데이터 모델을
                배워야 하는 화면이 된다.

                지우지는 않는다 — 전문가에게는 실제로 필요한 값이다. 접어서
                내린다.
              */}
              <details className="border-t border-border pt-4">
                <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
                  실행 조건과 식별자
                </summary>
                <dl className="mt-3 flex flex-col">
                  <InfoRow label="job / run ID" value={job.jobId} mono />
                  {job.runId !== job.jobId ? (
                    <InfoRow label="run ID" value={job.runId} mono />
                  ) : null}
                  <InfoRow
                    label="샘플"
                    value={listItem?.sampleId ?? '정보 없음'}
                    mono
                  />
                  <InfoRow label="분석 profile" value={job.profileId} mono />
                  <InfoRow
                    label="capture kit"
                    value={listItem?.captureKitId ?? '정보 없음'}
                    mono
                  />
                  <InfoRow label="실행 모드" value={job.runMode} mono />
                  <InfoRow label="상태" value={job.status} mono />
                  <InfoRow
                    label="pipeline 상태"
                    value={job.pipelineStatus ?? '—'}
                    mono
                  />
                  <InfoRow label="현재 단계" value={job.currentStep ?? '—'} mono />
                  <InfoRow
                    label="완료 단계 비율"
                    value={`${job.progress} %`}
                    mono
                  />
                  <InfoRow
                    label="제출"
                    value={isoOrDash(listItem?.createdAt ?? null)}
                  />
                  <InfoRow label="시작" value={isoOrDash(job.startedAt)} />
                  <InfoRow label="종료" value={isoOrDash(job.finishedAt)} />
                </dl>
              </details>
            </div>

            {/*
              우측 레일 — 단계를 선택했을 때만 존재한다.

              이전에는 선택이 없어도 같은 폭의 빈 aside가 남아 안내문만 담고
              있었다. 내용이 없는 패널이 화면의 30%를 차지하면 그것은 정보가
              아니라 dashboard 모양이다. 무엇을 누르면 무엇이 열리는지는 표의
              각 행에 있는 "상세"가 말한다.

              시안의 400px sticky 레일이며, lg 미만에서는 본문 아래로 내려간다.
            */}
            {selectedStepId ? (
              <aside
                id={STEP_DETAIL_PANEL_ID}
                className="w-full flex-none border-t border-border pt-6 lg:sticky lg:top-6 lg:w-rail lg:border-t-0 lg:border-l lg:pl-6"
              >
                <StepDetailRail
                  stepId={selectedStepId}
                  detail={step.data}
                  isPending={step.isPending}
                  error={step.error}
                />
              </aside>
            ) : null}
          </div>
        </TabsPanel>

        <TabsPanel value="results">
          <ResultsView
            data={results.data}
            isPending={results.isPending && terminal}
            waitingForRun={!terminal}
            terminal={terminal}
            error={results.error}
            currentStepLabel={currentStepLabel}
          />
        </TabsPanel>

        <TabsPanel value="files">
          <ArtifactsView
            data={artifacts.data}
            isPending={artifacts.isPending}
            error={artifacts.error}
            jobId={jobId}
            running={!terminal}
          />
        </TabsPanel>
      </TabsRoot>

      <div className="flex flex-col gap-4 border-t border-border pt-6">
        <p className="text-caption text-text-muted">
          연구·교육 목적 전용 — 진단 결과가 아닙니다
        </p>
        <DeveloperDetails
          sections={[
            { label: 'GET /api/jobs/{id}', value: job },
            {
              label: `GET /api/jobs/{id}/steps/${selectedStepId ?? '(선택 없음)'}`,
              value: step.data,
            },
            { label: 'GET /api/jobs/{id}/results', value: results.data },
            { label: 'GET /api/jobs/{id}/artifacts', value: artifacts.data },
          ]}
        />
      </div>
    </Shell>
  )
}

/** 페이지 폭. 파이프라인 탭은 레일이 있어 app 폭(1360), 나머지는 읽기 폭. */
function Shell({
  children,
  wide = false,
}: {
  children: React.ReactNode
  wide?: boolean
}) {
  return (
    <main
      className={
        wide
          ? 'mx-auto flex max-w-app flex-col gap-6 px-6 py-8'
          : 'mx-auto flex max-w-content flex-col gap-6 px-6 py-8'
      }
    >
      {children}
    </main>
  )
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border-subtle py-2 last:border-b-0">
      <dt className="flex-none text-small text-text-muted md:w-45">{label}</dt>
      <dd
        className={
          mono
            ? 'min-w-0 flex-1 basis-full break-all font-mono text-data text-text-strong md:basis-0'
            : 'min-w-0 flex-1 basis-full text-body text-text-strong md:basis-0'
        }
      >
        {value}
      </dd>
    </div>
  )
}

/** 실패한 단계의 사람이 읽는 이름. 없으면 null. */
function failedStepLabel(job: {
  steps: { stepId: string; status: string }[]
}): string | null {
  const failed = job.steps.find((step) => step.status === 'failed')
  return failed ? describeStep(failed.stepId).label : null
}

function isoOrDash(value: string | null): string {
  const formatted = formatTimestamp(value)
  return formatted ? formatted.full : '—'
}

/*
  상세를 읽지 못한 경우.

  404(없는 job)와 통신 실패를 구분한다. 404는 주소 문제이므로 목록으로 돌아가는
  것이 유일한 조치이고, 나머지는 재시도가 의미 있다.
  문구 근거: docs/design/remaining-screens.html의 404 화면.
*/
function RunDetailError({
  error,
  onRetry,
}: {
  error: unknown
  onRetry: () => void
}) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <MessageBlock
        tone="warning"
        title="이 실행 기록을 찾지 못했습니다"
        action={
          <Link
            to="/runs"
            className="inline-flex h-8 items-center rounded-sm bg-brand px-4 text-body font-medium text-surface no-underline hover:bg-brand-hover hover:no-underline"
          >
            실행 목록으로
          </Link>
        }
      >
        서버에서 이 실행 기록을 찾지 못했습니다. 주소가 정확한지 확인하거나 실행
        목록에서 다시 선택해 주세요.
      </MessageBlock>
    )
  }

  const apiError = error instanceof ApiError ? error : null

  return (
    <MessageBlock
      tone="danger"
      role="alert"
      title="실행 정보를 불러오지 못했습니다"
      action={
        <Button variant="primary" onClick={onRetry}>
          다시 시도
        </Button>
      }
    >
      <div className="flex flex-col gap-2">
        <p>
          {apiError?.kind === 'network'
            ? '요청이 서버에 도달하지 못했습니다. FastAPI가 실행 중인지 확인하세요.'
            : apiError?.kind === 'malformed'
              ? 'frontend가 아는 계약과 backend 응답이 어긋났습니다.'
              : `서버가 요청을 처리하지 못했습니다${apiError ? ` (HTTP ${apiError.status})` : ''}.`}
        </p>
        {apiError?.detail ? (
          <code className="break-all text-text-muted">{apiError.detail}</code>
        ) : null}
      </div>
    </MessageBlock>
  )
}
