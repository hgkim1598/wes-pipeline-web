/*
  step status → 화면 어휘.

  features/runs/status.ts가 job status를 맡는 것과 같은 역할이며, 값이 다르므로
  합치지 않는다. 근거: backend/app/schemas.py의 StepStatus
    pending · running · completed · warning · failed · skipped

  pending과 running은 backend가 계획에서 유도한 값이다 — main.sh는 끝난 step만
  문서를 쓰므로 디스크에 그 두 상태는 존재하지 않는다(run_status_reader의 주석).

  tag는 시안(docs/design/pipeline-tab.html)의 mono 대문자 표기를 따른다.
  step 행은 배지 대신 이 tag를 쓴다 — 8행에 알약을 8개 늘어놓으면 표의 밀도가
  깨지고, CLAUDE.md 23장이 경계하는 "배지 남발"이 된다.
*/

import type { StatusTone } from '@/components/ui/StatusBadge'

export interface StepStatusView {
  tone: StatusTone
  /** 표 왼쪽 mono tag. */
  tag: string
  /** 배지·문장에 쓰는 한국어 라벨. */
  label: string
}

const STEP_STATUS_VIEW: Record<string, StepStatusView> = {
  pending: { tone: 'idle', tag: 'QUEUED', label: '대기 중' },
  running: { tone: 'running', tag: 'RUNNING', label: '진행 중' },
  completed: { tone: 'success', tag: 'COMPLETED', label: '완료' },
  warning: { tone: 'warning', tag: 'WARNING', label: '완료 (경고)' },
  failed: { tone: 'failure', tag: 'FAILED', label: '실패' },
  skipped: { tone: 'cancelled', tag: 'SKIPPED', label: '건너뜀' },
}

/** 모르는 상태는 중립 tone + 원문. 성공이나 실패로 오독하게 만들지 않는다. */
export function describeStepStatus(status: string): StepStatusView {
  return (
    STEP_STATUS_VIEW[status] ?? {
      tone: 'idle',
      tag: status.toUpperCase() || 'UNKNOWN',
      label: status || '알 수 없음',
    }
  )
}

/** 실행 중인 단계인지. polling 대상 판단에 쓴다. */
export function isStepRunning(status: string): boolean {
  return status === 'running'
}

/** 문제가 있는 단계인지. 화면이 먼저 보여줘야 하는 행이다. */
export function isStepProblem(status: string): boolean {
  return status === 'failed' || status === 'warning'
}
