import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Activity, ArrowRight, BookOpenCheck, ListChecks, Plus, Quote, ShieldCheck, Workflow } from 'lucide-react'
import { Link } from 'react-router'

import { StatusBadge } from '@/components/ui/StatusBadge'
import { pipelineMap } from '@/features/entry/entryModel'
import type { PipelineNode } from '@/features/entry/entryModel'
import { runsDigest } from '@/features/entry/entryModel'
import { useHealthQuery } from '@/features/health/useHealthQuery'
import { describeJobStatus } from '@/features/runs/status'
import { formatTimestamp } from '@/features/runs/time'
import { useRunListQuery } from '@/features/runs/useRunListQuery'
import { cx } from '@/lib/cx'
import { allStepKnowledge } from '@/registries/knowledge'

/*
  진입 화면 (`/`) — 다크 + 네온 (2026-11-23 사용자 결정).

  ── 작업 화면과의 관계 ──────────────────────────────────────────────────

  실행 목록·상세는 밝은 작업 화면이다(긴 표와 로그를 오래 읽는 곳). 이 화면만
  어둡다. 둘을 잇는 것은 같은 사이드바 그래파이트, 같은 네온 강조색(선택·주
  행동), 같은 상태 아이콘 6종(StatusBadge surface="night")이다.

  ── 보여 주는 것은 모두 실제 값 ─────────────────────────────────────────

    서버          GET /api/health
    최근 실행      GET /api/jobs (최신 5건, backend 순서)
    파이프라인     config/knowledge/wes_steps.json + registries/stepPlan.ts

  KPI 카드·예시 결과·장식 이미지를 두지 않는다(CLAUDE.md 23·35장). 실행이 없으면
  없다고 말한다.

  ── 네온 ────────────────────────────────────────────────────────────────

  채도 높은 색 + 1px 선만 쓴다. glow·gradient·움직이는 장식은 없다.
  포커스 링은 어두운 면에서 보이도록 neon-blue로 바꾼다(SC 2.4.7 · 1.4.11).
*/

export function EntryPage() {
  return (
    <div className="min-h-dvh bg-night-950 text-night-text [--focus-ring-color:var(--color-neon-blue)] selection:bg-neon-blue/30 selection:text-night-strong">
      <EntryHeader />
      <main>
        <Hero />
        <PipelineSection />
        <RecordsSection />
      </main>
      <EntryFooter />
    </div>
  )
}

/* --- header ------------------------------------------------------------------------- */

function EntryHeader() {
  return (
    <header className="border-b border-night-line">
      <div className="mx-auto flex max-w-app flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 md:px-6">
        <Link
          to="/"
          className="flex items-center gap-2.5 text-night-strong no-underline hover:text-night-strong hover:no-underline"
        >
          <Workflow size={22} strokeWidth={1.75} aria-hidden="true" className="text-neon-cyan" />
          <span className="text-h3 font-semibold">WES Analysis Workspace</span>
        </Link>
        <nav aria-label="서비스 이동">
          <ul className="flex flex-wrap items-center gap-1">
            <HeaderLink to="/runs" icon={ListChecks}>
              실행 목록
            </HeaderLink>
            <HeaderLink to="/help/setup" icon={BookOpenCheck}>
              준비 안내
            </HeaderLink>
            <HeaderLink to="/health" icon={Activity}>
              서버 상태
            </HeaderLink>
          </ul>
        </nav>
      </div>
    </header>
  )
}

function HeaderLink({ to, icon: Icon, children }: { to: string; icon: LucideIcon; children: ReactNode }) {
  return (
    <li>
      <Link
        to={to}
        className="inline-flex min-h-9 items-center gap-2 rounded-sm px-3 text-body text-night-text no-underline hover:bg-night-850 hover:text-night-strong hover:no-underline"
      >
        <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
        {children}
      </Link>
    </li>
  )
}

/* --- hero --------------------------------------------------------------------------- */

