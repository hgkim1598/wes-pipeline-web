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
  /*
    2026-11-23 UI 정리(개발판단기록 63장): 카드 두 장 → 한 면 두 구획. 검색이
    0건이면 세 칸 지표(0건 · 기록 없음 · 기록 없음)를 그리지 않고 문장 하나로
    말한다 — 비어 있는 값을 지표처럼 꾸미지 않는다. 오른쪽 열은 스크롤을 따라와
    본문 옆 빈 공간을 남기지 않는다(xl:sticky, RunDetailPage).
  */
  return (
    <aside
      aria-label="이 실행의 관련 기록"
      className="flex flex-col divide-y divide-border-subtle rounded-lg border border-border bg-surface shadow-card"
    >
      <RailBlock
        headingId="overview-docs-heading"
        icon={<BookOpen size={15} strokeWidth={1.5} />}
        title="공식 문서"
        footer={
          <RailLink to={`${runPath}/docs`}>
            {latest ? '근거 흐름 보기' : '공식 문서 탭에서 검색하기'}
          </RailLink>
        }
      >
        {docPending ? (
          <p className="text-small text-text-muted">검색 기록을 불러오는 중입니다.</p>
        ) : !latest ? (
          <p className="text-small text-text">
            이 Run으로 검색한 기록이 없습니다. 검색은 기록된 실패의 도구·명령으로 서버의 공식
            문서 자료를 찾으며 모델을 호출하지 않습니다.
          </p>
        ) : latest.resultCount === 0 ? (
          <p className="text-small text-text">
            최근 검색(
            <time dateTime={latest.createdAt} title={time?.full}>
              {time?.display ?? latest.createdAt}
            </time>
            )에서 반환된 문서가 없습니다.
          </p>
        ) : (
          <>
            <p className="text-small text-text">
              <span className="font-mono font-semibold text-text-strong">{latest.resultCount}</span>건 반환
              {counts && counts.input !== null ? (
                <>
                  <span className="px-1.5 text-ink-400">·</span>요청 입력{' '}
                  <span className="font-mono text-text-strong">{counts.input}</span>
                </>
              ) : null}
              {counts && counts.cited !== null ? (
                <>
                  <span className="px-1.5 text-ink-400">·</span>답변 인용{' '}
                  <span className="font-mono text-text-strong">{counts.cited}</span>
                </>
              ) : null}
            </p>
            <ul className="-mx-2 flex flex-col">
              {latest.hits.slice(0, SHOWN_DOCS).map((hit) => (
                <li key={`${hit.inputId}-${hit.evidenceId}-${hit.rank}`}>
                  <Link
                    to={`${runPath}/docs?search=${encodeURIComponent(latest.searchId)}&doc=${encodeURIComponent(hit.evidenceId)}`}
                    className="flex min-h-11 items-start gap-2.5 rounded-sm px-2 py-2 no-underline hover:bg-sunken hover:no-underline"
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
                            : 'text-text-muted',
                      )}
                    >
                      {hit.usage.citedInAnswer ? '답변 인용' : hit.usage.inAgentInput ? '요청 입력' : '검색 결과'}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <p className="text-caption text-text-muted">
              최근 검색{' '}
              <time dateTime={latest.createdAt} title={time?.full}>
                {time?.display ?? latest.createdAt}
              </time>
              {latest.hits.length > SHOWN_DOCS ? ` · 외 ${latest.hits.length - SHOWN_DOCS}건` : ''}
            </p>
          </>
        )}
      </RailBlock>

      <RailBlock
        headingId="overview-ai-heading"
        icon={<Sparkles size={15} strokeWidth={1.5} className="text-ai-fg" />}
        title="AI 설명"
        mark={<SourceMark kind="ai" />}
        footer={<RailLink to={`${runPath}/ai`}>AI 설명 탭으로</RailLink>}
      >
        <p className="text-small font-medium text-text-strong">{AI_STATE_TITLE[ai.state]}</p>
        <p className="text-small text-text-muted">
          요청할 때만 Claude를 호출하고, 근거 검사를 통과한 응답만 문장별 근거와 함께 표시합니다.
        </p>
      </RailBlock>
    </aside>
  )
}

const AI_STATE_TITLE: Record<OverviewRailProps['ai']['state'], string> = {
  none: '이 화면에서 요청하지 않았습니다',
  pending: '설명을 만드는 중입니다',
  served: '이 화면에서 받은 설명이 있습니다',
  unavailable: '설명을 제공하지 못했습니다',
  error: '요청이 실패했습니다',
}

function RailBlock({
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
    <section aria-labelledby={headingId} className="flex flex-col gap-3 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className="text-text-muted">
          {icon}
        </span>
        <h2 id={headingId} className="text-small font-semibold text-text-strong">
          {title}
        </h2>
        {mark}
      </div>
      {children}
      {footer ? <div>{footer}</div> : null}
    </section>
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
