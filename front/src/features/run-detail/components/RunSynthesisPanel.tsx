import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { DiagnosticKindMark } from '@/components/ui/DiagnosticNote'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { createSynthesis } from '@/features/run-detail/api'
import type {
  SynthesisProvenance,
  SynthesisResult,
  SynthesisStatement,
} from '@/features/run-detail/api'
import { humanizeLocators } from '@/features/run-detail/locators'
import type { LocatorResolver } from '@/features/run-detail/locators'
import {
  groupByDiagnostic,
  partitionByRefs,
} from '@/features/run-detail/synthesisGroups'
import type { DiagnosticRef } from '@/features/run-detail/synthesisGroups'
import { describeJobStatus } from '@/features/runs/status'
import { formatDuration, formatTimestamp } from '@/features/runs/time'
import { describeDiagnostic, describeFailure } from '@/registries/diagnostics'
import type { DiagnosticKind, DiagnosticView } from '@/registries/diagnostics'
import { describeEvidenceRef } from '@/registries/evidence'

/*
  AI 종합 설명.

  ── mutation이지 query가 아니다 ────────────────────────────────────────

  이 화면에서 유일하게 **사용자의 Claude 구독 사용량을 쓰는** 요청이다.
  useQuery로 만들면 mount·refetch·window focus로 스스로 실행되고, 실행 상세를
  열어 두기만 해도 사용량이 빠져나간다. useMutation은 호출해야만 실행된다.

  같은 이유로 자동 재시도를 켜지 않는다. 실패한 요청을 조용히 3번 반복하면
  사용자가 모르는 사이에 3배를 쓴다.

  ── 실패해도 화면은 그대로다 ───────────────────────────────────────────

  backend는 대부분의 실패를 200 + `available: false`로 돌려준다. 이 컴포넌트는
  그때 메시지 한 줄만 덧붙이고, 위쪽의 deterministic 설명·진단·단계 표는
  전혀 건드리지 않는다. 선택 기능 하나 때문에 실행 상세가 오류 화면이 되면
  안 된다.

  ── AI임을 숨기지 않는다 ───────────────────────────────────────────────

  제목·버튼·본문 하단에 생성물임을 밝힌다. 위의 결정론적 설명과 시각적으로
  구분하고, 사용자가 어느 쪽이 파이프라인의 기록이고 어느 쪽이 모델의 문장인지
  알 수 있게 한다.

  ── 아직 끝나지 않은 실행에서는 호출하지 않는다 ────────────────────────

  진행 중인 실행을 종합해도 다음 단계가 끝나는 순간 낡은 설명이 되고, 구독
  사용량만 소모된다. 버튼을 비활성화하고 이유를 문장으로 적는다 — 비활성
  버튼만 두면 왜 눌리지 않는지 알 수 없다.

  ── 결과의 배치 `[설계판단]` ───────────────────────────────────────────

  실제 Run에서 받은 설명은 문장이 20개 가까이 되고, 그대로 나열하면 상태와
  경고가 수치 문장 사이에 묻힌다. 그래서 읽는 순서를 정한다.

    1. 요약 | 실행 상태   요약과, 실행 상태를 말한 문장(run:status 등 인용).
                          상태 배지는 AI가 아니라 backend의 runStatus다.
    2. 진단 기록          확인 필요 · 자동 복구 · 참고. 진단마다 한 칸.
    3. 측정값과 그 밖의 내용
                          진단·상태와 연결되지 않은 주요 문장.
    4. 한계 · 다음 확인 · 알 수 없는 것
                          건수를 보이고 접어 둔다.

  묶는 기준은 전부 모델이 인용한 evidenceRefs다(synthesisGroups.ts).

  ── 폭 `[설계판단]` ────────────────────────────────────────────────────

  실행 상세는 넓은 Shell(최대 1360px) 안에 있다. 1차에서는 문장마다
  max-w-prose(65ch, 13px 기준 약 500px)를 걸고 모든 구역을 세로 한 줄로
  쌓아서, 넓은 화면의 절반 이상이 비었다. 이제 줄 길이는 **칸의 폭**이
  정한다 — 진단은 auto-fit grid의 칸, 측정값·접힘 영역은 2·3열이다. 한 칸이
  화면 전체를 차지하는 경우(진단 한 건, 좁은 화면)에는 max-w-content(880px)로
  줄 길이의 상한만 둔다.

  ── 없앤 조작 ──────────────────────────────────────────────────────────

  "AI가 쓴 순서로 보기"와 "모두 펼치기"는 1차에 있었다. 앞의 것은 묶는
  규칙을 검증하기 위한 것이었고 그 검증은 렌더링 검사로 옮겼다. 뒤의 것은
  접힌 영역이 세 개뿐이고 각 머리글이 건수와 함께 바로 눌리므로 버튼 하나를
  더 둘 이유가 약했다. 응답 데이터는 그대로이며 모든 문장이 화면에 있다.

  **문장은 하나도 지우거나 고치지 않는다.** 바뀌는 것은 위치와 접힘뿐이다.
  모든 텍스트는 React text node로 들어간다. AI 문장을 HTML로 해석하지 않는다.
*/

