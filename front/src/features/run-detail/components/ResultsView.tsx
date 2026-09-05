import { EmptyState } from '@/components/ui/EmptyState'
import { FileText } from 'lucide-react'

import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import type { NotReady, Results } from '@/features/run-detail/api'
import { isNotReady } from '@/features/run-detail/api'
import { formatDuration } from '@/features/runs/time'

/*
  결과.

  시안 근거
    docs/design/results-precheck.html  점검 항목 표(PASS/WARN/FAIL) · 해결해야 할
                                       문제 · 입력 요약 KV
    docs/design/results-full.html      커버리지 · 변이 검출 · 선택 단계 · 경고

  차트를 만들지 않았다. breadth는 표로 보여준다 — 첫 실행의 실제 값을 아직 본 적이
  없고, CLAUDE.md 23장이 장식용 chart를 금지한다. viridis 막대는 값이 신뢰할 수
  있다고 확인된 뒤 refinement에서 붙인다.

  가장 중요한 처리: 409는 오류가 아니다. "아직"과 "없음"을 구분한다(CLAUDE.md 14장).
*/

export interface ResultsViewProps {
  data: Results | NotReady | undefined
  isPending: boolean
  /** 실행이 아직 끝나지 않아 query를 시작하지 않은 상태. */
  waitingForRun: boolean
  /** 실행이 이미 끝났는지. 409의 문구가 "아직"인지 "없음"인지를 가른다. */
  terminal: boolean
  error: unknown
  currentStepLabel: string | null
}

