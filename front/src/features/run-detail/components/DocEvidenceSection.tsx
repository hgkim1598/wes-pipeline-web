import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowRight, BookOpen, ExternalLink } from 'lucide-react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { createDocSearch, fetchDocSearches } from '@/features/run-detail/api'
import type {
  AgentRequest,
  DocCorpus,
  DocSearchHit,
  DocSearchInput,
  DocSearchRun,
} from '@/features/run-detail/api'
import { newLinkedAgentSearch, seenFrom } from '@/features/run-detail/docTraceSelection'
import type { SeenSearches } from '@/features/run-detail/docTraceSelection'
import { runDetailKey } from '@/features/run-detail/queries'
import { formatTimestamp } from '@/features/runs/time'
import { causeKindKnowledge } from '@/registries/knowledge'

/*
  실패와 관련된 공식 문서 — 검색 결과와 그 Trace (개발판단기록 26장).

  ── 무엇을 보여주나 ─────────────────────────────────────────────────────

  backend가 이 Run의 기록된 실패(원인 종류·도구·실행된 명령)로 로컬 공식 문서
  자료를 검색하고 저장한 결과다. **모델이 만든 것도, 모델이 고른 것도 아니다.**
  위쪽 "참조 데이터 검사에서 기록된 원인"이 이 Run의 관측 사실이고, 여기는 그
  사실로 찾은 일반 문서 지식이다. 둘을 한 덩어리로 섞지 않는다.

  입력마다 한 줄의 흐름을 그린다: 기록된 실패 → 실행된 명령 → 검색어 →
  반환된 문서. 모두 Trace에 저장된 값이며, 화면이 연결을 추론하지 않는다.
  "같은 명령의 설명 구간" 같은 관계는 매뉴얼 목차상의 위치일 뿐 원인이라는
  뜻이 아니다. 점수·신뢰도는 저장하지 않으므로 보여주지도 않는다.

  ── 쓰지 않는 말 ────────────────────────────────────────────────────────

  "AI가 참고한", "근거로 사용된" 같은 표현을 쓰지 않는다. 사실은 단계마다
  따로 기록된다(27장): 검색 결과에 나타남 → Agent 입력 후보(구조 규칙) →
  요청 입력에 포함(서버가 실제로 만든 요청) → 답변 인용(검사를 모두 통과한
  답변에서만 확인). 모델이 읽었는지는 어디에도 기록되지 않는다. Run 상세
  버튼으로 한 검색에는 앞의 하나만 있고 나머지는 null이며, null을 "아니오"로
  바꾸어 적지 않는다.

  AI 설명 요청이 만든 검색에는 그 요청의 이력(C)을 한 줄로 그린다: 검색 →
  후보 → 요청 입력 → 모델 응답 → 인용 검증. 저장된 값만 쓰며, 요청 기록이
  연결되지 않은 검색에는 그리지 않는다.

  ── 호출 정책 ───────────────────────────────────────────────────────────

  GET은 사용량을 쓰지 않으므로 query로 읽는다(polling 없음). POST는 Trace를
  하나 더 쌓으므로 버튼을 눌렀을 때만 부른다.
*/

const docSearchKey = (jobId: string) => [...runDetailKey(jobId), 'doc-search'] as const

const RELATION_LABEL: Record<string, string> = {
  filedUnderCauseKind: '이 원인 종류에 등록된 해설',
  sameCommandSection: '실행된 명령과 같은 매뉴얼 구간',
  otherCommandSection: '다른 명령의 매뉴얼 구간',
  generalSection: '매뉴얼의 일반 구간',
}

const RELATION_ORDER = [
  'filedUnderCauseKind',
  'sameCommandSection',
  'otherCommandSection',
  'generalSection',
]

const MATCHED_BY_LABEL: Record<string, string> = {
  causeKindKey: '원인 종류로 조회',
  optionLookup: '명령 옵션으로 조회',
  sectionIntro: '실행된 명령 구간의 첫 설명',
  fts5: '전문 검색',
}

const CORPUS_LABEL: Record<string, string> = {
  curated: '정리된 해설',
  manual: '공식 매뉴얼',
}

export interface DocEvidenceSectionProps {
  jobId: string
}