export interface RunSynthesisPanelProps {
  jobId: string
  /**
   * 이 실행의 artifact kind -> 표시 이름.
   *
   * AI 문장 안의 `artifact:...` locator를 사람 말로 바꾸는 데만 쓴다.
   * 비어 있으면 치환이 일어나지 않고 원문이 그대로 남는다 — 정상 동작이다.
   */
  locators: LocatorResolver
  /**
   * 실행이 끝났는가.
   *
   * 끝나지 않은 실행은 종합할 대상이 아직 확정되지 않았다. 진행 중에 만든
   * 설명은 다음 단계가 끝나는 순간 낡은 것이 되고, 사용량만 쓴다.
   */
  terminal: boolean
}

export function RunSynthesisPanel({
  jobId,
  locators,
  terminal,
}: RunSynthesisPanelProps) {
  /*
    시작 시각은 **요청을 시작한 이벤트**가 기록한다. effect 안에서 setState로
    초기화하면 렌더가 한 번 더 돌고(oxlint set-state-in-effect), 이전 실행의
    경과 시간이 잠깐 남는 문제도 생긴다.
  */
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const synthesis = useMutation({
    mutationFn: () => createSynthesis(jobId),
    onMutate: () => setStartedAt(Date.now()),
    // 재시도 없음. 위 주석 참고.
    retry: false,
  })

  const result = synthesis.data
  const elapsed = useElapsedSeconds(synthesis.isPending, startedAt)

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        eyebrow="AI SUMMARY"
        title="AI 종합 설명"
        meta="Claude가 생성 · 요청할 때만 실행"
      />

      <div className="flex flex-col gap-4 rounded-md border border-border bg-surface p-4">
        <p className="max-w-prose text-small text-text-muted">
          위의 진단·검증 결과를 하나의 설명으로 묶어 줍니다. 파이프라인이 기록한
          사실과 등록된 근거만 사용하며, 품질 판정이나 임상 해석은 하지 않습니다.
        </p>

        <div className="flex flex-col gap-2">
          <div>
            <Button
              type="button"
              onClick={() => synthesis.mutate()}
              /*
                중복 클릭 방지 + 미완료 실행 차단. 두 이유가 같은 속성에
                모이므로 아래 안내문으로 어느 쪽인지 구분한다.
              */
              disabled={synthesis.isPending || !terminal}
            >
              <Sparkles size={14} strokeWidth={1.5} aria-hidden="true" />
              {synthesis.isPending ? '생성 중…' : 'AI로 종합 설명 보기'}
            </Button>
          </div>
          {!terminal ? (
            <p className="text-small text-text-muted">
              실행이 끝난 뒤 AI 종합 설명을 사용할 수 있습니다.
            </p>
          ) : null}
        </div>

        {/*
          기다리는 동안 `[설계판단]`

          걸리는 시간은 실행마다 크게 다르다. 기록된 것만 해도 실제 Full Run
          160~213초, 개발용 사본의 같은 Run 약 20초다. 그래서 예상 시간을
          적지 않는다 — 틀린 숫자는 없는 숫자보다 나쁘다.

          **가짜 진행률을 만들지 않는다.** backend는 모델이 어디까지 왔는지
          모르고, 우리도 모른다. 대신 실제로 아는 것 — 지금까지 얼마나
          지났는지 — 만 말한다. 경과 시간은 client timer이며 "몇 % 완료"가
          아니다.
        */}
        {synthesis.isPending ? (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-col gap-1 border-t border-border pt-3"
          >
            <p className="text-small text-text">
              AI 종합 설명을 만들고 있습니다. 걸리는 시간은 실행 내용과 서버
              상태에 따라 다릅니다.
            </p>
            <p className="text-caption text-text-muted">
              경과 {formatElapsed(elapsed)} · 이 화면을 떠나도 실행 중인
              분석에는 영향이 없습니다.
            </p>
          </div>
        ) : null}

        {/*
          요청 자체가 실패한 경우(연결 실패 · HTTP 오류 · 응답 형식 불일치).
          backend가 200 + available:false로 답한 실패와는 다른 경로다.
        */}
        {synthesis.isError ? <SynthesisRequestError error={synthesis.error} /> : null}

        {result && !result.available ? (
          <MessageBlock
            tone="warning"
            title={
              result.errorCategory && GATE_REJECTIONS.has(result.errorCategory)
                ? '안전 검사에서 설명을 폐기했습니다'
                : 'AI 설명을 사용할 수 없습니다'
            }
          >
            {/* 문구는 backend가 category마다 정한 것을 그대로 쓴다. */}
            <p>{result.errorMessage}</p>
            <p className="mt-2 text-caption text-text-muted">
              위의 설명은 모델 없이 만들어진 것이며 그대로 유효합니다.
            </p>
          </MessageBlock>
        ) : null}

        {result?.available && result.synthesis ? (
          <SynthesisResultView
            synthesis={result.synthesis}
            provenance={result.provenance}
            locators={locators}
          />
        ) : null}
      </div>
    </section>
  )
}

