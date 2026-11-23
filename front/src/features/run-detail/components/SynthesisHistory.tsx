import { useState } from 'react'
import { History, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import type { StoredAnswer, StoredAnswerSummary, StoredDocEvidence } from '@/features/run-detail/api'
import type { RunSynthesisState } from '@/features/run-detail/useRunSynthesis'
import { formatTimestamp } from '@/features/runs/time'
import { cx } from '@/lib/cx'

/*
  저장된 AI 설명의 기록과 출처 (개발판단기록 66장).

  보이는 것은 전부 서버가 준 값이다(GET /synthesis/answers[/{version}]).

    - 지금 보는 설명이 방금 받은 것인지, 저장된 몇 번째 버전인지
    - 버전마다 시각 · 모델 · 삭제 여부 · 기록이 바뀌었는지
    - 그 요청에 넣은 공식 문서와, 답변이 실제로 인용한 문서
      (검색됨 ≠ 요청에 포함됨 ≠ 인용됨. 모델이 읽었는지는 기록되지 않는다)
    - 게이트 통과가 무엇을 확인한 것이고 무엇을 확인하지 않은 것인지

  삭제는 본문만 지운다. 번호와 생성 기록, 입력 해시는 남는다. 누르면 바로
  지우지 않고 한 번 더 묻는다.
*/

export function SynthesisHistory({ synthesis }: { synthesis: RunSynthesisState }) {
  const { history, source, result } = synthesis
  const list = history.list
  const versions = list?.versions ?? []

  if (!list) return null

  if (versions.length === 0) {
    // 저장이 꺼진 서버에서 설명을 받았을 때만 알린다. 받기 전에는 할 말이 없다.
    if (!list.storing && result?.available) {
      return (
        <p className="text-caption text-text-muted">
          이 서버는 AI 설명을 저장하지 않습니다. 이 화면을 새로 열면 지금 설명은
          사라집니다.
        </p>
      )
    }
    return null
  }

  const viewing = history.viewing
  const viewingSummary = versions.find((v) => v.version === history.viewingVersion)
  const freshNotStored = source === 'fresh' && history.viewingVersion === null
  const freshFailed = result !== undefined && !result.available

  return (
    <section
      aria-labelledby="synthesis-history-heading"
      className="flex flex-col gap-3 rounded-sm border border-border-subtle bg-sunken/40 p-3"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3
          id="synthesis-history-heading"
          className="flex items-center gap-1.5 text-small font-medium text-text-strong"
        >
          <History size={14} strokeWidth={1.5} aria-hidden="true" />
          설명 기록
        </h3>
        <p className="text-caption text-text-muted">
          {freshFailed
            ? '이번 요청은 설명을 만들지 못했습니다. 저장된 버전을 고르면 그 설명을 봅니다.'
            : viewingLabel(source, history.viewingVersion, list.latestVersion, freshNotStored)}
        </p>
      </div>

      {viewingSummary ? <ViewingNotes summary={viewingSummary} answer={viewing} /> : null}

      <VersionList
        versions={versions}
        latest={list.latestVersion}
        viewingVersion={history.viewingVersion}
        selectedVersion={history.selectedVersion}
        onSelect={history.select}
      />

      {viewing ? <DocRelations answer={viewing} /> : null}

      {viewing && !viewing.deleted ? (
        <DeleteVersion
          version={viewing.version}
          removing={history.removing === viewing.version}
          onDelete={() => history.remove(viewing.version)}
        />
      ) : null}
      {history.removeError ? (
        <p role="alert" className="text-caption text-status-failure-fg">
          버전을 삭제하지 못했습니다. 잠시 뒤 다시 시도하세요.
        </p>
      ) : null}

      <p className="text-caption text-text-muted">
        저장된 설명은 안전 검사를 통과한 것만입니다. 통과는 인용한 근거 id가 실제로
        모델 입력에 있었고 수치·식별자 검사를 넘었다는 뜻이며, 문장 내용이 옳다는
        검증은 아닙니다. 요약 문장에는 근거 id가 없습니다.
      </p>
    </section>
  )
}

function viewingLabel(
  source: RunSynthesisState['source'],
  version: number | null,
  latest: number | null,
  freshNotStored: boolean,
): string {
  if (freshNotStored) return '방금 받은 설명은 저장되지 않았습니다. 아래는 이전에 저장된 버전입니다.'
  if (version === null) return '버전을 고르면 그 설명을 봅니다.'
  const latestMark = version === latest ? ' (최신)' : ''
  return source === 'fresh'
    ? `방금 받은 설명 · v${version}${latestMark}로 저장됨`
    : `보는 중: 저장된 설명 v${version}${latestMark}`
}

/** 지금 보는 버전에 대해 알아야 할 것. 해당할 때만 보인다. */
function ViewingNotes({
  summary,
  answer,
}: {
  summary: StoredAnswerSummary
  answer: StoredAnswer | undefined
}) {
  return (
    <>
      {summary.deleted ? (
        <MessageBlock tone="info" title={`v${summary.version}의 본문은 삭제됐습니다`}>
          <p>번호, 생성 시각, 모델과 입력 해시만 남아 있습니다.</p>
        </MessageBlock>
      ) : null}
      {summary.recordChanged === true ? (
        <MessageBlock tone="warning" title="이 설명 이후 Run 기록이 바뀌었습니다">
          <p>
            v{summary.version}은 생성 당시의 기록을 근거로 합니다. 지금 화면의 진단·단계
            표와 다를 수 있습니다. 다시 생성하면 지금 기록으로 새 버전을 만듭니다.
          </p>
        </MessageBlock>
      ) : null}
      {summary.recordChanged === null ? (
        <p className="text-caption text-text-muted">
          지금 Run 기록을 읽지 못해, 이 설명 이후 기록이 바뀌었는지 확인하지 못했습니다.
        </p>
      ) : null}
      {summary.inputChangedFromPrevious === true && summary.supersedesVersion !== null ? (
        <p className="text-caption text-text-muted">
          v{summary.supersedesVersion}과 모델 입력이 다릅니다(입력 {summary.inputDigest}). 함께 보낸
          공식 문서나 기록 정리 방식이 달라졌을 수 있습니다.
        </p>
      ) : null}
      {answer && answer.citationsOutsidePayload.length > 0 ? (
        <MessageBlock tone="danger" title="요청에 넣지 않은 문서를 인용한 기록입니다">
          <p>
            이 버전은 근거 검사와 맞지 않아 신뢰하지 마세요:{' '}
            {answer.citationsOutsidePayload.join(', ')}
          </p>
        </MessageBlock>
      ) : null}
    </>
  )
}

function VersionList({
  versions,
  latest,
  viewingVersion,
  selectedVersion,
  onSelect,
}: {
  versions: StoredAnswerSummary[]
  latest: number | null
  viewingVersion: number | null
  selectedVersion: number | null
  onSelect: (version: number | null) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      <ol aria-label="저장된 버전" className="flex flex-col divide-y divide-border-subtle">
        {versions.map((v) => {
          const created = formatTimestamp(v.createdAt)
          const current = v.version === viewingVersion
          return (
            <li key={v.version} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
              <button
                type="button"
                aria-pressed={current}
                onClick={() => onSelect(v.version)}
                className={cx(
                  'inline-flex min-h-6 items-center rounded-sm border px-2 text-small font-medium tabular-nums',
                  current
                    ? 'border-brand text-text-strong'
                    : 'border-border text-text hover:bg-surface',
                )}
              >
                v{v.version}
              </button>
              <span className="text-caption text-text-muted tabular-nums">
                {created ? <time dateTime={created.machine}>{created.full}</time> : v.createdAt}
              </span>
              <span className="text-caption text-text-muted">{v.models.join(', ') || '모델 미상'}</span>
              {v.version === latest ? <Tag>최신</Tag> : null}
              {v.deleted ? <Tag>본문 삭제됨</Tag> : null}
              {v.recordChanged ? <Tag tone="warning">기록 바뀜</Tag> : null}
              {v.docSearchLinked ? <Tag>공식 문서 포함</Tag> : null}
            </li>
          )
        })}
      </ol>
      {selectedVersion !== null ? (
        <button
          type="button"
          onClick={() => onSelect(null)}
          className="self-start text-caption text-brand underline-offset-2 hover:underline"
        >
          기본 보기로 돌아가기(방금 받은 설명, 없으면 최신 버전)
        </button>
      ) : null}
    </div>
  )
}

function Tag({ children, tone }: { children: string; tone?: 'warning' }) {
  return (
    <span
      className={cx(
        'rounded-sm border px-1.5 text-caption',
        tone === 'warning'
          ? 'border-status-warning-bd bg-status-warning-bg text-status-warning-fg'
          : 'border-border-subtle text-text-muted',
      )}
    >
      {children}
    </span>
  )
}

function yesNo(value: boolean | null): string {
  if (value === null) return '확인 안 됨'
  return value ? '예' : '아니오'
}

/** 이 버전의 요청에 실린 공식 문서와 인용 관계. */
function DocRelations({ answer }: { answer: StoredAnswer }) {
  if (!answer.docSearchLinked && answer.docEvidence.length === 0) {
    return (
      <p className="text-caption text-text-muted">
        이 요청에는 공식 문서를 넣지 않았습니다. 근거는 이 Run의 기록뿐입니다.
      </p>
    )
  }
  if (answer.docEvidence.length === 0) {
    return (
      <p className="text-caption text-text-muted">
        공식 문서 검색과 연결됐지만 요청에 넣을 문서가 없었습니다. 근거는 이 Run의 기록뿐입니다.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-1">
      <table className="w-full max-w-content text-left text-caption">
        <caption className="pb-1 text-left text-caption text-text-muted">
          이 요청의 공식 문서 — 검색됨 · 요청에 포함됨 · 답변이 인용함은 서로 다른 사실입니다.
          모델이 문서를 읽었는지는 기록되지 않습니다.
        </caption>
        <thead className="text-text-muted">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">문서</th>
            <th scope="col" className="py-1 pr-3 font-medium">후보로 선정</th>
            <th scope="col" className="py-1 pr-3 font-medium">요청에 포함</th>
            <th scope="col" className="py-1 font-medium">답변이 인용</th>
          </tr>
        </thead>
        <tbody>
          {answer.docEvidence.map((doc: StoredDocEvidence) => (
            <tr key={doc.evidenceId} className="border-t border-border-subtle">
              <td className="py-1 pr-3 text-text">
                {doc.title ?? doc.evidenceId}
                {doc.selectionReason ? (
                  <span className="block text-text-muted">{doc.selectionReason}</span>
                ) : null}
              </td>
              <td className="py-1 pr-3">{yesNo(doc.selected)}</td>
              <td className="py-1 pr-3">{yesNo(doc.inPayload)}</td>
              <td className="py-1">{yesNo(doc.cited)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DeleteVersion({
  version,
  removing,
  onDelete,
}: {
  version: number
  removing: boolean
  onDelete: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  if (!confirming) {
    return (
      <div>
        <Button type="button" variant="secondary" onClick={() => setConfirming(true)}>
          <Trash2 size={14} strokeWidth={1.5} aria-hidden="true" />v{version} 본문 삭제
        </Button>
      </div>
    )
  }
  return (
    <div role="group" aria-label={`v${version} 삭제 확인`} className="flex flex-wrap items-center gap-2">
      <p className="text-small text-text">
        v{version}의 설명 본문을 지웁니다. 번호와 생성 기록은 남고, 되돌릴 수 없습니다.
      </p>
      <Button
        type="button"
        variant="danger"
        disabled={removing}
        onClick={() => {
          onDelete()
          setConfirming(false)
        }}
      >
        {removing ? '삭제 중…' : '삭제'}
      </Button>
      <Button type="button" variant="secondary" onClick={() => setConfirming(false)}>
        취소
      </Button>
    </div>
  )
}
