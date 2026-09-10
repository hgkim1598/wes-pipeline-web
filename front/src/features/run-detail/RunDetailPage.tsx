import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError } from '@/api/client'
import { isNotReady } from '@/features/run-detail/api'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { TabsList, TabsPanel, TabsRoot, TabsTab } from '@/components/ui/Tabs'
import { ArtifactsView } from '@/features/run-detail/components/ArtifactsView'
import { DeveloperDetails } from '@/features/run-detail/components/DeveloperDetails'
import { LogPanel } from '@/features/run-detail/components/LogPanel'
import { ResultsView } from '@/features/run-detail/components/ResultsView'
import { AttentionSection } from '@/features/run-detail/components/AttentionSection'
import { RunHeader } from '@/features/run-detail/components/RunHeader'
import { RunLimitations } from '@/features/run-detail/components/RunLimitations'
import { RunSynthesisPanel } from '@/features/run-detail/components/RunSynthesisPanel'
import { artifactLabelMap } from '@/features/run-detail/locators'
import { StepDetailRail } from '@/features/run-detail/components/StepDetailRail'
import {
  STEP_DETAIL_PANEL_ID,
  StepTable,
} from '@/features/run-detail/components/StepTable'
import {
  collectDiagnostics,
  collectFromExplanation,
} from '@/features/run-detail/diagnostics'
import {
  findStepStatus,
  useArtifactsQuery,
  useExplanationQuery,
  useJobDetailQuery,
  useResultsQuery,
  useStepDetailQuery,
} from '@/features/run-detail/queries'
import { useCancelJobMutation } from '@/features/run-detail/useCancelJobMutation'
import {
  resolveTab,
  visibleTabs,
} from '@/features/run-detail/resultsAvailability'
import { useRunListQuery } from '@/features/runs/useRunListQuery'
import { isTerminalStatus } from '@/features/runs/status'
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

/*
  탭 목록과 기본 탭은 resultsAvailability.ts가 정한다.

  이전에는 여기 상수 배열과 `DEFAULT_TAB = 'pipeline'`이 있었다. 완료된 실행을
  열면 "무엇이 나왔나"가 한 번의 클릭 뒤에 있고, 정작 볼 필요가 적은 과정이
  먼저 나왔다. 그리고 결과가 없는 실행에서도 결과 탭이 있어서, 없는 것을
  확인하려고 클릭해야 했다.

  status가 아니라 응답 내용으로 판단한다 — 같은 `failed`라도 정렬까지 간 실행과
  사전 점검에서 멈춘 실행은 보여줄 것이 다르다.
*/

