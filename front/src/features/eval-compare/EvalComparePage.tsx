import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, FlaskConical } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { StatusTone } from '@/components/ui/StatusBadge'
import { TabsList, TabsPanel, TabsRoot, TabsTab } from '@/components/ui/Tabs'
import { cx } from '@/lib/cx'

import { unblind, writeToken } from './api'
import type { CallDetail, CallState, CallSummary, Evaluation, ExperimentDetail, Outcome, PlanItem } from './api'
import { AnswerView } from './components/AnswerView'
import {
  answerScoresOf,
  armMetrics,
  diffChunks,
  evaluateCriteria,
  EXCLUSION_LABEL,
  exclusionSummary,
  formatNumber,
  lineDiff,
  modelsByArm,
  prettyLines,
} from './compareMetrics'
import type { Arm, ArmMetrics, CriterionStatus, MetricValue } from './compareMetrics'
import { evalCompareKey, useCall, useExperiment, useExperiments, usePayloads } from './queries'

/*
  비교 분석(Compare) — 같은 Run을 두 코드 경로에 넣어 받은 실제 Claude 답변을
  나란히 본다. 평가자 전용 화면이다(backend WES_EVAL_COMPARE=1 + 같은 PC +
  평가 토큰에서만 열린다).

    A  Without Run Ledger + Applicability   변경 전 코드(158cba7) 스냅샷
    B  With Run Ledger + Applicability      변경 후 작업 트리 스냅샷

  이 화면은 모델을 부르지 않는다. 답변은 승인 후 runner CLI가 만든 것이다.
  호출 결과와 상태는 backend가 contract.py로 판정한 값을 그대로 보인다.
  provider 실패는 "Gate 거부"가 아니다 — Gate가 실행되지 않았다.
  블라인드 해제 전에는 답변 원문이 이 화면에 나오지 않는다(채점 화면에서만).
  측정하지 않은 값은 "미평가"로 둔다. 모의(mock) 실험은 모든 영역에 표시하고
  성공 기준을 판정하지 않는다.
*/

const ARM_LABEL: Record<Arm, string> = {
  A: 'Without Run Ledger + Applicability',
  B: 'With Run Ledger + Applicability',
}
const ARM_SHORT: Record<Arm, string> = { A: 'Without (A)', B: 'With (B)' }

const OUTCOME_VIEW: Record<Outcome, { label: string; tone: StatusTone }> = {
  served: { label: 'Gate 통과', tone: 'success' },
  gateRejected: { label: 'Gate 거부', tone: 'failure' },
  providerError: { label: '호출 실패 · Gate 판정 없음', tone: 'warning' },
  unclassified: { label: '분류 불가', tone: 'idle' },
}

const STATE_VIEW: Record<CallState, { label: string; tone: StatusTone }> = {
  planned: { label: '호출 전', tone: 'idle' },
  recorded: { label: '기록됨', tone: 'success' },
  recoverable: { label: '결과 있음 · 기록 대기', tone: 'running' },
  running: { label: '실행 중', tone: 'running' },
  uncertain: { label: '불확실 · 호출됐을 수 있음', tone: 'warning' },
  notInvoked: { label: '모델 호출 전 중단', tone: 'idle' },
  inFlightOrUncertain: { label: '실행 중이거나 불확실', tone: 'warning' },
  inFlightOrNotInvoked: { label: '시작 준비 중이거나 호출 전 중단', tone: 'idle' },
}

export function DisabledOrError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <MessageBlock tone="info" title="이 서버에서는 비교 분석이 꺼져 있습니다">
        평가자 전용 기능입니다. backend를 <code className="font-mono">WES_EVAL_COMPARE=1</code>로 시작했고 같은
        PC에서 접속한 경우에만 열립니다. 일반 서비스 화면과 기능에는 영향이 없습니다.
      </MessageBlock>
    )
  }
  if (error instanceof ApiError && error.status === 401) return <TokenForm />
  if (error instanceof ApiError && error.status === 503) {
    return (
      <MessageBlock tone="warning" title="평가 토큰이 서버에 설정돼 있지 않습니다">
        backend를 <code className="font-mono">WES_EVAL_COMPARE_TOKEN</code>과 함께 시작해야 비교 데이터를 열 수
        있습니다.
      </MessageBlock>
    )
  }
  return (
    <MessageBlock tone="danger" title="비교 데이터를 읽지 못했습니다">
      {error instanceof Error ? error.message : String(error)}
    </MessageBlock>
  )
}

function TokenForm() {
  const client = useQueryClient()
  const [value, setValue] = useState('')
  return (
    <MessageBlock tone="info" title="평가 토큰이 필요합니다">
      <form
        className="mt-2 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          writeToken(value.trim())
          void client.invalidateQueries({ queryKey: evalCompareKey })
        }}
      >
        <label className="flex flex-col gap-1 text-small">
          <span>backend를 시작할 때 정한 WES_EVAL_COMPARE_TOKEN (이 탭에만 저장)</span>
          <input
            type="password"
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="min-h-9 w-72 max-w-full rounded-sm border border-border-strong bg-surface px-2 font-mono text-small"
          />
        </label>
        <Button type="submit" variant="primary" disabled={!value.trim()}>
          확인
        </Button>
      </form>
    </MessageBlock>
  )
}

export function MockBanner() {
  return (
    <MessageBlock tone="warning" title="모의(mock) 데이터 — 실제 Claude 답변이 아닙니다" role="status">
      모델을 부르지 않고 저장·화면 경로만 검증하려고 만든 고정 답변입니다. 이 실험의 수치는 성능 결과로
      쓸 수 없고, 성공 기준도 판정하지 않습니다.
    </MessageBlock>
  )
}