/*
  backend가 모델의 응답을 받은 뒤 검사에서 거부한 category.

  backend/app/services/explanation/llm/synthesis.py의 검사 단계 이름이며,
  backend 테스트(test_every_error_category_has_a_curated_message)의 domain
  집합과 같다. 사용자 문구는 여기서 만들지 않는다 — 제목만 "모델을 쓸 수
  없었다"와 "모델이 쓴 설명을 버렸다"로 구분한다. 모르는 category는 일반
  제목으로 간다.
*/
const GATE_REJECTIONS: ReadonlySet<string> = new Set([
  'invalidSynthesis',
  'unknownEvidenceRef',
  'unsupportedNumber',
  'internalFieldName',
  'runFactMismatch',
  'evidenceMismatch',
])

/**
 * 요청이 실패했을 때의 안내.
 *
 * 상태 코드는 backend/app/api/synthesis.py가 쓰는 것만 구분한다.
 *   400 job id 형식 오류 · 404 없는 실행 · 409 아직 끝나지 않은 실행 ·
 *   500 파이프라인 문서를 읽지 못함
 * backend가 보낸 상세(detail)는 사용자 문구와 섞지 않고 기술 상세로 아래에 둔다.
 */
function SynthesisRequestError({ error }: { error: unknown }) {
  const apiError = error instanceof ApiError ? error : null
  const status = apiError?.status ?? null

  let title = '요청이 실패했습니다'
  let body = 'AI 설명 요청을 처리하지 못했습니다.'
  if (apiError?.kind === 'network') {
    title = '서버에 연결하지 못했습니다'
    body = 'backend가 실행 중인지, 주소가 맞는지 확인한 뒤 다시 요청하세요.'
  } else if (apiError?.kind === 'malformed') {
    title = '응답 형식이 예상과 다릅니다'
    body = '서버의 응답을 frontend가 아는 계약대로 읽지 못했습니다. frontend와 backend의 버전이 맞는지 확인해야 합니다.'
  } else if (status === 400) {
    title = '잘못된 요청입니다'
    body = '실행 ID 형식이 올바르지 않습니다. 실행 목록에서 다시 선택하세요.'
  } else if (status === 404) {
    title = '이 실행을 찾을 수 없습니다'
    body = '서버에 이 실행의 기록이 없습니다. 실행 목록에서 다시 선택하세요.'
  } else if (status === 409) {
    title = '아직 끝나지 않은 실행입니다'
    body = '실행이 끝난 뒤 다시 요청하세요. 이 요청은 모델을 호출하지 않았습니다.'
  } else if (status !== null && status >= 500) {
    title = '서버 내부 오류가 발생했습니다'
    body = `서버가 HTTP ${status}로 응답했습니다. 실행 기록을 읽는 중 문제가 생겼을 수 있으며, 서버 로그를 확인해야 합니다.`
  } else if (status !== null) {
    body = `서버가 HTTP ${status}로 응답했습니다.`
  }

  return (
    <MessageBlock tone={status === 409 ? 'info' : 'warning'} title={title}>
      <div className="flex flex-col gap-2">
        <p>{body}</p>
        {apiError?.detail ? (
          <code className="break-all text-caption text-text-muted">
            {apiError.detail}
          </code>
        ) : null}
        <p className="text-caption text-text-muted">위의 설명은 그대로 유효합니다.</p>
      </div>
    </MessageBlock>
  )
}