export function DocEvidenceSection({ jobId }: DocEvidenceSectionProps) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const history = useQuery({
    queryKey: docSearchKey(jobId),
    queryFn: ({ signal }) => fetchDocSearches(jobId, signal),
    staleTime: Infinity,
  })

  // 방금 끝난 AI 설명 요청의 연결된 검색이 새로 생기면 그 기록으로 이동한다.
  // 그 외의 갱신은 선택을 바꾸지 않는다(규칙: docTraceSelection.ts, 29장).
  const seen = useRef<SeenSearches | null>(null)
  useEffect(() => {
    const data = history.data
    if (!data) return
    const next = newLinkedAgentSearch(seen.current, jobId, data)
    seen.current = seenFrom(jobId, data)
    if (next !== null) setSelectedId(next)
  }, [history.data, jobId])

  const search = useMutation({
    mutationFn: () => createDocSearch(jobId),
    retry: false,
    onSuccess: (created) => {
      queryClient.setQueryData<DocSearchRun[]>(docSearchKey(jobId), (runs) =>
        [created, ...(runs ?? []).filter((run) => run.searchId !== created.searchId)].slice(0, 10),
      )
      setSelectedId(created.searchId)
    },
  })

  const runs = history.data ?? []
  const current = runs.find((run) => run.searchId === selectedId) ?? runs[0]

  return (
    <section className="flex flex-col gap-4" aria-labelledby="doc-evidence-heading">
      <SectionHeader
        eyebrow="OFFICIAL DOCS"
        title={<span id="doc-evidence-heading">실패와 관련된 공식 문서</span>}
        meta="검색은 모델 호출 없음"
        action={
          <Button
            onClick={() => search.mutate()}
            disabled={search.isPending || history.isPending}
          >
            <BookOpen size={14} strokeWidth={1.5} aria-hidden="true" />
            {search.isPending ? '검색 중…' : runs.length > 0 ? '다시 검색' : '문서 검색'}
          </Button>
        }
      />

      <p className="text-small text-text-muted">
        이 Run에 기록된 실패의 도구와 실행 명령으로 서버의 공식 문서 자료를 검색합니다.
        검색 결과에 나타난 것, AI 설명 요청의 입력에 포함된 것, 답변에서 인용이 확인된
        것은 서로 다른 기록입니다. 모델이 문서를 읽었는지는 기록되지 않습니다.
      </p>

      {search.isError ? (
        <MessageBlock tone="danger" role="alert" title="검색하지 못했습니다">
          {errorText(search.error)}
        </MessageBlock>
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
        <SearchResult run={current} />
      ) : (
        <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-small text-text-muted">
          아직 이 Run으로 문서를 검색한 기록이 없습니다.
        </p>
      )}

      {runs.length > 1 ? (
        <TraceList runs={runs} selectedId={current?.searchId ?? null} onSelect={setSelectedId} />
      ) : null}
    </section>
  )
}

