import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  FileInput,
  FileText,
  Info,
  Layers,
  MessageSquare,
  Quote,
  Search,
  Terminal,
  TriangleAlert,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SourceMark } from '@/components/ui/SourceMark'
import {
  DOC_DETAIL_PANEL_ID,
  revealElement,
  revealStatement,
} from '@/features/run-detail/aiStatement'
import { createDocSearch } from '@/features/run-detail/api'
import type {
  AgentRequest,
  DocCorpus,
  DocSearchHit,
  DocSearchInput,
  DocSearchRun,
} from '@/features/run-detail/api'
import {
  filterHits,
  hitFilterCounts,
  splitInputs,
  usageStages,
} from '@/features/run-detail/docHitView'
import type { HitFilter } from '@/features/run-detail/docHitView'
import { docSearchKey } from '@/features/run-detail/docSearchQuery'
import { newLinkedAgentSearch, seenFrom } from '@/features/run-detail/docTraceSelection'
import type { SeenSearches } from '@/features/run-detail/docTraceSelection'
import {
  hitKey,
  orderedHits,
  resolveHit,
  runForEvidence,
  stageCounts,
} from '@/features/run-detail/docWorkspace'
import type { PlacedStatement } from '@/features/run-detail/synthesisPlacement'
import { formatTimestamp } from '@/features/runs/time'
import { cx } from '@/lib/cx'
import { causeKindKnowledge } from '@/registries/knowledge'

/*
  실패와 관련된 공식 문서 — 공식 문서 탭 (개발판단기록 26 · 39 · 40장).

  ── 무엇을 보여주나 ─────────────────────────────────────────────────────

  backend가 이 Run의 기록된 실패(원인 종류·도구·실행된 명령)로 로컬 공식 문서
  자료를 검색하고 저장한 결과다. **모델이 만든 것도, 모델이 고른 것도 아니다.**
  화면이 연결을 추론하지 않는다. "같은 명령의 설명 구간" 같은 관계는 매뉴얼
  목차상의 위치일 뿐 원인이라는 뜻이 아니다. 점수·신뢰도는 저장하지 않으므로
  보여주지도 않는다.

  ── 쓰지 않는 말 ────────────────────────────────────────────────────────

  "AI가 참고한", "근거로 사용된" 같은 표현을 쓰지 않는다. 사실은 단계마다
  따로 기록된다(27장): 검색 결과에 나타남 → Agent 입력 후보(구조 규칙) →
  요청 입력에 포함(서버가 실제로 만든 요청) → 답변 인용(검사를 모두 통과한
  답변에서만 확인). 모델이 읽었는지는 어디에도 기록되지 않는다. null을
  "아니오"로 바꾸어 적지 않는다(docHitView.ts · docWorkspace.ts).

  ── 워크스페이스 배치 `[설계판단]` (40장) ──────────────────────────────

    1. 머리 카드 · 표시 중인 검색 기록
    2. 증거 흐름   실패 → 명령 → 검색어 → 반환 → 후보 → 요청 입력 → 응답 →
                   인용. 이전의 요청 이력과 단계 막대를 하나로 합쳤다(2026-11-20
                   승인 시안). 거르기는 문서 리스트 위의 버튼이다.
    3. 왼쪽 문서 리스트  검색 이유(기록된 실패 · 명령)별로 묶는다.
       오른쪽 상세 패널  고른 문서의 검색 이유 · 관련 실패 기록 · 기록 단계 ·
                         근거 발췌 · 원문 링크 · 이 문서를 근거로 든 AI 문장.
    4. 문서가 반환되지 않은 입력 · 검색하지 않은 항목 · 검색한 자료와 방법

  고른 검색 기록·문서·거르기는 URL이다(?search= ?doc= ?input= ?view=). AI
  설명의 근거에서 오면 `?doc=`만 있고 거르기가 없으므로 그 문서가 늘 보인다.
  고른 기록에 그 문서가 없으면 그 문서를 가진 가장 최근 기록을 고른다. 어디에도
  없으면 그렇다고 말한다.

  ── 호출 정책 ───────────────────────────────────────────────────────────

  GET은 사용량을 쓰지 않으므로 query로 읽는다(polling 없음, docSearchQuery.ts).
  POST는 Trace를 하나 더 쌓으므로 버튼을 눌렀을 때만 부른다.
*/

const RELATION_LABEL: Record<string, string> = {
  filedUnderCauseKind: '이 원인 종류에 등록된 해설',
  sameCommandSection: '실행된 명령과 같은 매뉴얼 구간',
  otherCommandSection: '다른 명령의 매뉴얼 구간',
  generalSection: '매뉴얼의 일반 구간',
  suggestedByWording: '분류되지 않은 문장의 표현으로 추정한 종류의 해설',
}

const MATCHED_BY_LABEL: Record<string, string> = {
  causeKindKey: '원인 종류로 조회',
  optionLookup: '명령 옵션으로 조회',
  sectionIntro: '실행된 명령 구간의 첫 설명',
  fts5: '전문 검색',
  wordingLexicon: '표현 사전으로 종류 추정',
}

const CORPUS_LABEL: Record<string, string> = {
  curated: '정리된 해설',
  manual: '공식 매뉴얼',
}

const STATEMENT_GROUP_LABEL: Record<string, string> = {
  importantFindings: '주요 내용',
  limitations: '이 결과가 말하지 않는 것',
  nextChecks: '다음으로 확인할 수 있는 것',
  uncertainties: '알 수 없는 것',
}

const FILTERS: readonly HitFilter[] = ['all', 'inAgentInput', 'cited']

const FILTER_LABEL: Record<HitFilter, string> = {
  all: '전체',
  inAgentInput: '요청 입력 포함',
  cited: '답변 인용',
}

export interface DocEvidenceSectionProps {
  jobId: string
  /** 검색 기록(GET). 페이지가 한 번 읽어 파이프라인 패널과 나눠 쓴다. */
  history: UseQueryResult<DocSearchRun[]>
  /** 지금 화면에 있는 AI 종합 설명의 번호 붙은 문장. 없으면 빈 배열. */
  statements: readonly PlacedStatement[]
  /** 기록된 실패의 단계를 파이프라인 탭에서 연다. */
  onGoToStep: (stepId: string) => void
}

