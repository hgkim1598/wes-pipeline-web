import { EmptyState } from '@/components/ui/EmptyState'
import { FileText } from 'lucide-react'

import { DiagnosticList } from '@/components/ui/DiagnosticNote'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import type { NotReady, Results } from '@/features/run-detail/api'
import { isNotReady } from '@/features/run-detail/api'
import type { RunDiagnostic } from '@/features/run-detail/diagnostics'
import { byPriority, toDiagnostic } from '@/features/run-detail/diagnostics'
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

  /*
    실패와 경고를 하나의 진단 목록으로 합쳐 심각한 순서로 정렬한다.
    분류는 registries/diagnostics.ts가 맡는다 — 이 파일은 표시만 한다.
  */
  const diagnostics: RunDiagnostic[] = [
    ...data.failures.map((item, i) => toDiagnostic(item, true, i)),
    ...data.warnings.map((item, i) => toDiagnostic(item, false, i)),
  ].sort(byPriority)

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

      {/*
        확인할 사항.

        실패와 경고를 두 개의 section으로 나누지 않는다. 사용자가 묻는 것은
        "무엇을 확인해야 하나"이고, 그 답은 심각한 순서로 정렬된 하나의
        목록이다. 두 목록으로 쪼개면 실패가 없는 흔한 경우에 "경고"라는
        제목만 남아 실제보다 나쁜 인상을 준다.

        tint 카드를 쓰지 않는 이유는 DiagnosticNote의 주석에 있다.
      */}
      {diagnostics.length > 0 ? (
        <section className="flex flex-col gap-4">
          <SectionHeader
            title="확인할 사항"
            meta={summarizeDiagnostics(diagnostics)}
          />
          <DiagnosticList diagnostics={diagnostics} />
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

      {/*
        점검 항목 — Layer 3.

        통과 항목을 기본으로 접는다. 시안이 같은 처리를 한다
        (results-full.html: "통과 30건은 숨겨져 있습니다" + "전체 보기").
        31건 중 30건이 PASS인 표를 그대로 펼치면 유일하게 중요한 1건이
        묻히고, 첫 화면이 기술 표로 뒤덮인다. 통과 건수는 숨기더라도
        문장으로 계속 보여준다 — 검사가 없었던 것과 통과한 것은 다르다.
      */}
      {data.checks.length > 0 ? (
        <CheckTable checks={data.checks} />
      ) : null}

      {data.coverage ? (
        <section className="flex flex-col gap-5">
          <SectionHeader
            eyebrow="COVERAGE"
            title="커버리지"
            meta="분석 대상 영역이 read로 얼마나 덮였는지"
          />

          {/*
            핵심 수치 둘. 카드로 감싸지 않는다 — 숫자 하나당 상자 하나를
            만드는 것이 CLAUDE.md 23장과 시안이 함께 피하는 패턴이다.
            위계는 배경이 아니라 크기(metric-md 20px mono)가 만든다.
          */}
          {/*
            핵심 수치는 **염기 단위**다. 이전에는 여기에 interval 단위 값
            (uncoveredBasesPct)이 "read가 없는 target"이라는 이름으로 올라와
            있었는데, 그 값은 "평균 depth가 0인 구간이 차지하는 비율"이지
            "0X인 염기의 비율"이 아니다. 둘은 다른 수이고, 구간 값이 항상 더
            작다. 지금은 zeroCoverageBasesPct(thresholds 1X 기준)를 쓴다.
          */}
          <div className="flex flex-wrap gap-x-12 gap-y-4">
            <Metric
              label="평균 타깃 깊이"
              value={numberOrDash(data.coverage.meanTargetDepth)}
              unit="×"
            />
            <Metric
              label="한 번도 덮이지 않은 target 염기"
              value={percentOrDash(data.coverage.zeroCoverageBasesPct, false)}
              unit="%"
              note={
                data.coverage.zeroCoverageBases !== null
                  ? `${data.coverage.zeroCoverageBases.toLocaleString()} bp`
                  : undefined
              }
            />
          </div>

          {/*
            깊이별 누적 비율. mosdepth가 실제로 측정한 값이며 설명용 그림이
            아니다. 막대는 값을 읽는 것을 돕는 보조 수단이고, 숫자를 항상
            함께 적는다(CLAUDE.md 25장: viridis는 값과 함께만 쓴다).
          */}
          {Object.keys(data.coverage.breadth).length > 0 ? (
            <dl className="flex flex-col">
              {Object.entries(data.coverage.breadth).map(([label, pct]) => (
                <div
                  key={label}
                  className="flex min-h-9 items-center gap-x-4 border-b border-border-subtle py-1.5 last:border-b-0"
                >
                  <dt className="w-16 flex-none font-mono text-data text-text">
                    ≥{label}
                  </dt>
                  <dd className="flex min-w-0 flex-1 items-center gap-3">
                    <span
                      aria-hidden="true"
                      className="h-2 min-w-0 flex-1 overflow-hidden rounded-sm bg-ink-100"
                    >
                      <span
                        className="block h-full rounded-sm bg-cov-30"
                        style={{ width: `${clampPercent(pct)}%` }}
                      />
                    </span>
                    <span className="w-20 flex-none text-right font-mono text-data text-text-strong">
                      {pct} <span className="text-caption text-text-muted">%</span>
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          <dl className="flex flex-col">
            <Row
              label="target 염기 수"
              value={numberOrDash(data.coverage.targetNonoverlapBases)}
              mono
            />
          </dl>

          {/*
            구간 단위 지표는 위의 염기 단위 요약과 **분리해서** 둔다.
            같은 목록에 섞으면 "20× 미만 비율 89.9%"가 염기 비율로 읽힌다.
            실제로는 "평균 depth가 20× 미만인 구간들이 target 길이에서
            차지하는 비율"이다. 라벨에 '구간'을 명시한다.
          */}
          <div className="flex flex-col gap-3 border-t border-border pt-4">
            <div className="flex flex-col gap-1">
              <h3 className="text-h3 font-semibold text-text-strong">
                구간 단위 보조 지표
              </h3>
              <p className="max-w-prose text-small text-text-muted">
                target을 나눈 구간마다 평균 depth를 하나씩 계산한 값입니다. 위의
                염기 단위 수치와 다른 측정이며, 부분적으로만 덮인 구간은 평균이
                0보다 크므로 &ldquo;완전히 0×인 구간&rdquo;에 포함되지 않습니다.
              </p>
            </div>
            <dl className="flex flex-col">
              <Row
                label={
                  data.coverage.lowMeanDepthThresholdX !== null
                    ? `평균 depth가 ${data.coverage.lowMeanDepthThresholdX}× 미만인 구간 수`
                    : '평균 depth가 기준 미만인 구간 수'
                }
                value={numberOrDash(data.coverage.lowMeanDepthIntervals)}
                mono
              />
              <Row
                label={
                  data.coverage.lowMeanDepthThresholdX !== null
                    ? `평균 depth가 ${data.coverage.lowMeanDepthThresholdX}× 미만인 구간이 차지하는 비율`
                    : '평균 depth가 기준 미만인 구간이 차지하는 비율'
                }
                value={percentOrDash(
                  data.coverage.basesInLowMeanDepthIntervalsPct,
                )}
                mono
              />
              <Row
                label="완전히 0×인 구간 수"
                value={numberOrDash(data.coverage.fullyUncoveredIntervals)}
                mono
              />
              <Row
                label="완전히 0×인 구간이 차지하는 비율"
                value={percentOrDash(
                  data.coverage.basesInFullyUncoveredIntervalsPct,
                )}
                mono
              />
            </dl>
          </div>

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

/**
 * 실제 측정값 하나.
 *
 * 상자를 두르지 않는다. 라벨(12px sans ink-500)과 값(20px mono ink-900)의
 * 크기 대비만으로 위계를 만든다 — 시안의 metric 표기가 그렇고, KPI 카드는
 * CLAUDE.md 23장이 금지한다.
 */
function Metric({
  label,
  value,
  unit,
  note,
}: {
  label: string
  value: string
  unit?: string
  note?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-caption text-text-muted">{label}</span>
      <span className="flex items-baseline gap-1">
        <span className="font-mono text-metric-md font-medium text-text-strong">
          {value}
        </span>
        {unit ? (
          <span className="text-caption text-text-muted">{unit}</span>
        ) : null}
      </span>
      {note ? (
        <span className="font-mono text-caption text-text-muted">{note}</span>
      ) : null}
    </div>
  )
}

/*
  점검 항목 표.

  PASS를 기본으로 접는다. 통과 건수는 문장으로 남기므로 "검사하지 않았다"와
  "통과했다"가 혼동되지 않는다. 펼치기는 <details>다 — JS 상태를 만들지 않고
  브라우저의 기본 동작과 키보드 조작을 그대로 쓴다.
*/
function CheckTable({ checks }: { checks: CheckRow[] }) {
  const notable = checks.filter((c) => c.status.toUpperCase() !== 'PASS')
  const passed = checks.length - notable.length

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        title="점검 항목"
        meta={
          notable.length > 0
            ? `${checks.length}건 중 ${notable.length}건이 통과가 아님`
            : `${checks.length}건 전부 통과`
        }
      />
      {notable.length > 0 ? <CheckRows rows={notable} /> : null}
      {passed > 0 ? (
        <details>
          <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
            통과한 {passed}건 보기
          </summary>
          <div className="mt-3">
            <CheckRows
              rows={checks.filter((c) => c.status.toUpperCase() === 'PASS')}
            />
          </div>
        </details>
      ) : null}
    </section>
  )
}

interface CheckRow {
  name: string
  status: string
  detail: string
}

function CheckRows({ rows }: { rows: CheckRow[] }) {
  return (
    <div className="overflow-hidden rounded-sm border border-border bg-surface">
      {rows.map((check) => (
        <div
          key={check.name}
          className="flex min-h-10 flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-subtle px-3 py-1.5 last:border-b-0"
        >
          <code
            className={`w-16 flex-none text-caption ${checkClass(check.status)}`}
          >
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
  )
}

/** "확인 필요 1건 · 참고 2건". 종류별 건수를 색 없이 문장으로 요약한다. */
function summarizeDiagnostics(diagnostics: RunDiagnostic[]): string {
  const order = ['실패', '확인 필요', '자동 복구', '참고']
  const counts = new Map<string, number>()
  for (const diagnostic of diagnostics) {
    counts.set(
      diagnostic.view.label,
      (counts.get(diagnostic.view.label) ?? 0) + 1,
    )
  }
  return order
    .filter((label) => counts.has(label))
    .map((label) => `${label} ${counts.get(label)}건`)
    .join(' · ')
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

function percentOrDash(value: number | null, withUnit = true): string {
  if (value === null) return '—'
  return withUnit ? `${value} %` : String(value)
}

/** 막대 폭. backend 값을 검증하지 않고 표시만 방어한다(features/runs/api.ts와 같은 정책). */
function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, value))
}
