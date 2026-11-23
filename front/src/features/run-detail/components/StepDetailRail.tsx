import type { ReactNode } from 'react'
import {
  ArrowUpRight,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Clock,
  Info,
  Package,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import { DiagnosticList } from '@/components/ui/DiagnosticNote'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SourceMark } from '@/components/ui/SourceMark'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { revealElement } from '@/features/run-detail/aiStatement'
import type { ExplanationFailure, StepDetail } from '@/features/run-detail/api'
import { byPriority, toDiagnostic } from '@/features/run-detail/diagnostics'
import { occurrenceKey } from '@/features/run-detail/factApplicability'
import type { Withheld } from '@/features/run-detail/factApplicability'
import { stepStatusDisplay } from '@/features/run-detail/stepDisplay'
import { isNotRun, isUndetermined } from '@/features/run-detail/stepView'
import { describeFailureCode } from '@/registries/failures'
import { formatDuration, formatTimestamp } from '@/features/runs/time'
import { describeStep, stepOrdinal } from '@/registries/steps'
import { formatBytes } from '@/lib/formatBytes'

/*
  선택한 단계의 상세.

  시안 근거 (docs/design/pipeline-tab.html · 우측 레일)
    제목 h2 + mono "03_alignment · BWA-MEM" + 배지 + 소요시간
    지표     라벨(small ink-500) / 값(mono ink-900 우측) 행, 하단 1px
    검증     [PASS] mono + 이름
    접기     입력/출력 · 산출물 · 경고·실패 (건수와 함께)

  metrics를 한국어로 바꾸지 않는다. 첫 full 실행 결과를 아직 본 적이 없어서
  어떤 키가 오는지 모르고, 지어낸 라벨·단위는 잘못된 정보다. 키를 그대로 mono로
  두고 실제 값을 본 뒤 registry를 만드는 것이 순서다.

  data는 부모가 query로 가져와 넘긴다 — 실행 중인 단계만 폴링한다.

  ── 워크스페이스 상세 패널 (개발판단기록 40장) ─────────────────────────

  늘 한 단계를 보여 준다(기본 선택: stepView.ts). 추가된 것은 두 가지다.
    - 시작되지 않은 단계: 빈 시간·지표·검증 표 대신 그 사실 한 줄. 끝난
      실행이면 "실행되지 않았습니다", 진행 중이면 "아직 시작되지 않았습니다".
    - 이 단계의 실패와 근거: 이 단계에 귀속된 실패(explanation failures의
      actualStepId)와, 그 실패를 설명하는 다른 화면으로 가는 길 — 실패 카드,
      참조 데이터 검사의 기록된 원인, 공식 문서 탭. 연결이 없으면 없다고 쓴다.
      화면이 원인을 새로 추론하지 않는다.

  ── 2026-11-20 승인 시안 반영 ──────────────────────────────────────────

  머리(번호 · 이름 · 이전/다음 · 상태 · 소요 · exit) → 이 단계에서 확인하는
  내용 → 기록된 실패·경고 → 관련 근거 → (실제 해설이 있을 때만) AI 해설 → 시간 ·
  지표 · 검증 · 입력/출력 · 산출물 접기 → 공식 문서 · AI 설명 탭 이동. 기존
  정보는 하나도 빼지 않고 접기 안으로 옮겼다.
*/

export interface StepNeighbor {
  stepId: string
  label: string
}

