import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { BookOpen, ChevronRight, ExternalLink, ShieldCheck, Sparkles } from 'lucide-react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { DiagnosticKindMark } from '@/components/ui/DiagnosticNote'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { SourceMark } from '@/components/ui/SourceMark'
import { SynthesisHistory } from '@/features/run-detail/components/SynthesisHistory'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type {
  SynthesisProvenance,
  SynthesisResult,
  SynthesisStatement,
} from '@/features/run-detail/api'
import {
  GATE_REJECTIONS,
  SYNTHESIS_PANEL_ID,
  revealDocEvidence,
  revealElement,
  statementAnchorId,
} from '@/features/run-detail/aiStatement'
import { countEvidenceSources, isDocEvidence } from '@/features/run-detail/evidenceSource'
import type { EvidenceSource } from '@/features/run-detail/evidenceSource'
import { humanizeLocators } from '@/features/run-detail/locators'
import type { LocatorResolver } from '@/features/run-detail/locators'
import {
  groupByDiagnostic,
  partitionByRefs,
} from '@/features/run-detail/synthesisGroups'
import type { DiagnosticRef } from '@/features/run-detail/synthesisGroups'
import {
  numberStatements,
  statementNumber,
} from '@/features/run-detail/synthesisPlacement'
import type { StatementGroup } from '@/features/run-detail/synthesisPlacement'
import type { RunSynthesisState } from '@/features/run-detail/useRunSynthesis'
import { describeJobStatus } from '@/features/runs/status'
import { formatDuration, formatTimestamp } from '@/features/runs/time'
import { describeDiagnostic, describeFailure } from '@/registries/diagnostics'
import type { DiagnosticKind, DiagnosticView } from '@/registries/diagnostics'
import { describeEvidenceRef } from '@/registries/evidence'
import { synthesisErrorCopy } from '@/features/run-detail/synthesisErrorCopy'
import { cx } from '@/lib/cx'

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
  /**
   * 페이지가 가진 요청 상태(useRunSynthesis). 이전에는 이 패널이 mutation을
   * 직접 가졌다. 지금은 같은 응답을 상태 줄·각 항목의 AI 해설이 함께 읽는다.
   * 호출 정책(누를 때만, 재시도 없음)은 hook으로 그대로 옮겼다.
   */
  synthesis: RunSynthesisState
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
  synthesis,
  locators,
  terminal,
}: RunSynthesisPanelProps) {
  /*
    mutation과 요청 시작 시각은 useRunSynthesis로 옮겼다. 끝난 뒤 문서 검색
    목록을 다시 읽는 것(WES_AGENT_DOC_EVIDENCE, 개발판단기록 27장)도 거기서
    한다. GET 한 번이며 모델 호출이 아니다.
  */
  const result = synthesis.result
  const elapsed = useElapsedSeconds(synthesis.isPending, synthesis.startedAt)

  /*
    요청 버튼은 머리글 오른쪽에 둔다(공식 문서 구획의 "다시 검색"과 같은
    자리). 결과가 생긴 뒤에는 본문이 주인공이고, 버튼은 다시 만드는 조작이다.
    누르면 사용량을 쓴다는 사실은 그대로이며 호출 정책도 같다.
  */
  const hasAnswer = result?.available === true && result.synthesis !== null
  const buttonLabel = synthesis.isPending
    ? '생성 중…'
    : hasAnswer
      ? '다시 생성'
      : 'AI로 종합 설명 보기'

  return (
    <section
      id={SYNTHESIS_PANEL_ID}
      aria-labelledby="synthesis-heading"
      className="flex scroll-mt-6 flex-col gap-4"
    >
      <SectionHeader
        eyebrow="AI SUMMARY"
        title={<span id="synthesis-heading">AI 종합 설명</span>}
        meta={
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
            <SourceMark kind="ai">{' · Claude'}</SourceMark>
            <span>요청할 때만 실행</span>
          </span>
        }
        action={
          <Button
            type="button"
            onClick={() => synthesis.request()}
            /*
              중복 클릭 방지 + 미완료 실행 차단. 두 이유가 같은 속성에
              모이므로 아래 안내문으로 어느 쪽인지 구분한다.
            */
            disabled={synthesis.isPending || !terminal}
          >
            <Sparkles size={14} strokeWidth={1.5} aria-hidden="true" />
            {buttonLabel}
          </Button>
        }
      />

      <div className="flex flex-col gap-4 rounded-md border border-border bg-surface p-4 md:p-5">
        <p className="max-w-content text-small text-text-muted">
          위의 진단·검증 결과를 하나의 설명으로 묶어 줍니다. 파이프라인이 기록한
          사실과 등록된 근거만 사용하며, 품질 판정이나 임상 해석은 하지 않습니다.
        </p>

        {!terminal ? (
          <p className="text-small text-text-muted">
            실행이 끝난 뒤 AI 종합 설명을 사용할 수 있습니다.
          </p>
        ) : null}

        {/*
          요청 전에는 요청이 무엇을 하는지만 보여 준다(2026-11-23 발표용 정리).
          순서는 backend/app/api/synthesis.py의 처리 순서 그대로이고, 응답이나
          건수를 미리 만들어 보이지 않는다.
        */}
        {terminal && !result && !synthesis.isPending && !synthesis.isError ? (
          <RequestFlow />
        ) : null}

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

        {/*
          저장된 설명의 기록과 출처(개발판단기록 66장). 저장이 꺼진 서버에서는
          설명을 받은 뒤 "저장하지 않는다"는 한 줄만 보인다.
        */}
        {terminal ? <SynthesisHistory synthesis={synthesis} /> : null}

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

/** 요청 한 번이 서버에서 거치는 순서(api/synthesis.py). 모델은 4번에서만 호출된다. */
const REQUEST_FLOW: { title: string; body: string; ai?: boolean }[] = [
  { title: '실행 기록 정리', body: '단계 상태·실패·진단을 모델 없이 결정론 설명으로 묶습니다' },
  { title: '식별자 가림', body: '시료·Run·작업 ID를 바꾼 뒤에 서버 밖으로 보냅니다' },
  { title: '공식 문서 첨부', body: '서버 설정이 켜져 있을 때만 검색한 문서를 함께 넣습니다' },
  { title: 'Claude 요청', body: '버튼을 눌렀을 때만 호출합니다. 시간 초과·사용량 한도는 다시 시도하지 않습니다', ai: true },
  { title: '근거 검사', body: '근거 id나 숫자가 이 Run의 기록에 없으면 응답 전체를 표시하지 않습니다', ai: true },
]

function RequestFlow() {
  return (
    <div className="flex flex-col gap-2 border-t border-border-subtle pt-4">
      <h3 className="text-caption font-semibold tracking-wide-kr text-text-muted">
        요청하면 서버가 하는 일
      </h3>
      {/*
        2026-11-23 UI 정리(개발판단기록 63장): 단계마다 카드 다섯 장 → 한 줄의 순서
        목록(1px 구분선). 보라색은 모델이 관여하는 04·05에만 쓴다(번호와 옅은 배경).
      */}
      <ol className="grid grid-cols-1 divide-y divide-border-subtle overflow-hidden rounded-md border border-border-subtle md:grid-cols-5 md:divide-x md:divide-y-0">
        {REQUEST_FLOW.map((step, index) => (
          <li
            key={step.title}
            className={step.ai ? 'flex flex-col gap-1 bg-ai-bg px-3 py-3' : 'flex flex-col gap-1 px-3 py-3'}
          >
            <span className={step.ai ? 'font-mono text-caption text-ai-fg' : 'font-mono text-caption text-text-muted'}>
              {String(index + 1).padStart(2, '0')}
            </span>
            <span className="text-small font-semibold text-text-strong">{step.title}</span>
            <span className="text-caption text-text">{step.body}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/*
  검사에서 거부한 category 목록(GATE_REJECTIONS)과 패널·문장 id는
  aiStatement.ts로 옮겼다. 상태 줄과 각 항목의 AI 해설이 같은 값을 쓴다.
*/

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
  const { title, body, tone } = synthesisErrorCopy({
    kind: apiError?.kind ?? null,
    status: apiError?.status ?? null,
    code: apiError?.code ?? null,
  })

  return (
    <MessageBlock tone={tone} title={title}>
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
  /*
    번호는 응답 순서다(synthesisPlacement.ts). 각 항목 옆의 AI 해설이 같은
    번호를 보이므로, 같은 문장이 두 곳에 보여도 하나라는 것을 알 수 있다.
  */
  const numbered = numberStatements(synthesis)
  const numberOf = (group: StatementGroup, index: number) =>
    statementNumber(numbered, group, index)
  const hasStatusColumn = status !== null || statusEntries.length > 0
  const diagnosticCount = groups.reduce((sum, group) => sum + group.entries.length, 0)
  const otherTitle = groups.length > 0 ? '측정값과 그 밖의 내용' : '주요 내용'

  /*
    목차 `[설계판단]`. 요약 바로 아래에서 상세 해설의 구획과 문장 수를 한 줄로
    보인다. 누르면 그 구획으로 이동하고, 접힌 구획이면 연다. 구획이 무엇인지와
    몇 문장인지는 응답에서 센 값뿐이다.
  */
  const toc = [
    { id: 'synthesis-status', label: '실행 상태', count: statusEntries.length },
    { id: 'synthesis-diagnostics', label: '진단별 해설', count: diagnosticCount },
    { id: 'synthesis-other', label: otherTitle, count: otherEntries.length },
    { id: 'synthesis-limitations', label: '이 결과가 말하지 않는 것', count: synthesis.limitations.length },
    { id: 'synthesis-next-checks', label: '다음으로 확인할 수 있는 것', count: synthesis.nextChecks.length },
    { id: 'synthesis-uncertainties', label: '알 수 없는 것', count: synthesis.uncertainties.length },
  ].filter((entry) => entry.count > 0)

  return (
    <div className="flex flex-col gap-8 border-t border-border pt-5">
      {/* --- 1. 핵심 요약 ------------------------------------------------ */}
      {/*
        요약은 상세 해설과 다른 층이다. 글자를 한 단계 키우고, 출처 표시와
        생성 사실을 같은 줄에 둔다. 요약에는 근거 id가 없으므로(응답 계약)
        근거는 아래 각 문장에서 확인한다고 적는다.
      */}
      <section aria-labelledby="synthesis-summary" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Eyebrow id="synthesis-summary">핵심 요약</Eyebrow>
          <SourceMark kind="ai" />
          {provenance ? (
            <span className="inline-flex items-center gap-1 text-caption text-text-muted">
              <ShieldCheck size={12} strokeWidth={1.5} aria-hidden="true" />
              근거 검사를 모두 통과한 응답
            </span>
          ) : null}
        </div>
        <p className="max-w-content text-h3 font-medium whitespace-pre-wrap text-text-strong">
          {synthesis.summary}
        </p>
        <p className="text-caption text-text-muted">
          요약에는 근거가 따로 붙지 않습니다. 근거는 아래 상세 해설의 각 문장에서
          확인할 수 있습니다.
        </p>
        {toc.length > 0 ? (
          <nav aria-label="상세 해설 목차">
            <ul className="flex flex-wrap gap-2">
              {toc.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => revealElement(document.getElementById(entry.id), 'start')}
                    className="inline-flex min-h-7 items-center gap-1.5 rounded-sm border border-border bg-surface px-2.5 text-caption text-text hover:border-border-strong hover:bg-sunken"
                  >
                    {entry.label}
                    <span className="font-mono text-text-muted">{entry.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
      </section>

      {/* --- 2. 상세 해설 ------------------------------------------------ */}
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-subtle pb-2">
          <h3 className="text-body font-medium text-text-strong">
            상세 해설{' '}
            <span className="font-normal text-text-muted">{numbered.length}개 문장</span>
          </h3>
          <p className="text-caption text-text-muted">
            문장 앞 번호는 응답 순서이며, 각 항목 옆 AI 해설과 같은 번호입니다.
          </p>
        </div>

        {/* 2-1. 실행 상태: 왼쪽은 backend 기록, 오른쪽은 그 상태를 말한 AI 문장 */}
        {hasStatusColumn ? (
          <section
            id="synthesis-status"
            aria-labelledby="synthesis-status-heading"
            className="grid scroll-mt-6 grid-cols-1 gap-x-8 gap-y-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]"
          >
            <div className="flex flex-col gap-2">
              <Eyebrow id="synthesis-status-heading">실행 상태</Eyebrow>
              {status ? (
                <div className="flex flex-col gap-1.5 rounded-sm bg-sunken px-3 py-2.5">
                  <SourceMark kind="record" className="self-start bg-surface" />
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone={status.tone} size="sm">
                      {status.label}
                    </StatusBadge>
                    <span className="text-caption text-text-muted">
                      설명을 만들 때의 상태
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
            {statusEntries.length > 0 ? (
              <AiStatements>
                {statusEntries.map(({ index, item }) => (
                  <StatementItem
                    key={index}
                    item={item}
                    number={numberOf('importantFindings', index)}
                  />
                ))}
              </AiStatements>
            ) : null}
          </section>
        ) : null}

        {/* 2-2. 진단별 해설 */}
        {groups.length > 0 ? (
          <section
            id="synthesis-diagnostics"
            aria-labelledby="synthesis-diagnostics-heading"
            className="flex scroll-mt-6 flex-col gap-3"
          >
            <div className="flex flex-col gap-0.5">
              <SubHeading id="synthesis-diagnostics-heading" count={groups.length} unit="건">
                진단별 해설
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

              칸 안에서 위(회색 바탕)는 이 Run의 기록, 아래(점선 아래)는 AI
              문장이다.
            */}
            <ul className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] gap-3">
              {groups.map(({ diagnostic, entries }) => {
                const view = viewOf(diagnostic)
                return (
                  <li
                    key={diagnostic.ref}
                    className="flex flex-col overflow-hidden rounded-md border border-border"
                  >
                    <div className="flex flex-col gap-1 bg-sunken px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <DiagnosticKindMark kind={view.kind} label={view.label} />
                        <SourceMark kind="record" className="bg-surface" />
                      </div>
                      <h4 className="text-body font-medium text-text-strong">
                        {titleOf(diagnostic)}
                      </h4>
                      <code className="text-caption break-all text-text-muted">
                        {diagnostic.code}
                      </code>
                    </div>
                    <AiStatements className="px-4 py-3">
                      {entries.map(({ index, item, related }) => (
                        <StatementItem
                          key={index}
                          item={item}
                          number={numberOf('importantFindings', index)}
                          note={
                            related.length > 0
                              ? `함께 관련된 진단: ${related.map(titleOf).join(', ')}`
                              : undefined
                          }
                        />
                      ))}
                    </AiStatements>
                  </li>
                )
              })}
            </ul>
          </section>
        ) : null}

        {/* 2-3. 측정값과 그 밖의 내용 */}
        {otherEntries.length > 0 ? (
          <section
            id="synthesis-other"
            aria-labelledby="synthesis-other-heading"
            className="flex scroll-mt-6 flex-col gap-3"
          >
            <SubHeading id="synthesis-other-heading" count={otherEntries.length} unit="개">
              {otherTitle}
            </SubHeading>
            <ul className="grid grid-cols-1 gap-x-8 gap-y-4 border-t border-dashed border-border pt-3 md:grid-cols-2">
              {otherEntries.map(({ index, item }) => (
                <StatementItem
                  key={index}
                  item={item}
                  number={numberOf('importantFindings', index)}
                />
              ))}
            </ul>
          </section>
        ) : null}

        {/* 2-4. 접힘 영역 */}
        {/*
          넓은 화면에서는 세 영역을 나란히 둔다. 접혀 있을 때 한 줄이고,
          펼치면 각자 아래로 늘어난다(items-start). 좁은 화면에서는 세로.
          "다음으로 확인할 수 있는 것"만 처음부터 연다 — 사용자가 이어서 할
          일이고 보통 몇 문장뿐이다. 나머지는 건수와 함께 접어 둔다.
        */}
        <div className="grid grid-cols-1 items-start gap-x-8 gap-y-3 border-t border-border-subtle pt-4 lg:grid-cols-3">
          <FoldSection
            id="synthesis-limitations"
            title="이 결과가 말하지 않는 것"
            items={synthesis.limitations}
            numberOf={(index) => numberOf('limitations', index)}
          />
          <FoldSection
            id="synthesis-next-checks"
            title="다음으로 확인할 수 있는 것"
            items={synthesis.nextChecks}
            locators={locators}
            numberOf={(index) => numberOf('nextChecks', index)}
            defaultOpen
          />
          <FoldSection
            id="synthesis-uncertainties"
            title="알 수 없는 것"
            items={synthesis.uncertainties}
            numberOf={(index) => numberOf('uncertainties', index)}
          />
        </div>
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

/** AI 문장 목록. 점선 위쪽(기록)과 구분하는 공통 틀. */
function AiStatements({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <ul
      className={cx(
        'flex flex-col gap-4 border-t border-dashed border-border-strong pt-3',
        className,
      )}
    >
      {children}
    </ul>
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
  id,
  title,
  items,
  locators,
  numberOf,
  defaultOpen = false,
}: {
  id: string
  title: string
  items: SynthesisStatement[]
  locators?: LocatorResolver
  numberOf: (index: number) => number | null
  defaultOpen?: boolean
}) {
  if (items.length === 0) return null
  return (
    <details id={id} open={defaultOpen} className="group min-w-0 scroll-mt-6">
      <summary className="inline-flex min-h-7 cursor-pointer items-center gap-1 text-small font-medium text-text-strong">
        <ChevronRight
          size={14}
          strokeWidth={1.5}
          aria-hidden="true"
          className="flex-none text-text-muted group-open:rotate-90"
        />
        {title}
        <span className="font-normal text-text-muted">{items.length}개</span>
      </summary>
      <ul className="mt-2 flex flex-col gap-4 border-t border-dashed border-border-strong pt-3">
        {items.map((item, index) => (
          <StatementItem
            key={index}
            item={item}
            locators={locators}
            number={numberOf(index)}
          />
        ))}
      </ul>
    </details>
  )
}

function StatementItem({
  item,
  locators,
  note,
  number,
}: {
  item: SynthesisStatement
  locators?: LocatorResolver
  /** 문장 아래 보조 설명. 문장 자체를 바꾸지 않고 덧붙이기만 한다. */
  note?: string
  /** 응답 순서 번호. 각 항목 옆 AI 해설과 같은 번호다. */
  number: number | null
}) {
  const shown = locators
    ? humanizeLocators(item.statement, locators)
    : item.statement
  return (
    <li
      id={number === null ? undefined : statementAnchorId(number)}
      // 각 항목의 "전체 설명에서 보기"가 여기로 초점을 옮긴다(aiStatement.ts).
      tabIndex={number === null ? undefined : -1}
      className="flex max-w-content min-w-0 scroll-mt-6 flex-col gap-1"
    >
      <span className="text-small leading-body text-text">
        {number === null ? null : (
          <span className="mr-1.5 font-mono text-caption text-text-muted">
            #{number}
          </span>
        )}
        {shown}
      </span>
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
  /*
    접힌 상태에서도 출처의 종류는 보이게 한다: "이 Run의 기록 2 · 공식 문서 1".
    이 문장이 실행의 관측에 기대는지, 일반 문서 지식에 기대는지가 펼치지
    않아도 읽힌다. 건수는 인용된 id를 prefix로 나눈 값뿐이다(evidenceSource.ts).
  */
  const sources = countEvidenceSources(refs)
  return (
    <details className="group/evidence">
      <summary className="inline-flex min-h-6 cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-text-muted hover:text-text">
        <span className="inline-flex items-center gap-0.5">
          <ChevronRight
            size={12}
            strokeWidth={1.5}
            aria-hidden="true"
            className="flex-none group-open/evidence:rotate-90"
          />
          근거 {refs.length}개 보기
        </span>
        {sources.map(({ source, count }) => (
          <span key={source} className="inline-flex items-center gap-1">
            <span aria-hidden="true">·</span>
            {EVIDENCE_SOURCE_LABEL[source]} {count}
          </span>
        ))}
      </summary>
      <ul className="mt-1.5 flex flex-col gap-2 border-l border-border pl-3">
        {views.map((view) => (
          <li key={view.id} className="flex flex-col gap-0.5">
            <span className="text-caption text-text">
              {view.label}
              {view.known ? (
                <span className="ml-2 text-text-muted">{view.group}</span>
              ) : null}
            </span>
            {view.quote ? (
              <span className="text-caption text-text-muted">“{view.quote}”</span>
            ) : null}
            <span className="flex flex-wrap gap-x-3">
              {view.href ? (
                <a
                  href={view.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-6 items-center gap-1 text-caption text-text-muted underline underline-offset-2 hover:text-brand"
                >
                  원문 열기
                  <ExternalLink size={12} strokeWidth={1.5} aria-hidden="true" />
                </a>
              ) : null}
              {/*
                공식 문서 근거는 공식 문서 탭에서 검색 기록과 함께 볼 수 있다.
                그 문서를 가진 검색 기록을 골라 상세 패널에 연다. 어느 기록에도
                없으면 탭이 그렇다고 말한다(aiStatement.ts revealDocEvidence).
              */}
              {isDocEvidence(view.id) ? (
                <button
                  type="button"
                  onClick={() => revealDocEvidence(view.id)}
                  className="inline-flex min-h-6 items-center gap-1 text-caption text-text-muted underline underline-offset-2 hover:text-brand"
                >
                  <BookOpen size={12} strokeWidth={1.5} aria-hidden="true" />
                  공식 문서 탭에서 보기
                </button>
              ) : null}
            </span>
            {view.known ? (
              <code className="font-mono text-caption break-all text-text-muted">
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

const EVIDENCE_SOURCE_LABEL: Record<EvidenceSource, string> = {
  record: '이 Run의 기록',
  mixed: '이 Run의 기록·일반 설명',
  doc: '공식 문서',
  knowledge: '등록된 지식',
  other: '기타',
}
