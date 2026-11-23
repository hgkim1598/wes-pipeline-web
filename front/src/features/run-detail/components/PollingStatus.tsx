import type { ConnectionState } from '@/features/run-detail/runDetailPolicy'
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
 *
 * "끊김"은 다음 요청이 성공할 때까지 유지된다(runDetailPolicy.connectionState).
 * 화면은 마지막 성공 값을 계속 보여 주므로, 그 값이 언제 것인지 여기서 알린다.
 */

export interface PollingStatusProps {
  /** 폴링이 동작해야 하는 상태인지. terminal이면 false. */
  active: boolean
  /** react-query의 dataUpdatedAt (epoch ms). */
  updatedAt: number
  /** 마지막 요청의 결과(runDetailPolicy.connectionState). */
  connection: ConnectionState
}

export function PollingStatus({ active, updatedAt, connection }: PollingStatusProps) {
  if (!active) return null

  if (connection === 'disconnected') {
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
      {connection === 'refreshing' ? '갱신 중' : `${secondsAgo(updatedAt)}초 전 갱신`}
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