function Hero() {
  return (
    <section aria-labelledby="entry-title" className="border-b border-night-line">
      <div className="mx-auto grid max-w-app gap-10 px-4 py-12 md:px-6 md:py-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:items-start lg:gap-12">
        <div className="flex min-w-0 flex-col gap-6">
          <p className="font-mono text-caption tracking-wide text-neon-cyan uppercase">
            Research use only · Illumina WES germline
          </p>
          <h1
            id="entry-title"
            className="max-w-[20em] text-display font-semibold tracking-tight text-night-strong md:text-hero"
          >
            FASTQ 한 쌍에서 변이 검출까지,
            <br />
            각 단계가 남긴 기록으로 확인합니다
          </h1>
          <p className="max-w-prose text-h3 font-normal text-night-text">
            WES 파이프라인(<code className="text-night-strong">script/main.sh</code>)을 웹에서
            실행하고, 단계별 상태·로그·산출물과 실패 원인을 파이프라인이 기록한 그대로
            보여 줍니다. AI 설명은 요청할 때만 만들고, 각 문장이 근거로 삼은 기록을 함께
            표시합니다.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              to="/new"
              className="inline-flex h-10 items-center gap-2 rounded-sm bg-neon-blue px-5 text-body font-semibold text-night-950 no-underline hover:bg-night-strong hover:text-night-950 hover:no-underline"
            >
              <Plus size={16} strokeWidth={2} aria-hidden="true" />새 분석 시작
            </Link>
            <Link
              to="/runs"
              className="inline-flex h-10 items-center gap-2 rounded-sm border border-night-line-strong px-5 text-body font-medium text-night-strong no-underline hover:border-neon-blue hover:text-night-strong hover:no-underline"
            >
              실행 목록
              <ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" />
            </Link>
          </div>
          <p className="text-caption text-night-muted">
            입력은 샘플 1개의 paired FASTQ(R1·R2, <code>.fastq.gz</code>·<code>.fq.gz</code>)입니다.
          </p>
        </div>

        <ServerPanel />
      </div>
    </section>
  )
}

/* --- live panel: 이 서버의 실제 상태 ------------------------------------------------- */

function ServerPanel() {
  return (
    <aside
      aria-label="이 서버의 현재 상태"
      className="flex min-w-0 flex-col rounded-md border border-night-line bg-night-900"
    >
      <ServerLine />
      <RecentRuns />
    </aside>
  )
}

const RUN_MODE_LABEL: Record<string, string> = { check_only: '사전 점검', full: '전체 분석' }

function ServerLine() {
  const health = useHealthQuery()
  const view = health.isPending
    ? { dot: 'bg-night-muted', label: '서버 확인 중', detail: null as string | null }
    : health.isError
      ? { dot: 'bg-night-status-failure', label: '서버 응답 없음', detail: 'backend가 실행 중인지 확인하세요.' }
      : health.data?.status === 'ok'
        ? {
            dot: 'bg-neon-cyan',
            label: '서버 연결됨',
            detail: `기본 실행 모드 ${RUN_MODE_LABEL[health.data.runMode] ?? health.data.runMode}${
              health.data.release ? ` · ${health.data.release}` : ''
            }`,
          }
        : { dot: 'bg-night-status-warning', label: `서버 상태: ${health.data?.status ?? '알 수 없음'}`, detail: null }
  return (
    <div className="flex items-start gap-3 border-b border-night-line px-4 py-3">
      <span aria-hidden="true" className={cx('mt-1.5 size-2 flex-none rounded-pill', view.dot)} />
      <div className="flex min-w-0 flex-col">
        <span className="text-body font-medium text-night-strong" role="status">
          {view.label}
        </span>
        {view.detail ? <span className="truncate text-caption text-night-muted">{view.detail}</span> : null}
      </div>
      <Link
        to="/health"
        className="ml-auto inline-flex min-h-6 flex-none items-center text-caption text-neon-blue hover:text-night-strong"
      >
        자세히
      </Link>
    </div>
  )
}

