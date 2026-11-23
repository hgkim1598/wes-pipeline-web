import {
  Activity,
  Ban,
  Check,
  CircleDashed,
  CircleHelp,
  Hourglass,
  OctagonX,
  TriangleAlert,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import type { StatusTone } from '@/components/ui/StatusBadge'
import { describeStepStatus } from '@/features/run-detail/stepStatus'
import {
  NOT_RUN_LABEL,
  UNDETERMINED_LABEL,
  isNotRun,
  isUndetermined,
} from '@/features/run-detail/stepView'

/*
  단계 상태의 화면 표시(아이콘 + 글자 + tone). 파이프라인 목록과 상세 패널이
  같이 쓴다. component 파일에 두면 fast refresh 규칙에 걸려 따로 둔다.
*/

/**
 * StatusBadge와 거의 같은 아이콘 세트. 단계의 warning만 다르다: 끝났지만 경고가 남은
 * 단계를 완료와 같은 체크로 그리면 색 하나로만 구분된다(CLAUDE.md 24장). 2026-11-23
 * 실제 완료 Run(04·05·06 단계 warning)에서 확인했다(개발판단기록 61장).
 */
const STATUS_ICON: Record<StatusTone, LucideIcon> = {
  idle: Hourglass,
  running: Activity,
  success: Check,
  warning: TriangleAlert,
  failure: OctagonX,
  cancelled: Ban,
}

/** 목록·상세 패널이 같이 쓰는 상태 표시 값. */
export function stepStatusDisplay(
  status: string,
  terminal: boolean,
  /** backend 장부의 실행 상태(factApplicability.ts). 있으면 pending 해석보다 우선한다. */
  execution?: string,
): { tone: StatusTone; label: string; icon: LucideIcon } {
  const view = describeStepStatus(status)
  if (isUndetermined(execution)) {
    // 실행됨·실행 안 됨 어느 쪽으로도 쓰지 않는다.
    return { tone: 'idle', label: UNDETERMINED_LABEL, icon: CircleHelp }
  }
  if (isNotRun(status, terminal, execution)) {
    return { tone: 'idle', label: NOT_RUN_LABEL, icon: CircleDashed }
  }
  return {
    tone: view.tone,
    // warning은 "완료 (경고)"다(stepStatus.ts). 단계는 끝났지만 확인할 경고가 있다.
    label: view.label,
    icon: STATUS_ICON[view.tone] ?? Hourglass,
  }
}
