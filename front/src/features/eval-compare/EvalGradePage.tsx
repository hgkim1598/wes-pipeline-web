import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { SourceMark } from '@/components/ui/SourceMark'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { cx } from '@/lib/cx'
import { readGrader, writeGrader } from '@/lib/evalGrader'

import { saveGrade } from './api'
import type { Blind, ClaimGrade, Grade, GradeInput } from './api'
import { RefChip } from './components/AnswerView'
import { SECTION_LABEL } from './labels'
import { DisabledOrError, MockBanner, MockTag } from './EvalComparePage'
import { evalCompareKey, useBlind } from './queries'

/*
  블라인드 채점 — 어느 코드 경로의 답인지, Gate를 통과했는지, 얼마나 걸렸는지
  보이지 않는다(backend /blind가 그 값을 보내지 않는다). 답변 순서는 실험을
  만들 때 섞은 코드(X01…) 순서다.

  저장은 덧붙이기만 한다. 같은 답을 다시 저장하면 새 판이 생기고 비교 화면은
  가장 최근 판을 쓴다. 이전 판은 지워지지 않는다.
*/


const SOURCE_LABEL: Record<string, 'record' | 'doc' | 'knowledge'> = {
  record: 'record',
  doc: 'doc',
  knowledge: 'knowledge',
}

/** backend가 보내는 미완료 사유(api/eval_compare.py _completeness). */
const MISSING_LABEL: Record<string, string> = {
  claims: '판정 안 한 문장',
  requiredCauses: '선택 안 한 원인',
  understanding: '이해도 점수',
  usefulness: '유용성 점수',
  answer: '채점할 답변이 더 이상 없음',
}

export function EvalGradePage() {
  const { experimentId = '' } = useParams()
  const { data, error, isPending } = useBlind(experimentId)
  return (
    <main className="mx-auto flex max-w-app flex-col gap-8 px-4 py-8 md:px-6">
      <nav className="text-caption text-text-muted">
        <Link to="/eval/compare">비교 분석</Link> / <span className="font-mono">{experimentId}</span> / 블라인드 채점
      </nav>
      <h1 className="text-h1 font-semibold tracking-tight text-text-strong">블라인드 채점</h1>
      {isPending ? <p className="text-small text-text-muted">불러오는 중</p> : null}
      {error ? <DisabledOrError error={error} /> : null}
      {data ? <Grading blind={data} /> : null}
    </main>
  )
}

function Guide() {
  return (
    <details open className="rounded-md border border-border bg-surface p-4 text-small text-text">
      <summary className="cursor-pointer font-medium text-text-strong">채점 방법 (처음이면 읽어 주세요)</summary>
      <ol className="mt-3 flex list-decimal flex-col gap-2 pl-5">
        <li>
          답변 하나를 고르고, 문장(주장)마다 아래 <b>정답 사실표</b>와 대조합니다. 요약 문단은 채점하지 않습니다.
        </li>
        <li>
          <b>지지</b>: 사실표나 그 문장이 단 근거로 맞다고 확인됨. <b>모순</b>: 사실표와 반대됨.{' '}
          <b>판단 불가</b>: 기록으로 맞는지 틀린지 확인할 수 없음 — 확신이 없으면 이것을 고릅니다. 판단 불가는
          성공으로 세지 않습니다.
        </li>
        <li>
          <b>근거 출처</b>: 그 문장을 확인한 곳. <i>이 Run의 기록</i>만이 "이 실행에서 일어난 일"의 근거입니다.{' '}
          <i>공식 문서</i>·<i>등록된 지식</i>은 일반적인 설명의 근거입니다.
        </li>
        <li>
          <b>실행 안 된 단계의 결과를 말함</b>: 사실표에서 "실행 안 됨"인 단계의 결과나 동작을 있었던 일처럼 말함.
          예: 원본 품질 검사가 실행되지 않았는데 "개별 FastQC 결과는 그대로 있다".
        </li>
        <li>
          <b>실행 상태와 모순</b>: 단계의 상태를 다르게 말함(실패한 실행을 완료라고 하는 등).{' '}
          <b>근거 없는 원인 단정</b>: 기록에 없는 원인을 이 Run의 원인이라고 단정함.
        </li>
        <li>
          끝으로 필수 원인을 말했는지, 이해하기 쉬운지(1–5), 점검 방법이 실제로 쓸모 있는지(1–5)를 고릅니다.
        </li>
      </ol>
    </details>
  )
}

