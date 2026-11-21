import {
  Activity,
  Ban,
  Check,
  CircleDashed,
  CircleHelp,
  Hourglass,
  OctagonX,
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

/** StatusBadge와 같은 아이콘 세트. warning은 "완료"로 쓰므로 체크다. */
const STATUS_ICON: Record<StatusTone, LucideIcon> = {
  idle: Hourglass,
  running: Activity,
  success: Check,
  warning: Check,
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
    // warning도 사용자에게는 완료다. 경고의 존재는 진단 줄이 말한다.
    label: status === 'warning' ? '완료' : view.label,
    icon: STATUS_ICON[view.tone] ?? Hourglass,
  }
}
