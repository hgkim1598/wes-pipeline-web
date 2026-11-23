import { ArrowRight, BookOpen, FileText, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { SourceMark } from '@/components/ui/SourceMark'
import type { DocSearchRun } from '@/features/run-detail/api'
import { stageCounts } from '@/features/run-detail/docWorkspace'
import { formatTimestamp } from '@/features/runs/time'
import { cx } from '@/lib/cx'

/*
  개요 탭 오른쪽 열(2026-11-23 발표용 정리, ref 다크 시안의 오른쪽 열).

  시안의 오른쪽 열은 공식 문서 · 지식 그래프 · Agent 실행 trace였다. 이 화면은
  **이미 있는 기록만** 요약한다.

    공식 문서   GET /doc-search 기록(모델 호출 없음). 가장 최근 검색의 건수와
                상위 문서 몇 개. 검색하지 않았으면 그렇다고 말한다.
    AI 설명     이 화면에서 받은 응답만(useRunSynthesis). 설명은 서버에 저장되지
                않으므로 "요청하지 않음"과 "요청했지만 다른 화면에서"를 구분할
                수 없다 — 이 화면에서 받은 것이 없으면 요청 전으로 표시한다.

  지식 그래프와 실행 trace 요약은 만들지 않는다. 그래프는 backend가 주는 구조가
  없고, trace는 AI 설명 탭이 응답과 함께 보여 준다.
*/

export interface OverviewRailProps {
  runPath: string
  docRuns: DocSearchRun[] | undefined
  docPending: boolean
  ai: { state: 'none' | 'pending' | 'served' | 'unavailable' | 'error' }
}

const SHOWN_DOCS = 3

export function OverviewRail({ runPath, docRuns, docPending, ai }: OverviewRailProps) {
  const latest = docRuns?.[0]
  const counts = latest ? stageCounts(latest.hits) : null
  const time = latest ? formatTimestamp(latest.createdAt) : null
  return (
    <div className="flex flex-col gap-6">
      <RailCard
        headingId="overview-docs-heading"
        icon={<BookOpen size={16} strokeWidth={1.5} />}
        title="공식 문서"
        mark={<SourceMark kind="doc" />}
        footer={
          <RailLink to={`${runPath}/docs`}>
            {latest ? '공식 문서 탭에서 근거 흐름 보기' : '공식 문서 탭에서 검색하기'}
          </RailLink>
        }
      >
        {docPending ? (
          <p className="text-small text-text-muted">검색 기록을 불러오는 중입니다.</p>
        ) : !latest ? (
          <p className="text-small text-text">
            이 Run으로 공식 문서를 검색한 기록이 없습니다. 검색은 기록된 실패의 도구·명령으로
            서버의 공식 문서 자료를 찾으며 모델을 호출하지 않습니다.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-border-subtle bg-border-subtle">
              <Stat term="반환 문서" value={`${latest.resultCount}건`} />
              <Stat term="요청 입력 포함" value={counts?.input === null || !counts ? '기록 없음' : `${counts.input}건`} />
              <Stat term="답변 인용" value={counts?.cited === null || !counts ? '기록 없음' : `${counts.cited}건`} />
            </dl>
            {latest.hits.length > 0 ? (
              <ul className="flex flex-col divide-y divide-border-subtle rounded-md border border-border">
                {latest.hits.slice(0, SHOWN_DOCS).map((hit) => (
                  <li key={`${hit.inputId}-${hit.evidenceId}-${hit.rank}`}>
                    <Link
                      to={`${runPath}/docs?search=${encodeURIComponent(latest.searchId)}&doc=${encodeURIComponent(hit.evidenceId)}`}
                      className="flex min-h-12 items-start gap-2.5 px-3 py-2.5 no-underline hover:bg-sunken hover:no-underline"
                    >
                      <FileText size={15} strokeWidth={1.5} aria-hidden="true" className="mt-0.5 flex-none text-text-muted" />
                      <span className="flex min-w-0 flex-col">
                        <span className="line-clamp-2 text-small font-medium text-text-strong">{hit.sourceTitle}</span>
                        <span className="truncate text-caption text-text-muted">{hit.location}</span>
                      </span>
                      <span
                        className={cx(
                          'ml-auto flex-none rounded-sm px-1.5 py-0.5 text-caption',
                          hit.usage.citedInAnswer
                            ? 'bg-ai-bg text-ai-fg'
                            : hit.usage.inAgentInput
                              ? 'bg-status-info-bg text-status-info-fg'
                              : 'bg-sunken text-text-muted',
                        )}
                      >
                        {hit.usage.citedInAnswer ? '답변 인용' : hit.usage.inAgentInput ? '요청 입력' : '검색 결과'}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-small text-text">이 검색은 반환된 문서가 없습니다.</p>
            )}
            <p className="text-caption text-text-muted">
              최근 검색{' '}
              <time dateTime={latest.createdAt} title={time?.full}>
                {time?.display ?? latest.createdAt}
              </time>
              {latest.hits.length > SHOWN_DOCS ? ` · 외 ${latest.hits.length - SHOWN_DOCS}건` : ''}
            </p>
          </>
        )}
      </RailCard>

      <RailCard
        headingId="overview-ai-heading"
        icon={<Sparkles size={16} strokeWidth={1.5} className="text-ai-fg" />}
        title="AI 설명"
        mark={<SourceMark kind="ai" />}
        footer={<RailLink to={`${runPath}/ai`}>AI 설명 탭으로</RailLink>}
      >
        <p className="text-body font-medium text-text-strong">{AI_STATE_TITLE[ai.state]}</p>
        <p className="text-small text-text">
          AI 설명은 요청할 때만 Claude를 호출해 만들고, 근거 검사를 통과한 응답만
          표시합니다. 문장마다 근거로 삼은 실행 기록이나 공식 문서를 함께 볼 수 있습니다.
        </p>
      </RailCard>
    </div>
  )
}

const AI_STATE_TITLE: Record<OverviewRailProps['ai']['state'], string> = {
  none: '이 화면에서 요청하지 않았습니다',
  pending: '설명을 만드는 중입니다',
  served: '이 화면에서 받은 설명이 있습니다',
  unavailable: '설명을 제공하지 못했습니다',
  error: '요청이 실패했습니다',
}

function RailCard({
  headingId,
  icon,
  title,
  mark,
  footer,
  children,
}: {
  headingId: string
  icon: ReactNode
  title: string
  mark?: ReactNode
  footer?: ReactNode
  children: ReactNode
}) {
  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-5 shadow-card"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className="text-text-muted">
          {icon}
        </span>
        <h2 id={headingId} className="text-body font-semibold text-text-strong">
          {title}
        </h2>
        {mark}
      </div>
      {children}
      {footer ? <div className="border-t border-border-subtle pt-3">{footer}</div> : null}
    </section>
  )
}

function Stat({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col bg-surface px-3 py-2">
      <dt className="truncate text-caption text-text-muted">{term}</dt>
      <dd className="truncate text-body font-semibold text-text-strong">{value}</dd>
    </div>
  )
}

function RailLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex min-h-6 items-center gap-1 text-small font-medium text-brand no-underline hover:underline"
    >
      {children}
      <ArrowRight size={14} strokeWidth={1.5} aria-hidden="true" />
    </Link>
  )
}