export function DocEvidenceSection({
  jobId,
  history,
  statements,
  onGoToStep,
}: DocEvidenceSectionProps) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const [params, setParams] = useSearchParams()

  /** URL 값 몇 개를 바꾼다. null이면 지운다. 선택은 기록에 쌓지 않는다. */
  const update = (changes: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(changes)) {
          if (value === null) next.delete(key)
          else next.set(key, value)
        }
        return next
      },
      { replace: true },
    )

  const runs = history.data ?? []
  const searchParam = params.get('search')
  const docParam = params.get('doc')
  const viewRaw = params.get('view')
  const view: HitFilter = FILTERS.includes(viewRaw as HitFilter) ? (viewRaw as HitFilter) : 'all'

  /*
    어느 검색 기록을 보여 줄까. 문서가 지정되어 있으면 그 문서를 가진 기록,
    아니면 고른 기록, 아니면 가장 최근 기록.
  */
  const runWithDoc = docParam ? runForEvidence(runs, searchParam, docParam) : null
  const current =
    runs.find((run) => run.searchId === (runWithDoc ?? searchParam)) ?? runs[0]
  const docMissing = Boolean(docParam) && runs.length > 0 && runWithDoc === null

  // 방금 끝난 AI 설명 요청의 연결된 검색이 새로 생기면 그 기록으로 이동한다.
  // 그 외의 갱신은 선택을 바꾸지 않는다(규칙: docTraceSelection.ts, 29장).
  const seen = useRef<SeenSearches | null>(null)
  useEffect(() => {
    const data = history.data
    if (!data) return
    const next = newLinkedAgentSearch(seen.current, jobId, data)
    seen.current = seenFrom(jobId, data)
    if (next !== null) {
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev)
          out.set('search', next)
          for (const key of ['doc', 'input', 'view']) out.delete(key)
          return out
        },
        { replace: true },
      )
    }
  }, [history.data, jobId, setParams])

  /*
    AI 근거에서 이동해 왔으면(state.revealDoc) 상세 패널을 화면에 올린다.
    기록이 아직 오지 않았으면 온 뒤에 한 번 더 시도한다.
  */
  const reveal = (location.state as { revealDoc?: boolean } | null)?.revealDoc === true
  const hasCurrent = Boolean(current)
  useEffect(() => {
    if (!reveal || !hasCurrent) return
    revealElement(document.getElementById(DOC_DETAIL_PANEL_ID), 'start')
  }, [reveal, hasCurrent, location.key])

  const search = useMutation({
    mutationFn: () => createDocSearch(jobId),
    retry: false,
    onSuccess: (created) => {
      queryClient.setQueryData<DocSearchRun[]>(docSearchKey(jobId), (prev) =>
        [created, ...(prev ?? []).filter((run) => run.searchId !== created.searchId)].slice(0, 10),
      )
      update({ search: created.searchId, doc: null, input: null, view: null })
    },
  })

  return (
    <section className="flex flex-col gap-5" aria-labelledby="doc-evidence-heading">
      {/* 머리 카드: 제목 · 설명 · 다시 검색 · 표시 중인 검색의 실제 건수. */}
      <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 max-w-content flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 id="doc-evidence-heading" className="text-h2 font-semibold text-text-strong">
                공식 문서
              </h2>
              <SourceMark kind="doc" />
              <span className="text-caption text-text-muted">검색은 모델 호출 없음</span>
            </div>
            <p className="text-small text-text-muted">
              이 Run에 기록된 실패의 도구와 실행 명령으로 서버의 공식 문서 자료를 검색합니다.
              검색 결과에 나타난 것, AI 설명 요청의 입력에 포함된 것, 답변에서 인용이 확인된
              것은 서로 다른 기록입니다. 모델이 문서를 읽었는지는 기록되지 않습니다.
            </p>
          </div>
          <Button
            onClick={() => search.mutate()}
            disabled={search.isPending || history.isPending}
          >
            <BookOpen size={14} strokeWidth={1.5} aria-hidden="true" />
            {search.isPending ? '검색 중…' : runs.length > 0 ? '다시 검색' : '문서 검색'}
          </Button>
        </div>
        {current ? <SearchStats run={current} /> : null}
      </div>

      {search.isError ? (
        <MessageBlock tone="danger" role="alert" title="검색하지 못했습니다">
          {errorText(search.error)}
        </MessageBlock>
      ) : null}

      {docMissing ? (
        <MessageBlock tone="warning" title="이 문서가 검색 기록에 없습니다">
          <span>
            AI 설명이 근거로 든 <code className="font-mono break-all">{docParam}</code>을(를)
            저장된 검색 기록 {runs.length}건 어디에서도 찾지 못했습니다. 아래는 가장 최근
            검색 기록입니다.
          </span>
        </MessageBlock>
      ) : null}

      {current ? (
        <SearchPicker
          runs={runs}
          current={current}
          onSelect={(id) => update({ search: id, doc: null, input: null, view: null })}
        />
      ) : null}

      {history.isError ? (
        <MessageBlock tone="warning" title="이전 검색 기록을 읽지 못했습니다">
          {errorText(history.error)}
        </MessageBlock>
      ) : history.isPending ? (
        <p role="status" className="text-small text-text-muted">
          검색 기록을 확인하고 있습니다.
        </p>
      ) : current ? (
        <SearchResult
          run={current}
          view={view}
          docParam={docMissing ? null : docParam}
          inputParam={params.get('input')}
          statements={statements}
          onView={(next) => update({ view: next === 'all' ? null : next })}
          onSelectHit={(hit) => {
            update({ search: current.searchId, doc: hit.evidenceId, input: hit.inputId })
            // 좁은 화면에서는 상세가 목록 아래에 있다. 누른 결과가 보이게 내려 준다.
            if (window.matchMedia('(max-width: 69.99rem)').matches) {
              requestAnimationFrame(() =>
                document
                  .getElementById(DOC_DETAIL_PANEL_ID)
                  ?.scrollIntoView({ block: 'start' }),
              )
            }
          }}
          onGoToStep={onGoToStep}
        />
      ) : (
        <p className="rounded-lg border border-dashed border-border bg-surface px-4 py-6 text-center text-small text-text-muted">
          아직 이 Run으로 문서를 검색한 기록이 없습니다.
        </p>
      )}
    </section>
  )
}

