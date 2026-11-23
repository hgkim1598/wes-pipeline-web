import { useEffect } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  BookOpen,
  ChevronRight,
  FolderOpen,
  LayoutDashboard,
  ListChecks,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { ApiError } from '@/api/client'
import { isNotReady } from '@/features/run-detail/api'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { cx } from '@/lib/cx'
import { TabsList, TabsPanel, TabsRoot, TabsTab } from '@/components/ui/Tabs'
import { AiNote } from '@/features/run-detail/components/AiNote'
import { AiStatusBar } from '@/features/run-detail/components/AiStatusBar'
import { ArtifactsView } from '@/features/run-detail/components/ArtifactsView'
import { DeveloperDetails } from '@/features/run-detail/components/DeveloperDetails'
import { DocEvidenceSection } from '@/features/run-detail/components/DocEvidenceSection'
import { LogPanel } from '@/features/run-detail/components/LogPanel'
import { ResultsView } from '@/features/run-detail/components/ResultsView'
import { AttentionSection } from '@/features/run-detail/components/AttentionSection'
import { RunFacts, RunHeader } from '@/features/run-detail/components/RunHeader'
import { PipelineStepper } from '@/features/run-detail/components/PipelineStepper'
import { ResourceCauseSection } from '@/features/run-detail/components/ResourceCauseSection'
import { RunLimitations } from '@/features/run-detail/components/RunLimitations'
import { RunSynthesisPanel } from '@/features/run-detail/components/RunSynthesisPanel'
import { artifactLabelMap } from '@/features/run-detail/locators'
import {
  OPEN_DOC_EVIDENCE_EVENT,
  OPEN_STATEMENT_EVENT,
  revealElement,
  statementAnchorId,
} from '@/features/run-detail/aiStatement'
import { useDocSearchHistory } from '@/features/run-detail/docSearchQuery'
import { hitsForStep } from '@/features/run-detail/docWorkspace'
import { resolveStepId } from '@/features/run-detail/stepView'
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
  applyWithheld,
  executionByStep,
  withLedger,
  withheldByOccurrence,
} from '@/features/run-detail/factApplicability'
import {
  findStepStatus,
  phaseOf,
  useArtifactsQuery,
  useExplanationQuery,
  useJobDetailQuery,
  useRefreshOnSettle,
  useResultsQuery,
  useStepDetailQuery,
} from '@/features/run-detail/queries'
import { connectionState } from '@/features/run-detail/runDetailPolicy'
import { useCancelJobMutation } from '@/features/run-detail/useCancelJobMutation'
import { useRunSynthesis } from '@/features/run-detail/useRunSynthesis'
import {
  numberStatements,
  pick,
  placeStatements,
} from '@/features/run-detail/synthesisPlacement'
import type { StatementPlacement } from '@/features/run-detail/synthesisPlacement'
import {
  resolveTab,
  visibleTabs,
} from '@/features/run-detail/resultsAvailability'
import { useRunListQuery } from '@/features/runs/useRunListQuery'
import { isTerminalStatus } from '@/features/runs/status'
import { describeDiagnostic } from '@/registries/diagnostics'
import { describeFailureCode } from '@/registries/failures'
import { describeStep } from '@/registries/steps'

/*
  실행 상세 — Analysis Workspace.

  2026-11-20 승인 시안(개발판단기록 41장)
    전역 사이드바(AppShell) · 짧은 Run 헤더 · 바로 아래 Run 탭
    (개요 / 파이프라인 / 공식 문서 / AI 설명 / 파일) · 하단 RUO 문구.
    카드는 1px 선 + 옅은 --shadow-card + --radius-lg다(CLAUDE.md 23장).
    이전 탭 밖에 있던 실패 카드·제한·AI 상태·AI 패널은 각각 개요 탭과 AI 설명
    탭으로 들어갔다. 헤더의 한 줄이 개요 밖의 탭에서 멈춘 위치와 실패 건수를 말한다(개요는 RunFacts).

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

/** Run 탭 아이콘. 표식일 뿐이고 이름은 글자가 말한다. AI 탭만 AI 색(보라)이다. */
const TAB_ICON: Record<string, LucideIcon> = {
  overview: LayoutDashboard,
  pipeline: ListChecks,
  docs: BookOpen,
  ai: Sparkles,
  files: FolderOpen,
}

