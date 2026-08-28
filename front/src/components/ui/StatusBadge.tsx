import { Check, Circle, CircleSlash, Contrast, Triangle, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cx } from '@/lib/cx'

/**
 * 상태 배지.
 *
 * 시안 근거 (components.html C1)
 *   md : body 14/500 · icon 16 · padding 4/8 · radius 4 · 1px border
 *   sm : caption 12/400 · icon 12 · padding 2/6 · 표 셀용
 *
 * 색 하나로 상태를 전달하지 않는다. 아이콘 실루엣(원·반원·체크·삼각형·
 * 엑스·사선원)과 보이는 텍스트가 항상 함께 간다. 아이콘은 장식이므로
 * aria-hidden이고, 의미는 children 텍스트가 담당한다.
 *
 * 이 component는 backend 상태 문자열을 알지 못한다.
 * job/step/check 상태 → tone 변환은 이후 registry 계층이 담당한다.
 */
export type StatusTone =
  | 'idle'
  | 'running'
  | 'success'
  | 'warning'
  | 'failure'
  | 'cancelled'

const TONE_CLASS: Record<StatusTone, string> = {
  idle: 'text-status-idle-fg bg-status-idle-bg border-status-idle-bd',
  running:
    'text-status-running-fg bg-status-running-bg border-status-running-bd',
  success:
    'text-status-success-fg bg-status-success-bg border-status-success-bd',
  warning:
    'text-status-warning-fg bg-status-warning-bg border-status-warning-bd',
  failure:
    'text-status-failure-fg bg-status-failure-bg border-status-failure-bd',
  cancelled:
    'text-status-cancelled-fg bg-status-cancelled-bg border-status-cancelled-bd',
}

const TONE_ICON: Record<StatusTone, LucideIcon> = {
  idle: Circle,
  running: Contrast, // 반쯤 채워진 원
  success: Check,
  warning: Triangle,
  failure: X,
  cancelled: CircleSlash,
}

const SIZE_CLASS = {
  md: 'gap-2 px-2 py-1 text-body font-medium',
  sm: 'gap-2 px-1.5 py-0.5 text-caption',
} as const

const ICON_PX = { md: 16, sm: 12 } as const

export interface StatusBadgeProps {
  tone: StatusTone
  /** 보이는 상태 텍스트. 색만으로 상태를 전달하지 않기 위해 필수다. */
  children: ReactNode
  size?: 'md' | 'sm'
  className?: string
}

export function StatusBadge({
  tone,
  children,
  size = 'md',
  className,
}: StatusBadgeProps) {
  const Icon = TONE_ICON[tone]

  return (
    <span
      className={cx(
        'inline-flex items-center rounded-sm border',
        TONE_CLASS[tone],
        SIZE_CLASS[size],
        className,
      )}
    >
      <Icon
        size={ICON_PX[size]}
        strokeWidth={1.5}
        aria-hidden="true"
        className="shrink-0"
      />
      {children}
    </span>
  )
}