/*
  머리 카드의 건수. 표시 중인 검색 기록 하나의 실제 값이다. 요청 기록이 없는
  검색에서 요청 입력·인용은 0건이 아니라 "기록 없음"이고, 요청은 있었지만
  인용을 확인하지 못했으면 "확인 불가"다.
*/
function SearchStats({ run }: { run: DocSearchRun }) {
  const agent = run.purpose === 'agentRequest' ? run.agentRequest : null
  const counts = stageCounts(run.hits)
  const time = formatTimestamp(run.createdAt)
  const stat = (value: number | null, none: string) => (value === null ? none : `${value}건`)
  const items: { label: string; value: ReactNode; ai?: boolean }[] = [
    {
      label: '검색 기록',
      value: (
        <time dateTime={run.createdAt} title={time?.full}>
          {time?.display ?? run.createdAt}
        </time>
      ),
    },
    { label: '입력', value: `${run.inputs.length}건` },
    { label: '반환 문서', value: `${run.resultCount}건` },
    { label: '요청 입력 포함', value: stat(counts.input, '기록 없음') },
    {
      label: '답변 인용 확인',
      value: stat(counts.cited, agent ? '확인 불가' : '기록 없음'),
      ai: true,
    },
  ]
  /*
    2026-11-23 UI 정리(개발판단기록 63장): 아이콘 타일 다섯 칸 → 한 줄 사실 목록.
    "0건 · 기록 없음"을 지표 카드처럼 크게 그리면 비어 있는 값이 성과처럼 읽힌다.
    값과 그 구분(0건 / 기록 없음 / 확인 불가)은 그대로다.
  */
  return (
    <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 border-t border-border-subtle pt-3 text-small">
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline gap-1.5">
          <dt className="text-text-muted">{item.label}</dt>
          <dd className={cx('font-medium', item.ai ? 'text-ai-fg' : 'text-text-strong')}>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function SearchResult({
  run,
  view,
  docParam,
  inputParam,
  statements,
  onView,
  onSelectHit,
  onGoToStep,
}: {
  run: DocSearchRun
  view: HitFilter
  docParam: string | null
  inputParam: string | null
  statements: readonly PlacedStatement[]
  onView: (view: HitFilter) => void
  onSelectHit: (hit: DocSearchHit) => void
  onGoToStep: (stepId: string) => void
}) {
  const agent = run.purpose === 'agentRequest' ? run.agentRequest : null
  const inputsById = new Map(run.inputs.map((input) => [input.inputId, input]))
  const ordered = orderedHits(
    run.inputs.map((input) => input.inputId),
    run.hits,
  )
  // 거르기는 요청 기록이 있는 검색에서만 의미가 있다.
  const effectiveView: HitFilter = agent ? view : 'all'
  const shown = filterHits(ordered, effectiveView)
  const selected = resolveHit(shown, docParam, inputParam)
  const selectedInput = selected ? inputsById.get(selected.inputId) ?? null : null
  const filterCounts = hitFilterCounts(ordered)

  const { withHits, withoutHits } = splitInputs(
    run.inputs,
    (inputId) => run.hits.filter((hit) => hit.inputId === inputId).length,
  )

  return (
    <div className="flex flex-col gap-5">
      {run.purpose === 'agentRequest' && !run.agentRequest ? (
        <MessageBlock tone="warning" title="요청 기록과 연결되지 않은 검색">
          AI 설명 요청이 입력을 만들려고 한 검색이지만 요청 기록이 저장되지 않아, 어떤
          문서가 요청에 들어갔는지 확인할 수 없습니다.
        </MessageBlock>
      ) : null}

      {run.errorMessage ? (
        <MessageBlock tone="warning" title="검색 결과가 없습니다">
          {run.errorMessage}
        </MessageBlock>
      ) : null}

      {run.inputs.length === 0 && !run.errorCategory ? (
        <MessageBlock tone="info" title="검색할 실패 기록이 없습니다">
          이 Run의 기록에는 도구나 명령과 연결된 실패가 없습니다. 아래는 기록되었지만
          검색하지 않은 항목입니다.
        </MessageBlock>
      ) : null}

      {run.inputs.length > 0 || run.hits.length > 0 ? (
        <EvidenceFlow run={run} agent={agent} />
      ) : null}

      {run.hits.length > 0 ? (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <section
            aria-labelledby="doc-list-heading"
            className="flex min-w-0 flex-col gap-4 rounded-lg border border-border bg-surface p-4 shadow-card md:p-5"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 id="doc-list-heading" className="text-h3 font-semibold text-text-strong">
                문서 리스트
              </h3>
              <span className="text-small text-text-muted">
                반환된 공식 문서 {run.hits.length}건과 각 문서의 기록 단계
              </span>
            </div>
            {agent ? (
              <div role="group" aria-label="문서 거르기" className="flex flex-wrap gap-2">
                {FILTERS.map((filter) => {
                  const pressed = effectiveView === filter
                  return (
                    <button
                      key={filter}
                      type="button"
                      aria-pressed={pressed}
                      onClick={() => onView(filter)}
                      className={cx(
                        'inline-flex min-h-8 items-center gap-2 rounded-md border px-3 text-small',
                        pressed
                          ? 'border-brand bg-brand-selected font-medium text-text-strong'
                          : 'border-border bg-surface text-text hover:border-border-strong',
                      )}
                    >
                      {FILTER_LABEL[filter]}
                      <span className="font-mono text-caption text-text-muted">
                        {filterCounts[filter]}
                      </span>
                    </button>
                  )
                })}
              </div>
            ) : null}
            <DocList
              inputs={withHits.filter((input) => shown.some((hit) => hit.inputId === input.inputId))}
              hits={shown}
              agent={agent}
              selectedKey={selected ? hitKey(selected) : null}
              onSelect={onSelectHit}
            />
          </section>
          <aside
            id={DOC_DETAIL_PANEL_ID}
            tabIndex={-1}
            aria-label="선택한 문서의 상세"
            className="min-w-0 scroll-mt-6 rounded-lg border border-border bg-surface p-5 shadow-card outline-none lg:sticky lg:top-6"
          >
            {selected ? (
              <DocDetail
                key={hitKey(selected)}
                hit={selected}
                input={selectedInput}
                agent={agent}
                statements={statements}
                onGoToStep={onGoToStep}
              />
            ) : (
              <p className="text-small text-text-muted">
                이 조건에 해당하는 문서가 없습니다. 문서 리스트의 &quot;전체&quot;를 눌러 모두
                보세요.
              </p>
            )}
          </aside>
        </div>
      ) : null}

      {withoutHits.length > 0 ? (
        <EmptyInputs inputs={withoutHits} agent={agent} />
      ) : null}

      {run.excludedObservations.length > 0 ? (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4 shadow-card">
          <h3 className="text-small font-medium text-text-strong">
            기록되었지만 검색하지 않은 항목
          </h3>
          <ul className="flex flex-col gap-1.5">
            {run.excludedObservations.map((item, index) => (
              <li key={`${item.stepId}-${item.kind}-${index}`} className="flex flex-col gap-0.5 md:flex-row md:gap-3">
                <code className="font-mono text-caption break-all text-text">{item.kind}</code>
                <span className="text-caption text-text-muted">{item.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <CorporaList corpora={run.corpora} method={run.method} />
    </div>
  )
}

function kindTitle(kind: string): string {
  // 규칙표가 분류하지 못한 문장(backend resource_bundle_causes.UNKNOWN). 원문 어휘를 그대로 보이지 않는다.
  if (kind === 'unknown') return '분류되지 않은 문장'
  return causeKindKnowledge(kind)?.title ?? kind
}

/** 문서 주소의 호스트. 주소가 없거나 읽을 수 없으면 null. */
function hostOf(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

/*
  문서 리스트. 검색 이유(입력 = 기록된 실패 + 실행된 명령)별로 묶는다.
  행: 순위 · 제목 · 호스트 · 버전 · 일치 이유(위치 관계 + 조회 방식) · 위치 ·
  발췌 미리보기 · 네 단계 표시. 정렬은 저장된 순위 그대로다 — 관련도 점수는
  저장하지 않으므로 "관련도 순" 정렬을 만들지 않는다.

  `data-evidence-id`: AI 근거와 같은 id. 테스트·자동화가 행을 찾을 때 쓴다.
*/
function DocList({
  inputs,
  hits,
  agent,
  selectedKey,
  onSelect,
}: {
  inputs: DocSearchInput[]
  hits: DocSearchHit[]
  agent: AgentRequest | null
  selectedKey: string | null
  onSelect: (hit: DocSearchHit) => void
}) {
  if (hits.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-small text-text-muted">
        이 조건에 해당하는 문서가 없습니다.
      </p>
    )
  }
  return (
    <nav aria-label="반환된 공식 문서" className="flex flex-col gap-4">
      {inputs.map((input) => {
        const inputHits = hits.filter((hit) => hit.inputId === input.inputId)
        return (
          <section
            key={input.inputId}
            aria-label={`검색 이유: ${kindTitle(input.kind)}`}
            className="flex flex-col gap-2"
          >
            <header className="flex flex-col gap-0.5 px-1">
              <span className="text-caption text-text-muted">
                검색 이유 · 기록된 실패{' '}
                <span className="font-medium text-text-strong">{kindTitle(input.kind)}</span>
              </span>
              {input.kind === 'unknown' && input.suggestedKind ? (
                <span className="text-caption text-text">
                  규칙표로 분류되지 않은 문장입니다. 아래 문서는 문장 표현으로 추정한 종류{' '}
                  <span className="font-medium text-text-strong">{kindTitle(input.suggestedKind)}</span>의
                  해설이며, 이 실행의 원인을 판정한 것이 아닙니다. AI 설명 요청에는 넣지 않습니다.
                </span>
              ) : null}
              <span className="text-caption break-all text-text-muted">
                {input.stepId}
                {input.ruleId ? ` · ${input.ruleId}` : ''}
                {input.command ? ` · ${input.command.display}` : input.tool ? ` · 도구 ${input.tool}` : ''}
              </span>
            </header>
            <ul className="flex flex-col gap-2">
              {inputHits.map((hit) => {
                const key = hitKey(hit)
                const selected = key === selectedKey
                const host = hostOf(hit.sourceUrl)
                const matched = hit.matchedBy.map((m) => MATCHED_BY_LABEL[m] ?? m).join(' + ')
                return (
                  <li key={key} data-evidence-id={hit.evidenceId}>
                    <button
                      type="button"
                      onClick={() => onSelect(hit)}
                      aria-current={selected ? 'true' : undefined}
                      aria-controls={DOC_DETAIL_PANEL_ID}
                      className={cx(
                        'grid w-full grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 rounded-lg border px-3 py-3 text-left focus-visible:[outline-offset:-2px] md:px-4',
                        selected
                          ? 'border-brand bg-brand-faint shadow-card'
                          : 'border-border bg-surface hover:border-border-strong hover:bg-brand-faint',
                      )}
                    >
                      <span className="flex items-start gap-2">
                        <span className="mt-0.5 rounded-sm bg-sunken px-1.5 font-mono text-caption text-text-muted">
                          #{hit.rank}
                        </span>
                        <span
                          aria-hidden="true"
                          className="flex size-8 items-center justify-center rounded-md border border-border-subtle bg-sunken text-text-muted"
                        >
                          <FileText size={16} strokeWidth={1.5} />
                        </span>
                      </span>
                      <span className="flex min-w-0 flex-col gap-1">
                        <span
                          className={cx(
                            'text-body text-text-strong',
                            selected ? 'font-semibold' : 'font-medium',
                          )}
                        >
                          {hit.sourceTitle}
                        </span>
                        {host || hit.version ? (
                          <span className="line-clamp-1 text-caption text-text-muted">
                            {host}
                            {host && hit.version ? ' · ' : ''}
                            {hit.version}
                          </span>
                        ) : null}
                        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-caption">
                          <span className="flex-none rounded-sm bg-brand-selected px-1.5 font-medium text-text-strong">
                            일치 이유
                          </span>
                          <span className="min-w-0 text-text">
                            {RELATION_LABEL[hit.relation] ?? '기타 위치'}
                            {matched ? ` · ${matched}` : ''}
                          </span>
                        </span>
                        <span className="truncate text-caption text-text-muted">{hit.location}</span>
                        {hit.excerpt ? (
                          <span className="line-clamp-1 font-mono text-caption text-text-muted">
                            {hit.excerpt}
                          </span>
                        ) : null}
                      </span>
                      <span className="col-span-2 md:col-start-2">
                        <StageDots usage={hit.usage} agent={agent} size="sm" />
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}
    </nav>
  )
}

/*
  오른쪽 상세 패널 — 고른 문서 하나.

    문서        아이콘 · 제목 · 호스트 · 버전 · 원문 보기 · 순위 · 자료 · 확인일 · id
    기록 단계   검색 결과 → 입력 후보 → 요청 입력 → 답변 인용 (+ 모델이 읽음: 기록 없음)
    왜 검색됐나 기록된 실패(→ 파이프라인 단계) · 실행된 명령 · 검색어 · 조회 방식 · 위치 관계
    메모 · 근거 발췌 · 이 문서를 근거로 든 AI 문장
*/
function DocDetail({
  hit,
  input,
  agent,
  statements,
  onGoToStep,
}: {
  hit: DocSearchHit
  input: DocSearchInput | null
  agent: AgentRequest | null
  statements: readonly PlacedStatement[]
  onGoToStep: (stepId: string) => void
}) {
  const citing = statements.filter((statement) =>
    statement.evidenceRefs.includes(hit.evidenceId),
  )
  const host = hostOf(hit.sourceUrl)
  const readStage = usageStages(hit.usage, agent !== null).find((stage) => stage.key === 'read')
  const matched = hit.matchedBy.map((m) => MATCHED_BY_LABEL[m] ?? m).join(' + ')
  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-3 border-b border-border pb-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="flex size-10 flex-none items-center justify-center rounded-md border border-border-subtle bg-sunken text-text-muted"
          >
            <FileText size={18} strokeWidth={1.5} />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <h3 className="text-h3 font-semibold text-text-strong">{hit.sourceTitle}</h3>
            {host || hit.version ? (
              <span className="text-caption break-words text-text-muted">
                {host}
                {host && hit.version ? ' · ' : ''}
                {hit.version}
              </span>
            ) : null}
          </div>
          {hit.sourceUrl ? (
            <a
              href={hit.sourceUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex min-h-8 flex-none items-center gap-1 rounded-md border border-border bg-surface px-2.5 text-small text-text no-underline hover:border-brand hover:text-brand"
            >
              <ExternalLink size={13} strokeWidth={1.5} aria-hidden="true" />
              원문 보기
            </a>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-text-muted">
          <SourceMark kind="doc" />
          <span className="font-mono">#{hit.rank}</span>
          <span>{CORPUS_LABEL[hit.corpus] ?? hit.corpus}</span>
          {hit.checkedOn ? <span>확인일 {hit.checkedOn}</span> : null}
        </div>
        <span className="text-small break-all text-text">{hit.location}</span>
        <code className="font-mono text-caption break-all text-text-muted">{hit.evidenceId}</code>
        {hit.sourceMatches === false ? (
          <p className="text-caption text-status-warning-fg">
            검색 이후 자료가 바뀌었습니다. 아래 본문은 검색 당시와 다를 수 있습니다.
          </p>
        ) : hit.sourceMatches === null ? (
          <p className="text-caption text-text-muted">
            이 서버에 해당 자료가 없어 본문을 표시할 수 없습니다.
          </p>
        ) : null}
      </header>

      <DetailBlock title="이 문서의 기록 단계">
        <div className="rounded-md border border-border-subtle bg-sunken px-3 py-3">
          <StageDots usage={hit.usage} agent={agent} size="md" />
        </div>
        <p className="text-caption text-text-muted">
          모델이 읽음: {readStage?.value ?? '기록 없음'} — 모델이 문서를 읽었는지는 기록되지
          않습니다.
        </p>
        {hit.usage.selectedForAgent === false && hit.usage.selectionReason ? (
          <p className="text-caption text-text-muted">
            Agent 입력에서 제외: {hit.usage.selectionReason}
          </p>
        ) : null}
      </DetailBlock>

      <section
        aria-labelledby="doc-why-heading"
        className="flex flex-col gap-3 rounded-md border border-border-subtle p-3.5"
      >
        <h4
          id="doc-why-heading"
          className="inline-flex items-center gap-1.5 text-small font-semibold text-text-strong"
        >
          <Info size={14} strokeWidth={1.5} aria-hidden="true" className="text-text-muted" />
          왜 이 문서가 검색되었는가
        </h4>
        {input ? (
          <>
            <p className="text-small text-text">
              이 Run의 기록된 실패 「{kindTitle(input.kind)}」로 만든 검색 입력에서
              {matched ? ` ${matched}(으)로` : ''} 반환된 문서입니다.
            </p>
            <dl className="grid grid-cols-1 gap-x-4 gap-y-3 md:grid-cols-[7rem_minmax(0,1fr)]">
              <dt className="text-caption text-text-muted">관련 실패 기록</dt>
              <dd className="flex flex-col items-start gap-1">
                <button
                  type="button"
                  onClick={() => onGoToStep(input.stepId)}
                  className="inline-flex min-h-7 max-w-full items-center gap-1 rounded-pill border border-status-failure-bd bg-status-failure-bg px-2.5 text-caption break-all text-status-failure-fg hover:border-fill-failure"
                >
                  <ArrowUpRight size={12} strokeWidth={1.5} aria-hidden="true" className="flex-none" />
                  {input.stepId}
                  {input.ruleId ? ` · ${input.ruleId}` : ''}
                </button>
                <span className="text-caption text-text-muted">
                  {kindTitle(input.kind)}
                  {input.occurrences > 1 ? ` · ${input.occurrences}건` : ''} · 누르면 파이프라인에서
                  이 단계를 엽니다
                </span>
              </dd>
              <dt className="text-caption text-text-muted">실행된 명령</dt>
              <dd className="flex flex-col gap-0.5">
                <CommandValue input={input} />
              </dd>
              <dt className="text-caption text-text-muted">검색어</dt>
              <dd>
                <QueryTerms terms={input.queryTerms} />
              </dd>
              <dt className="text-caption text-text-muted">조회 방식</dt>
              <dd className="text-small text-text">{matched || '기록 없음'}</dd>
              <dt className="text-caption text-text-muted">위치 관계</dt>
              <dd className="flex flex-col gap-0.5">
                <span className="text-small text-text">
                  {RELATION_LABEL[hit.relation] ?? '기타 위치'}
                </span>
                <span className="text-caption text-text-muted">
                  매뉴얼 구간의 관계는 목차상 위치입니다. 이 Run의 원인이라는 뜻이 아닙니다.
                </span>
              </dd>
            </dl>
            <SkippedCorpora input={input} />
          </>
        ) : (
          <p className="text-small text-text-muted">
            이 문서와 연결된 검색 입력 기록이 없습니다.
          </p>
        )}
      </section>

      {hit.note || hit.limits ? (
        <DetailBlock title="문서에 대한 메모">
          {hit.note ? <p className="text-small text-text">{hit.note}</p> : null}
          {hit.limits ? (
            <p className="text-small text-text-muted">이 Run에 대해 알려주지 않는 것: {hit.limits}</p>
          ) : null}
        </DetailBlock>
      ) : null}

      <DetailBlock title="문서 주요 내용 (발췌)">
        {hit.excerpt ? (
          /*
            인용 표시는 1px 전체 테두리다. 이전의 왼쪽 2px 브랜드 선은 CLAUDE.md 23장의
            "한쪽 accent rail"과 같은 모양이었다(2026-11-23 화면 점검).
          */
          <pre className="max-h-80 overflow-auto rounded-sm border border-border bg-sunken px-3 py-2 font-mono text-caption leading-body break-words whitespace-pre-wrap text-text">
            {hit.excerpt}
          </pre>
        ) : (
          <p className="text-small text-text-muted">표시할 발췌가 없습니다.</p>
        )}
      </DetailBlock>

      <DetailBlock title="AI 설명에서 이 문서를 근거로 든 문장">
        {citing.length > 0 ? (
          <ul className="flex flex-col gap-3 rounded-md border border-ai-bd bg-ai-bg p-3">
            {citing.map((statement) => (
              <li key={statement.number} className="flex flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                  <SourceMark kind="ai" />
                  <span className="text-caption text-text-muted">
                    #{statement.number} · {STATEMENT_GROUP_LABEL[statement.group] ?? statement.group}
                  </span>
                </span>
                <span className="text-small leading-body text-text">{statement.statement}</span>
                <button
                  type="button"
                  onClick={() => revealStatement(statement.number)}
                  className="inline-flex min-h-6 w-fit items-center gap-1 text-caption text-ai-fg underline underline-offset-2 hover:text-text-strong"
                >
                  AI 설명 탭에서 보기
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-small text-text-muted">
            {statements.length === 0
              ? '이 화면에 AI 종합 설명이 없습니다. 설명을 요청하면 이 문서를 근거로 든 문장이 여기에 표시됩니다.'
              : '지금 AI 종합 설명에서 이 문서를 근거로 든 문장은 없습니다.'}
          </p>
        )}
      </DetailBlock>
    </div>
  )
}

function DetailBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-small font-semibold text-text-strong">{title}</h4>
      {children}
    </section>
  )
}

function CommandValue({ input }: { input: DocSearchInput }) {
  return input.command ? (
    <>
      <code className="font-mono text-small break-all text-text-strong">{input.command.display}</code>
      <span className="text-caption text-text-muted">{input.command.recordedBy}</span>
    </>
  ) : (
    <span className="text-small text-text-muted">
      {input.tool ? `도구 ${input.tool} · 명령 기록 없음` : '도구·명령 기록 없음'}
    </span>
  )
}

function QueryTerms({ terms }: { terms: string[] }) {
  return terms.length > 0 ? (
    <span className="flex flex-wrap gap-1">
      {terms.map((term) => (
        <code key={term} className="rounded-sm bg-sunken px-1.5 font-mono text-caption text-text">
          {term}
        </code>
      ))}
    </span>
  ) : (
    <span className="text-small text-text-muted">없음</span>
  )
}

function SkippedCorpora({ input }: { input: DocSearchInput }) {
  if (input.skipped.length === 0) return null
  return (
    <ul className="flex flex-col gap-1">
      {input.skipped.map((skip) => (
        <li key={skip.corpus} className="text-caption text-text-muted">
          {CORPUS_LABEL[skip.corpus] ?? skip.corpus} 검색 안 함 — {skip.reason}
        </li>
      ))}
    </ul>
  )
}

/*
  문서가 반환되지 않은 입력. 한 표에 모으되, 각 입력의 실패·명령·검색어·
  건너뛴 이유는 모두 그대로 보인다(39장).
*/
function EmptyInputs({
  inputs,
  agent,
}: {
  inputs: DocSearchInput[]
  agent: AgentRequest | null
}) {
  return (
    <section
      aria-labelledby="doc-empty-inputs"
      className="flex flex-col rounded-lg border border-border bg-surface shadow-card"
    >
      <h3
        id="doc-empty-inputs"
        className="border-b border-border px-4 py-3 text-small font-medium text-text-strong"
      >
        문서가 반환되지 않은 입력
        <span className="ml-2 font-normal text-text-muted">{inputs.length}건</span>
      </h3>
      <ul className="flex flex-col">
        {inputs.map((input) => (
          <li
            key={input.inputId}
            className="grid grid-cols-1 gap-x-6 gap-y-2 border-t border-border-subtle px-4 py-3 first:border-t-0 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_auto]"
          >
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-caption text-text-muted">기록된 실패</span>
              <span className="text-small font-medium text-text-strong">{kindTitle(input.kind)}</span>
              <span className="text-caption text-text-muted">
                {input.stepId}
                {input.ruleId ? ` · ${input.ruleId}` : ''}
                {input.occurrences > 1 ? ` · ${input.occurrences}건` : ''}
              </span>
            </div>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-caption text-text-muted">실행된 명령</span>
              <CommandValue input={input} />
            </div>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-caption text-text-muted">검색어</span>
              <QueryTerms terms={input.queryTerms} />
            </div>
            <dl className="flex gap-4 text-caption md:flex-col md:gap-0.5 md:text-right">
              <div className="flex gap-1 md:justify-end">
                <dt className="text-text-muted">반환된 문서</dt>
                <dd className="font-medium text-text-strong">0건</dd>
              </div>
              {agent ? (
                <div className="flex gap-1 md:justify-end">
                  <dt className="text-text-muted">요청 입력에 포함</dt>
                  <dd className="font-medium text-text-strong">0건</dd>
                </div>
              ) : null}
            </dl>
            {input.skipped.length > 0 ? (
              <div className="md:col-span-4">
                <SkippedCorpora input={input} />
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

/*
  문서 하나의 네 단계 표시: 검색 결과 → 입력 후보 → 요청 입력 → 답변 인용.
  값은 글자(화면 낭독기 포함)로 말하고, 점 모양으로 보조한다 — 예는 채운
  체크, 아니오는 빈 원, 기록 없음·확인 불가는 점선 원과 물음표. 답변 인용만
  AI 색이다. "모델이 읽음"은 기록되지 않으므로 여기에 넣지 않고 상세가 따로
  말한다.
*/
const SHORT_STAGE_LABEL: Record<string, string> = {
  returned: '검색 결과',
  candidate: '입력 후보',
  input: '요청 입력',
  cited: '답변 인용',
}

function StageDots({
  usage,
  agent,
  size,
}: {
  usage: DocSearchHit['usage']
  agent: AgentRequest | null
  size: 'sm' | 'md'
}) {
  const stages = usageStages(usage, agent !== null).filter((stage) => stage.key !== 'read')
  const dot = size === 'md' ? 'size-6' : 'size-5'
  return (
    <ol aria-label="이 문서의 기록 단계" className="grid grid-cols-4">
      {stages.map((stage, index) => {
        const ai = stage.key === 'cited'
        return (
          <li key={stage.key} className="relative flex flex-col items-center gap-1 text-center">
            {index > 0 ? (
              <span
                aria-hidden="true"
                className={cx(
                  'absolute right-1/2 left-[-50%] h-px',
                  size === 'md' ? 'top-3' : 'top-2.5',
                  stage.state === 'yes' ? 'bg-ink-300' : 'bg-border',
                )}
              />
            ) : null}
            <span
              aria-hidden="true"
              className={cx(
                'relative z-10 flex items-center justify-center rounded-pill',
                dot,
                stage.state === 'yes'
                  ? ai
                    ? 'bg-ai-fg text-surface'
                    : 'bg-fill-success text-surface'
                  : stage.state === 'no'
                    ? 'border-2 border-ink-300 bg-surface'
                    : 'border-2 border-dashed border-ink-300 bg-surface text-text-muted',
              )}
            >
              {stage.state === 'yes' ? (
                <Check size={size === 'md' ? 14 : 12} strokeWidth={2.5} />
              ) : stage.state === 'none' ? (
                <CircleHelp size={size === 'md' ? 12 : 10} strokeWidth={2} />
              ) : null}
            </span>
            <span
              className={cx(
                'text-caption',
                stage.state === 'yes'
                  ? ai
                    ? 'font-medium text-ai-fg'
                    : 'text-text-strong'
                  : 'text-text-muted',
              )}
            >
              {SHORT_STAGE_LABEL[stage.key] ?? stage.label}
            </span>
            <span
              className={cx(
                'text-caption text-text-muted',
                size === 'sm' && 'sr-only',
              )}
            >
              {stage.value}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

const OUTCOME_LABEL: Record<string, string> = {
  answerServed: '답변이 모든 검사를 통과해 제공됨',
  answerRejected: '답변이 왔지만 검사에서 거부됨',
  noAnswer: '사용할 수 있는 답변이 오지 않음',
}

/*
  증거 흐름 — 이 검색 기록의 실패 → 명령 → 검색어 → 반환 문서 → 후보 → 요청
  입력 → 모델 응답 → 답변 인용. 이전의 "요청 이력"(RequestTrace)과 "단계
  막대"(StageBar)가 같은 건수를 두 번 보여 주던 것을 하나로 합쳤다(2026-11-20).
  두 곳의 값은 모두 여기 있다: 요청 시각 · 반환 · 후보 · 요청 입력 · 응답
  결과 · 오류 분류 · 검증된 인용 · 설명 문구.

  건수는 문서별 기록(hits[].usage)에서 센다. 요청 기록의 집계값(candidateCount ·
  inPayloadCount · citedCount)이 그것과 다를 때만 따로 적는다. 실패·명령·
  검색어 건수는 이 검색의 입력에서 중복을 뺀 수다. 모두 저장된 값이며 화면이
  관계를 만들지 않는다.
*/
function EvidenceFlow({ run, agent }: { run: DocSearchRun; agent: AgentRequest | null }) {
  const counts = stageCounts(run.hits)
  const failures = new Set(run.inputs.map((i) => `${i.stepId}|${i.kind}|${i.ruleId ?? ''}`))
  const commands = [
    ...new Set(run.inputs.flatMap((i) => (i.command ? [i.command.display] : []))),
  ]
  const terms = [...new Set(run.inputs.flatMap((i) => i.queryTerms))]
  const kinds = [...new Set(run.inputs.map((i) => kindTitle(i.kind)))]
  const time = agent ? formatTimestamp(agent.requestedAt) : null
  const n = (value: number | null, none = '기록 없음') => (value === null ? none : `${value}건`)
  const differs = (recorded: number | null | undefined, counted: number | null) =>
    recorded !== null && recorded !== undefined && recorded !== counted

  const cells: {
    key: string
    label: string
    icon: typeof FileText
    value: string
    sub?: ReactNode
    tone?: 'failure' | 'ai'
  }[] = [
    {
      key: 'failure',
      label: '기록된 실패',
      icon: TriangleAlert,
      value: `${failures.size}건`,
      sub: kinds.length > 0 ? kinds.slice(0, 2).join(' · ') + (kinds.length > 2 ? ' 등' : '') : undefined,
      tone: 'failure',
    },
    {
      key: 'command',
      label: '실행된 명령',
      icon: Terminal,
      value: `${commands.length}건`,
      sub: commands[0] ? (
        <code className="font-mono">{commands[0] + (commands.length > 1 ? ' 등' : '')}</code>
      ) : (
        '명령 기록 없음'
      ),
    },
    {
      key: 'terms',
      label: '검색어',
      icon: Search,
      value: `${terms.length}개`,
      sub: terms.length > 0 ? terms.slice(0, 3).join(', ') + (terms.length > 3 ? ' 등' : '') : undefined,
    },
    {
      key: 'returned',
      label: '반환 문서',
      icon: FileText,
      value: `${counts.returned}건`,
      sub:
        run.resultCount !== counts.returned
          ? `검색 기록 ${run.resultCount}건`
          : '공식 문서 검색 결과',
    },
    {
      key: 'candidate',
      label: 'Agent 입력 후보',
      icon: Layers,
      value: n(counts.candidate),
      sub: agent
        ? differs(agent.candidateCount, counts.candidate)
          ? `요청 기록 ${agent.candidateCount}건`
          : '실행 명령의 매뉴얼 절 · 원인 종류 등록 발췌'
        : undefined,
    },
    {
      key: 'input',
      label: '요청 입력 포함',
      icon: FileInput,
      value: n(counts.input),
      sub: agent
        ? differs(agent.inPayloadCount, counts.input)
          ? `요청 기록 ${agent.inPayloadCount}건 포함`
          : '서버가 만든 요청에 들어감'
        : undefined,
    },
    {
      key: 'response',
      label: '모델 응답',
      icon: MessageSquare,
      value: agent ? (OUTCOME_LABEL[agent.outcome] ?? agent.outcome) : '기록 없음',
      sub: agent?.errorCategory ? (
        <code className="font-mono break-all">{agent.errorCategory}</code>
      ) : undefined,
      tone: 'ai',
    },
    {
      key: 'cited',
      label: '답변 인용',
      icon: Quote,
      value: n(counts.cited, agent ? '확인 불가' : '기록 없음'),
      sub:
        agent && agent.citedCount === null
          ? '제공된 답변이 없어 인용을 확인하지 않음'
          : agent && differs(agent.citedCount, counts.cited)
            ? `검증된 인용 ${agent.citedCount}건`
            : agent
              ? '검사를 통과한 답변에서 확인'
              : undefined,
      tone: 'ai',
    },
  ]

  return (
    <section
      aria-labelledby="doc-flow-heading"
      className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-5 shadow-card"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 id="doc-flow-heading" className="text-h3 font-semibold text-text-strong">
          증거 흐름
        </h3>
        <span className="text-small text-text-muted">
          실패 → 검색 → 입력 → 응답 → 인용. 각 칸은 따로 저장된 기록입니다.
        </span>
        {time && agent ? (
          <span className="text-caption text-text-muted">
            AI 설명 요청{' '}
            <time dateTime={agent.requestedAt} title={time.full}>
              {time.display}
            </time>
          </span>
        ) : null}
      </div>
      <ol
        aria-label="증거 흐름"
        className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8"
      >
        {cells.map((cell, index) => {
          const Icon = cell.icon
          return (
            <li
              key={cell.key}
              className={cx(
                'relative flex min-w-0 flex-col items-center gap-1 rounded-md border px-2 py-3 text-center',
                cell.tone === 'failure'
                  ? 'border-status-failure-bd bg-status-failure-bg'
                  : cell.tone === 'ai'
                    ? 'border-ai-bd bg-ai-bg'
                    : 'border-border-subtle bg-sunken',
              )}
            >
              {index > 0 ? (
                <ArrowRight
                  size={12}
                  strokeWidth={1.5}
                  aria-hidden="true"
                  className="absolute top-1/2 -left-2 hidden -translate-y-1/2 text-text-muted xl:block"
                />
              ) : null}
              <Icon
                size={18}
                strokeWidth={1.5}
                aria-hidden="true"
                className={
                  cell.tone === 'failure'
                    ? 'text-status-failure-fg'
                    : cell.tone === 'ai'
                      ? 'text-ai-fg'
                      : 'text-text-muted'
                }
              />
              <span className="text-caption font-medium text-text-strong">{cell.label}</span>
              <span
                className={cx(
                  'text-small font-semibold',
                  cell.tone === 'ai' ? 'text-ai-fg' : 'text-text-strong',
                )}
              >
                {cell.value}
              </span>
              {cell.sub ? (
                <span className="line-clamp-2 text-caption break-all text-text-muted">{cell.sub}</span>
              ) : null}
            </li>
          )
        })}
      </ol>
      <p className="text-caption text-text-muted">
        모델이 문서를 읽었는지는 기록되지 않습니다.
        {agent
          ? ' "요청 입력 포함"은 서버가 만든 요청에 들어갔다는 뜻이며 모델이 읽었다는 기록이 아닙니다. 인용은 모든 검사를 통과해 제공된 답변에서만 확인합니다.'
          : ' 이 검색은 AI 설명 요청과 연결되지 않아 검색 결과 단계만 기록됩니다.'}
      </p>
    </section>
  )
}

function CorporaList({ corpora, method }: { corpora: DocCorpus[]; method: string }) {
  return (
    <details className="group rounded-lg border border-border bg-surface p-4 shadow-card">
      {/* 다른 접힘 묶음(실행 로그 등)과 같은 chevron 표식. 브라우저 기본 ▶를 쓰지 않는다. */}
      <summary className="flex min-h-6 cursor-pointer list-none items-center gap-2 text-small font-medium text-text-strong [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={16}
          strokeWidth={1.5}
          aria-hidden="true"
          className="text-text-muted transition-transform group-open:rotate-90"
        />
        검색한 자료와 방법
      </summary>
      <ul className="mt-3 flex flex-col gap-3">
        {corpora.map((corpus) => (
          <li key={corpus.corpusId} className="flex flex-col gap-0.5">
            <span className="text-small text-text">
              {corpus.title}
              <span className="ml-2 text-caption text-text-muted">
                {corpus.available ? `${corpus.itemCount}개 항목` : '사용할 수 없음'}
              </span>
            </span>
            <span className="text-caption text-text-muted">{corpus.officialStatus}</span>
            {corpus.version ? (
              <span className="text-caption text-text-muted">버전: {corpus.version}</span>
            ) : null}
            {corpus.snapshot ? (
              <span className="text-caption text-text-muted">
                스냅샷 <code className="font-mono">{corpus.snapshot}</code>
              </span>
            ) : null}
            {corpus.excludedItems > 0 ? (
              <span className="text-caption text-status-warning-fg">
                기록된 해시와 다른 항목 {corpus.excludedItems}개는 검색에서 뺐습니다.
              </span>
            ) : null}
            {corpus.note ? <span className="text-caption text-text-muted">{corpus.note}</span> : null}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-caption text-text-muted">
        방법: <code className="font-mono break-all">{method}</code>
      </p>
    </details>
  )
}

function purposeLabel(run: DocSearchRun): string {
  return run.purpose === 'agentRequest' ? 'AI 설명 요청이 만든 검색' : 'Run 상세에서 요청한 검색'
}

/*
  표시 중인 검색 기록과 다른 기록으로 바꾸기(39장). 결과 위에 한 줄로 보이고,
  기록이 둘 이상이면 같은 자리에서 펼쳐 고른다.
*/
function SearchPicker({
  runs,
  current,
  onSelect,
}: {
  runs: DocSearchRun[]
  current: DocSearchRun
  onSelect: (id: string) => void
}) {
  const time = formatTimestamp(current.createdAt)
  const summary = (
    <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <span className="text-caption text-text-muted">표시 중인 검색</span>
      <time dateTime={current.createdAt} title={time?.full} className="text-small font-medium text-text-strong">
        {time?.display ?? current.createdAt}
      </time>
      <span className="text-small text-text">{purposeLabel(current)}</span>
      <span className="text-caption text-text-muted">
        입력 {current.inputs.length} · 문서 {current.resultCount}
      </span>
    </span>
  )
  if (runs.length <= 1) {
    return <div className="rounded-lg border border-border bg-surface px-4 py-2.5 shadow-card">{summary}</div>
  }
  return (
    <details className="group rounded-lg border border-border bg-surface shadow-card">
      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5">
        {summary}
        <span className="inline-flex items-center gap-1 text-caption text-text-muted group-hover:text-text">
          검색 기록 {runs.length}건
          <ChevronRight
            size={12}
            strokeWidth={1.5}
            aria-hidden="true"
            className="flex-none group-open:rotate-90"
          />
        </span>
      </summary>
      <ul className="flex flex-col gap-1 border-t border-border-subtle px-2 py-2">
        {runs.map((run) => {
          const runTime = formatTimestamp(run.createdAt)
          const selected = run.searchId === current.searchId
          return (
            <li key={run.searchId}>
              <button
                type="button"
                onClick={() => onSelect(run.searchId)}
                aria-current={selected ? 'true' : undefined}
                className={
                  'flex w-full flex-wrap items-baseline gap-x-3 rounded-sm px-2 py-1 text-left text-caption ' +
                  (selected ? 'bg-sunken text-text-strong' : 'text-text-muted hover:bg-sunken')
                }
              >
                <time dateTime={run.createdAt} title={runTime?.full}>
                  {runTime?.display ?? run.createdAt}
                </time>
                <span>입력 {run.inputs.length}</span>
                <span>문서 {run.resultCount}</span>
                {run.durationMs !== null ? <span>{run.durationMs}ms</span> : null}
                <span>{purposeLabel(run)}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </details>
  )
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : '알 수 없는 오류가 발생했습니다.'
}