function RecentRuns() {
  const runs = useRunListQuery()
  const digest = runs.data ? runsDigest(runs.data.jobs, 5) : null

  return (
    <div className="flex flex-col">
      <div className="flex items-baseline justify-between gap-3 px-4 pt-3 pb-2">
        {/* 한글 라벨: 영문 eyebrow 자간(0.09em)은 낱자를 흩어 놓는다 → tracking-wide-kr */}
        <h2 className="text-caption font-semibold tracking-wide-kr text-night-muted">최근 실행</h2>
        {digest ? (
          <span className="text-caption text-night-muted">
            전체 <span className="font-mono text-night-strong">{digest.total}</span>건
            {digest.active > 0 ? (
              <>
                {' · '}진행 중 <span className="font-mono text-neon-cyan">{digest.active}</span>건
              </>
            ) : null}
          </span>
        ) : null}
      </div>

      {runs.isPending ? (
        <p role="status" className="px-4 pb-4 text-small text-night-muted">
          실행 기록을 불러오는 중입니다.
        </p>
      ) : runs.isError ? (
        <p className="px-4 pb-4 text-small text-night-muted">
          실행 기록을 불러오지 못했습니다. 기록이 없다는 뜻은 아닙니다.
        </p>
      ) : digest && digest.total === 0 ? (
        <p className="px-4 pb-4 text-small text-night-muted">
          아직 실행이 없습니다. 첫 분석을 제출하면 여기에 나타납니다.
        </p>
      ) : digest ? (
        <>
          <ul className="flex flex-col">
            {digest.recent.map((job) => {
              const status = describeJobStatus(job.status)
              const created = formatTimestamp(job.createdAt)
              return (
                <li key={job.jobId} className="border-t border-night-line first:border-t-0">
                  <Link
                    to={`/runs/${encodeURIComponent(job.jobId)}`}
                    className="flex items-center gap-3 px-4 py-2.5 text-night-text no-underline hover:bg-night-850 hover:text-night-strong hover:no-underline focus-visible:[outline-offset:-2px]"
                  >
                    <StatusBadge tone={status.tone} size="sm" surface="night">
                      {status.label}
                    </StatusBadge>
                    <span className="min-w-0 flex-1 truncate font-mono text-data text-night-strong">
                      {job.sampleId ?? job.runId}
                    </span>
                    {created ? (
                      <time dateTime={created.machine} title={created.full} className="flex-none text-caption text-night-muted">
                        {created.display}
                      </time>
                    ) : null}
                  </Link>
                </li>
              )
            })}
          </ul>
          <Link
            to="/runs"
            className="flex min-h-10 items-center justify-between gap-2 border-t border-night-line px-4 text-small font-medium text-neon-blue no-underline hover:bg-night-850 hover:text-night-strong hover:no-underline"
          >
            실행 목록 전체
            <ArrowRight size={14} strokeWidth={1.75} aria-hidden="true" />
          </Link>
        </>
      ) : null}
    </div>
  )
}

/* --- pipeline map ------------------------------------------------------------------- */

function PipelineSection() {
  const nodes = pipelineMap(allStepKnowledge())
  return (
    <section aria-labelledby="entry-pipeline" className="border-b border-night-line">
      <div className="mx-auto flex max-w-app flex-col gap-6 px-4 py-12 md:px-6">
        <div className="flex flex-col gap-2">
          <p className="font-mono text-caption tracking-wide text-neon-cyan uppercase">Pipeline · script/main.sh</p>
          <h2 id="entry-pipeline" className="text-h1 font-semibold tracking-tight text-night-strong">
            실행 계획의 단계
          </h2>
          <p className="max-w-prose text-body text-night-muted">
            각 단계는 상태와 로그를 남기고, 실행 상세의 파이프라인 탭에서 단계별로 열어 볼 수
            있습니다. 채워진 칸은 전체 분석(full)의 계획이고, 빈 칸은 그 계획에 기본으로
            들어가지 않는 단계입니다. 사전 점검(check_only)은 00 입력 검증만 실행합니다.
          </p>
        </div>
        <ol className="grid grid-cols-1 gap-x-0 gap-y-6 md:grid-cols-2 lg:grid-cols-4">
          {nodes.map((node, index) => (
            <PipelineStep key={node.stepId} node={node} last={index === nodes.length - 1} />
          ))}
        </ol>
        <Legend />
      </div>
    </section>
  )
}

