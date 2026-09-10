import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { createSynthesis } from '@/features/run-detail/api'
import type { SynthesisStatement } from '@/features/run-detail/api'
import { humanizeLocators } from '@/features/run-detail/locators'
import type { LocatorResolver } from '@/features/run-detail/locators'
import { describeEvidenceRef } from '@/registries/evidence'

/*
  AI 종합 설명 — 첫 vertical slice.

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

  ⚠️ 이번 단계에서 AI UI를 재설계하지 않았다. 생성 경과 시간·근거 표시·
     locator 이름화는 2차 polish다.
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

          실제 Full Run에서 160~213초가 걸렸다. "생성 중…" 하나만 있으면
          2분이 지난 시점에 사용자는 멈춘 것인지 알 수 없다.

          **가짜 진행률을 만들지 않는다.** backend는 모델이 어디까지 왔는지
          모르고, 우리도 모른다. 대신 우리가 실제로 아는 두 가지를 말한다 —
          보통 몇 분 걸린다는 것과, 지금까지 얼마나 지났는지.

          경과 시간은 client timer다. 그것이 무엇을 뜻하는지 과장하지 않는다:
          "몇 % 완료"가 아니라 "경과 1분 42초"다.
        */}
        {synthesis.isPending ? (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-col gap-1 border-t border-border pt-3"
          >
            <p className="text-small text-text">
              AI 종합 설명을 만들고 있습니다. 완료까지 보통 2~4분 걸립니다.
            </p>
            <p className="text-caption text-text-muted">
              경과 {formatElapsed(elapsed)} · 이 화면을 떠나도 실행 중인
              분석에는 영향이 없습니다.
            </p>
          </div>
        ) : null}

        {/* 네트워크 자체가 실패한 경우. backend가 응답한 실패와 구분한다. */}
        {synthesis.isError ? (
          <MessageBlock tone="warning" title="요청을 보내지 못했습니다">
            서버에 연결하지 못했습니다. 위의 설명은 그대로 유효합니다.
          </MessageBlock>
        ) : null}

        {result && !result.available ? (
          <MessageBlock tone="warning" title="AI 설명을 사용할 수 없습니다">
            <p>{result.errorMessage}</p>
            <p className="mt-2 text-caption text-text-muted">
              위의 설명은 모델 없이 만들어진 것이며 그대로 유효합니다.
            </p>
          </MessageBlock>
        ) : null}

        {result?.available && result.synthesis ? (
          <div className="flex flex-col gap-5 border-t border-border pt-4">
            <p className="max-w-prose text-body whitespace-pre-wrap text-text">
              {result.synthesis.summary}
            </p>

            <StatementList
              title="확인할 사항"
              items={result.synthesis.importantFindings}
            />
            <StatementList
              title="이 결과가 말하지 않는 것"
              items={result.synthesis.limitations}
            />
            <StatementList
              title="다음으로 확인할 수 있는 것"
              items={result.synthesis.nextChecks}
              locators={locators}
            />
            <StatementList
              title="알 수 없는 것"
              items={result.synthesis.uncertainties}
            />

            {/*
              생성물임을 본문 끝에서 다시 밝힌다. provenance는 어느 모델이
              언제 만들었는지 추적할 수 있게 그대로 보여준다.
            */}
            {result.provenance ? (
              <p className="border-t border-border pt-3 text-caption text-text-muted">
                이 설명은 {result.provenance.provider}가 생성한 AI 결과입니다 ·
                {' '}
                {result.provenance.models.join(', ') || '모델 미상'} ·{' '}
                {result.provenance.generatedAt}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
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

function StatementList({
  title,
  items,
  locators,
}: {
  title: string
  items: SynthesisStatement[]
  /** 주어지면 문장 안의 내부 locator를 사람 말로 바꾼다. nextChecks만 쓴다. */
  locators?: LocatorResolver
}) {
  if (items.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-small font-medium text-text-strong">{title}</h3>
      <ul className="flex flex-col gap-3">
        {items.map((item, index) => {
          const shown = locators
            ? humanizeLocators(item.statement, locators)
            : item.statement
          return (
            <li key={index} className="flex flex-col gap-1">
              <span className="max-w-prose text-small text-text">{shown}</span>
              <EvidenceRefs refs={item.evidenceRefs} raw={item.statement} shown={shown} />
            </li>
          )
        })}
      </ul>
    </section>
  )
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
    <details className="max-w-prose">
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