function SearchResult({ run }: { run: DocSearchRun }) {
  const hitsByInput = new Map<string, DocSearchHit[]>()
  for (const hit of run.hits) {
    const list = hitsByInput.get(hit.inputId) ?? []
    list.push(hit)
    hitsByInput.set(hit.inputId, list)
  }

  const agent = run.purpose === 'agentRequest' ? run.agentRequest : null

  return (
    <div className="flex flex-col gap-4">
      <RequestTrace run={run} />

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

      <ul className="flex flex-col gap-4">
        {run.inputs.map((input) => (
          <li key={input.inputId}>
            <InputCard
              input={input}
              hits={hitsByInput.get(input.inputId) ?? []}
              agent={agent}
            />
          </li>
        ))}
      </ul>

      {run.excludedObservations.length > 0 ? (
        <div className="flex flex-col gap-2 rounded-md border border-border bg-surface p-4">
          <h3 className="text-small font-medium text-text-strong">
            기록되었지만 검색하지 않은 항목
          </h3>
          <ul className="flex flex-col gap-1.5">
            {run.excludedObservations.map((item, index) => (
              <li key={`${item.stepId}-${item.kind}-${index}`} className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
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
  return causeKindKnowledge(kind)?.title ?? kind
}

/** 입력 하나: 흐름(실패 → 명령 → 검색어 → 반환 건수)과 반환된 문서. */
function InputCard({
  input,
  hits,
  agent,
}: {
  input: DocSearchInput
  hits: DocSearchHit[]
  agent: AgentRequest | null
}) {
  const groups = RELATION_ORDER.map((relation) => ({
    relation,
    hits: hits.filter((hit) => hit.relation === relation),
  }))
  const unknown = hits.filter((hit) => !RELATION_ORDER.includes(hit.relation))
  if (unknown.length > 0) groups.push({ relation: 'other', hits: unknown })

  return (
    <article className="flex flex-col rounded-md border border-border bg-surface">
      <ol
        aria-label="검색 흐름"
        className="flex flex-col items-stretch gap-1 border-b border-border p-4 lg:flex-row lg:items-start lg:gap-2"
      >
        <FlowStep label="기록된 실패" first>
          <span className="text-small font-medium text-text-strong">{kindTitle(input.kind)}</span>
          <span className="text-caption text-text-muted">
            {input.stepId}
            {input.ruleId ? ` · ${input.ruleId}` : ''}
            {input.occurrences > 1 ? ` · ${input.occurrences}건` : ''}
          </span>
        </FlowStep>
        <FlowStep label="실행된 명령">
          {input.command ? (
            <>
              <code className="font-mono text-small break-all text-text-strong">{input.command.display}</code>
              <span className="text-caption text-text-muted">{input.command.recordedBy}</span>
            </>
          ) : (
            <span className="text-small text-text-muted">
              {input.tool ? `도구 ${input.tool} · 명령 기록 없음` : '도구·명령 기록 없음'}
            </span>
          )}
        </FlowStep>
        <FlowStep label="검색어">
          {input.queryTerms.length > 0 ? (
            <span className="flex flex-wrap gap-1">
              {input.queryTerms.map((term) => (
                <code key={term} className="rounded-sm bg-sunken px-1.5 font-mono text-caption text-text">
                  {term}
                </code>
              ))}
            </span>
          ) : (
            <span className="text-small text-text-muted">없음</span>
          )}
        </FlowStep>
        <FlowStep label="반환된 문서">
          <span className="text-small font-medium text-text-strong">{hits.length}건</span>
        </FlowStep>
        {agent ? (
          <FlowStep label="요청 입력에 포함">
            <span className="text-small font-medium text-text-strong">
              {hits.filter((hit) => hit.usage.inAgentInput).length}건
            </span>
          </FlowStep>
        ) : null}
      </ol>

      <div className="flex flex-col gap-4 p-4">
        {input.skipped.length > 0 ? (
          <ul className="flex flex-col gap-1">
            {input.skipped.map((skip) => (
              <li key={skip.corpus} className="text-caption text-text-muted">
                {CORPUS_LABEL[skip.corpus] ?? skip.corpus} 검색 안 함 — {skip.reason}
              </li>
            ))}
          </ul>
        ) : null}

        {groups
          .filter((group) => group.hits.length > 0)
          .map((group) => (
            <div key={group.relation} className="flex flex-col gap-2">
              <h4 className="text-small font-medium text-text-strong">
                {RELATION_LABEL[group.relation] ?? '기타 위치'}
                <span className="ml-2 font-normal text-text-muted">{group.hits.length}건</span>
              </h4>
              <ul className="flex flex-col gap-2">
                {group.hits.map((hit) => (
                  <HitRow key={`${hit.corpus}-${hit.rank}`} hit={hit} agent={agent} />
                ))}
              </ul>
            </div>
          ))}

        {hits.length > 0 ? (
          <p className="text-caption text-text-muted">
            매뉴얼 구간의 관계는 목차상 위치입니다. 이 Run의 원인이라는 뜻이 아닙니다.
          </p>
        ) : null}
      </div>
    </article>
  )
}

function FlowStep({
  label,
  first = false,
  children,
}: {
  label: string
  first?: boolean
  children: ReactNode
}) {
  return (
    <li className="flex min-w-0 flex-col gap-1 lg:flex-1 lg:flex-row lg:gap-2">
      {first ? null : (
        <span aria-hidden="true" className="flex justify-center text-text-muted lg:items-center lg:pt-5">
          <ArrowDown size={14} strokeWidth={1.5} className="lg:hidden" />
          <ArrowRight size={14} strokeWidth={1.5} className="hidden lg:block" />
        </span>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-1 rounded-sm bg-sunken px-3 py-2">
        <span className="text-caption text-text-muted">{label}</span>
        {children}
      </div>
    </li>
  )
}

function HitRow({ hit, agent }: { hit: DocSearchHit; agent: AgentRequest | null }) {
  return (
    <li className="flex flex-col gap-1.5 border-t border-border-subtle pt-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="font-mono text-caption text-text-muted">#{hit.rank}</span>
        <span className="text-small text-text">{hit.sourceTitle}</span>
        <span className="text-caption text-text-muted">
          {hit.matchedBy.map((m) => MATCHED_BY_LABEL[m] ?? m).join(' + ')}
        </span>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption text-text-muted">
        {hit.sourceUrl ? (
          <a
            href={hit.sourceUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex min-w-0 items-center gap-1 break-all text-text underline decoration-border-strong underline-offset-2 hover:decoration-text"
          >
            {hit.location}
            <ExternalLink size={12} strokeWidth={1.5} aria-hidden="true" className="flex-none" />
          </a>
        ) : (
          <span className="break-all">{hit.location}</span>
        )}
        {hit.version ? <span>{hit.version}</span> : null}
        {hit.checkedOn ? <span>확인일 {hit.checkedOn}</span> : null}
        <code className="font-mono break-all">{hit.evidenceId}</code>
      </div>

      {hit.sourceMatches === false ? (
        <p className="text-caption text-status-warning-fg">
          검색 이후 자료가 바뀌었습니다. 아래 본문은 검색 당시와 다를 수 있습니다.
        </p>
      ) : hit.sourceMatches === null ? (
        <p className="text-caption text-text-muted">
          이 서버에 해당 자료가 없어 본문을 표시할 수 없습니다.
        </p>
      ) : null}

      {hit.excerpt ? (
        <details className="group">
          <summary className="cursor-pointer text-caption text-text-muted hover:text-text">
            본문 보기
          </summary>
          <pre className="mt-1 max-h-64 overflow-auto rounded-sm bg-sunken px-2 py-1 font-mono text-caption break-words whitespace-pre-wrap text-text">
            {hit.excerpt}
          </pre>
        </details>
      ) : null}

      {hit.note ? <p className="text-caption text-text">{hit.note}</p> : null}
      {hit.limits ? (
        <p className="text-caption text-text-muted">이 Run에 대해 알려주지 않는 것: {hit.limits}</p>
      ) : null}

      {hit.usage.selectedForAgent === false && hit.usage.selectionReason ? (
        <p className="text-caption text-text-muted">
          Agent 입력에서 제외: {hit.usage.selectionReason}
        </p>
      ) : null}

      <UsageLine usage={hit.usage} agent={agent} />
    </li>
  )
}

function UsageLine({
  usage,
  agent,
}: {
  usage: DocSearchHit['usage']
  agent: AgentRequest | null
}) {
  const state = (value: boolean | null) => (value === null ? '기록 없음' : value ? '예' : '아니오')
  // 요청이 있었는데 인용이 null이면 "답변이 없거나 거부되어 확인할 수 없음"이다.
  const cited =
    usage.citedInAnswer === null
      ? agent
        ? '확인 불가'
        : '기록 없음'
      : usage.citedInAnswer
        ? '확인됨'
        : '아니오'
  const rows: [string, string, boolean][] = [
    ['검색 결과에 나타남', usage.returnedBySearch ? '예' : '아니오', true],
    ['Agent 입력 후보', state(usage.selectedForAgent), usage.selectedForAgent === true],
    ['요청 입력에 포함', state(usage.inAgentInput), usage.inAgentInput === true],
    ['모델이 읽음', state(usage.readByModel), false],
    ['답변 인용', cited, usage.citedInAnswer === true],
  ]
  return (
    <dl className="flex flex-wrap gap-x-3 gap-y-0.5 text-caption text-text-muted">
      {rows.map(([label, value, strong]) => (
        <div key={label} className="flex gap-1">
          <dt>{label}</dt>
          <dd className={strong ? 'font-medium text-text' : undefined}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

const OUTCOME_LABEL: Record<string, string> = {
  answerServed: '답변이 모든 검사를 통과해 제공됨',
  answerRejected: '답변이 왔지만 검사에서 거부됨',
  noAnswer: '사용할 수 있는 답변이 오지 않음',
}

/** AI 설명 요청이 만든 검색: 그 요청에서 문서가 어디까지 갔는지(C). 저장된 값만. */
function RequestTrace({ run }: { run: DocSearchRun }) {
  if (run.purpose !== 'agentRequest') return null
  const agent = run.agentRequest
  if (!agent) {
    return (
      <MessageBlock tone="warning" title="요청 기록과 연결되지 않은 검색">
        AI 설명 요청이 입력을 만들려고 한 검색이지만 요청 기록이 저장되지 않아, 어떤
        문서가 요청에 들어갔는지 확인할 수 없습니다.
      </MessageBlock>
    )
  }
  const time = formatTimestamp(agent.requestedAt)
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-surface p-4">
      <h3 className="text-small font-medium text-text-strong">
        AI 설명 요청에서의 사용 기록
        {time ? (
          <time
            dateTime={agent.requestedAt}
            title={time.full}
            className="ml-2 font-normal text-text-muted"
          >
            {time.display}
          </time>
        ) : null}
      </h3>
      <ol
        aria-label="요청 이력"
        className="flex flex-col items-stretch gap-1 lg:flex-row lg:items-start lg:gap-2"
      >
        <FlowStep label="문서 검색" first>
          <span className="text-small text-text-strong">반환 {run.resultCount}건</span>
        </FlowStep>
        <FlowStep label="Agent 입력 후보">
          <span className="text-small text-text-strong">{agent.candidateCount}건</span>
          <span className="text-caption text-text-muted">
            실행 명령의 매뉴얼 절 · 원인 종류 등록 발췌
          </span>
        </FlowStep>
        <FlowStep label="요청 입력 구성">
          <span className="text-small text-text-strong">{agent.inPayloadCount}건 포함</span>
        </FlowStep>
        <FlowStep label="모델 응답">
          <span className="text-small text-text-strong">
            {OUTCOME_LABEL[agent.outcome] ?? agent.outcome}
          </span>
          {agent.errorCategory ? (
            <code className="font-mono text-caption break-all text-text-muted">
              {agent.errorCategory}
            </code>
          ) : null}
        </FlowStep>
        <FlowStep label="인용 검증">
          <span className="text-small text-text-strong">
            {agent.citedCount === null ? '확인 불가' : `검증된 인용 ${agent.citedCount}건`}
          </span>
          {agent.citedCount === null ? (
            <span className="text-caption text-text-muted">
              제공된 답변이 없어 인용을 확인하지 않음
            </span>
          ) : null}
        </FlowStep>
      </ol>
      <p className="text-caption text-text-muted">
        &quot;요청 입력 구성&quot;은 서버가 만든 요청에 들어갔다는 뜻이며, 모델이 읽었다는
        기록은 아닙니다. 인용은 모든 검사를 통과해 제공된 답변에서만 확인합니다.
      </p>
    </div>
  )
}

function CorporaList({ corpora, method }: { corpora: DocCorpus[]; method: string }) {
  return (
    <details className="rounded-md border border-border bg-surface p-4">
      <summary className="cursor-pointer text-small font-medium text-text-strong">
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

function TraceList({
  runs,
  selectedId,
  onSelect,
}: {
  runs: DocSearchRun[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <details className="rounded-md border border-border bg-surface p-4">
      <summary className="cursor-pointer text-small font-medium text-text-strong">
        검색 기록 {runs.length}건
      </summary>
      <ul className="mt-3 flex flex-col gap-1">
        {runs.map((run) => {
          const time = formatTimestamp(run.createdAt)
          const selected = run.searchId === selectedId
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
                <time dateTime={run.createdAt} title={time?.full}>
                  {time?.display ?? run.createdAt}
                </time>
                <span>입력 {run.inputs.length}</span>
                <span>문서 {run.resultCount}</span>
                {run.durationMs !== null ? <span>{run.durationMs}ms</span> : null}
                <span>
                  {run.purpose === 'agentRequest' ? 'AI 설명 요청이 만든 검색' : 'Run 상세에서 요청한 검색'}
                </span>
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