export interface StepDetailRailProps {
  stepId: string
  detail: StepDetail | undefined
  isPending: boolean
  error: unknown
  /**
   * 이 단계에 확인 가능하게 연결된 AI 해설(synthesisPlacement.ts). 실제 해설이
   * 있을 때만 부모가 넘긴다 — 없으면 AI 칸을 만들지 않는다.
   */
  aiNote?: ReactNode
  /** 목록(job.steps)의 이 단계 상태. 상세 응답 전에도 상태를 말할 수 있다. */
  stepStatus: string | undefined
  /** 실행이 끝났는가. 끝난 실행의 pending은 "실행 안 됨"이다. */
  terminal: boolean
  /**
   * backend 장부의 이 단계 실행 사실과 근거(factApplicability.ts). 있으면
   * pending 해석보다 우선한다. 이전 응답에는 없다.
   */
  execution?: { execution: string; basis: string }
  /** "(단계)|(code)" -> 이 실행에서 표시하지 않는 문장과 이유(factApplicability.ts). */
  withheld?: ReadonlyMap<string, Withheld>
  /** 이 단계에 귀속된 실패(explanation). 설명 응답이 없으면 빈 배열. */
  failures: ExplanationFailure[]
  /** 참조 데이터 검사의 기록된 원인 구획이 화면에 있는가. */
  hasResourceCauses: boolean
  /** 이 단계의 실패로 검색된 공식 문서 수. 검색 기록이 없으면 null. */
  docHitCount: number | null
  onOpenDocs: () => void
  /** 참조 데이터 검사에서 기록된 원인(ResourceCauseSection). 입력 검증 단계에만 있다. */
  causes?: ReactNode
  /** 이전·다음 단계. 처음·마지막이면 null. */
  prev?: StepNeighbor | null
  next?: StepNeighbor | null
  onSelectStep?: (stepId: string) => void
  /** AI 설명 탭으로 이동. */
  onOpenAi?: () => void
  /** 개요 탭으로 이동하고, 주어지면 그 id의 요소를 보여 준다. */
  onOpenOverview?: (revealId?: string) => void
}

