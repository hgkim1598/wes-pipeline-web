import { formatTimestamp } from '@/features/runs/time'

/**
 * 갱신 신선도 표시.
 *
 * 시안 근거 (docs/design/pipeline-tab.html · POLLING INDICATOR — 3초 폴링)
 *   정상  "3초 전 갱신"
 *   지연  "갱신 지연"
 *   끊김  "연결 끊김 · 재시도 중" + 마지막 성공 시각
 *
 * 회전 스피너를 쓰지 않았다. 수 시간 실행되는 화면에서 계속 돌아가는 요소는
 * CLAUDE.md 23·27장이 금지하는 반복 모션이고, 여기서 전달할 정보는 "언제
 * 갱신됐는가" 하나라서 텍스트로 충분하다.
 *
 * 폴링이 멈춘 뒤(terminal)에는 아무것도 보여주지 않는다. 더 이상 갱신될 값이
 * 없는데 "3초 전 갱신"이 남아 있으면 거짓이 된다.
 */

export interface PollingStatusProps {
  /** 폴링이 동작해야 하는 상태인지. terminal이면 false. */
  active: boolean
  /** react-query의 dataUpdatedAt (epoch ms). */
  updatedAt: number
  /** 연속 실패 횟수. 0보다 크면 연결이 끊긴 것으로 본다. */
  failureCount: number
  /** 지금 요청이 진행 중인지. */
  isFetching: boolean
}

export function PollingStatus({
  active,
  updatedAt,
  failureCount,
  isFetching,
}: PollingStatusProps) {
  if (!active) return null

  if (failureCount > 0) {
    const last = formatTimestamp(new Date(updatedAt).toISOString())
    return (
      <span className="text-caption text-status-warning-fg">
        연결 끊김 · 재시도 중
        {last ? <span className="text-text-muted"> · {last.display} 기준</span> : null}
      </span>
    )
  }

  return (
    <span className="text-caption text-text-muted">
      {isFetching ? '갱신 중' : `${secondsAgo(updatedAt)}초 전 갱신`}
    </span>
  )
}

/**
 * 마지막 갱신으로부터 몇 초.
 *
 * 매초 다시 렌더링하지 않는다 — 폴링이 3초마다 데이터를 갱신하면서 이 값도 함께
 * 다시 계산되므로, 별도 타이머 없이 대략 0~3초 사이의 값이 보인다. 초 단위
 * 정확도를 위해 타이머를 하나 더 도는 것은 이 정보의 가치에 비해 과하다.
 */
function secondsAgo(updatedAt: number): number {
  if (!updatedAt) return 0
  return Math.max(0, Math.round((Date.now() - updatedAt) / 1000))
}