export function ResultsView({
  data,
  isPending,
  waitingForRun,
  terminal,
  error,
  currentStepLabel,
}: ResultsViewProps) {
  if (waitingForRun) {
    return (
      <MessageBlock tone="info" role="status" title="결과는 실행이 끝난 뒤 제공됩니다">
        분석이 진행 중입니다.
        {currentStepLabel ? ` 현재 단계는 "${currentStepLabel}"입니다.` : ''} 결과가
        0건이라는 뜻이 아닙니다.
      </MessageBlock>
    )
  }

  if (isPending) {
    return (
      <p role="status" className="text-body text-text-muted">
        결과를 불러오는 중입니다.
      </p>
    )
  }

  if (error) {
    return (
      <MessageBlock tone="danger" title="결과를 불러오지 못했습니다">
        서버가 결과 응답을 주지 못했습니다. 실행 자체의 실패와는 다른 문제입니다.
      </MessageBlock>
    )
  }

  if (!data) return null

  if (isNotReady(data)) {
    /*
      실행이 이미 끝났는데 결과 문서가 없는 경우도 있다 — main.sh가 run
      디렉터리를 만들기 전에 죽으면(worker의 EXEC_FAILED) 결과가 영원히 오지
      않는다. 그때 "아직"이라고 말하면 기다리면 될 것처럼 읽힌다.
    */
    return (
      <MessageBlock
        tone="info"
        role="status"
        title={
          terminal
            ? '이 실행은 결과 문서를 만들지 않았습니다'
            : '결과가 아직 준비되지 않았습니다'
        }
      >
        <div className="flex flex-col gap-2">
          <p>
            {terminal
              ? '실행이 끝났지만 결과 문서가 없습니다. 파이프라인이 결과를 기록하기 전에 중단된 경우입니다 — 원인은 파이프라인 탭의 실패 사유와 로그에서 확인하세요.'
              : '이 실행은 결과 문서를 아직 만들지 않았습니다. 결과가 0건이라는 뜻이 아닙니다.'}
          </p>
          {data.reason ? (
            <code className="break-all text-text-muted">{data.reason}</code>
          ) : null}
        </div>
      </MessageBlock>
    )
  }

  const isPrecheck = data.resultType === 'precheck'

  return (
    <div className="flex flex-col gap-8">
      {/*
        check_only 오해 방지. analysisOutputProduced가 false면 BAM/VCF가 없다는
        사실을 결과 화면 맨 위에서 말한다. "완료"만 보고 전체 분석이 끝났다고
        읽히는 것을 막는 지점이다.
      */}
      {!data.analysisOutputProduced ? (
        <MessageBlock
          tone="warning"
          title="사전 점검만 수행되었습니다"
        >
          입력·환경·참조 데이터 검사만 실행되었고, 실제 분석 산출물(BAM·VCF)은
          생성되지 않았습니다. 전체 분석은 서버 실행 모드가 <code>full</code>일 때
          수행됩니다.
        </MessageBlock>
      ) : null}

      {data.failures.length > 0 ? (
        <section className="flex flex-col gap-4">
          <SectionHeader
            title="해결해야 할 문제"
            meta={`${data.failures.length}건`}
          />
          <div className="flex flex-col gap-3">
            {data.failures.map((failure, index) => (
              <MessageBlock
                key={`${failure.code}-${index}`}
                tone="danger"
                title={failure.message}
              >
                <div className="flex flex-col gap-1">
                  {failure.code ? <code>{failure.code}</code> : null}
                  {failure.stepId ? (
                    <span className="text-caption text-text-muted">
                      단계 {failure.stepId}
                    </span>
                  ) : null}
                </div>
              </MessageBlock>
            ))}
          </div>
        </section>
      ) : null}

      {data.warnings.length > 0 ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="경고" meta={`${data.warnings.length}건`} />
          <div className="flex flex-col gap-3">
            {data.warnings.map((warning, index) => (
              <MessageBlock
                key={`${warning.code}-${index}`}
                tone="warning"
                title={warning.message}
              >
                <div className="flex flex-col gap-1">
                  {warning.code ? <code>{warning.code}</code> : null}
                  {warning.impact ? <p>{warning.impact}</p> : null}
                </div>
              </MessageBlock>
            ))}
          </div>
        </section>
      ) : null}

      <section className="flex flex-col gap-4">
        <SectionHeader
          title="실행 요약"
          meta={isPrecheck ? '사전 점검' : '전체 분석'}
        />
        <dl className="flex flex-col">
          <Row label="결과 유형" value={data.resultType} mono />
          <Row
            label="분석 산출물"
            value={data.analysisOutputProduced ? '생성됨' : '생성되지 않음'}
          />
          <Row label="샘플" value={data.sample ?? '—'} mono />
          <Row
            label="소요 시간"
            value={
              data.elapsedSeconds !== null
                ? formatDuration(data.elapsedSeconds)
                : '—'
            }
          />
          <Row label="pipeline 상태" value={data.pipelineStatus ?? '—'} mono />
          <Row label="산출물 수" value={String(data.artifactCount)} mono />
          {data.intendedUse ? (
            <Row label="사용 범위" value={data.intendedUse} />
          ) : null}
        </dl>
      </section>

      {data.checks.length > 0 ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="점검 항목" meta={`${data.checks.length}건`} />
          <div className="overflow-hidden rounded-sm border border-border bg-surface">
            <div className="flex min-h-10 items-center gap-x-3 border-b border-border bg-sunken px-3">
              <span className="w-16 flex-none text-caption font-semibold tracking-wide-kr text-text-muted">
                상태
              </span>
              <span className="min-w-0 flex-1 text-caption font-semibold tracking-wide-kr text-text-muted">
                항목
              </span>
            </div>
            {data.checks.map((check) => (
              <div
                key={check.name}
                className="flex min-h-10 flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-subtle px-3 py-1 last:border-b-0"
              >
                <code className={`w-16 flex-none text-caption ${checkClass(check.status)}`}>
                  [{check.status.toUpperCase()}]
                </code>
                <code className="min-w-0 flex-1 break-all text-data text-text-strong">
                  {check.name}
                </code>
                {check.detail ? (
                  <span className="basis-full text-body text-text md:basis-auto">
                    {check.detail}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {data.coverage ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="커버리지" />
          <dl className="flex flex-col">
            <Row
              label="평균 타깃 깊이"
              value={numberOrDash(data.coverage.meanTargetDepth)}
              mono
            />
            <Row
              label="저커버리지 비율"
              value={percentOrDash(data.coverage.lowCoverageBasesPct)}
              mono
            />
            <Row
              label="미커버 비율"
              value={percentOrDash(data.coverage.uncoveredBasesPct)}
              mono
            />
            {Object.entries(data.coverage.breadth).map(([label, pct]) => (
              <Row key={label} label={`≥${label} 비율`} value={`${pct} %`} mono />
            ))}
          </dl>
          {data.coverage.medianNote ? (
            <p className="text-caption text-text-muted">
              {data.coverage.medianNote}
            </p>
          ) : null}
        </section>
      ) : null}

      {data.variantCalling ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="변이 검출" />
          <dl className="flex flex-col">
            <Row
              label="검출 레코드"
              value={numberOrDash(data.variantCalling.rawVariantRecords)}
              mono
            />
            <Row
              label="필터 적용"
              value={data.variantCalling.filteringApplied ? '예' : '아니오'}
            />
            <Row label="결과 지점" value={data.variantCalling.coreEndpoint} />
            <Row
              label="raw VCF"
              value={data.variantCalling.rawVcfRelative ?? '—'}
              mono
            />
            <Row label="gVCF" value={data.variantCalling.gvcfRelative ?? '—'} mono />
          </dl>
        </section>
      ) : null}

      {data.inputSummary ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="입력 요약" />
          <dl className="flex flex-col">
            <Row label="샘플" value={data.inputSummary.sample ?? '—'} mono />
            <Row
              label="Lane 수"
              value={numberOrDash(data.inputSummary.laneCount)}
              mono
            />
            <Row label="assembly" value={data.inputSummary.assembly ?? '—'} mono />
            <Row
              label="contig style"
              value={data.inputSummary.contigStyle ?? '—'}
              mono
            />
            <Row label="bundle" value={data.inputSummary.bundleId ?? '—'} mono />
            <Row
              label="capture kit"
              value={data.inputSummary.captureKitId ?? '—'}
              mono
            />
            <Row
              label="target BED sha256"
              value={data.inputSummary.targetBedSha256 ?? '—'}
              mono
            />
            <Row
              label="coverage BED sha256"
              value={data.inputSummary.coverageBedSha256 ?? '—'}
              mono
            />
          </dl>
        </section>
      ) : null}

      {Object.keys(data.optionalSteps).length > 0 ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="선택 단계" />
          <dl className="flex flex-col">
            {Object.entries(data.optionalSteps).map(([stepId, state]) => (
              <Row key={stepId} label={stepId} value={state} mono />
            ))}
          </dl>
        </section>
      ) : null}

      {data.checks.length === 0 &&
      !data.coverage &&
      !data.variantCalling &&
      !data.inputSummary ? (
        <EmptyState
          icon={<FileText size={32} strokeWidth={1.5} aria-hidden="true" />}
          title="표시할 결과 항목이 없습니다"
          titleLevel={3}
          description="이 실행은 결과 문서를 만들었지만 표시할 세부 항목이 없습니다. 원본 응답은 아래 개발자 정보에서 확인할 수 있습니다."
        />
      ) : null}
    </div>
  )
}

function Row({
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

function checkClass(status: string): string {
  const upper = status.toUpperCase()
  if (upper === 'PASS') return 'text-status-success-fg'
  if (upper === 'WARN') return 'text-status-warning-fg'
  return 'text-status-failure-fg'
}

function numberOrDash(value: number | null): string {
  return value === null ? '—' : value.toLocaleString()
}

function percentOrDash(value: number | null): string {
  return value === null ? '—' : `${value} %`
}