export function StepDetailRail({
  stepId,
  detail,
  isPending,
  error,
  aiNote,
  stepStatus,
  terminal,
  execution,
  withheld,
  failures,
  hasResourceCauses,
  docHitCount,
  onOpenDocs,
  causes,
  prev = null,
  next = null,
  onSelectStep,
  onOpenAi,
  onOpenOverview,
}: StepDetailRailProps) {
  const definition = describeStep(stepId)
  const status = detail?.status ?? stepStatus
  const display = status ? stepStatusDisplay(status, terminal, execution?.execution) : null
  /*
    시작되지 않은 단계. 상세 응답은 200이지만 시간·지표·검증이 전부 비어 있다.
    빈 표를 늘어놓는 대신 그 사실을 한 줄로 말한다.
  */
  const undetermined = isUndetermined(execution?.execution)
  const notStarted = status === 'pending' && !undetermined
  const notRun = status !== undefined && isNotRun(status, terminal, execution?.execution)

  /*
    이 레일의 진단은 /steps/{stepId}에서 온다. /results와 달리 실행 중에도
    응답하므로, 끝나지 않은 실행에서도 구조화된 진단을 볼 수 있는 유일한
    자리다(features/run-detail/diagnostics.ts의 출처 설명 참고).
  */
  const railDiagnostics = detail
    ? [
        ...detail.failures.map((item, i) => toDiagnostic(item, true, i)),
        ...detail.warnings.map((item, i) => toDiagnostic(item, false, i)),
      ]
        .map((d) => {
          // 단계 문서의 진단은 step_id가 비어 올 수 있다. 이 레일의 단계가 그 위치다.
          const found = withheld?.get(occurrenceKey(d.stepId ?? stepId, d.code))
          return found ? { ...d, withheld: found } : d
        })
        .sort(byPriority)
    : []
  const problemCount = railDiagnostics.length > 0 ? railDiagnostics.length : failures.length

  return (
    <div className="flex flex-col gap-5">
      {/* 머리: 번호 · 이름 · 이전/다음 · 상태 · 소요 · exit */}
      <div className="flex flex-col gap-3 border-b border-border pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex-none rounded-sm border border-border bg-sunken px-1.5 py-0.5 font-mono text-caption text-text">
              {stepOrdinal(stepId)}
            </span>
            <h2 className="min-w-0 text-h2 font-semibold text-text-strong">
              {definition.label}
            </h2>
          </div>
          {onSelectStep ? (
            <div className="flex flex-none items-center gap-1">
              <NeighborButton
                direction="prev"
                neighbor={prev}
                onSelect={onSelectStep}
              />
              <NeighborButton
                direction="next"
                neighbor={next}
                onSelect={onSelectStep}
              />
            </div>
          ) : null}
        </div>
        {display ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {/* 목록과 같은 규칙(stepDisplay.ts) — warning은 완료, 끝난 실행의 pending은 실행 안 됨. */}
            <StatusBadge tone={display.tone} size="sm">
              {display.label}
            </StatusBadge>
            {detail && detail.elapsedSeconds > 0 ? (
              <span className="inline-flex items-center gap-1 font-mono text-data text-text">
                <Clock size={13} strokeWidth={1.5} aria-hidden="true" className="text-text-muted" />
                {formatDuration(detail.elapsedSeconds)}
              </span>
            ) : null}
            {detail && detail.exitCode !== null ? (
              <span className="font-mono text-caption text-text-muted">
                exit {detail.exitCode}
              </span>
            ) : null}
          </div>
        ) : null}
        <p className="font-mono text-caption text-text-muted">
          {stepId}
          {definition.tool ? ` · ${definition.tool}` : ''}
        </p>
      </div>

      {/*
        Layer 1 — 이 단계의 성질. 이번 Run의 측정값이 아니다(CLAUDE.md 21장).
        실제 결과와 섞이지 않게 제목을 단 별도 상자로 둔다.
      */}
      {definition.purpose ? (
        <section
          aria-labelledby="step-purpose-heading"
          className="flex flex-col gap-1.5 rounded-md border border-border-subtle bg-sunken p-3.5"
        >
          <h3
            id="step-purpose-heading"
            className="inline-flex items-center gap-1.5 text-small font-semibold text-text-strong"
          >
            <Info size={14} strokeWidth={1.5} aria-hidden="true" className="text-text-muted" />
            이 단계에서 확인하는 내용
          </h3>
          <p className="text-body text-text">{definition.purpose}</p>
        </section>
      ) : null}

      {undetermined ? (
        <MessageBlock tone="info" title="이 단계가 실행됐는지 기록으로 판정할 수 없습니다">
          {execution?.basis} 실행됨·실행 안 됨 어느 쪽으로도 표시하지 않습니다.
        </MessageBlock>
      ) : notStarted ? (
        <MessageBlock
          tone="info"
          title={notRun || terminal ? '이 단계는 실행되지 않았습니다' : '이 단계는 아직 시작되지 않았습니다'}
        >
          {execution && notRun
            ? `${execution.basis} 이 단계의 시간·지표·검증·산출물 기록은 없습니다.`
            : terminal
              ? '실행이 이 단계에 도달하기 전에 끝났습니다. 이 단계의 시간·지표·검증·산출물 기록은 없습니다.'
              : '앞 단계가 끝나면 시작됩니다. 시작되기 전에는 시간·지표·검증 기록이 없습니다.'}
        </MessageBlock>
      ) : null}

      {isPending ? (
        <p role="status" className="text-body text-text-muted">
          단계 정보를 불러오는 중입니다.
        </p>
      ) : null}

      {error ? <StepDetailError error={error} /> : null}

      {/*
        기록된 실패·경고(이전 이름 "발견된 문제" — 참고 수준 경고까지 "문제"로 셌다, 2026-11-23). 이 단계 기록(/steps/{stepId})의 실패·경고가 먼저이고, 그것이
        없으면 설명 응답에서 이 단계에 귀속된 실패다. 진단은 목록·결과 화면과 같은
        어휘(DiagnosticList)로, code와 backend 원문까지 보인다(Layer 3).
      */}
      {!notStarted && (detail || failures.length > 0) ? (
        <section aria-labelledby="step-problems-heading" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 id="step-problems-heading" className="text-h3 font-semibold text-text-strong">
              기록된 실패·경고{' '}
              <span className="font-mono text-data text-text-muted">({problemCount})</span>
            </h3>
            <SourceMark kind="record" />
          </div>
          {railDiagnostics.length > 0 ? (
            <DiagnosticList diagnostics={railDiagnostics} />
          ) : failures.length > 0 ? (
            <ul className="flex flex-col gap-2 rounded-md border border-status-failure-bd bg-status-failure-bg p-3.5">
              {failures.map((failure, index) => {
                const view = describeFailureCode(failure.code)
                return (
                  <li key={`${failure.code}-${index}`} className="flex flex-col gap-0.5">
                    <span className="text-body font-medium text-text-strong">
                      {view.known ? view.title : failure.message}
                    </span>
                    <code className="font-mono text-caption break-all text-text-muted">
                      {failure.code}
                    </code>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="text-small text-text-muted">
              {status === 'failed'
                ? '이 단계에 기록된 구조화된 실패·경고가 없습니다. 개요 탭 실패 카드의 원문을 확인해 주세요.'
                : '이 단계에 기록된 실패·경고가 없습니다.'}
            </p>
          )}
        </section>
      ) : null}

      <StepFailureLinks
        failures={failures}
        stepFailed={status === 'failed'}
        hasResourceCauses={hasResourceCauses}
        docHitCount={docHitCount}
        onOpenDocs={onOpenDocs}
        onOpenOverview={onOpenOverview}
        artifactCount={detail && !notStarted ? detail.artifacts.length : 0}
      />

      {/* 참조 데이터 검사의 기록된 원인(입력 검증 단계만). */}
      {causes ? (
        <div className="flex flex-col">
          <RailFoldout title="참조 데이터 검사에서 기록된 원인" count={null}>
            {causes}
          </RailFoldout>
        </div>
      ) : null}

      {/* AI 해설 — 실제로 이 단계에 연결된 해설이 있을 때만 부모가 넘긴다. */}
      {aiNote ?? null}

      {detail && !notStarted ? (
        <div className="flex flex-col">
          <RailFoldout title="시간" count={null}>
            <KeyValue label="시작" value={formatIso(detail.startedAt)} />
            <KeyValue label="종료" value={formatIso(detail.finishedAt)} />
            <KeyValue
              label="다음 단계 준비"
              value={detail.nextStepReady ? '예' : '아니오'}
            />
          </RailFoldout>

          <RailFoldout title="지표" count={Object.keys(detail.metrics).length}>
            {Object.entries(detail.metrics).map(([key, value]) => (
              <KeyValue key={key} label={key} value={formatMetric(value)} mono />
            ))}
          </RailFoldout>

          <RailFoldout title="검증" count={detail.validation.results.length}>
            {detail.validation.results.map((check) => (
              <div
                key={check.name}
                className="flex min-h-9 flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-subtle py-1 last:border-b-0"
              >
                <code
                  className={
                    check.status.toUpperCase() === 'PASS'
                      ? 'flex-none text-caption text-status-success-fg'
                      : check.status.toUpperCase() === 'WARN'
                        ? 'flex-none text-caption text-status-warning-fg'
                        : 'flex-none text-caption text-status-failure-fg'
                  }
                >
                  [{check.status.toUpperCase()}]
                </code>
                <code className="min-w-0 flex-1 break-all text-caption text-text">
                  {check.name}
                </code>
                {check.detail ? (
                  <span className="basis-full text-caption text-text-muted">
                    {check.detail}
                  </span>
                ) : null}
              </div>
            ))}
          </RailFoldout>

          <RailFoldout
            title="입력 / 출력"
            count={detail.inputs.length + detail.outputs.length}
          >
            {[
              ...detail.inputs.map((io) => ({ ...io, direction: '입력' })),
              ...detail.outputs.map((io) => ({ ...io, direction: '출력' })),
            ].map((io, index) => (
              <div
                key={`${io.direction}-${io.path}-${index}`}
                className="flex flex-col gap-0.5 border-b border-border-subtle py-1 last:border-b-0"
              >
                <span className="text-caption text-text-muted">
                  {io.direction}
                  {io.type ? ` · ${io.type}` : ''}
                </span>
                <code className="break-all text-caption text-text">{io.path}</code>
              </div>
            ))}
          </RailFoldout>

          <RailFoldout title="산출물" count={detail.artifacts.length} id="step-artifacts-fold">
            {detail.artifacts.map((artifact) => (
              <div
                key={artifact.fileId}
                className="flex flex-col gap-0.5 border-b border-border-subtle py-1 last:border-b-0"
              >
                <code className="break-all text-caption text-text-strong">
                  {artifact.displayName || artifact.relativePath}
                </code>
                <span className="text-caption text-text-muted">
                  {artifact.kind}
                  {artifact.sizeBytes !== null
                    ? ` · ${formatBytes(artifact.sizeBytes)}`
                    : ''}
                  {artifact.available ? '' : ' · 파일 없음'}
                </span>
              </div>
            ))}
          </RailFoldout>
        </div>
      ) : null}

      {/* 다른 탭으로. 문서·AI 설명이 있는지는 그 탭이 말한다 — 여기서 있다고 단정하지 않는다. */}
      {onOpenAi ? (
        <div className="flex flex-wrap gap-2 border-t border-border pt-4">
          <button type="button" className={LINK_CLASS} onClick={onOpenDocs}>
            <BookOpen size={14} strokeWidth={1.5} aria-hidden="true" />
            공식 문서 탭으로
          </button>
          <button type="button" className={LINK_CLASS} onClick={onOpenAi}>
            <Sparkles size={14} strokeWidth={1.5} aria-hidden="true" />
            AI 설명 탭으로
          </button>
        </div>
      ) : null}
    </div>
  )
}

function NeighborButton({
  direction,
  neighbor,
  onSelect,
}: {
  direction: 'prev' | 'next'
  neighbor: StepNeighbor | null
  onSelect: (stepId: string) => void
}) {
  const Icon = direction === 'prev' ? ChevronLeft : ChevronRight
  const word = direction === 'prev' ? '이전 단계' : '다음 단계'
  return (
    <button
      type="button"
      disabled={!neighbor}
      onClick={() => neighbor && onSelect(neighbor.stepId)}
      aria-label={neighbor ? `${word}: ${neighbor.label}` : `${word} 없음`}
      title={neighbor ? `${word}: ${neighbor.label}` : undefined}
      className="inline-flex size-8 items-center justify-center rounded-md border border-border bg-surface text-text hover:border-brand hover:text-brand disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border disabled:hover:text-text"
    >
      <Icon size={16} strokeWidth={1.5} aria-hidden="true" />
    </button>
  )
}

/** 실패 카드 · 기록된 원인 · 공식 문서로 가는 버튼의 모양. */
const LINK_CLASS =
  'inline-flex min-h-8 items-center gap-1.5 rounded-pill border border-border bg-surface px-3 text-small text-text hover:border-brand hover:text-brand'

/*
  관련 근거. 실패가 귀속되지 않았고 실패하지도 않은 단계에서는 그리지 않는다.
  이유·해결 방법 본문은 개요 탭의 실패 카드에 있다 — 여기서 다시 쓰지 않고
  그쪽으로 이동한다. 연결이 없으면 없다고 쓴다.
*/
function StepFailureLinks({
  failures,
  stepFailed,
  hasResourceCauses,
  docHitCount,
  onOpenDocs,
  onOpenOverview,
  artifactCount,
}: {
  failures: ExplanationFailure[]
  stepFailed: boolean
  hasResourceCauses: boolean
  docHitCount: number | null
  onOpenDocs: () => void
  onOpenOverview?: (revealId?: string) => void
  artifactCount: number
}) {
  if (failures.length === 0 && !stepFailed) return null
  const openAttention = () =>
    onOpenOverview
      ? onOpenOverview('run-attention-heading')
      : revealElement(document.getElementById('run-attention-heading'), 'start')
  return (
    <section aria-labelledby="step-failure-links-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 id="step-failure-links-heading" className="text-h3 font-semibold text-text-strong">
          관련 근거
        </h3>
        <SourceMark kind="record" />
      </div>
      <div className="flex flex-wrap gap-2">
        {failures.map((failure, index) => (
          <button
            key={`${failure.code}-${index}`}
            type="button"
            className={LINK_CLASS}
            onClick={openAttention}
          >
            <TriangleAlert size={14} strokeWidth={1.5} aria-hidden="true" />
            <code className="font-mono text-caption">{failure.code}</code>
          </button>
        ))}
        <button type="button" className={LINK_CLASS} onClick={openAttention}>
          <ArrowUpRight size={14} strokeWidth={1.5} aria-hidden="true" />
          실패 카드에서 이유·해결 방법 보기
        </button>
        {hasResourceCauses ? (
          <button
            type="button"
            className={LINK_CLASS}
            onClick={() =>
              revealElement(document.getElementById('resource-cause-heading'), 'start')
            }
          >
            <ArrowUpRight size={14} strokeWidth={1.5} aria-hidden="true" />
            기록된 원인 보기
          </button>
        ) : null}
        <button type="button" className={LINK_CLASS} onClick={onOpenDocs}>
          <BookOpen size={14} strokeWidth={1.5} aria-hidden="true" />
          {docHitCount === null
            ? '공식 문서 · 검색 기록 없음'
            : `관련 공식 문서 ${docHitCount}건`}
        </button>
        {artifactCount > 0 ? (
          <button
            type="button"
            className={LINK_CLASS}
            onClick={() => {
              const fold = document.getElementById('step-artifacts-fold')
              if (fold instanceof HTMLDetailsElement) fold.open = true
              revealElement(fold, 'start')
            }}
          >
            <Package size={14} strokeWidth={1.5} aria-hidden="true" />
            산출물 {artifactCount}건
          </button>
        ) : null}
      </div>
      {docHitCount === 0 ? (
        <p className="text-caption text-text-muted">
          가장 최근 검색 기록에서 이 단계의 실패로 반환된 공식 문서는 없습니다.
        </p>
      ) : null}
    </section>
  )
}

/** 접기. 건수가 0이면 열 것이 없으므로 제목만 흐리게 둔다. count가 null이면 건수를 쓰지 않는다. */
function RailFoldout({
  title,
  count,
  id,
  children,
}: {
  title: string
  count: number | null
  id?: string
  children: ReactNode
}) {
  if (count === 0) {
    return (
      <div className="flex min-h-11 items-center justify-between gap-3 border-t border-border-subtle py-2">
        <span className="text-body font-medium text-text-muted">{title}</span>
        <span className="text-small text-text-muted">없음</span>
      </div>
    )
  }

  return (
    <details id={id} className="group border-t border-border-subtle">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 [&::-webkit-details-marker]:hidden">
        <span className="inline-flex items-center gap-1.5 text-body font-medium text-text-strong">
          <ChevronRight
            size={14}
            strokeWidth={1.5}
            aria-hidden="true"
            className="text-text-muted transition-transform group-open:rotate-90"
          />
          {title}
        </span>
        {count !== null ? <span className="text-small text-text-muted">{count}건</span> : null}
      </summary>
      <div className="flex flex-col pb-3 pl-5">{children}</div>
    </details>
  )
}

function KeyValue({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex min-h-9 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border-subtle py-1 last:border-b-0">
      <span
        className={
          mono
            ? 'min-w-0 flex-1 truncate font-mono text-caption text-text-muted'
            : 'flex-none text-small text-text-muted'
        }
      >
        {label}
      </span>
      <span className="min-w-0 text-right font-mono text-data text-text-strong">
        {value}
      </span>
    </div>
  )
}

function formatIso(value: string | null): string {
  const formatted = formatTimestamp(value)
  return formatted ? formatted.full : '—'
}

/** metric 값은 해석하지 않는다. 객체·배열이면 JSON 그대로 보여준다. */
function formatMetric(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/*
  단계 상세를 읽지 못한 경우.

  step endpoint는 실패한 단계에도 200을 준다(api/steps.py). 따라서 여기 오는
  오류는 단계의 실패가 아니라 통신·계약 문제다. 둘을 섞어 보여주면 사용자가
  "분석이 실패했다"로 오독한다.
*/
function StepDetailError({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return (
        <MessageBlock tone="info" title="이 단계의 기록이 없습니다">
          이 실행의 계획에 없는 단계이거나, 아직 기록이 만들어지지 않았습니다.
        </MessageBlock>
      )
    }
    return (
      <MessageBlock tone="danger" title="단계 정보를 불러오지 못했습니다">
        <div className="flex flex-col gap-2">
          <p>
            {error.kind === 'network'
              ? '서버에 연결하지 못했습니다.'
              : error.kind === 'malformed'
                ? '응답 형식이 frontend가 아는 계약과 다릅니다.'
                : `서버가 HTTP ${error.status}로 응답했습니다.`}
          </p>
          {error.detail ? (
            <code className="break-all text-caption text-text-muted">
              {error.detail}
            </code>
          ) : null}
        </div>
      </MessageBlock>
    )
  }
  return (
    <MessageBlock tone="danger" title="단계 정보를 불러오지 못했습니다">
      알 수 없는 오류입니다.
    </MessageBlock>
  )
}