/** 영역마다 붙이는 모의 표시. 한 영역만 잘라 봐도 모의인 것이 보이게. */
export function MockTag({ mock }: { mock: boolean }) {
  return mock ? (
    <StatusBadge tone="warning" size="sm">
      모의 데이터
    </StatusBadge>
  ) : null
}

export function EvalCompareListPage() {
  const { data, error, isPending } = useExperiments()
  return (
    <main className="mx-auto flex max-w-app flex-col gap-6 px-4 py-8 sm:px-6">
      <h1 className="text-h1 font-semibold tracking-tight text-text-strong">비교 분석</h1>
      <p className="max-w-content text-body text-text">
        같은 Run을 변경 전·후 두 코드 경로에 넣어 각각 새로 받은 Claude 답변과 평가를 나란히 봅니다.
      </p>
      {isPending ? <p className="text-small text-text-muted">불러오는 중</p> : null}
      {error ? <DisabledOrError error={error} /> : null}
      {data && data.experiments.length === 0 ? (
        <EmptyState
          icon={<FlaskConical size={32} strokeWidth={1.5} aria-hidden="true" />}
          title="저장된 비교 실험이 없습니다"
          titleLevel={2}
          description="backend에서 python -m evals.ab_compare prepare 로 실험을 만든 뒤 다시 확인하세요."
        />
      ) : null}
      {data && data.experiments.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {data.experiments.map((e) => (
            <li key={e.experimentId}>
              <Link
                to={`/eval/compare/${e.experimentId}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-surface px-4 py-3 no-underline hover:border-border-strong"
              >
                <span className="flex flex-col">
                  <span className="font-mono text-small text-text-strong">{e.experimentId}</span>
                  <span className="text-caption text-text-muted">{e.title}</span>
                </span>
                <span className="flex items-center gap-2">
                  <MockTag mock={e.mock} />
                  <span className="font-mono text-data text-text">
                    답변 {e.answered} · 기록 {e.recorded} / 계획 {e.planned}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  )
}

export function EvalComparePage() {
  const { experimentId = '' } = useParams()
  const { data, error, isPending } = useExperiment(experimentId)
  return (
    <main className="mx-auto flex max-w-app flex-col gap-8 px-4 py-8 sm:px-6">
      <nav className="text-caption text-text-muted">
        <Link to="/eval/compare">비교 분석</Link> / <span className="font-mono">{experimentId}</span>
      </nav>
      {isPending ? <p className="text-small text-text-muted">불러오는 중</p> : null}
      {error ? <DisabledOrError error={error} /> : null}
      {data ? <Workspace detail={data} /> : null}
    </main>
  )
}

function Workspace({ detail }: { detail: ExperimentDetail }) {
  const cases = detail.protocol.cases
  const [caseName, setCaseName] = useState(cases[0]?.case ?? '')
  const [repeat, setRepeat] = useState(1)
  const caseSpec = cases.find((c) => c.case === caseName) ?? cases[0]
  const recorded = detail.plan.filter((p) => p.state === 'recorded').length
  const answered = detail.calls.filter((c) => c.evaluation.countsForGate).length

  return (
    <>
      <header className="flex flex-col gap-3">
        <p className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
          Engineering evaluation · A/B
        </p>
        <h1 className="text-h1 font-semibold tracking-tight text-text-strong">{detail.protocol.title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-caption text-text-muted">
          <span className="font-mono">{detail.experimentId}</span>
          <span>·</span>
          <span>
            답변 <span className="font-mono text-text">{answered}</span> · 기록{' '}
            <span className="font-mono text-text">{recorded}</span> / 계획{' '}
            <span className="font-mono text-text">{detail.plan.length}</span>
          </span>
          <span>·</span>
          <span>
            프로토콜 v{detail.protocol.protocolVersion} 고정 {detail.protocol.fixedAt}
          </span>
          <span className="font-mono">sha256 {detail.protocolSha256.slice(0, 12)}</span>
        </div>
        {detail.mock ? <MockBanner /> : null}
        <BlindPanel detail={detail} />
      </header>

      <CallStatus detail={detail} />

      <section aria-labelledby="case-pick" className="flex flex-col gap-3">
        <h2 id="case-pick" className="text-h3 font-semibold text-text-strong">
          비교할 Run
        </h2>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Run 선택">
          {cases.map((c) => (
            <button
              key={c.case}
              type="button"
              aria-pressed={c.case === caseName}
              onClick={() => setCaseName(c.case)}
              className={cx(
                'inline-flex min-h-9 items-center gap-2 rounded-sm border px-3 text-small',
                c.case === caseName ? 'border-brand bg-brand-selected text-text-strong' : 'border-border bg-surface text-text',
              )}
            >
              <span className="font-mono">{c.label}</span>
              <span className="text-caption text-text-muted">{c.synthetic ? '합성' : '실제'}</span>
            </button>
          ))}
        </div>
        {caseSpec?.role ? <p className="text-small text-text-muted">{caseSpec.role}</p> : null}
      </section>

      <Conditions detail={detail} caseName={caseName} />
      <MetricTable detail={detail} caseName={caseName} />
      <Criteria detail={detail} />

      <section aria-labelledby="answers" className="flex flex-col gap-4">
        <SectionHeader
          title={
            <span id="answers" className="inline-flex flex-wrap items-center gap-2">
              답변 나란히 보기 <MockTag mock={detail.mock} />
            </span>
          }
          meta={`${caseSpec?.label ?? ''} · 반복 ${repeat}/${detail.protocol.repeats}`}
        />
        <div className="flex flex-wrap gap-2" role="group" aria-label="반복 선택">
          {Array.from({ length: detail.protocol.repeats }, (_, i) => i + 1).map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={r === repeat}
              onClick={() => setRepeat(r)}
              className={cx(
                'min-h-9 rounded-sm border px-3 text-small',
                r === repeat ? 'border-brand bg-brand-selected text-text-strong' : 'border-border bg-surface text-text',
              )}
            >
              반복 {r}
            </button>
          ))}
        </div>
        <SideBySide detail={detail} caseName={caseName} repeat={repeat} />
      </section>

      <PayloadDiff detail={detail} caseName={caseName} />
    </>
  )
}

// --- 블라인드 ------------------------------------------------------------------

function BlindPanel({ detail }: { detail: ExperimentDetail }) {
  const client = useQueryClient()
  const [by, setBy] = useState('')
  const [confirming, setConfirming] = useState(false)
  const mutation = useMutation({
    mutationFn: () => unblind(detail.experimentId, by.trim()),
    onSuccess: () => client.invalidateQueries({ queryKey: evalCompareKey }),
  })
  const { blind } = detail
  const gradeLink = (
    <Link
      to={`/eval/compare/${detail.experimentId}/grade`}
      className="inline-flex min-h-9 items-center gap-1.5 rounded-sm border border-border bg-surface px-3 text-small font-medium no-underline hover:border-border-strong"
    >
      <ClipboardCheck size={16} strokeWidth={1.5} aria-hidden="true" />
      블라인드 채점 열기
    </Link>
  )
  if (blind.unblinded) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        {gradeLink}
        <span className="text-caption text-text-muted">
          블라인드 해제됨 ({blind.unblindedAt}) · 채점 {blind.graded}/{blind.gradable}
          {blind.gradedAfterUnblind ? ` · 해제 뒤 채점 ${blind.gradedAfterUnblind}건(비블라인드로 표시)` : ''}
        </span>
      </div>
    )
  }
  return (
    <MessageBlock
      tone="info"
      title={`블라인드 채점 단계 · 채점 ${blind.graded}/${blind.gradable}`}
      action={
        <div className="flex flex-wrap items-end gap-2">
          {gradeLink}
          {confirming ? (
            <>
              <label className="flex flex-col gap-1 text-caption">
                <span>해제하는 사람</span>
                <input
                  value={by}
                  onChange={(e) => setBy(e.target.value)}
                  maxLength={40}
                  className="min-h-9 w-40 rounded-sm border border-border-strong bg-surface px-2 text-small"
                />
              </label>
              <Button variant="danger" disabled={!by.trim() || mutation.isPending} onClick={() => mutation.mutate()}>
                블라인드 해제 (되돌릴 수 없음)
              </Button>
              <Button onClick={() => setConfirming(false)}>취소</Button>
            </>
          ) : (
            <Button onClick={() => setConfirming(true)}>블라인드 해제…</Button>
          )}
        </div>
      }
    >
      채점을 마치기 전에는 어느 답이 어느 경로인지 이 화면에 나오지 않습니다(답변 원문, 채점 결과, 검출 문장을
      숨김). 해제는 한 번만 기록되며, 해제 뒤에 저장한 채점은 비블라인드로 표시됩니다.
      {mutation.error ? <span className="mt-1 block text-status-failure-fg">해제하지 못했습니다.</span> : null}
    </MessageBlock>
  )
}

// --- 호출 상태와 승인 범위 --------------------------------------------------------

function CallStatus({ detail }: { detail: ExperimentDetail }) {
  const attention = detail.plan.filter((p) => p.state !== 'recorded' && p.state !== 'planned')
  return (
    <section aria-labelledby="call-status" className="flex flex-col gap-3">
      <SectionHeader
        title={
          <span id="call-status" className="inline-flex flex-wrap items-center gap-2">
            호출 상태와 승인 범위 <MockTag mock={detail.mock} />
          </span>
        }
        meta="runner와 같은 상태 규칙(contract.py)"
      />
      {attention.length ? (
        <MessageBlock tone="warning" title={`확인이 필요한 호출 ${attention.length}개`}>
          <ul className="flex flex-col gap-1">
            {attention.map((p) => (
              <li key={p.callId}>
                <span className="font-mono">{p.callId}</span> — {STATE_VIEW[p.state].label}
              </li>
            ))}
          </ul>
          불확실한 호출은 자동으로 다시 부르지 않습니다. 다시 부르려면 승인 범위 안에서 runner의{' '}
          <code className="font-mono">--retry</code>를 씁니다.
        </MessageBlock>
      ) : null}
      {detail.approvals.length ? (
        <ul className="flex flex-col gap-1 text-small">
          {detail.approvals.map((a) => (
            <li key={a.approvalId} className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-caption">{a.approvalId}</span>
              <span className="text-text">
                {a.mode === 'mock' ? '모의' : '실제'} · 호출 {a.calls.length}개 · CLI 사용 최대 {a.usedAtMost}/
                {a.maxCliCalls ?? '—'}회
              </span>
              <span className="font-mono text-caption break-all text-text-muted">{a.calls.join(', ')}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-small text-text-muted">아직 승인된 호출이 없습니다.</p>
      )}
      <details className="rounded-md border border-border bg-surface p-3 text-small">
        <summary className="cursor-pointer font-medium text-text-strong">호출 {detail.plan.length}개의 상태</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-small">
            <thead className="text-left text-caption text-text-muted">
              <tr>
                <th className="px-2 py-1 font-medium">호출</th>
                <th className="px-2 py-1 font-medium">상태</th>
                <th className="px-2 py-1 font-medium">결과</th>
                <th className="px-2 py-1 font-medium">시도</th>
              </tr>
            </thead>
            <tbody>
              {detail.plan.map((p) => (
                <PlanRow key={p.callId} item={p} />
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}

function PlanRow({ item }: { item: PlanItem }) {
  return (
    <tr className="border-t border-border-subtle">
      <td className="px-2 py-1 font-mono text-caption">{item.callId}</td>
      <td className="px-2 py-1">
        <StatusBadge tone={STATE_VIEW[item.state].tone} size="sm">
          {STATE_VIEW[item.state].label}
        </StatusBadge>
      </td>
      <td className="px-2 py-1">
        {item.outcome ? (
          <StatusBadge tone={OUTCOME_VIEW[item.outcome].tone} size="sm">
            {OUTCOME_VIEW[item.outcome].label}
          </StatusBadge>
        ) : (
          <span className="text-text-muted">—</span>
        )}
      </td>
      <td className="px-2 py-1 text-caption text-text-muted">
        {item.attempts}
        {item.history.length > 1 ? ` (${item.history.map((h) => OUTCOME_VIEW[h.outcome].label).join(' → ')})` : ''}
      </td>
    </tr>
  )
}

// --- 조건 -------------------------------------------------------------------

const CONDITION_LABEL: Record<string, string> = {
  model: '모델 (설정값 · 별칭)',
  variant: '프롬프트 variant',
  offerTools: 'Tool(단계 상세 조회) 제공',
  docRag: '공식 문서 발췌(RAG)',
  agentDocEvidence: '문서 검색 결과를 Agent 입력에 포함',
  officialDocsInPayload: 'payload의 officialDocs',
  repair: 'Gate 거부 후 자동 수정',
  redactor: '식별자 가림(redactor)',
  gate: '검증 Gate',
  timeoutSeconds: '호출 제한 시간(초)',
}

const DIFF_CLASS_LABEL: Record<string, string> = {
  intended: '비교하려는 변경',
  inertInCallPath: '호출 경로에 있으나 바뀐 부분은 쓰이지 않음',
  notInCallPath: '호출 경로 밖 (호출마다 import 여부 확인)',
}

function show(value: unknown): string {
  if (value === true) return '켬'
  if (value === false) return '끔'
  return String(value)
}

function Conditions({ detail, caseName }: { detail: ExperimentDetail; caseName: string }) {
  const checks = detail.payloadChecks?.[caseName]
  const diff = detail.armDiff
  const classification = detail.diffClassification
  const models = modelsByArm(detail)
  const groups = new Map<string, string[]>()
  for (const [path, entry] of Object.entries(classification?.byPath ?? {})) {
    groups.set(entry.class, [...(groups.get(entry.class) ?? []), path])
  }
  return (
    <section aria-labelledby="conditions" className="flex flex-col gap-4">
      <SectionHeader
        title={
          <span id="conditions" className="inline-flex flex-wrap items-center gap-2">
            실험 조건 <MockTag mock={detail.mock} />
          </span>
        }
        meta="두 경로 공통 · 사전 고정"
      />
      {models.differ ? (
        <MessageBlock tone="warning" title="두 경로가 받은 실제 모델 ID가 다릅니다">
          설정은 같은 별칭이지만 기록된 모델이 다릅니다. A: <span className="font-mono">{models.A.join(', ')}</span> · B:{' '}
          <span className="font-mono">{models.B.join(', ')}</span>. 같은 모델의 비교로 보지 마세요.
        </MessageBlock>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <dl className="grid grid-cols-[minmax(9rem,auto)_1fr] gap-x-4 gap-y-1.5 rounded-md border border-border bg-surface p-4 text-small">
          {Object.entries(detail.protocol.conditions).map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-text-muted">{CONDITION_LABEL[key] ?? key}</dt>
              <dd className="text-text">{show(value)}</dd>
            </div>
          ))}
          <dt className="text-text-muted">실제 모델 ID</dt>
          <dd className="font-mono text-caption break-all text-text">
            A {models.A.join(', ') || '기록 없음'} · B {models.B.join(', ') || '기록 없음'}
          </dd>
          <dt className="text-text-muted">반복 · 순서</dt>
          <dd className="text-text">
            조건마다 {detail.protocol.repeats}회 · {detail.protocol.order === 'interleaved' ? '교차(A·B 순서를 반복마다 바꿈)' : detail.protocol.order}
          </dd>
          <dt className="text-text-muted">주장 단위</dt>
          <dd className="text-text">{detail.protocol.claimUnit}</dd>
        </dl>
        <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4 text-small">
          {(['A', 'B'] as const).map((arm) => {
            const info = detail.arms[arm]
            return (
              <div key={arm} className="flex flex-col gap-0.5">
                <p className="font-semibold text-text-strong">{ARM_LABEL[arm]}</p>
                <p className="text-text-muted">
                  {info.source.kind === 'git' ? (
                    <>
                      git <span className="font-mono">{info.source.commit?.slice(0, 7)}</span> 스냅샷 (blob 검증)
                    </>
                  ) : (
                    <>
                      작업 트리 스냅샷 · 기준 HEAD <span className="font-mono">{info.headAtSnapshot?.slice(0, 7)}</span>
                    </>
                  )}
                  {info.fileCount ? <> · 파일 {info.fileCount}개</> : null}
                </p>
              </div>
            )
          })}
          <ul className="flex flex-col gap-1 border-t border-border-subtle pt-3">
            <Check
              ok={classification ? classification.unclassified.length === 0 : undefined}
              label={
                classification
                  ? `두 경로의 차이 ${Object.keys(classification.byPath).length + classification.unclassified.length}개가 모두 프로토콜에 분류됨`
                  : '차이 분류 없음 (이전 형식 실험)'
              }
            />
            <Check ok={diff.harnessIdentical} label="평가 harness 코드 동일" />
            <Check ok={checks?.constraintsEqual} label="모델 지시문(constraints) 동일" />
            <Check ok={checks?.promptHashEqual} label="프롬프트 해시 동일" />
            <Check ok={checks ? !checks.payloadEqual : undefined} label="이 Run의 모델 입력(payload)은 다름 — 의도한 차이" />
            <Check
              ok={checks ? Object.values(checks.privacy).every((v) => v === 'pass') && Object.values(checks.leaks).every((n) => n === 0) : undefined}
              label="모델 입력 식별자·경로 검사 통과"
            />
          </ul>
          <p className="text-caption text-text-muted">
            호출마다 직전에 스냅샷·지시문·Knowledge·payload를 다시 확인하고, 호출 뒤에 실제로 쓴 payload·프롬프트 해시와
            import한 파일을 확인합니다. 실패한 호출은 지표에서 빠집니다.
          </p>
        </div>
      </div>
      <details className="rounded-md border border-border bg-surface p-4 text-small">
        <summary className="cursor-pointer font-medium text-text-strong">
          두 경로의 의도된 차이 · 바뀐 파일 {diff.changed.length + diff.added.length + diff.removed.length}개
        </summary>
        <ul className="mt-3 list-disc pl-5 text-text">
          {detail.protocol.intendedDifference.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {classification ? (
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {['intended', 'inertInCallPath', 'notInCallPath'].map((cls) => (
              <FileList key={cls} title={DIFF_CLASS_LABEL[cls]} files={groups.get(cls) ?? []} />
            ))}
            {classification.unclassified.length ? <FileList title="분류 안 됨 — 실행 거부 대상" files={classification.unclassified} /> : null}
          </div>
        ) : (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <FileList title="바뀐 파일" files={diff.changed} />
            <FileList title="B에만 있는 파일" files={diff.added} />
          </div>
        )}
        {detail.sharedLocalInputs.length ? (
          <p className="mt-3 text-caption text-text-muted">
            git에 없는 채점 입력(정답 파일)은 두 경로에 같은 바이트로 복사했습니다: {detail.sharedLocalInputs.length}개.
            Agent 입력에는 들어가지 않습니다.
          </p>
        ) : null}
      </details>
    </section>
  )
}

function Check({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <li className="flex items-start gap-2">
      <span
        className={cx(
          'mt-0.5 inline-flex h-4 min-w-10 items-center justify-center rounded-sm px-1 text-caption',
          ok === undefined ? 'bg-status-idle-bg text-status-idle-fg' : ok ? 'bg-status-success-bg text-status-success-fg' : 'bg-status-failure-bg text-status-failure-fg',
        )}
      >
        {ok === undefined ? '미확인' : ok ? '예' : '아니오'}
      </span>
      <span className="text-text">{label}</span>
    </li>
  )
}

function FileList({ title, files }: { title: string; files: string[] }) {
  return (
    <div>
      <p className="font-medium text-text-strong">
        {title} <span className="font-mono text-caption text-text-muted">{files.length}</span>
      </p>
      <ul className="mt-1 flex flex-col gap-0.5 font-mono text-caption break-all text-text">
        {files.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
    </div>
  )
}

// --- 지표 표 ----------------------------------------------------------------

function fmt(v: MetricValue): string {
  if (v.status === 'unmeasured' || v.value === null) return '미평가'
  let main: string
  if (v.unit === '비율' && v.numerator !== null && v.denominator !== null) {
    main = `${v.numerator} / ${v.denominator} (${Math.round(v.value * 100)}%)`
  } else if (v.denominator !== null && v.numerator !== null) {
    main = `${v.numerator} / ${v.denominator}${v.unit === '회' ? '' : ` ${v.unit}`}`
  } else {
    main = `${formatNumber(v.value)} ${v.unit}`
  }
  return v.status === 'partial' ? `${main} · ${v.basis}/${v.expected}만` : main
}

interface Row {
  label: string
  method: string
  pick: (m: ArmMetrics) => MetricValue
}

const ROWS: Row[] = [
  { label: '실행되지 않은 단계의 결과 주장', method: '자동 검출 (고정 문형)', pick: (m) => m.auto.nonRunClaims },
  { label: '실행되지 않은 단계의 결과 주장', method: '사람 채점', pick: (m) => m.human.nonRunClaims },
  { label: '실행 사실과 모순된 주장', method: '자동 검출 (고정 문형)', pick: (m) => m.auto.execContradictions },
  { label: '실행 사실과 모순된 주장', method: '사람 채점', pick: (m) => m.human.execContradictions },
  { label: '근거가 주장을 뒷받침 / 평가한 주장', method: '사람 채점', pick: (m) => m.human.supportedClaims },
  { label: '필수 실패 원인 언급 / 필수 원인', method: '자동 문형 (참고)', pick: (m) => m.auto.requiredCauses },
  { label: '필수 실패 원인 언급 / 필수 원인', method: '사람 채점', pick: (m) => m.human.requiredCauses },
  { label: '근거 없는 원인 단정', method: '자동 후보 (확인 전)', pick: (m) => m.auto.wrongCauses },
  { label: '근거 없는 원인 단정', method: '사람 채점', pick: (m) => m.human.wrongCauses },
  { label: '검증 Gate 거부 / 답변을 받은 호출', method: '정확 집계', pick: (m) => m.exact.gateRejected },
  { label: '응답 시간 (답변을 받은 호출)', method: 'provider 기록', pick: (m) => m.exact.latency },
  { label: 'provider 실패 / 기록된 호출 (평가 아님)', method: '실행 상태', pick: (m) => m.exact.providerErrors },
  { label: '이해도 (1–5)', method: '사람 채점', pick: (m) => m.human.understanding },
  { label: '점검 방법 유용성 (1–5)', method: '사람 채점', pick: (m) => m.human.usefulness },
]

function MetricCell({ v }: { v: MetricValue }) {
  return (
    <td className={cx('px-3 py-2 align-top font-mono text-data', v.status === 'unmeasured' ? 'text-text-muted' : 'text-text')}>
      {fmt(v)}
      {v.note && v.status !== 'measured' ? <span className="block font-sans text-caption text-text-muted">{v.note}</span> : null}
    </td>
  )
}

function MetricTable({ detail, caseName }: { detail: ExperimentDetail; caseName: string }) {
  const [scope, setScope] = useState<'case' | 'all'>('case')
  const target = scope === 'case' ? caseName : null
  const a = armMetrics(detail, 'A', target)
  const b = armMetrics(detail, 'B', target)
  return (
    <section aria-labelledby="metrics" className="flex flex-col gap-3">
      <SectionHeader
        title={
          <span id="metrics" className="inline-flex flex-wrap items-center gap-2">
            결과 비교 <MockTag mock={detail.mock} />
          </span>
        }
        meta={`답변 A ${a.answered}/${a.planned} · B ${b.answered}/${b.planned}`}
        action={
          <div className="flex gap-1" role="group" aria-label="집계 범위">
            {(['case', 'all'] as const).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={scope === s}
                onClick={() => setScope(s)}
                className={cx(
                  'min-h-8 rounded-sm border px-2 text-caption',
                  scope === s ? 'border-brand bg-brand-selected text-text-strong' : 'border-border bg-surface text-text',
                )}
              >
                {s === 'case' ? '선택한 Run' : '모든 Run'}
              </button>
            ))}
          </div>
        }
      />
      <div className="overflow-x-auto rounded-md border border-border bg-surface">
        <table className="w-full min-w-[40rem] text-small">
          <thead className="bg-sunken text-left text-caption text-text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">지표</th>
              <th className="px-3 py-2 font-medium">방법</th>
              <th className="px-3 py-2 font-medium">
                {ARM_SHORT.A}
                {detail.mock ? ' · 모의' : ''}
              </th>
              <th className="px-3 py-2 font-medium">
                {ARM_SHORT.B}
                {detail.mock ? ' · 모의' : ''}
              </th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={`${row.label}-${row.method}`} className="border-t border-border-subtle">
                <td className="px-3 py-2 align-top text-text">{row.label}</td>
                <td className="px-3 py-2 align-top text-caption text-text-muted">{row.method}</td>
                <MetricCell v={row.pick(a)} />
                <MetricCell v={row.pick(b)} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-caption text-text-muted">
        평가에서 빠진 호출 — A: {exclusionSummary(a.excluded) || '없음'} · B: {exclusionSummary(b.excluded) || '없음'}. provider
        실패는 Gate가 실행되지 않은 것이라 Gate 거부의 분자·분모와 응답 시간에서 뺍니다. 내용 지표의 단위는 모델이 낸
        답변입니다(Gate가 거부한 답변 포함). 판단 불가 주장은 분모에만 들어갑니다
        {a.undeterminedClaims !== null || b.undeterminedClaims !== null
          ? ` (판단 불가 A ${a.undeterminedClaims ?? '—'} · B ${b.undeterminedClaims ?? '—'})`
          : ''}
        . 자동 값은 미리 정한 문형만 셉니다 — 0은 "그 문형이 없다"는 뜻입니다. 반복 {detail.protocol.repeats}회의 기술
        통계이며 통계적 유의성을 뜻하지 않습니다.
      </p>
    </section>
  )
}

const CRITERION_VIEW: Record<CriterionStatus, { label: string; tone: StatusTone }> = {
  met: { label: '충족', tone: 'success' },
  notMet: { label: '미충족', tone: 'failure' },
  unmeasured: { label: '미평가', tone: 'idle' },
  mock: { label: '모의 — 판정 안 함', tone: 'warning' },
}

function Criteria({ detail }: { detail: ExperimentDetail }) {
  const results = evaluateCriteria(detail)
  return (
    <section aria-labelledby="criteria" className="flex flex-col gap-3">
      <SectionHeader
        title={
          <span id="criteria" className="inline-flex flex-wrap items-center gap-2">
            사전 고정 성공 기준 <MockTag mock={detail.mock} />
          </span>
        }
        meta="모든 Run 합산 · 실행 전 고정"
      />
      {detail.protocol.evaluationRule ? <p className="text-caption text-text-muted">{detail.protocol.evaluationRule}</p> : null}
      <ul className="flex flex-col gap-2">
        {results.map((r) => (
          <li key={r.criterion.id} className="flex flex-wrap items-start gap-3 rounded-sm border border-border-subtle bg-surface px-3 py-2">
            <StatusBadge tone={CRITERION_VIEW[r.status].tone} size="sm">
              {CRITERION_VIEW[r.status].label}
            </StatusBadge>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="text-small text-text">
                <span className="font-mono text-caption text-text-muted">{r.criterion.id}</span> {r.criterion.label}
              </span>
              <span className="text-caption text-text-muted">
                {r.criterion.source === 'human' ? '사람 채점' : '자동'} · {r.reason}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// --- 답변 나란히 ---------------------------------------------------------------

function SideBySide({ detail, caseName, repeat }: { detail: ExperimentDetail; caseName: string; repeat: number }) {
  const items = {
    A: detail.plan.find((p) => p.case === caseName && p.repeat === repeat && p.arm === 'A'),
    B: detail.plan.find((p) => p.case === caseName && p.repeat === repeat && p.arm === 'B'),
  }
  const summaries = new Map(detail.calls.map((c) => [c.callId, c]))
  const column = (arm: Arm) => {
    const item = items[arm]
    const summary = item ? summaries.get(item.callId) : undefined
    return <ArmColumn detail={detail} arm={arm} item={item} summary={summary} />
  }
  return (
    <>
      <div className="hidden gap-4 lg:grid lg:grid-cols-2">
        {(['A', 'B'] as const).map((arm) => (
          <div key={arm} className="min-w-0">
            {column(arm)}
          </div>
        ))}
      </div>
      <div className="lg:hidden">
        <TabsRoot defaultValue="A">
          <TabsList>
            <TabsTab value="A">{ARM_SHORT.A}</TabsTab>
            <TabsTab value="B">{ARM_SHORT.B}</TabsTab>
          </TabsList>
          {(['A', 'B'] as const).map((arm) => (
            <TabsPanel key={arm} value={arm}>
              <div className="pt-4">{column(arm)}</div>
            </TabsPanel>
          ))}
        </TabsRoot>
      </div>
    </>
  )
}

function EvaluationNote({ evaluation }: { evaluation: Evaluation }) {
  if (evaluation.outcome === 'providerError') {
    return (
      <MessageBlock tone="warning" title={`호출 실패 (${evaluation.category ?? '분류 없음'}) — Gate 판정이 아닙니다`}>
        provider가 답변을 내지 못해 검증 Gate가 실행되지 않았습니다. Gate 거부 수와 응답 시간에서 빠지며, 성공 기준은
        이 호출이 답변을 받을 때까지 판정하지 않습니다.
      </MessageBlock>
    )
  }
  if (evaluation.outcome === 'unclassified') {
    return (
      <MessageBlock tone="warning" title="기록을 분류할 수 없습니다">
        어느 결과와도 맞지 않는 기록이라 어떤 지표에도 세지 않습니다. 사람이 원본 기록을 확인해야 합니다.
      </MessageBlock>
    )
  }
  if (evaluation.exclusion) {
    return (
      <MessageBlock tone="warning" title={`평가에서 제외: ${EXCLUSION_LABEL[evaluation.exclusion]}`}>
        이 호출은 지표에 세지 않습니다.
      </MessageBlock>
    )
  }
  return null
}

function ArmColumn({
  detail,
  arm,
  item,
  summary,
}: {
  detail: ExperimentDetail
  arm: Arm
  item: PlanItem | undefined
  summary: CallSummary | undefined
}) {
  const { data, error, isPending } = useCall(detail.experimentId, summary ? summary.callId : null)
  const evaluation = summary?.evaluation
  return (
    <article aria-label={ARM_LABEL[arm]} className="flex min-w-0 flex-col gap-3 rounded-md border border-border bg-paper p-4">
      <header className="flex flex-col gap-2">
        <p className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">{ARM_SHORT[arm]}</p>
        <h3 className="text-h3 font-semibold text-text-strong">{ARM_LABEL[arm]}</h3>
        {summary && evaluation ? (
          <div className="flex flex-wrap items-center gap-2 text-caption text-text-muted">
            <StatusBadge tone={OUTCOME_VIEW[evaluation.outcome].tone} size="sm">
              {OUTCOME_VIEW[evaluation.outcome].label}
            </StatusBadge>
            {evaluation.countsForGate ? (
              <span>
                응답 <span className="font-mono text-text">{summary.durationMs ?? '—'} ms</span>
              </span>
            ) : null}
            <span>
              전체 <span className="font-mono text-text">{summary.wallMs ?? '—'} ms</span>
            </span>
            {summary.attempts > 1 ? <span>시도 {summary.attempt}번째</span> : null}
            {summary.mock ? (
              <StatusBadge tone="warning" size="sm">
                모의
              </StatusBadge>
            ) : null}
          </div>
        ) : null}
      </header>
      {!summary ? (
        <p className="rounded-sm border border-dashed border-border p-4 text-small text-text-muted">
          {item && item.state !== 'planned' ? `${STATE_VIEW[item.state].label} — 결과 기록 없음, 미평가.` : '아직 호출하지 않았습니다 — 미평가.'}
        </p>
      ) : null}
      {evaluation ? <EvaluationNote evaluation={evaluation} /> : null}
      {summary && isPending ? <p className="text-small text-text-muted">불러오는 중</p> : null}
      {error ? <DisabledOrError error={error} /> : null}
      {data ? <CallBody data={data} /> : null}
    </article>
  )
}

function CallBody({ data }: { data: CallDetail }) {
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-caption">
        <dt className="text-text-muted">모델</dt>
        <dd className="font-mono break-all text-text">{data.models?.join(', ') || '기록 없음'}</dd>
        <dt className="text-text-muted">Tool 사용</dt>
        <dd className="text-text">
          {data.toolUse.toolUsed ? `${data.toolUse.callCount ?? 0}회 · ${data.toolUse.openedStepIds.join(', ')}` : '사용 안 함'}
        </dd>
        <dt className="text-text-muted">payload</dt>
        <dd className="font-mono text-text">{data.payloadDigest?.slice(0, 12) ?? '—'}</dd>
        <dt className="text-text-muted">지식 해시</dt>
        <dd className="font-mono text-text">{data.knowledgeHash ?? '—'}</dd>
        <dt className="text-text-muted">사후 무결성</dt>
        <dd className="text-text">
          {data.integrity
            ? data.integrity.ok
              ? '통과 (payload·프롬프트·지식 해시, import 목록)'
              : `실패: ${Object.entries(data.integrity.checks)
                  .filter(([, ok]) => !ok)
                  .map(([k]) => k)
                  .join(', ')}${data.integrity.notInCallPathImported.length ? ` · ${data.integrity.notInCallPathImported.join(', ')}` : ''}`
            : '확인 기록 없음 (이전 형식)'}
        </dd>
      </dl>
      {data.withheldForPrivacy ? (
        <MessageBlock tone="warning" title="식별자 검사에서 걸려 본문을 표시하지 않습니다">
          저장 기록에 Run 식별자·경로가 들어 있을 수 있어 평가자 화면에서도 숨깁니다.
        </MessageBlock>
      ) : null}
      {data.withheldForBlind ? (
        <MessageBlock tone="info" title="블라인드 채점 중 — 답변 원문은 채점 화면에서만 봅니다">
          어느 경로의 답인지 알면 채점이 기울 수 있어, 블라인드를 해제하기 전에는 이 화면에 원문·Gate 거부 사유·검사
          상세를 보이지 않습니다.
        </MessageBlock>
      ) : null}
      {data.output ? <AnswerView answer={data.output} scores={answerScoresOf(data)} /> : null}
      {data.rejected ? (
        <div className="flex flex-col gap-3">
          <MessageBlock tone="danger" title={`Gate 거부 (${data.rejected.category ?? '분류 없음'}) — 평가자 전용 원문`}>
            이 답변은 검증 Gate에서 거부되어 일반 사용자 화면에는 표시되지 않았습니다. 거부 이유와 원문을 평가를
            위해서만 보여 줍니다.
            <ul className="mt-2 list-disc pl-5 font-mono text-caption break-all">
              {data.rejected.findings.map((f, i) => (
                <li key={i}>{typeof f === 'string' ? f : JSON.stringify(f)}</li>
              ))}
            </ul>
          </MessageBlock>
          {data.rejected.answer ? <AnswerView answer={data.rejected.answer} scores={answerScoresOf(data)} /> : null}
        </div>
      ) : null}
    </>
  )
}

// --- payload 차이 --------------------------------------------------------------

function PayloadDiff({ detail, caseName }: { detail: ExperimentDetail; caseName: string }) {
  const [open, setOpen] = useState(false)
  const { data, error, isPending } = usePayloads(detail.experimentId, caseName, open && detail.payloadChecks !== null)
  return (
    <section aria-labelledby="payload-diff" className="flex flex-col gap-3">
      <details
        className="rounded-md border border-border bg-surface p-4"
        onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary id="payload-diff" className="cursor-pointer text-small font-medium text-text-strong">
          모델 입력(payload) 차이 보기 — 같은 Run, 두 코드 경로
        </summary>
        {detail.payloadChecks === null ? (
          <p className="mt-3 text-small text-text-muted">payload를 아직 만들지 않았습니다 (runner의 payloads 단계).</p>
        ) : null}
        {open && isPending && detail.payloadChecks !== null ? <p className="mt-3 text-small text-text-muted">불러오는 중</p> : null}
        {error ? <DisabledOrError error={error} /> : null}
        {data ? <DiffBody a={data.arms.A} b={data.arms.B} /> : null}
      </details>
    </section>
  )
}

function DiffBody({
  a,
  b,
}: {
  a: { payload: unknown; withheldForPrivacy: boolean; knowledgeHash?: string | null; payloadDigest?: string | null }
  b: { payload: unknown; withheldForPrivacy: boolean; knowledgeHash?: string | null; payloadDigest?: string | null }
}) {
  if (a.withheldForPrivacy || b.withheldForPrivacy) {
    return <p className="mt-3 text-small text-text-muted">식별자 검사에서 걸린 payload는 표시하지 않습니다.</p>
  }
  const diff = lineDiff(prettyLines(a.payload), prettyLines(b.payload))
  const added = diff.filter((l) => l.kind === 'add').length
  const removed = diff.filter((l) => l.kind === 'del').length
  return (
    <div className="mt-3 flex flex-col gap-2">
      <p className="text-caption text-text-muted">
        <span className="font-mono">−{removed}</span> 줄은 A에만, <span className="font-mono">+{added}</span> 줄은 B에만 있습니다 ·
        A <span className="font-mono">{a.payloadDigest?.slice(0, 12)}</span> · B{' '}
        <span className="font-mono">{b.payloadDigest?.slice(0, 12)}</span>
      </p>
      <pre className="max-h-[32rem] overflow-auto rounded-sm bg-sunken p-3 font-mono text-caption leading-relaxed">
        {diffChunks(diff).map((chunk, i) =>
          chunk.kind === 'skip' ? (
            <div key={i} className="text-text-muted">
              ⋯ 같은 줄 {chunk.count}개
            </div>
          ) : (
            chunk.lines.map((line, j) => (
              <div
                key={`${i}-${j}`}
                className={cx(
                  'whitespace-pre-wrap break-all',
                  line.kind === 'add' && 'bg-status-success-bg text-status-success-fg',
                  line.kind === 'del' && 'bg-status-failure-bg text-status-failure-fg',
                )}
              >
                {line.kind === 'add' ? '+ ' : line.kind === 'del' ? '− ' : '  '}
                {line.text}
              </div>
            ))
          ),
        )}
      </pre>
    </div>
  )
}
