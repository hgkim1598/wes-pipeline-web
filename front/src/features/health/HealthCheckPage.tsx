import { RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { StatusTone } from '@/components/ui/StatusBadge'
import type { HealthResponse } from '@/features/health/api'
import { HEALTH_PATH } from '@/features/health/api'
import { useHealthQuery } from '@/features/health/useHealthQuery'

/*
  GET /api/health 확인 화면.

  제품 화면이 아니라 "frontend가 실제 backend를 읽을 수 있는가"를 확인하는
  첫 vertical slice다. 새 시각 언어를 만들지 않고 기존 primitive만 쓴다.

  레이아웃 근거 — 시안에 이미 있는 두 패턴을 그대로 가져왔다.

    점검 항목 표   docs/design/results-precheck.html "점검 항목"
                   1px 테두리 컨테이너 · sunken 머리글 · 행 min-height 40 ·
                   padding 4/12 · 상태(88) / 항목(200) / 상세(가변) 3열
    서버 설정 KV   docs/design/results-precheck.html "입력 요약"
                   행 min-height 36 · 라벨 180 small ink-500 · 값 mono

  판단 규칙: 응답의 각 필드는 서로 다른 의미를 가지므로 하나의 성공/실패로
  뭉치지 않는다. 특히 referenceConfigured=false는 backend 장애도 pipeline
  장애도 아니라 아직 준비하지 않은 리소스다.
*/

/** 실행을 막는 조건. reference 미설정은 여기 들어가지 않는다. */
function hasBlockingProblem(health: HealthResponse): boolean {
  return (
    health.status !== 'ok' ||
    !health.pipelineScriptPresent ||
    !health.captureKitRegistryPresent
  )
}

/**
 * backend가 쓰는 실행 모드 값의 뜻.
 *
 * 모르는 값이면 설명을 붙이지 않고 값만 그대로 보여준다. 없는 의미를
 * 지어내는 것보다 값만 보여주는 편이 정확하다.
 */
const RUN_MODE_NOTE: Record<string, string> = {
  check_only:
    '입력·환경·reference를 확인하는 precheck만 실행합니다. 분석 산출물은 생성되지 않습니다.',
  full: '전체 WES pipeline을 실행합니다.',
}

interface CheckRow {
  /** backend 응답의 원래 키. 표의 "항목" 열에 mono로 그대로 노출한다. */
  termKey: string
  tone: StatusTone
  /** 배지에 보이는 짧은 상태 텍스트. 색만으로 상태를 전달하지 않는다. */
  state: string
  detail: ReactNode
}

/*
  점검 항목 4행.

  시안의 check variant는 PASS / WARN / FAIL mono 표기를 쓰지만, 그 어휘는
  main.sh가 validation.results에 기록하는 값이다(backend CheckResult.status).
  /api/health는 그 어휘를 반환하지 않고 boolean만 준다. 여기서 PASS/FAIL을
  쓰면 backend에 없는 어휘를 지어내는 것이라, 상태는 배지로 표현한다.
*/
function buildRows(health: HealthResponse): CheckRow[] {
  return [
    {
      termKey: 'status',
      tone: health.status === 'ok' ? 'success' : 'failure',
      state: health.status === 'ok' ? '정상' : health.status,
      detail: 'Backend가 응답했습니다.',
    },
    {
      termKey: 'pipelineScriptPresent',
      tone: health.pipelineScriptPresent ? 'success' : 'failure',
      state: health.pipelineScriptPresent ? '존재함' : '없음',
      detail: 'Pipeline script(main.sh)가 서버에 있습니다.',
    },
    {
      termKey: 'captureKitRegistryPresent',
      tone: health.captureKitRegistryPresent ? 'success' : 'failure',
      state: health.captureKitRegistryPresent ? '존재함' : '없음',
      detail: 'Capture kit registry 파일이 서버에 있습니다.',
    },
    {
      /*
        false는 warning이다. failure가 아니다.
        backend는 WES_REFERENCE_FASTA와 WES_CONTIG_STYLE이 모두 비어 있지
        않을 때만 true를 준다(backend/app/config.py, main.py의 health()).
        값이 없다는 것은 운영자가 아직 리소스를 준비하지 않았다는 뜻이지
        무언가 고장났다는 뜻이 아니다.
      */
      termKey: 'referenceConfigured',
      tone: health.referenceConfigured ? 'success' : 'warning',
      state: health.referenceConfigured ? '설정됨' : '미설정',
      detail: health.referenceConfigured
        ? 'Reference genome 경로가 설정되어 있습니다.'
        : 'Reference genome이 아직 설정되지 않았습니다. backend 오류가 아니라 준비하지 않은 리소스입니다.',
    },
  ]
}

interface ErrorView {
  summary: string
  hint: string
  detail: string | null
}

function describeError(error: unknown): ErrorView {
  if (error instanceof ApiError) {
    if (error.kind === 'network') {
      return {
        summary: '요청이 backend에 도달하지 못했습니다.',
        hint: `VM에서 FastAPI가 실행 중인지, ${HEALTH_PATH}로 이어지는 포트 포워딩이 열려 있는지 확인하세요.`,
        detail: error.detail,
      }
    }
    if (error.kind === 'http') {
      return {
        summary: `backend가 HTTP ${error.status}로 응답했습니다.`,
        hint: 'backend는 살아 있지만 이 요청을 처리하지 못했습니다. 서버 로그를 확인하세요.',
        detail: error.detail,
      }
    }
    return {
      summary: '응답을 읽었지만 예상한 형식이 아닙니다.',
      hint: 'frontend가 아는 계약과 backend 응답이 어긋났습니다. 아래 상세와 backend/app/main.py의 health()를 대조하세요.',
      detail: error.detail,
    }
  }
  return {
    summary: '알 수 없는 오류가 발생했습니다.',
    hint: '브라우저 개발자 도구의 Network / Console 탭을 확인하세요.',
    detail: error instanceof Error ? error.message : String(error),
  }
}

export function HealthCheckPage() {
  const { data, error, isPending, isFetching, refetch } = useHealthQuery()

  return (
    <main className="mx-auto flex max-w-content flex-col gap-8 px-6 py-12">
      <div className="flex flex-col gap-1">
        <p className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
          System · Health check
        </p>
        <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
          백엔드 연결 확인
        </h1>
        <p className="mt-2 text-body text-text">
          frontend가 <code>{HEALTH_PATH}</code>를 실제로 읽을 수 있는지
          확인합니다. 분석을 실행하거나 결과를 보여주지 않습니다.
        </p>
      </div>

      {isPending ? (
        <MessageBlock tone="info" role="status" title="확인하는 중입니다">
          <code>{HEALTH_PATH}</code> 응답을 기다리고 있습니다.
        </MessageBlock>
      ) : null}

      {error ? (
        <HealthError error={error} onRetry={() => void refetch()} />
      ) : null}

      {data ? (
        <HealthReport
          health={data}
          isRefreshing={isFetching}
          onRefresh={() => void refetch()}
        />
      ) : null}
    </main>
  )
}

function HealthError({
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
      // 요청 실패는 화면에 새로 나타나는 사건이라 즉시 알려야 한다.
      role="alert"
      title="백엔드에 연결하지 못했습니다"
      action={
        <Button variant="primary" onClick={onRetry}>
          <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
          다시 확인
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

function HealthReport({
  health,
  isRefreshing,
  onRefresh,
}: {
  health: HealthResponse
  isRefreshing: boolean
  onRefresh: () => void
}) {
  const rows = buildRows(health)

  return (
    <div className="flex flex-col gap-8">
      <HealthSummary health={health} />

      <section className="flex flex-col gap-4">
        <SectionHeader
          title="점검 항목"
          meta={
            <>
              <span className="font-mono text-data">{rows.length}</span>건
            </>
          }
          action={
            <Button
              variant="secondary"
              onClick={onRefresh}
              disabled={isRefreshing}
            >
              <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
              {isRefreshing ? '확인 중' : '다시 확인'}
            </Button>
          }
        />
        <CheckTable rows={rows} />
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader title="서버 설정" />
        <ServerConfig health={health} />
      </section>
    </div>
  )
}

function HealthSummary({ health }: { health: HealthResponse }) {
  if (hasBlockingProblem(health)) {
    return (
      <MessageBlock tone="danger" title="backend 구성에 문제가 있습니다">
        응답은 받았지만 pipeline 실행에 필요한 항목이 충족되지 않았습니다. 아래
        점검 항목에서 실패한 줄을 확인하세요.
      </MessageBlock>
    )
  }

  if (health.referenceConfigured) {
    return (
      <MessageBlock tone="success" title="백엔드와 정상적으로 연결되었습니다">
        점검 항목이 모두 충족되었습니다.
      </MessageBlock>
    )
  }

  return (
    <MessageBlock tone="warning" title="연결됨 · 분석 리소스는 아직 준비 전">
      backend와 pipeline script는 정상입니다. Reference genome이 아직 설정되지
      않아 실제 WES 분석은 실행할 수 없습니다. 이것은 backend 장애가 아니라
      준비하지 않은 리소스입니다.
    </MessageBlock>
  )
}

/*
  시안의 점검 항목 표와 같은 골격이다.
  좁은 화면에서는 3열을 유지할 수 없어 상세가 아래 줄로 내려간다
  (토큰이 md/lg/xl만 정의하므로 sm 변형은 존재하지 않는다).
*/
function CheckTable({ rows }: { rows: CheckRow[] }) {
  return (
    <div className="overflow-hidden rounded-sm border border-border bg-surface">
      <div className="flex min-h-10 items-center gap-x-3 border-b border-border bg-sunken px-3">
        <span className="flex-none text-caption font-semibold tracking-wide-kr text-text-muted md:min-w-22">
          상태
        </span>
        <span className="hidden flex-none text-caption font-semibold tracking-wide-kr text-text-muted md:block md:w-50">
          항목
        </span>
        <span className="min-w-0 flex-1 text-caption font-semibold tracking-wide-kr text-text-muted">
          상세
        </span>
      </div>

      <dl className="flex flex-col">
        {rows.map((row) => (
          <div
            key={row.termKey}
            className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border-subtle px-3 py-1 last:border-b-0"
          >
            <dt className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              {/*
                열 너비는 시안의 --col-check-state(88px) 기준이지만, 그 값은
                mono [PASS] 텍스트용이라 알약 배지에는 빠듯하다. 고정폭 대신
                최소폭으로 두어 배지가 잘리지 않게 한다.
              */}
              <span className="flex-none md:min-w-22">
                <StatusBadge tone={row.tone} size="sm">
                  {row.state}
                </StatusBadge>
              </span>
              <code className="min-w-0 break-all text-data text-text-strong md:w-50">
                {row.termKey}
              </code>
            </dt>
            <dd className="min-w-0 flex-1 basis-full text-body text-text md:basis-0">
              {row.detail}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/*
  시안의 입력 요약과 같은 골격이다.
  pipelineScript의 Linux 절대경로는 사용자 판단에 거의 쓰이지 않는
  기술 상세라, 값 색을 ink-900이 아닌 본문 색으로 한 단계 낮추고
  break-all로 감싼다 — 공백이 없어서 그냥 두면 페이지가 가로로 밀린다.
*/
function ServerConfig({ health }: { health: HealthResponse }) {
  const runModeNote = RUN_MODE_NOTE[health.runMode]

  return (
    <dl className="flex flex-col">
      <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 py-1">
        <dt className="flex-none text-small text-text-muted md:w-45">
          실행 모드 <code className="text-caption">runMode</code>
        </dt>
        <dd className="flex min-w-0 flex-1 basis-full flex-col gap-0.5 md:basis-0">
          {/* 점검 결과가 아니라 설정값이다. 통과/실패 배지를 붙이지 않는다. */}
          <code className="text-text-strong">{health.runMode}</code>
          {runModeNote ? (
            <span className="text-caption text-text-muted">{runModeNote}</span>
          ) : null}
        </dd>
      </div>

      <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 py-1">
        <dt className="flex-none text-small text-text-muted md:w-45">
          Pipeline script <code className="text-caption">pipelineScript</code>
        </dt>
        <dd className="min-w-0 flex-1 basis-full md:basis-0">
          <code className="break-all text-text">{health.pipelineScript}</code>
        </dd>
      </div>
    </dl>
  )
}