/*
  실행 상태를 말하는 근거. 진단과 연결되지 않은 문장 중 이 둘 중 하나를
  인용한 문장은 요약 옆 "실행 상태"로 올린다. 이름은 backend build_payload의
  구획 이름이며 registries/evidence.ts의 RUN_SECTION_LABEL과 같다.
*/
const STATUS_REFS: ReadonlySet<string> = new Set(['run:status', 'run:checkSummary'])

/**
 * 성공한 응답 한 건의 본문.
 *
 * mutation과 분리해 둔 이유는 하나다. 이 부분은 응답 값만으로 결정되므로
 * 모델을 부르지 않고 고정된 응답으로 렌더링을 확인할 수 있다.
 */
export function SynthesisResultView({
  synthesis,
  provenance,
  locators,
}: {
  synthesis: NonNullable<SynthesisResult['synthesis']>
  provenance: SynthesisProvenance | null
  locators: LocatorResolver
}) {
  const { groups, ungrouped } = groupByDiagnostic(
    synthesis.importantFindings,
    rankOf,
  )
  const { matched: statusEntries, rest: otherEntries } = partitionByRefs(
    ungrouped,
    STATUS_REFS,
  )
  const status = provenance ? describeJobStatus(provenance.runStatus) : null
  const hasStatusColumn = status !== null || statusEntries.length > 0

  return (
    <div className="flex flex-col gap-6 border-t border-border pt-4">
      {/* --- 1. 요약 | 실행 상태 ----------------------------------------- */}
      <div
        className={
          hasStatusColumn
            ? 'grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'
            : 'grid grid-cols-1'
        }
      >
        <section aria-labelledby="synthesis-summary" className="flex flex-col gap-1.5">
          <Eyebrow id="synthesis-summary">요약</Eyebrow>
          <p className="max-w-content text-body font-medium whitespace-pre-wrap text-text-strong">
            {synthesis.summary}
          </p>
        </section>

        {hasStatusColumn ? (
          <section
            aria-labelledby="synthesis-status"
            className="flex flex-col gap-2 border-t border-border-subtle pt-4 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-6"
          >
            <Eyebrow id="synthesis-status">실행 상태</Eyebrow>
            {status ? (
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge tone={status.tone} size="sm">
                  {status.label}
                </StatusBadge>
                <span className="text-caption text-text-muted">
                  설명을 만들 때의 상태
                </span>
              </div>
            ) : null}
            {statusEntries.length > 0 ? (
              <ul className="flex flex-col gap-3">
                {statusEntries.map(({ index, item }) => (
                  <StatementItem key={index} item={item} />
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
      </div>

      {/* --- 2. 진단 기록 ------------------------------------------------ */}
      {groups.length > 0 ? (
        <section aria-labelledby="synthesis-diagnostics" className="flex flex-col gap-3">
          <div className="flex flex-col gap-0.5">
            <SubHeading id="synthesis-diagnostics" count={groups.length} unit="건">
              진단 기록
            </SubHeading>
            <p className="text-caption text-text-muted">
              파이프라인이 남긴 진단별로 AI 설명을 묶었습니다. 진단의 종류는
              실행 상태와 별개입니다.
            </p>
          </div>
          {/*
            auto-fit: 칸 수는 폭이 정한다. 1360px 화면에서 3칸, 태블릿 2칸,
            모바일 1칸. 진단이 한 건이면 한 칸이 줄 전체를 쓰고, 그때 문장
            길이는 StatementItem의 max-w-content가 막는다.
          */}
          <ul className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] gap-3">
            {groups.map(({ diagnostic, entries }) => {
              const view = viewOf(diagnostic)
              return (
                <li
                  key={diagnostic.ref}
                  className="flex flex-col gap-3 rounded-md border border-border p-4"
                >
                  <div className="flex flex-col gap-1">
                    <DiagnosticKindMark kind={view.kind} label={view.label} />
                    <h4 className="text-body font-medium text-text-strong">
                      {titleOf(diagnostic)}
                    </h4>
                    <code className="text-caption break-all text-text-muted">
                      {diagnostic.code}
                    </code>
                  </div>
                  <ul className="flex flex-col gap-3 border-t border-border-subtle pt-3">
                    {entries.map(({ index, item, related }) => (
                      <StatementItem
                        key={index}
                        item={item}
                        note={
                          related.length > 0
                            ? `함께 관련된 진단: ${related.map(titleOf).join(', ')}`
                            : undefined
                        }
                      />
                    ))}
                  </ul>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      {/* --- 3. 측정값과 그 밖의 내용 ------------------------------------ */}
      {otherEntries.length > 0 ? (
        <section aria-labelledby="synthesis-other" className="flex flex-col gap-3">
          <SubHeading id="synthesis-other" count={otherEntries.length} unit="개">
            {groups.length > 0 ? '측정값과 그 밖의 내용' : '주요 내용'}
          </SubHeading>
          <ul className="grid grid-cols-1 gap-x-8 gap-y-3 border-t border-border-subtle pt-3 md:grid-cols-2">
            {otherEntries.map(({ index, item }) => (
              <StatementItem key={index} item={item} />
            ))}
          </ul>
        </section>
      ) : null}

      {/* --- 4. 접힘 영역 ------------------------------------------------ */}
      {/*
        넓은 화면에서는 세 영역을 나란히 둔다. 접혀 있을 때 한 줄이고,
        펼치면 각자 아래로 늘어난다(items-start). 좁은 화면에서는 세로.
      */}
      <div className="grid grid-cols-1 items-start gap-x-8 gap-y-3 border-t border-border-subtle pt-3 lg:grid-cols-3">
        <FoldSection title="이 결과가 말하지 않는 것" items={synthesis.limitations} />
        <FoldSection
          title="다음으로 확인할 수 있는 것"
          items={synthesis.nextChecks}
          locators={locators}
        />
        <FoldSection title="알 수 없는 것" items={synthesis.uncertainties} />
      </div>

      {/*
        생성물임을 본문 끝에서 다시 밝힌다. provenance는 어느 모델이 언제
        만들었는지 추적할 수 있게 보여준다. 실행 시간은 backend가 보고한
        모델 실행 시간(durationMs)이며 브라우저에서 잰 값이 아니다.
      */}
      {provenance ? <ProvenanceLine provenance={provenance} /> : null}
    </div>
  )
}

/*
  진단의 표시 순서. DiagnosticCounts와 같은 순서(심각한 것부터)다 — 같은
  화면 위쪽의 진단 건수 표시와 순서가 달라지면 안 된다.
*/
const KIND_RANK: Record<DiagnosticKind, number> = {
  failure: 0,
  attention: 1,
  repaired: 2,
  note: 3,
}

function viewOf(diagnostic: DiagnosticRef): DiagnosticView {
  return diagnostic.prefix === 'fail'
    ? describeFailure()
    : describeDiagnostic(diagnostic.code)
}

function rankOf(diagnostic: DiagnosticRef): number {
  return KIND_RANK[viewOf(diagnostic).kind]
}

/**
 * 진단 제목. knowledge에 있으면 등록된 제목, 없으면 code 그대로.
 * 이름을 지어내지 않는다(registries/evidence.ts와 같은 규칙).
 */
function titleOf(diagnostic: DiagnosticRef): string {
  const view = describeEvidenceRef(diagnostic.ref)
  return view.known ? view.label : diagnostic.code
}

function Eyebrow({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h3
      id={id}
      className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase"
    >
      {children}
    </h3>
  )
}

function SubHeading({
  id,
  count,
  unit,
  children,
}: {
  id: string
  count: number
  unit: string
  children: ReactNode
}) {
  return (
    <h3 id={id} className="text-small font-medium text-text-strong">
      {children}{' '}
      <span className="font-normal text-text-muted">
        {count}
        {unit}
      </span>
    </h3>
  )
}

function FoldSection({
  title,
  items,
  locators,
}: {
  title: string
  items: SynthesisStatement[]
  locators?: LocatorResolver
}) {
  if (items.length === 0) return null
  return (
    <details className="min-w-0">
      <summary className="inline-flex min-h-6 cursor-pointer items-center gap-1 text-small font-medium text-text-strong">
        {title}
        <span className="font-normal text-text-muted">{items.length}개</span>
      </summary>
      <ul className="mt-3 flex flex-col gap-3">
        {items.map((item, index) => (
          <StatementItem key={index} item={item} locators={locators} />
        ))}
      </ul>
    </details>
  )
}

function StatementItem({
  item,
  locators,
  note,
}: {
  item: SynthesisStatement
  locators?: LocatorResolver
  /** 문장 아래 보조 설명. 문장 자체를 바꾸지 않고 덧붙이기만 한다. */
  note?: string
}) {
  const shown = locators
    ? humanizeLocators(item.statement, locators)
    : item.statement
  return (
    <li className="flex max-w-content min-w-0 flex-col gap-1">
      <span className="text-small text-text">{shown}</span>
      {note ? (
        <span className="text-caption text-text-muted">{note}</span>
      ) : null}
      <EvidenceRefs refs={item.evidenceRefs} raw={item.statement} shown={shown} />
    </li>
  )
}

function ProvenanceLine({ provenance }: { provenance: SynthesisProvenance }) {
  const generated = formatTimestamp(provenance.generatedAt)
  return (
    <p className="flex flex-wrap gap-x-1.5 border-t border-border pt-3 text-caption text-text-muted">
      <span>이 설명은 {provenance.provider}가 생성한 AI 결과입니다</span>
      <span aria-hidden="true">·</span>
      <span>{provenance.models.join(', ') || '모델 미상'}</span>
      <span aria-hidden="true">·</span>
      <span>
        생성{' '}
        {generated ? (
          <time dateTime={generated.machine}>{generated.full}</time>
        ) : (
          provenance.generatedAt
        )}
      </span>
      <span aria-hidden="true">·</span>
      <span>
        모델 실행 시간{' '}
        {provenance.durationMs === null
          ? '기록 없음'
          : formatDuration(provenance.durationMs / 1000)}
      </span>
    </p>
  )
}

/**
 * 경과 초. 요청 중일 때만 흐른다.
 *
 * client timer일 뿐이며 backend 진행률과는 아무 관계가 없다. 그래서 이름도
 * elapsed이지 progress가 아니다.
 */
function useElapsedSeconds(running: boolean, startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    // setState는 interval 콜백 안에서만 일어난다 — effect 본문에서 동기적으로
    // 부르면 렌더가 한 번 더 돌고 linter가 그것을 잡는다.
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [running])
  if (!running || startedAt === null) return 0
  return Math.max(0, Math.floor((now - startedAt) / 1000))
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest === 0 ? `${minutes}분` : `${minutes}분 ${rest}초`
}

/*
  근거 표시.

  본문에는 건수만 둔다. raw id 목록(`dx:NM_MD_REPAIRED · src:sam-tags-spec`)이
  문장마다 붙어 있으면 정작 읽어야 할 문장이 식별자에 파묻힌다.

  펼치면 사람이 읽는 이름이 나온다. 이름은 지어내지 않고
  registries/evidence.ts가 canonical knowledge에서 가져온다 — 해석되지 않는
  id는 raw 그대로 남는다.

  raw id와, locator 치환이 일어난 경우 모델의 원문까지 같은 자리에 둔다.
  provenance를 잃지 않으면서 본문에서 치우는 것이 목적이지 숨기는 것이 아니다.
*/
function EvidenceRefs({
  refs,
  raw,
  shown,
}: {
  refs: string[]
  raw: string
  shown: string
}) {
  if (refs.length === 0) return null
  const views = refs.map(describeEvidenceRef)
  return (
    <details>
      <summary className="inline-flex min-h-6 cursor-pointer items-center text-caption text-text-muted">
        근거 {refs.length}개 보기
      </summary>
      <ul className="mt-1.5 flex flex-col gap-1 border-l border-border pl-3">
        {views.map((view) => (
          <li key={view.id} className="flex flex-col">
            <span className="text-caption text-text">
              {view.label}
              {view.known ? (
                <span className="ml-2 text-text-muted">{view.group}</span>
              ) : null}
            </span>
            {view.known ? (
              <code className="font-mono text-caption text-text-muted">
                {view.id}
              </code>
            ) : null}
          </li>
        ))}
        {shown !== raw ? (
          <li className="flex flex-col pt-1">
            <span className="text-caption text-text-muted">모델 원문</span>
            <span className="text-caption text-text">{raw}</span>
          </li>
        ) : null}
      </ul>
    </details>
  )
}
