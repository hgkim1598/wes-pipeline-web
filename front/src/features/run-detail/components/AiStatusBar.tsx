import { Sparkles } from 'lucide-react'

import { GATE_REJECTIONS, SYNTHESIS_PANEL_ID } from '@/features/run-detail/aiStatement'
import type { StatementPlacement } from '@/features/run-detail/synthesisPlacement'
import type { RunSynthesisState } from '@/features/run-detail/useRunSynthesis'
import { formatTimestamp } from '@/features/runs/time'

/*
  AI 해설의 상태 한 줄 — 헤더 바로 아래.

  각 항목 옆 AI 해설은 있을 때만 그려진다. 그래서 "없다"와 "아직 요청하지
  않았다"와 "검사에서 버려졌다"를 항목 옆에서는 구분할 수 없다. 그 차이를
  이 줄 하나가 말한다. 요청 버튼은 기존 "AI 종합 설명" 패널에 그대로 있고,
  여기서는 그곳으로 이동만 한다 — 사용량을 쓰는 버튼을 두 곳에 두지 않는다.

  숫자는 배분 결과(synthesisPlacement.ts)를 그대로 센다. 연결하지 못한 문장도
  패널에는 모두 있다는 것을 함께 적는다.
*/

export function AiStatusBar({
  synthesis,
  terminal,
  placement,
  explanationAvailable,
}: {
  synthesis: RunSynthesisState
  terminal: boolean
  /** 답변이 있고 실행 설명을 읽었을 때만 있다. */
  placement: StatementPlacement | null
  /** 실행 설명(GET /explanation)을 읽었는가. 없으면 항목을 확인할 수 없다. */
  explanationAvailable: boolean
}) {
  const { result } = synthesis
  let message: string
  let detail: string | null = null

  if (synthesis.isPending) {
    message = 'AI 해설을 생성하고 있습니다. 끝나면 관련 항목 옆에도 표시됩니다.'
  } else if (synthesis.isError) {
    message = 'AI 해설 요청이 실패했습니다. 이유는 아래 AI 종합 설명에 있습니다.'
  } else if (result && !result.available) {
    message =
      result.errorCategory && GATE_REJECTIONS.has(result.errorCategory)
        ? 'AI 해설이 안전 검사에서 폐기되어 표시하지 않습니다.'
        : 'AI 해설을 사용할 수 없습니다.'
    detail = result.errorCategory
  } else if (result?.available && result.synthesis) {
    if (placement && explanationAvailable) {
      const total = placement.statements.length
      const rest = placement.unplaced.length
      message = `AI 해설 ${total}개 중 ${placement.placedCount}개를 근거 기록이 확인된 항목 옆에 표시했습니다.`
      detail =
        rest > 0
          ? `${rest}개와 요약은 연결할 항목을 근거 id로 확인할 수 없어 AI 종합 설명에만 있습니다.`
          : '요약은 근거 id가 없어 AI 종합 설명에만 있습니다.'
    } else {
      message = 'AI 해설이 있습니다. 실행 설명을 읽지 못해 항목 옆에는 표시하지 않았습니다.'
    }
    const generated = result.provenance
      ? formatTimestamp(result.provenance.generatedAt)
      : null
    if (result.provenance) {
      const models = result.provenance.models.join(', ') || '모델 미상'
      // 저장본이면 몇 번째인지 함께 적는다(개발판단기록 66장).
      const stored =
        synthesis.source === 'stored' && result.storedVersion != null
          ? `저장된 설명 v${result.storedVersion} · `
          : ''
      detail = [detail, `${stored}${models} · 생성 ${generated ? generated.full : result.provenance.generatedAt}`]
        .filter(Boolean)
        .join(' ')
    }
  } else if (!terminal) {
    message = 'AI 해설은 실행이 끝난 뒤 요청할 수 있습니다.'
  } else {
    message = 'AI 해설이 없습니다. AI 종합 설명에서 요청하면 관련 항목 옆에도 표시됩니다.'
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-y border-border-subtle py-2"
    >
      <span className="flex items-center gap-1 text-small font-medium text-text-strong">
        <Sparkles size={14} strokeWidth={1.5} aria-hidden="true" />
        AI 해설
      </span>
      <span className="text-small text-text">{message}</span>
      {detail ? (
        <span className="text-caption text-text-muted">{detail}</span>
      ) : null}
      {/* URL hash를 바꾸지 않는다 — 탭이 URL 세그먼트라 주소는 그대로 둔다. */}
      <button
        type="button"
        onClick={() =>
          document
            .getElementById(SYNTHESIS_PANEL_ID)
            ?.scrollIntoView({ block: 'start' })
        }
        className="ml-auto inline-flex min-h-6 items-center text-caption text-text-muted underline underline-offset-2 hover:text-brand"
      >
        AI 종합 설명으로
      </button>
    </div>
  )
}