function PipelineStep({ node, last }: { node: PipelineNode; last: boolean }) {
  const core = node.plan === 'core'
  return (
    <li className="flex min-w-0 flex-col gap-2 pr-4">
      {/* 신호선: 점(단계) + 1px 선. 마지막 단계는 선이 없다 */}
      <div aria-hidden="true" className="flex items-center gap-2">
        <span
          className={cx(
            'size-2.5 flex-none rounded-[2px]',
            core ? 'bg-neon-cyan' : node.plan === 'conditional' ? 'border border-neon-cyan' : 'border border-night-muted',
          )}
        />
        {last ? null : (
          <span className={cx('h-px flex-1', core ? 'bg-neon-cyan/50' : 'border-t border-dashed border-night-line-strong')} />
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-baseline gap-2">
          <span className={cx('font-mono text-data', core ? 'text-neon-cyan' : 'text-night-muted')}>{node.ordinal}</span>
          <span className={cx('text-body font-medium', core ? 'text-night-strong' : 'text-night-text')}>{node.label}</span>
        </span>
        {node.tools ? <span className="font-mono text-caption text-night-muted">{node.tools}</span> : null}
        {node.note ? <span className="text-caption text-night-muted">{node.note}</span> : null}
      </div>
    </li>
  )
}

/*
  범례. 2026-11-23 리뷰 반영:
  - "기본 실행"은 backend 기본 모드(check_only, 00만 실행)와 어긋났다 → "전체 분석에서 실행".
  - 예전 <dl>은 <dt>가 aria-hidden인 빈 칸이라 화면 낭독기에 용어 없는 설명만 남았다.
    표식은 장식이므로 목록(<ul>) + 글자로 바꿨다.
*/
function Legend() {
  return (
    <ul aria-label="단계 표식" className="flex flex-wrap gap-x-6 gap-y-2 text-caption text-night-muted">
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 rounded-[2px] bg-neon-cyan" />
        전체 분석에서 실행
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 rounded-[2px] border border-neon-cyan" />
        조건부 실행
      </li>
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2.5 rounded-[2px] border border-night-muted" />
        웹 제출에서는 실행하지 않음
      </li>
    </ul>
  )
}

/* --- what is recorded --------------------------------------------------------------- */

const RECORDS: readonly { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: Activity,
    title: '단계 상태와 로그',
    body: '단계마다 시작·종료·상태를 파이프라인의 상태 파일에서 읽고, 실행 중에는 3초마다 다시 확인합니다. 진행률은 끝난 단계의 비율이며 남은 시간을 추정하지 않습니다.',
  },
  {
    icon: ShieldCheck,
    title: '실패 원인과 준비 안내',
    body: '실패는 등록된 코드로 분류해 무엇이 멈췄는지 보여 주고, 도구·참조 데이터를 준비하는 앱 안의 안내로 연결합니다. 기록에 없는 원인은 만들지 않습니다.',
  },
  {
    icon: Quote,
    title: '근거를 밝히는 AI 설명',
    body: 'Claude 설명은 버튼을 눌렀을 때만 요청합니다. 각 문장 옆에 근거로 삼은 실행 기록이나 공식 문서를 표시해, 무엇을 보고 쓴 문장인지 확인할 수 있습니다.',
  },
]

function RecordsSection() {
  return (
    <section aria-labelledby="entry-records">
      <div className="mx-auto flex max-w-app flex-col gap-6 px-4 py-12 md:px-6">
        <h2 id="entry-records" className="text-h1 font-semibold tracking-tight text-night-strong">
          기록으로 확인하는 것
        </h2>
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {RECORDS.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex flex-col gap-3 rounded-md border border-night-line bg-night-900 p-5">
              <Icon size={20} strokeWidth={1.5} aria-hidden="true" className="text-neon-cyan" />
              <h3 className="text-h3 font-semibold text-night-strong">{title}</h3>
              <p className="text-small text-night-text">{body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function EntryFooter() {
  return (
    <footer className="border-t border-night-line">
      <div className="mx-auto flex max-w-app flex-col gap-1 px-4 py-6 text-caption text-night-muted md:px-6">
        <p>
          Research Use Only — 임상 진단에 쓰지 않습니다. ACMG 자동 분류가 표시되더라도 최종 판단을
          대신하지 않습니다.
        </p>
        <p>전체 분석의 산출물은 서버의 참조 데이터·도구 준비 상태에 따라 달라집니다.</p>
      </div>
    </footer>
  )
}