/** 리소스 검사(resource_bundle)를 담당하는 단계. P0-1 원인은 이 단계 상세에만 있다. */
const VALIDATION_STEP_ID = '00_input_validation'

export function RunDetailPage() {
  const { jobId = '', tab } = useParams<{ jobId: string; tab?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()

  const detail = useJobDetailQuery(jobId)
  const job = detail.data
  const terminal = job ? isTerminalStatus(job.status) : false
  // 딸린 query의 정책은 모두 이 값 하나로 정한다(runDetailPolicy.ts).
  const phase = phaseOf(job, detail.error)
  useRefreshOnSettle(jobId, phase)

  /*
    파이프라인 워크스페이스의 선택 단계는 URL(?step=)이다(개발판단기록 40장).
    상세 패널은 늘 한 단계를 보여 주므로, 값이 없거나 계획에 없는 단계면
    실패 → 실행 중 → 경고 → 첫 단계 순으로 고른다(stepView.ts). 링크를
    공유하거나 새로고침해도 같은 단계가 열린다.
  */
  const selectedStepId = resolveStepId(
    searchParams.get('step'),
    job?.steps ?? [],
    job?.currentStep ?? null,
  )
  const selectStep = (stepId: string) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('step', stepId)
        return next
      },
      { replace: true },
    )

  /*
    공식 문서 검색 기록(GET). 공식 문서 탭과 상세 패널의 "관련 공식 문서 n건"이
    같은 query를 읽는다.
  */
  const docHistory = useDocSearchHistory(jobId)

  /*
    AI 설명의 근거(doc:·manual:)에서 "공식 문서 탭에서 보기"를 누르면 이
    탭으로 옮겨 그 문서를 연다. 거르기·검색 기록 선택은 탭이 정한다
    (DocEvidenceSection). revealDoc 상태는 "상세 패널로 스크롤하라"는 뜻이다.
  */
  useEffect(() => {
    const onOpen = (event: Event) => {
      const evidenceId = (event as CustomEvent<string>).detail
      navigate(
        `/runs/${encodeURIComponent(jobId)}/docs?doc=${encodeURIComponent(evidenceId)}`,
        { state: { revealDoc: true } },
      )
    }
    window.addEventListener(OPEN_DOC_EVIDENCE_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_DOC_EVIDENCE_EVENT, onOpen)
  }, [jobId, navigate])

  /*
    AI 해설의 "전체 설명에서 근거 보기"(AiNote)·공식 문서 상세의 AI 문장 버튼은
    AI 설명 탭의 그 문장으로 간다. AI 설명은 탭이라 지금 화면에 없을 수 있어서
    요청만 알리고(aiStatement.ts) 여기서 탭을 옮긴다.
  */
  useEffect(() => {
    const onOpen = (event: Event) => {
      const number = (event as CustomEvent<number>).detail
      navigate(`/runs/${encodeURIComponent(jobId)}/ai`, {
        state: { reveal: statementAnchorId(number) },
      })
    }
    window.addEventListener(OPEN_STATEMENT_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_STATEMENT_EVENT, onOpen)
  }, [jobId, navigate])

  /*
    탭 이동과 함께 온 "이 요소를 보여 달라"(state.reveal). 새 탭의 내용이 그려진
    뒤 다음 프레임에 찾는다. 접힌 묶음 안이면 연다(revealElement).
  */
  const revealId = (location.state as { reveal?: string } | null)?.reveal
  useEffect(() => {
    if (!revealId) return
    const frame = requestAnimationFrame(() =>
      revealElement(document.getElementById(revealId), 'center'),
    )
    return () => cancelAnimationFrame(frame)
  }, [location.key, revealId])

  // 목록에서 이 job의 행을 찾는다. 상세 응답에 없는 필드의 출처다.
  const list = useRunListQuery()
  const listItem = list.data?.jobs.find((item) => item.jobId === jobId)

  const stepStatus = findStepStatus(job, selectedStepId)
  const step = useStepDetailQuery(jobId, selectedStepId, stepStatus)
  const results = useResultsQuery(jobId, phase)
  const artifacts = useArtifactsQuery(jobId, phase)
  const explanation = useExplanationQuery(jobId, phase)
  const cancel = useCancelJobMutation(jobId)
  /*
    AI 종합 설명 요청은 페이지가 하나 가진다. 패널·상태 줄·각 항목의 AI 해설이
    같은 응답을 읽는다(useRunSynthesis). 호출은 여전히 패널의 버튼으로만 한다.
  */
  const synthesis = useRunSynthesis(jobId)

  /*
    리소스 검사 실패 원인(P0-1)은 입력 검증 단계의 상세에만 실려 온다. 그
    단계가 실패했을 때만 한 번 읽는다(GET, 모델 호출 없음). 레일에서 같은 단계를
    선택하면 같은 query key라 다시 요청하지 않는다.
  */
  const validationStep = job?.steps.find((s) => s.stepId === VALIDATION_STEP_ID)
  const validationDetail = useStepDetailQuery(
    jobId,
    validationStep?.status === 'failed' ? VALIDATION_STEP_ID : null,
    validationStep?.status,
  )

  /*
    탭은 응답이 실제로 무엇을 담고 있는지로 정해진다. `/runs/{id}/results`를
    직접 열었는데 그 실행에 결과가 없으면 파이프라인으로 접는다 — 숨긴 탭의
    주소가 빈 화면이 되지 않게 한다.
  */
  const tabs = visibleTabs()
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

  /*
    받은 상세가 하나도 없을 때만 전체 오류 화면이다. 폴링 중의 일시적 실패는
    react-query가 마지막 성공 값을 그대로 두므로 화면을 유지하고, 헤더의
    PollingStatus가 "연결 끊김 · 마지막 성공 시각 기준"을 보여 준다.
  */
  if (!job) {
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
  /*
    이 실행의 기록이 뒷받침하지 않는 설명 문장(backend applicability)을 표시
    전에 표시한다. 어느 경로로 모았든 같은 (단계, code)에 붙는다.
  */
  const withheld = withheldByOccurrence(explanation.data)
  const diagnostics = applyWithheld(
    fromResults.all.length > 0 || !explanation.data
      ? fromResults
      : collectFromExplanation(explanation.data.diagnostics),
    withheld,
  )

  /*
    단계별 실행 사실(backend 장부). 있으면 목록·진행 표시·상세 패널이 pending
    해석 대신 이것을 쓴다(stepView.isNotRun). 이전 응답이면 빈 Map이다.
  */
  const ledger = executionByStep(explanation.data)
  const steps = withLedger(job.steps, ledger)

  /*
    요약 띠의 건수. AttentionSection과 같은 입력에서 센다 — 실패는 구조화된
    failures(없으면 원문 error 한 건), 확인 필요·참고는 진단의 kind다.
  */
  const failureCount =
    explanation.data?.failures.length ||
    diagnostics.counts.failure ||
    (job.error && job.status !== 'cancelled' ? 1 : 0)
  const issues = {
    failures: failureCount,
    attention: diagnostics.counts.attention,
    notes: diagnostics.counts.repaired + diagnostics.counts.note,
  }

  /*
    AI 문장 → 화면 항목 배분(synthesisPlacement.ts). 근거 id가 이 Run의 항목
    하나를 확인 가능하게 가리킬 때만 붙인다. 실행 설명이 없으면 항목을 확인할
    수 없으므로 배분하지 않는다 — 문장은 전부 패널에 그대로 있다.

    화면 목록(shownDiagnosticCodes)은 실패 카드가 실제로 그리는 진단이다.
    /results에서 왔을 수 있으므로 설명 응답과 따로 넘겨 두 곳 모두에서 하나일
    때만 붙인다.
  */
  const synthesisBody = synthesis.result?.available ? synthesis.result.synthesis : null
  const placement: StatementPlacement | null =
    synthesisBody && explanation.data
      ? placeStatements({
          synthesis: synthesisBody,
          failures: explanation.data.failures.map((f) => ({
            code: f.code,
            stepId: f.actualStepId,
          })),
          diagnostics: explanation.data.diagnostics.map((d) => ({
            code: d.code,
            stepId: d.actualStepId,
          })),
          shownDiagnosticCodes: diagnostics.all
            .filter((d) => d.view.kind !== 'failure')
            .map((d) => d.code),
          limitationCodes: explanation.data.limitations.map((l) => l.code),
          stepIds: job.steps.map((s) => s.stepId),
          isRegisteredDiagnostic: (code) => describeDiagnostic(code).title !== '',
          isRegisteredFailure: (code) => describeFailureCode(code).known,
        })
      : null

  const locators = {
    artifactLabels: artifactLabelMap(
      artifacts.data && !isNotReady(artifacts.data) ? artifacts.data : undefined,
    ),
  }

  /** 번호 목록 → AI 해설 줄. 없으면 null(아무것도 그리지 않음). */
  const aiNote = (numbers: readonly number[] | undefined) => {
    if (!placement) return null
    const statements = pick(placement, numbers)
    return statements.length > 0 ? (
      <AiNote statements={statements} locators={locators} />
    ) : null
  }
  const aiNoteCountByStep = placement
    ? new Map([...placement.byStep].map(([stepId, numbers]) => [stepId, numbers.length]))
    : undefined

  /** 다른 화면(실패 카드·공식 문서 탭)에서 파이프라인의 한 단계로 이동. */
  const goToStep = (stepId: string) =>
    navigate(
      `/runs/${encodeURIComponent(jobId)}/pipeline?step=${encodeURIComponent(stepId)}`,
    )

  const resourceDiagnosis = validationDetail.data?.resourceBundleDiagnosis
  const hasResourceCauses =
    job.status !== 'cancelled' &&
    resourceDiagnosis?.state === 'parsed' &&
    resourceDiagnosis.causes.length > 0
  const selectedStepState = job.steps.find((s) => s.stepId === selectedStepId)

  const selectedIndex = job.steps.findIndex((s) => s.stepId === selectedStepId)
  const neighbor = (index: number) => {
    const item = job.steps[index]
    return item ? { stepId: item.stepId, label: describeStep(item.stepId).label } : null
  }
  const finishedSteps = job.steps.filter(
    (s) => s.status !== 'pending' && s.status !== 'running',
  ).length
  const runPath = `/runs/${encodeURIComponent(jobId)}`
  const openOverview = (revealId?: string) =>
    navigate(`${runPath}/overview`, revealId ? { state: { reveal: revealId } } : undefined)

  return (
    <Shell wide>
      <RunHeader
        job={job}
        listItem={listItem}
        issues={issues}
        showPositionLine={activeTab !== 'overview'}
        polling={{
          updatedAt: detail.dataUpdatedAt,
          connection: connectionState({
            isError: detail.isError,
            failureCount: detail.failureCount,
            isFetching: detail.isFetching,
          }),
        }}
        onCancel={() => cancel.mutate()}
        isCancelling={cancel.isPending}
        cancelError={cancel.error}
      />

      {/*
        Run 탭은 헤더 바로 아래다(2026-11-20 승인 시안, 사용자 결정). 왼쪽
        사이드바는 서비스 전체 이동이고 이 탭은 한 Run 안의 화면 전환이다.
        탭은 URL 경로 세그먼트이며 한 Route(/runs/:jobId/:tab?)라 탭을 옮겨도
        페이지가 다시 마운트되지 않는다 — AI 요청 상태(useRunSynthesis)가 유지된다.
      */}
      <TabsRoot
        value={activeTab}
        onValueChange={(next) => {
          navigate(`${runPath}/${next}`)
        }}
      >
        <TabsList>
          {tabs.map((item) => {
            const Icon = TAB_ICON[item.id]
            return (
              <TabsTab key={item.id} value={item.id}>
                <span className="inline-flex items-center gap-1.5">
                  {Icon ? (
                    <Icon
                      size={15}
                      strokeWidth={1.5}
                      aria-hidden="true"
                      /*
                        좁은 화면에서는 아이콘을 뺀다 — 표식일 뿐이고 이름은 글자가
                        말한다. 그래야 390px에서 다섯 탭이 한 줄에 들어간다.
                      */
                      className={cx('hidden md:block', item.id === 'ai' && 'text-ai-fg')}
                    />
                  ) : null}
                  {item.label}
                </span>
              </TabsTab>
            )
          })}
        </TabsList>

        <TabsPanel value="overview">
          <div className="flex flex-col gap-6">
            {/*
              취소는 실패가 아니므로 MessageBlock이다 — 준비할 항목도, 해결
              방법도 없다.
            */}
            {job.status === 'cancelled' && job.error ? (
              <MessageBlock tone="info" title="이 실행은 취소되었습니다">
                <p className="whitespace-pre-wrap">{job.error}</p>
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

            {/* 헤더에 있던 네 칸 요약. 값은 모두 응답에서 온다. */}
            <RunFacts job={job} listItem={listItem} issues={issues} />

            {/*
              어디서 멈췄나·어디까지 왔나를 띠 하나로(2026-11-23, ref 1). 파이프라인
              탭과 같은 component·같은 단계 상태(장부 반영)다. 점을 누르면 그
              단계의 파이프라인 상세로 간다. 강조 단계는 실패 → 실행 중 → 경고 순
              (stepView.resolveStepId)이라 URL에 ?step=이 없어도 멈춘 곳이 보인다.
            */}
            {steps.length > 0 ? (
              <section
                aria-labelledby="overview-pipeline-heading"
                className="flex flex-col gap-3 rounded-lg border border-border bg-surface px-5 py-4 shadow-card"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h2 id="overview-pipeline-heading" className="text-body font-semibold text-text-strong">
                    파이프라인
                  </h2>
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
                  onSelect={goToStep}
                  controlsDetail={false}
                />
              </section>
            ) : null}

            {/*
              이 실행에서 일어난 일의 유일한 본문(실패·확인 필요·자동 해결).
              구조화된 failures가 있으면 그것이 본문이고 backend error 문자열은
              카드 안 "기술 정보"로 내려간다. explanation 응답에 의존하지 않는다
              — 그 요청이 실패해도 원문만 남은 카드가 된다. 성공한 실행이면
              카드가 스스로 null을 반환한다.
            */}
            {job.status !== 'cancelled' ? (
              <AttentionSection
                failures={explanation.data?.failures ?? []}
                rawError={job.error}
                diagnostics={diagnostics.all}
                isPrecheck={explanation.data?.contextKind === 'precheck'}
                onGoToStep={(stepId) => goToStep(stepId)}
                renderAiNote={
                  placement
                    ? (kind, code) =>
                        aiNote(
                          (kind === 'failure' ? placement.byFailure : placement.byDiagnostic).get(code),
                        )
                    : undefined
                }
              />
            ) : null}

            {/*
              결과 해석의 범위 제한. backend deterministic explanation이 만든
              문장이며 AI 생성물이 아니다.
            */}
            {explanation.data ? (
              <RunLimitations
                limitations={explanation.data.limitations}
                renderAiNote={
                  placement ? (code) => aiNote(placement.byLimitation.get(code)) : undefined
                }
              />
            ) : null}

            {/*
              분석 결과(이전 "결과" 탭, /results 주소는 이 탭으로 온다). 결과가
              없거나 아직 끝나지 않은 실행의 안내는 ResultsView가 그대로 말한다.
            */}
            <ResultsView
              data={results.data}
              isPending={results.isPending && terminal}
              waitingForRun={!terminal}
              terminal={terminal}
              error={results.error}
              currentStepLabel={currentStepLabel}
            />
          </div>
        </TabsPanel>

        <TabsPanel value="pipeline">
          <div className="flex flex-col gap-6">
            {/* 가로 진행 표시(이전 헤더의 단계 띠). 점을 누르면 그 단계를 선택한다. */}
            <section
              aria-labelledby="pipeline-progress-heading"
              className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-5 shadow-card"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h2 id="pipeline-progress-heading" className="text-h3 font-semibold text-text-strong">
                  파이프라인 진행
                </h2>
                <span className="text-small text-text-muted">
                  {job.steps.length}단계 중{' '}
                  <span className="font-mono text-data text-text">{finishedSteps}</span>단계 끝남
                </span>
              </div>
              <PipelineStepper
                steps={steps}
                selectedStepId={selectedStepId}
                terminal={terminal}
                onSelect={selectStep}
              />
            </section>

            {/*
              파이프라인 워크스페이스 — 왼쪽 단계 목록(약 60%), 오른쪽 선택 단계의
              상세 패널(약 40%, sticky). 패널은 늘 있다(기본 선택: stepView.ts).
              lg 미만에서는 목록 아래로 내려간다.

              단계에 귀속되지 않은 진단은 여기 따로 그리지 않는다 — 개요 탭의
              AttentionSection이 전부 보여준다.
            */}
            <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <section
                aria-labelledby="pipeline-steps-heading"
                className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-card md:p-5"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h2 id="pipeline-steps-heading" className="text-h3 font-semibold text-text-strong">
                    분석 단계
                  </h2>
                  <span className="text-small text-text-muted">{job.steps.length}단계 계획</span>
                </div>
                <StepTable
                  steps={steps}
                  currentStepId={job.currentStep}
                  selectedStepId={selectedStepId}
                  terminal={terminal}
                  diagnosticsByStep={diagnostics.byStep}
                  aiNoteCountByStep={aiNoteCountByStep}
                  onSelect={(stepId) => {
                    selectStep(stepId)
                    // 좁은 화면에서는 패널이 목록 아래에 있다. 누른 결과가 보이게 내려 준다.
                    if (window.matchMedia('(max-width: 69.99rem)').matches) {
                      requestAnimationFrame(() =>
                        document
                          .getElementById(STEP_DETAIL_PANEL_ID)
                          ?.scrollIntoView({ block: 'start' }),
                      )
                    }
                  }}
                />
              </section>

              {selectedStepId ? (
                <aside
                  id={STEP_DETAIL_PANEL_ID}
                  aria-label="선택한 단계의 상세"
                  className="scroll-mt-6 rounded-lg border border-border bg-surface p-5 shadow-card lg:sticky lg:top-6"
                >
                  <StepDetailRail
                    key={selectedStepId}
                    stepId={selectedStepId}
                    detail={step.data}
                    isPending={step.isPending}
                    error={step.error}
                    aiNote={placement ? aiNote(placement.byStep.get(selectedStepId)) : undefined}
                    stepStatus={selectedStepState?.status}
                    terminal={terminal}
                    execution={ledger.get(selectedStepId)}
                    withheld={withheld}
                    failures={
                      explanation.data?.failures.filter(
                        (f) => f.actualStepId === selectedStepId,
                      ) ?? []
                    }
                    hasResourceCauses={
                      hasResourceCauses && selectedStepId === VALIDATION_STEP_ID
                    }
                    docHitCount={hitsForStep(docHistory.data?.[0], selectedStepId)}
                    causes={
                      hasResourceCauses && selectedStepId === VALIDATION_STEP_ID ? (
                        <ResourceCauseSection diagnosis={resourceDiagnosis} />
                      ) : undefined
                    }
                    onOpenDocs={() => navigate(`${runPath}/docs`)}
                    onOpenAi={() => navigate(`${runPath}/ai`)}
                    onOpenOverview={openOverview}
                    prev={neighbor(selectedIndex - 1)}
                    next={neighbor(selectedIndex + 1)}
                    onSelectStep={selectStep}
                  />
                </aside>
              ) : null}
            </div>

            {/* 실행 로그. 접어 두되 지우지 않는다. */}
            <details className="group rounded-lg border border-border bg-surface shadow-card">
              <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-5 py-3 text-body font-semibold text-text-strong [&::-webkit-details-marker]:hidden">
                <ChevronRight
                  size={16}
                  strokeWidth={1.5}
                  aria-hidden="true"
                  className="text-text-muted transition-transform group-open:rotate-90"
                />
                실행 로그
                <span className="text-small font-normal text-text-muted">
                  최근 {job.logTail.length}줄
                </span>
              </summary>
              <div className="border-t border-border-subtle p-5">
                <LogPanel lines={job.logTail} />
              </div>
            </details>
          </div>
        </TabsPanel>

        <TabsPanel value="docs">
          <DocEvidenceSection
            jobId={jobId}
            history={docHistory}
            statements={synthesisBody ? numberStatements(synthesisBody) : []}
            onGoToStep={goToStep}
          />
        </TabsPanel>

        <TabsPanel value="ai">
          <div className="flex flex-col gap-6">
            {/*
              AI 해설의 상태 한 줄. 각 항목 옆 해설은 있을 때만 그려지므로, 없음·
              요청 전·폐기·생성 중의 차이는 여기서 읽힌다.
            */}
            <AiStatusBar
              synthesis={synthesis}
              terminal={terminal}
              placement={placement}
              explanationAvailable={Boolean(explanation.data)}
            />
            {/*
              AI 종합 설명. ⚠️ 이 컴포넌트만 사용자의 Claude 사용량을 소모한다.
              버튼을 눌러야만 호출되며 3초 polling과 무관하다(mutation). 요청
              상태는 페이지가 가지므로 탭을 옮겨도 사라지지 않는다.
            */}
            <RunSynthesisPanel synthesis={synthesis} terminal={terminal} locators={locators} />
          </div>
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
