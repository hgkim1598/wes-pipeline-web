import { Activity, Ban, Check, Hourglass, OctagonX, TriangleAlert } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cx } from '@/lib/cx'

/**
 * 상태 배지.
 *
 * 시안 근거 — 제품 화면에서 반복 사용된 최신(G4) 형태다.
 *   docs/design/prototype.html · pipeline-tab.html · results-precheck.html
 *   docs/design/results-full.html · wizard.html · remaining-screens.html
 *   형태 탐색 과정: docs/design/archive/badge-shapes-2.html (Track A · E안)
 *
 *   알약(--radius-pill) · padding 4/12 · gap 8 · 아이콘 16 · weight 500
 *   테두리 없음. tone의 bg/fg만으로 면을 만든다.
 *   md : body 14   sm : small 13   (그 외 값은 두 크기가 동일)
 *
 * components.html C1의 사각 배지(radius 4 · 1px 테두리 · padding 4/8)는
 * 구세대 참고안이다. 제품 화면 어디에서도 쓰이지 않는다.
 *
 * ⚠️ 렌더링 면 제약 — surface(#FFFFFF) 위에 놓아야 한다.
 *   cancelled의 배경(#F7F9FB)이 페이지 배경 paper와 **같은 값**이라,
 *   paper 위에 그대로 놓으면 알약이 보이지 않는다. 이것은 색 오류가 아니라
 *   시안이 처음부터 그렇게 정의한 값이다 — badge-shapes-2의 E안도 예외 없이
 *   `background:var(--surface)` 패널 안에서 렌더링된다.
 *   표·패널 등 surface 위에서 쓰고, paper 위에 직접 놓지 않는다.
 *
 * 색 하나로 상태를 전달하지 않는다. 아이콘 실루엣과 보이는 텍스트가 항상
 * 함께 간다. 아이콘은 장식이므로 aria-hidden이고, 의미는 children이 담당한다.
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

/** 테두리 토큰(-bd)은 쓰지 않는다. 알약은 면으로만 구분한다. */
const TONE_CLASS: Record<StatusTone, string> = {
  idle: 'text-status-idle-fg bg-status-idle-bg',
  running: 'text-status-running-fg bg-status-running-bg',
  success: 'text-status-success-fg bg-status-success-bg',
  warning: 'text-status-warning-fg bg-status-warning-bg',
  failure: 'text-status-failure-fg bg-status-failure-bg',
  cancelled: 'text-status-cancelled-fg bg-status-cancelled-bg',
}

/*
  E안 아이콘 세트.

  badge-shapes-2가 5개 후보(A~E) 중 "6종 모두 실루엣으로 갈림"으로 평가한
  세트이고, 제품 화면들이 실제로 이 path를 쓴다. 앞선 후보들은 완료·실패·취소가
  모두 원이라 "어려운 쌍"으로 기록돼 있다.
*/
const TONE_ICON: Record<StatusTone, LucideIcon> = {
  idle: Hourglass,
  running: Activity, // 파형
  success: Check,
  warning: TriangleAlert,
  failure: OctagonX,
  cancelled: Ban, // 사선 원
}

/*
  E안은 아이콘마다 stroke를 따로 준다. 체크만 2, 나머지는 1.5다.
  체크는 획이 3개뿐이라 1.5로 그리면 다른 5종보다 눈에 띄게 가늘어진다.
*/
const ICON_STROKE: Record<StatusTone, number> = {
  idle: 1.5,
  running: 1.5,
  success: 2,
  warning: 1.5,
  failure: 1.5,
  cancelled: 1.5,
}

/* 두 크기의 차이는 글자 크기뿐이다. padding·gap·아이콘은 같다. */
const SIZE_CLASS = {
  md: 'text-body',
  sm: 'text-small',
} as const

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
        'inline-flex items-center gap-2 rounded-pill py-1 font-medium whitespace-nowrap',
        // 가로 padding은 시안의 --pad-pill-x(12px)를 그대로 쓴다.
        'px-[var(--pad-pill-x)]',
        TONE_CLASS[tone],
        SIZE_CLASS[size],
        className,
      )}
    >
      <Icon
        size={16}
        strokeWidth={ICON_STROKE[tone]}
        aria-hidden="true"
        className="shrink-0"
      />
      {children}
    </span>
  )
}