function FactTable({ blind }: { blind: Blind }) {
  return (
    <section aria-labelledby="facts" className="flex flex-col gap-3">
      <SectionHeader title={<span id="facts">정답 사실표</span>} meta="Run마다 · 출처 표시" />
      <div className="grid gap-4 lg:grid-cols-3">
        {blind.cases.map((c) => (
          <div key={c.case} className="flex flex-col gap-2 rounded-md border border-border bg-surface p-4 text-small">
            <p className="font-semibold text-text-strong">
              <span className="font-mono">{c.label}</span>{' '}
              <span className="text-caption font-normal text-text-muted">{c.synthetic ? '합성 Run' : '실제 Run'}</span>
            </p>
            <ul className="flex flex-col gap-1">
              {c.facts.steps.map((s) => (
                <li key={s.stepId} className="flex flex-wrap items-center gap-2">
                  <span className={cx(s.state.startsWith('notRun') ? 'text-text-muted' : 'text-text')}>{s.label}</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 font-medium text-text-strong">필수 원인</p>
            <ul className="flex flex-col gap-1">
              {c.facts.requiredCauses.map((cause) => (
                <li key={cause.id} className="flex flex-wrap items-center gap-2">
                  <span className="text-text">{cause.label}</span>
                  {SOURCE_LABEL[cause.source] ? <SourceMark kind={SOURCE_LABEL[cause.source]} /> : null}
                </li>
              ))}
            </ul>
            {c.facts.notes.length ? (
              <ul className="mt-1 flex flex-col gap-1">
                {c.facts.notes.map((n) => (
                  <li key={n.text} className="flex flex-wrap items-center gap-2 text-caption text-text-muted">
                    {n.text}
                    {SOURCE_LABEL[n.source] ? <SourceMark kind={SOURCE_LABEL[n.source]} /> : null}
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="text-caption text-text-muted">
              단계 상태의 출처: <SourceMark kind="record" />
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}

function Grading({ blind }: { blind: Blind }) {
  const [code, setCode] = useState<string | null>(blind.answers[0]?.code ?? null)
  const answer = blind.answers.find((a) => a.code === code) ?? null
  // 완료(backend의 complete)만 채점됨으로 센다. 미완료는 따로 보인다(H2).
  const graded = blind.answers.filter((a) => blind.grades[a.code]?.complete === true).length
  const incomplete = blind.answers.filter((a) => blind.grades[a.code] && blind.grades[a.code].complete !== true).length
  return (
    <>
      {blind.mock ? <MockBanner /> : null}
      {blind.unblinded ? (
        <MessageBlock tone="warning" title="블라인드가 이미 해제됐습니다">
          지금부터 저장하는 채점은 어느 경로의 답인지 볼 수 있는 상태에서 한 것으로 기록되고, 비교 화면에
          비블라인드 채점으로 따로 표시됩니다.
        </MessageBlock>
      ) : (
        <MessageBlock tone="info">
          어느 코드 경로의 답인지, 검증 Gate를 통과했는지, 응답 시간은 이 화면에 나오지 않습니다. 비교 화면도
          블라인드를 해제하기 전에는 답변 원문을 보이지 않습니다. 채점을 모두 마친 뒤에 해제하세요. 답변은 같은
          사례·반복의 두 경로가 모두 채점할 답을 받은 뒤에 둘이 함께 나옵니다. 한쪽만 답을 받았거나 아직 실행 중이면
          그 짝은 해제 뒤에 채점합니다
          {blind.heldUntilUnblind ? ` (지금 ${blind.heldUntilUnblind}건)` : ''}. 어느 답이 언제 나타나는지로 경로를
          짐작할 수 없게 하려는 규칙입니다.
        </MessageBlock>
      )}
      <Guide />
      <FactTable blind={blind} />
      <section aria-labelledby="answers" className="flex flex-col gap-3">
        <SectionHeader
          title={
            <span id="answers" className="inline-flex flex-wrap items-center gap-2">
              답변 <MockTag mock={blind.mock} />
            </span>
          }
          meta={`채점 완료 ${graded}/${blind.answers.length}${incomplete ? ` · 미완료 ${incomplete}` : ''}`}
        />
        <div className="flex flex-wrap gap-2" role="group" aria-label="답변 선택">
          {blind.answers.map((a) => (
            <button
              key={a.code}
              type="button"
              aria-pressed={a.code === code}
              onClick={() => setCode(a.code)}
              className={cx(
                'inline-flex min-h-9 items-center gap-1.5 rounded-sm border px-2.5 text-small',
                a.code === code ? 'border-brand bg-brand-selected text-text-strong' : 'border-border bg-surface text-text',
              )}
            >
              <span className="font-mono">{a.code}</span>
              <span className="text-caption text-text-muted">{a.caseLabel}</span>
              {blind.grades[a.code]?.complete === true ? (
                <StatusBadge tone="success" size="sm">채점 완료</StatusBadge>
              ) : blind.grades[a.code] ? (
                <StatusBadge tone="warning" size="sm">미완료</StatusBadge>
              ) : null}
            </button>
          ))}
        </div>
        {blind.answers.length === 0 ? (
          <p className="text-small text-text-muted">채점할 답변이 아직 없습니다.</p>
        ) : null}
        {answer ? (
          <GradeForm
            key={`${answer.code}-${blind.grades[answer.code]?.savedAt ?? 'new'}`}
            experimentId={blind.experimentId}
            answer={answer}
            causes={blind.cases.find((c) => c.case === answer.case)?.facts.requiredCauses ?? []}
            previous={blind.grades[answer.code]}
          />
        ) : null}
      </section>
    </>
  )
}

type Answer = Blind['answers'][number]

function initialClaims(answer: Answer, previous: Grade | undefined): ClaimGrade[] {
  return answer.claims.map((c) => {
    const old = previous?.claims.find((p) => p.section === c.section && p.index === c.index)
    return (
      old ?? {
        section: c.section,
        index: c.index,
        verdict: null,
        source: null,
        nonRunClaim: false,
        execContradiction: false,
        unsupportedCause: false,
      }
    )
  })
}

function GradeForm({
  experimentId,
  answer,
  causes,
  previous,
}: {
  experimentId: string
  answer: Answer
  causes: { id: string; label: string }[]
  previous: Grade | undefined
}) {
  const client = useQueryClient()
  const [grader, setGrader] = useState(previous?.grader ?? readGrader())
  const [claims, setClaims] = useState<ClaimGrade[]>(() => initialClaims(answer, previous))
  const [required, setRequired] = useState<Record<string, boolean | null>>(
    () => Object.fromEntries(causes.map((c) => [c.id, previous?.requiredCauses[c.id] ?? null])),
  )
  const [understanding, setUnderstanding] = useState<number | null>(previous?.understanding ?? null)
  const [usefulness, setUsefulness] = useState<number | null>(previous?.usefulness ?? null)
  const [notes, setNotes] = useState(previous?.notes ?? '')

  const mutation = useMutation({
    mutationFn: (input: GradeInput) => saveGrade(experimentId, answer.code, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: evalCompareKey })
    },
  })

  const update = (i: number, patch: Partial<ClaimGrade>) =>
    setClaims((all) => all.map((c, k) => (k === i ? { ...c, ...patch } : c)))

  const verdictCount = claims.filter((c) => c.verdict !== null).length

  return (
    <form
      className="flex flex-col gap-5 rounded-md border border-border bg-paper p-4"
      onSubmit={(e) => {
        e.preventDefault()
        writeGrader(grader)
        mutation.mutate({ grader, claims, requiredCauses: required, understanding, usefulness, notes })
      }}
    >
      <header className="flex flex-col gap-1">
        <h3 className="text-h3 font-semibold text-text-strong">
          <span className="font-mono">{answer.code}</span> · {answer.caseLabel}
        </h3>
        {answer.summary ? <p className="text-body text-text">{answer.summary}</p> : null}
        <p className="text-caption text-text-muted">
          주장 {answer.claims.length}개 중 {verdictCount}개 판정
          {previous ? ` · 저장된 판 ${previous.versions ?? 1}개 (가장 최근 판을 불러왔습니다)` : ''}
          {previous && previous.complete !== true
            ? ` · 저장된 판은 미완료라 채점 완료로 세지 않습니다(빠진 것: ${(previous.missing ?? []).map((m) => MISSING_LABEL[m] ?? m).join(', ') || '확인 필요'})`
            : ''}
        </p>
      </header>

      <ol className="flex flex-col gap-3">
        {answer.claims.map((claim, i) => {
          const g = claims[i]
          return (
            <li key={`${claim.section}.${claim.index}`} className="flex flex-col gap-2 rounded-sm border border-border-subtle bg-surface p-3">
              <p className="text-caption text-text-muted">
                {SECTION_LABEL[claim.section] ?? claim.section} {claim.index + 1}
              </p>
              <p className="text-body text-text">{claim.statement}</p>
              <div className="flex flex-wrap gap-2">
                {claim.evidenceRefs.map((ref) => (
                  <RefChip key={ref} evidenceRef={ref} />
                ))}
              </div>
              <fieldset className="flex flex-wrap items-center gap-3 text-small">
                <legend className="sr-only">판정</legend>
                {(
                  [
                    ['supported', '지지'],
                    ['contradicted', '모순'],
                    ['undetermined', '판단 불가'],
                  ] as const
                ).map(([v, label]) => (
                  <label key={v} className="inline-flex min-h-8 items-center gap-1.5">
                    <input
                      type="radio"
                      name={`v-${answer.code}-${i}`}
                      checked={g.verdict === v}
                      onChange={() => update(i, { verdict: v })}
                    />
                    {label}
                  </label>
                ))}
                <label className="inline-flex min-h-8 items-center gap-1.5">
                  근거 출처
                  <select
                    value={g.source ?? ''}
                    onChange={(e) => update(i, { source: (e.target.value || null) as ClaimGrade['source'] })}
                    className="min-h-8 rounded-sm border border-border bg-surface px-1"
                  >
                    <option value="">선택 안 함</option>
                    <option value="record">이 Run의 기록</option>
                    <option value="doc">공식 문서</option>
                    <option value="knowledge">등록된 지식</option>
                    <option value="none">근거 없음</option>
                  </select>
                </label>
              </fieldset>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-small">
                {(
                  [
                    ['nonRunClaim', '실행 안 된 단계의 결과를 말함'],
                    ['execContradiction', '실행 상태와 모순'],
                    ['unsupportedCause', '근거 없는 원인 단정'],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="inline-flex min-h-8 items-center gap-1.5">
                    <input type="checkbox" checked={g[key]} onChange={(e) => update(i, { [key]: e.target.checked })} />
                    {label}
                  </label>
                ))}
              </div>
            </li>
          )
        })}
      </ol>

      <fieldset className="flex flex-col gap-2 text-small">
        <legend className="font-medium text-text-strong">필수 원인을 올바르게 말했는가</legend>
        {causes.map((cause) => (
          <label key={cause.id} className="flex flex-wrap items-center gap-2">
            <select
              value={required[cause.id] === null || required[cause.id] === undefined ? '' : String(required[cause.id])}
              onChange={(e) =>
                setRequired((r) => ({ ...r, [cause.id]: e.target.value === '' ? null : e.target.value === 'true' }))
              }
              className="min-h-8 rounded-sm border border-border bg-surface px-1"
            >
              <option value="">선택 안 함</option>
              <option value="true">예</option>
              <option value="false">아니오</option>
            </select>
            {cause.label}
          </label>
        ))}
      </fieldset>

      <div className="flex flex-wrap gap-6 text-small">
        <Score label="이해도 (1 어려움 – 5 쉬움)" value={understanding} onChange={setUnderstanding} />
        <Score label="점검 방법 유용성 (1 – 5)" value={usefulness} onChange={setUsefulness} />
      </div>

      <label className="flex flex-col gap-1 text-small">
        메모
        <textarea
          value={notes}
          maxLength={2000}
          onChange={(e) => setNotes(e.target.value)}
          className="min-h-20 rounded-sm border border-border bg-surface p-2"
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-small">
          채점자
          <input
            value={grader}
            maxLength={40}
            required
            onChange={(e) => setGrader(e.target.value)}
            className="min-h-9 rounded-sm border border-border bg-surface px-2"
          />
        </label>
        <Button type="submit" variant="primary" disabled={mutation.isPending || !grader.trim()}>
          {mutation.isPending ? '저장 중' : '채점 저장 (새 판으로 추가)'}
        </Button>
        {mutation.isSuccess ? <span className="text-small text-status-success-fg">저장했습니다.</span> : null}
        {mutation.error ? (
          <span className="text-small text-status-failure-fg">
            저장하지 못했습니다: {mutation.error instanceof Error ? mutation.error.message : String(mutation.error)}
          </span>
        ) : null}
      </div>
    </form>
  )
}

function Score({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number | null) => void }) {
  return (
    <label className="flex items-center gap-2">
      {label}
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className="min-h-8 rounded-sm border border-border bg-surface px-1"
      >
        <option value="">선택 안 함</option>
        {[1, 2, 3, 4, 5].map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </label>
  )
}
