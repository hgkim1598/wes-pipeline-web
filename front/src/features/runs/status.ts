/*
  backend job status → 화면 어휘.

  StatusBadge는 backend 상태 문자열을 알지 못하도록 만들어져 있다
  (components/ui/StatusBadge.tsx). 그 변환을 이 한 곳에 모은다. 화면 코드가
  'completed_with_warnings' 같은 문자열을 직접 비교하기 시작하면 상태가
  하나 늘 때 고쳐야 할 곳이 흩어진다.

  근거: backend/app/schemas.py 의 JobStatus
    queued · running · completed · completed_with_warnings · failed · cancelled

  tone 대응은 styles/tokens.css의 상태 팔레트 주석과 같다.
*/

import type { StatusTone } from '@/components/ui/StatusBadge'

export interface JobStatusView {
  tone: StatusTone
  /** 배지에 보이는 문구. 색만으로 상태를 전달하지 않기 위해 항상 함께 쓴다. */
  label: string
}

/*
  completed_with_warnings의 문구를 "완료 (경고)"로 줄였다.
  목록 행의 상태 열은 132px(시안 --col-run-badge)이고, "완료 (경고 있음)"은
  그 폭을 넘겨 열 정렬이 행마다 흔들린다. 경고의 성격은 실행 상세에서
  설명하고, 목록에서는 "완료됐지만 경고가 있다"만 전달하면 충분하다.
*/
const JOB_STATUS_VIEW: Record<string, JobStatusView> = {
  queued: { tone: 'idle', label: '대기 중' },
  running: { tone: 'running', label: '분석 중' },
  completed: { tone: 'success', label: '완료' },
  completed_with_warnings: {
    tone: 'warning',
    label: '완료 (경고)',
  },
  failed: { tone: 'failure', label: '실패' },
  cancelled: { tone: 'cancelled', label: '취소됨' },
}

/*
  terminal 상태 — 더 이상 바뀌지 않는 상태.

  polling을 멈출 시점이자, 결과·산출물을 요청해도 되는 시점이다. 판단이
  화면마다 흩어지면 어떤 화면은 영원히 폴링하고 어떤 화면은 너무 일찍 멈춘다.
  근거: backend/app/schemas.py의 JobStatus 6종 중 queued·running만 진행 중이다.
*/
const ACTIVE_STATUSES = ['queued', 'running'] as const

/**
 * 더 이상 바뀌지 않는 상태인가.
 *
 * queued·running만 진행 중으로 보고 나머지는 전부 terminal로 취급한다.
 * 모르는 상태를 terminal 쪽에 두는 것은 의도다 — 반대로 두면 backend가 상태를
 * 하나 추가했을 때 화면이 영원히 3초마다 서버를 두드린다. 멈춘 화면은
 * 사용자가 새로고침으로 복구할 수 있지만 끝나지 않는 폴링은 그럴 수 없다.
 */
export function isTerminalStatus(status: string): boolean {
  return !ACTIVE_STATUSES.some((active) => active === status)
}

/**
 * 모르는 상태가 와도 화면을 세우지 않는다.
 *
 * backend가 상태를 추가했는데 frontend가 아직 모르는 경우, 임의의 의미를
 * 붙이는 대신 원문을 그대로 보여준다. 중립 tone을 쓰는 것은 모르는 값을
 * 성공이나 실패로 오독하게 만들지 않기 위해서다.
 */
export function describeJobStatus(status: string): JobStatusView {
  const known = JOB_STATUS_VIEW[status]
  if (known) return known

  return { tone: 'idle', label: status || '알 수 없음' }
}
