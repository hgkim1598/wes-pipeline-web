import { Info } from 'lucide-react'

import type { Limitation } from '@/features/run-detail/api'

/*
  결과를 볼 때의 범위 제한.

  ── 이 문장들은 어디서 오는가 ───────────────────────────────────────────

  backend의 deterministic explanation이 만든다. **AI가 생성한 것이 아니다** —
  structured field 하나가 특정 값일 때 고정 문장이 선택되고, 같은 실행이면
  항상 같은 문장이 온다. 예:

    variantCalling.filteringApplied === false  ->  "품질 필터가 적용되지 않았습니다…"
    outcome.analysisOutputProduced === false   ->  "분석 산출물을 만들지 않았습니다."
    intendedUse 존재                            ->  파이프라인 원문 그대로

  ── frontend에서 다시 해석하지 않는다 ──────────────────────────────────

  statement를 그대로 렌더링한다. 여기서 문장을 고르거나 바꾸면 backend가
  기록한 `basis`(어느 field가 그 문장을 골랐는지)와 화면이 어긋난다.
  화면에 basis를 노출하지는 않지만, 응답에는 남아 있어 나중에 근거 표시를
  붙일 수 있다.

  ── 왜 진단(diagnostics)과 별도인가 ────────────────────────────────────

  진단은 "이번 실행에서 일어난 사건"이고, 이것은 "결과를 어디까지 쓸 수
  있는가"다. 필터를 적용하지 않은 것은 사건이 아니라 조건이다. 두 가지를 한
  목록에 섞으면 사용자가 무엇에 대응해야 하는지 알 수 없게 된다.
*/

export interface RunLimitationsProps {
  limitations: Limitation[]
}

export function RunLimitations({ limitations }: RunLimitationsProps) {
  if (limitations.length === 0) return null

  return (
    <section
      className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4"
      aria-labelledby="run-limitations-heading"
    >
      <div className="flex items-center gap-2">
        <Info
          size={14}
          strokeWidth={1.5}
          aria-hidden="true"
          className="flex-none text-text-muted"
        />
        <h2
          id="run-limitations-heading"
          className="text-body font-medium text-text-strong"
        >
          이 결과를 볼 때 유의할 점
        </h2>
        <span className="text-small text-text-muted">
          {limitations.length}건
        </span>
      </div>

      <ul className="flex flex-col gap-2">
        {limitations.map((limitation) => (
          <li
            key={limitation.code}
            className="max-w-prose text-body text-text before:mr-2 before:text-text-muted before:content-['·']"
          >
            {limitation.statement}
          </li>
        ))}
      </ul>
    </section>
  )
}
