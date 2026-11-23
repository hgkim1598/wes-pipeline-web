/*
  실행 목록 머리의 상태 요약 한 줄.

  KPI 카드가 아니다. 목록을 읽기 전에 "지금 진행 중인 것·멈춘 것이 있는가"를
  알려 주는 문장이다. 개수는 GET /api/jobs 응답을 센 것뿐이고, 응답에 없는
  상태는 쓰지 않는다(0건 항목을 만들지 않는다).

  순서는 주의가 필요한 순서다: 진행 중 → 대기 → 실패 → 경고 → 완료 → 취소.
  모르는 상태는 원문 그대로 맨 뒤에 둔다(status.ts의 describeJobStatus).

  React·경로 별칭을 쓰지 않는다: scripts/entry-model.test.mjs가 node로 읽는다.
*/

import { describeJobStatus } from './status.ts'
import type { StatusTone } from '../../components/ui/StatusBadge.tsx'

export interface StatusCount {
  status: string
  tone: StatusTone
  label: string
  count: number
}

const ORDER = ['running', 'queued', 'failed', 'completed_with_warnings', 'completed', 'cancelled']

export function summarizeStatuses(jobs: readonly { status: string }[]): StatusCount[] {
  const counts = new Map<string, number>()
  for (const job of jobs) counts.set(job.status, (counts.get(job.status) ?? 0) + 1)
  const rank = (status: string) => {
    const i = ORDER.indexOf(status)
    return i === -1 ? ORDER.length : i
  }
  return [...counts.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([status, count]) => ({ status, count, ...describeJobStatus(status) }))
}
