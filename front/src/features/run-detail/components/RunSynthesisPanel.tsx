import { useMutation } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { createSynthesis } from '@/features/run-detail/api'
import type { SynthesisStatement } from '@/features/run-detail/api'

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
   * 실행이 끝났는가.
   *
   * 끝나지 않은 실행은 종합할 대상이 아직 확정되지 않았다. 진행 중에 만든
   * 설명은 다음 단계가 끝나는 순간 낡은 것이 되고, 사용량만 쓴다.
   */
  terminal: boolean
}

export function RunSynthesisPanel({ jobId, terminal }: RunSynthesisPanelProps) {
  const synthesis = useMutation({
    mutationFn: () => createSynthesis(jobId),
    // 재시도 없음. 위 주석 참고.
    retry: false,
  })

  const result = synthesis.data

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
          진행 상태는 aria-live로 알린다. 버튼 라벨 변화만으로는 스크린리더
          사용자가 요청이 시작된 것을 알 수 없다.
        */}
        <p aria-live="polite" className="sr-only">
          {synthesis.isPending ? 'AI 설명을 생성하는 중입니다' : ''}
        </p>

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

function StatementList({
  title,
  items,
}: {
  title: string
  items: SynthesisStatement[]
}) {
  if (items.length === 0) return null
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-small font-medium text-text-strong">{title}</h3>
      <ul className="flex flex-col gap-2">
        {items.map((item, index) => (
          <li key={index} className="flex flex-col gap-0.5">
            <span className="max-w-prose text-small text-text">
              {item.statement}
            </span>
            {/*
              근거 id를 그대로 노출한다. 사용자에게 예쁜 이름은 아니지만,
              이 단계에서 중요한 것은 "이 문장이 무엇에 근거했는가"를 사람이
              대조할 수 있다는 것이다. 표기 개선은 backlog다.
            */}
            <span className="font-mono text-caption text-text-muted">
              {item.evidenceRefs.join(' · ')}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