export function RunDetailPage() {
  const { jobId = '', tab } = useParams<{ jobId: string; tab?: string }>()
  const navigate = useNavigate()

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
  const explanation = useExplanationQuery(jobId, job?.status)
  const cancel = useCancelJobMutation(jobId)

  /*
    탭은 응답이 실제로 무엇을 담고 있는지로 정해진다. `/runs/{id}/results`를
    직접 열었는데 그 실행에 결과가 없으면 파이프라인으로 접는다 — 숨긴 탭의
    주소가 빈 화면이 되지 않게 한다.
  */
  const tabs = visibleTabs(results.data, terminal)
  const activeTab = resolveTab(tab, results.data, terminal)

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
  const fromResults = collectDiagnostics(
    results.data,
    job.steps.map((s) => s.stepId),
  )

  /*
    /results가 없는 실행(실패·진행 중)에서는 explanation이 유일한 구조화
    출처다. 그때만 대체한다 — /results가 있으면 그쪽이 core_summary의 step
    귀속까지 갖고 있어 더 정확하다.
  */
  const diagnostics =
    fromResults.all.length > 0 || !explanation.data
      ? fromResults
      : collectFromExplanation(explanation.data.diagnostics)

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

        취소는 실패가 아니므로 계속 MessageBlock이다 — 준비할 항목도,
        해결 방법도 없다.
      */}
      {job.status === 'cancelled' && job.error ? (
        <MessageBlock tone="info" title="이 실행은 취소되었습니다">
          <p className="whitespace-pre-wrap">{job.error}</p>
        </MessageBlock>
      ) : null}

      {/*
        이 실행에서 일어난 일의 유일한 본문이다. 실패·확인 필요·자동 해결을
        한 표면에서 구분한다.

        이전에는 같은 warning이 결과 탭 "확인할 사항"과 파이프라인 탭에 각각
        나타나서, 사용자가 그것이 몇 개의 문제인지 스스로 세야 했다. 이제
        본문은 여기 하나이고 StepTable은 위치만 표시한다.

        구조화된 failures가 있으면 그것이 본문이고, backend가 이어 붙인
        error 문자열은 카드 안 "기술 정보"로 내려간다.

        explanation 응답에 의존하지 않는다. 그 요청이 실패해도 job.error는
        이미 있고, 실패 설명이 통째로 사라지는 것이 최악이다. 그때는 원문만
        남은 카드가 되며 이전 화면보다 나빠지지 않는다.

        보여줄 것이 없으면(성공한 실행) 카드가 스스로 null을 반환한다.
      */}
      {job.status !== 'cancelled' ? (
        <AttentionSection
          failures={explanation.data?.failures ?? []}
          rawError={job.error}
          diagnostics={diagnostics.all}
          isPrecheck={explanation.data?.contextKind === 'precheck'}
          /*
            "어디서 일어났나"로 이동. 단계를 선택하고 파이프라인 탭으로 옮긴다.
            탭은 이미 URL 세그먼트이므로 뒤로가기가 그대로 동작하고, 선택
            상태만 local state로 남는다.
          */
          onGoToStep={(stepId) => {
            setSelectedStepId(stepId)
            navigate(`/runs/${encodeURIComponent(jobId)}/pipeline`)
          }}
        />
      ) : null}

      {job.unsupportedOptions.length > 0 ? (
        <MessageBlock
          tone="warning"
          title="이 서버가 적용하지 않은 요청 옵션이 있습니다"
        >
          <code>{job.unsupportedOptions.join(', ')}</code>
        </MessageBlock>
      ) : null}

      {/*
        결과 해석의 범위 제한. 위의 job.error·unsupportedOptions와 같은 자리에
        둔다 — 셋 다 어느 탭에 있든 유효한 실행 단위 사실이고, 탭 안에 넣으면
        결과 탭을 열지 않은 사용자는 "필터가 적용되지 않았다"를 보지 못한다.

        backend deterministic explanation이 만든 문장이며 AI 생성물이 아니다.
      */}
      {explanation.data ? (
        <RunLimitations limitations={explanation.data.limitations} />
      ) : null}

      {/*
        AI 종합 설명. 탭 바깥, 결정론적 설명 바로 아래에 둔다 — 위의 사실들을
        묶은 것이므로 그 사실들 다음에 읽히는 것이 맞다.

        ⚠️ 이 컴포넌트만 사용자의 Claude 사용량을 소모한다. 버튼을 눌러야만
        호출되며, 3초 polling과 무관하다(mutation이지 query가 아니다).
      */}
      <RunSynthesisPanel
        jobId={jobId}
        terminal={terminal}
        /*
          AI 문장 안의 `artifact:...`를 이 실행의 실제 산출물 이름으로 바꾸는
          데만 쓴다. artifacts가 아직 없으면 빈 표이고, 그때는 원문이 그대로
          남는다.
        */
        locators={{
          artifactLabels: artifactLabelMap(
            artifacts.data && !isNotReady(artifacts.data)
              ? artifacts.data
              : undefined,
          ),
        }}
      />

      <TabsRoot
        value={activeTab}
        onValueChange={(next) => {
          navigate(`/runs/${encodeURIComponent(jobId)}/${next}`)
        }}
      >
        <TabsList>
          {tabs.map((item) => (
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
                단계에 귀속되지 않은 진단을 여기서 따로 그리지 않는다.
                AttentionSection이 귀속 여부와 무관하게 전부 보여주므로,
                여기 두면 같은 항목이 화면에 두 번 나온다.
              */}

              <LogPanel lines={job.logTail} />

              {/*
                "실행 조건과 식별자" 12행 표가 여기 있었다.

                job/run ID·샘플·profile·capture kit·실행 모드·상태·pipeline
                상태·진행률을 담고 있었는데, 상태 계열은 헤더가 사람이 읽는
                말로 이미 말하고 식별 계열은 결과 탭 "입력 요약"에 있다.
                같은 값을 한 번은 사람 말로, 한 번은 backend 내부 어휘로
                보여주면 사용자가 데이터 모델을 배워야 하는 화면이 된다.

                전문가용 원본은 페이지 맨 아래 DeveloperDetails가
                `GET /api/jobs/{id}` 응답 그대로 유지한다 — 접근성을 잃지
                않으면서 본문에서는 뺀다.
              */}
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
            /*
              전문가용. contextKind·sources·evidence까지 여기서 볼 수 있다 —
              화면에는 노출하지 않지만 근거를 확인할 수 있어야 한다.
            */
            { label: 'GET /api/jobs/{id}/explanation', value: explanation.data },
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

/*
  failedStepLabel()은 여기 있었다. RunFailureCard가 각 failure의
  actualStepLabel을 backend에서 받아 쓰므로, steps[]에서 실패 단계를 다시
  찾아낼 이유가 없어졌다.
*/

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
