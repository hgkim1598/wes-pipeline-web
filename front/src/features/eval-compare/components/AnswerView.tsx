import { SourceMark } from '@/components/ui/SourceMark'
import type { SourceKind } from '@/components/ui/SourceMark'
import { evidenceSourceOf } from '@/features/run-detail/evidenceSource'
import { cx } from '@/lib/cx'

import type { Answer, AnswerScores } from '../api'
import { SECTION_LABEL } from '../labels'

/*
  저장된 Claude 답변 하나를 읽기 전용으로 그린다(평가자 화면).

  자동 검출기에 걸린 문장은 표시만 한다 — 판정은 사람 채점이 한다.
  근거 id는 제품 화면과 같은 기준(evidenceSource.ts)으로 출처를 붙인다.
*/

const SECTIONS = ['importantFindings', 'limitations', 'nextChecks', 'uncertainties'] as const

const REF_KIND: Record<string, SourceKind | null> = {
  record: 'record',
  mixed: 'record',
  doc: 'doc',
  knowledge: 'knowledge',
  other: null,
}

export function RefChip({ evidenceRef }: { evidenceRef: string }) {
  const source = evidenceSourceOf(evidenceRef)
  const kind = REF_KIND[source]
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <code className="rounded-sm bg-sunken px-1 font-mono text-caption break-all text-text">{evidenceRef}</code>
      {kind ? (
        <SourceMark kind={kind}>{source === 'mixed' ? ' · 일반 설명 포함' : null}</SourceMark>
      ) : null}
    </span>
  )
}

export function AnswerView({ answer, scores }: { answer: Answer; scores: AnswerScores | null }) {
  const flagged = new Map<string, string[]>()
  for (const hit of scores?.detectorHits ?? []) {
    flagged.set(hit.where, [...(flagged.get(hit.where) ?? []), hit.detector])
  }
  for (const hit of scores?.wrongCauseCandidates ?? []) {
    flagged.set(hit.where, [...(flagged.get(hit.where) ?? []), hit.candidate])
  }
  return (
    <div className="flex flex-col gap-4">
      {answer.summary ? (
        <div className={cx('rounded-sm border border-border bg-surface p-3', flagged.has('summary') && 'border-status-warning-bd')}>
          <p className="text-caption font-semibold text-text-muted">요약 (주장 수에 넣지 않음)</p>
          <p className="mt-1 text-body text-text">{answer.summary}</p>
          <Flags ids={flagged.get('summary')} />
        </div>
      ) : null}
      {SECTIONS.map((section) => {
        const items = answer[section]
        if (!items.length) return null
        return (
          <section key={section} className="flex flex-col gap-2">
            <h4 className="text-small font-semibold text-text-strong">
              {SECTION_LABEL[section]} <span className="font-mono text-caption text-text-muted">{items.length}</span>
            </h4>
            <ol className="flex flex-col gap-2">
              {items.map((item, index) => {
                const where = `${section}.${index}`
                return (
                  <li
                    key={where}
                    className={cx(
                      'rounded-sm border border-border-subtle bg-surface p-3',
                      flagged.has(where) && 'border-status-warning-bd bg-status-warning-bg',
                    )}
                  >
                    <p className="text-body text-text">{item.statement}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.evidenceRefs.map((ref) => (
                        <RefChip key={ref} evidenceRef={ref} />
                      ))}
                    </div>
                    <Flags ids={flagged.get(where)} />
                  </li>
                )
              })}
            </ol>
          </section>
        )
      })}
    </div>
  )
}

function Flags({ ids }: { ids: string[] | undefined }) {
  if (!ids?.length) return null
  return (
    <p className="mt-2 text-caption text-status-warning-fg">
      자동 검출(고정 문형, 사람 확인 전): <span className="font-mono">{ids.join(', ')}</span>
    </p>
  )
}
