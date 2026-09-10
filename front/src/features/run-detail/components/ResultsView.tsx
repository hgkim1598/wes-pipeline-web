import { EmptyState } from '@/components/ui/EmptyState'
import { FileText } from 'lucide-react'

import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import type { NotReady, Results } from '@/features/run-detail/api'
import { isNotReady } from '@/features/run-detail/api'
import { CoverageSection } from '@/features/run-detail/components/CoverageSection'
import { VariantSection } from '@/features/run-detail/components/VariantSection'

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

  ── 이 탭의 역할은 좁다 `[설계판단]` ────────────────────────────────────

  **실제 분석 결과와 측정값을 이해하는 곳**이다. 여기 있던 두 section을 뺐다.

    "확인할 사항"   AttentionSection과 같은 `warnings`·`failures` 배열을 각각
                    렌더링하고 있었다. 사건의 본문은 탭 바깥 한 곳에만 둔다
    "실행 요약"     상태·샘플·소요시간·pipeline 상태가 헤더와 겹쳤다.
                    식별 정보는 아래 "입력 요약" 하나로 모은다

  진단을 여기서 다시 나열하지 않는다. 커버리지 숫자를 보다가 그 숫자에 대한
  경고를 다시 만나면, 사용자는 그것이 새 사건인지 이미 읽은 것인지 알 수 없다.
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

  return (
    <div className="flex flex-col gap-8">
      {/*
        "확인할 사항"과 "실행 요약"이 여기 있었다.

        전자는 AttentionSection과 같은 `data.warnings`/`data.failures`를 각각
        렌더링해서, 경고 하나가 화면에 두 번(파이프라인 탭까지 세면 그 이상)
        나타났다. 사건의 본문은 탭 바깥 AttentionSection 하나로 옮겼다.

        후자는 상태·샘플·소요시간·pipeline 상태를 헤더와 중복해서 보여줬다.
        식별 정보는 아래 "입력 요약"으로 모았다.
      */}

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
        <CoverageSection coverage={data.coverage} />
      ) : null}

      {data.variantCalling ? (
        <VariantSection variantCalling={data.variantCalling} />
      ) : null}

      {data.inputSummary ? (
        <section className="flex flex-col gap-4">
          <SectionHeader title="입력 요약" />
          {/*
            먼저 볼 것과 재현성 정보를 나눈다.

            이전에는 여덟 행이 한꺼번에 펼쳐져 있었고, 그 안에 sha256 두 개와
            contig style·bundle id가 섞여 있었다. 사용자가 "무엇을 분석했나"를
            확인하려고 열었는데 해시가 절반을 차지하면 핵심이 묻힌다.

            **지우지 않는다.** 재현성은 이 프로젝트의 목적 중 하나이고,
            해시·bundle id는 같은 입력이었는지 확인하는 유일한 수단이다.
            접어서 내릴 뿐이다.

            label도 사람 말로 바꾼다. 원래 technical key는 아래 상세에서
            그대로 확인할 수 있다.
          */}
          <dl className="flex flex-col">
            <Row label="샘플" value={data.inputSummary.sample ?? '—'} mono />
            <Row
              label="참조 유전체"
              value={data.inputSummary.assembly ?? '—'}
              mono
            />
            <Row
              label="캡처 키트"
              value={data.inputSummary.captureKitId ?? '—'}
              mono
            />
            <Row
              label="Lane 수"
              value={numberOrDash(data.inputSummary.laneCount)}
              mono
            />
          </dl>

          <details>
            <summary className="inline-flex min-h-6 cursor-pointer items-center text-small font-medium text-text-muted">
              세부 설정과 재현성 정보
            </summary>
            <dl className="mt-2 flex flex-col">
              <Row
                label="contig style"
                value={data.inputSummary.contigStyle ?? '—'}
                mono
              />
              <Row
                label="resource bundle id"
                value={data.inputSummary.bundleId ?? '—'}
                mono
              />
              <Row
                label="capture kit id"
                value={data.inputSummary.captureKitId ?? '—'}
                mono
              />
              <Row
                label="assembly"
                value={data.inputSummary.assembly ?? '—'}
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
          </details>
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

function checkClass(status: string): string {
  const upper = status.toUpperCase()
  if (upper === 'PASS') return 'text-status-success-fg'
  if (upper === 'WARN') return 'text-status-warning-fg'
  return 'text-status-failure-fg'
}

function numberOrDash(value: number | null): string {
  return value === null ? '—' : value.toLocaleString()
}
