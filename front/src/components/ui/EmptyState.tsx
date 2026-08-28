import type { ReactNode } from 'react'

import { cx } from '@/lib/cx'

/**
 * 빈 화면.
 *
 * 시안 근거 (components.html C4)
 *   1px ink-100 테두리 · radius 8 · padding 64/24 · gap 12
 *   아이콘 32 · 제목 h3 600 · 설명 small ink-500 · 액션 선택
 *
 * 이 제품에서 가운데 정렬을 쓰는 유일한 component다.
 * 문구는 상태 설명이 아니라 다음 행동을 적는다(PLAN 9-3).
 */
export interface EmptyStateProps {
  /** 32px 기준의 아이콘. 장식이므로 호출부에서 aria-hidden으로 넘긴다. */
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cx(
        'flex flex-col items-center gap-3 rounded-md border border-border-subtle px-6 py-16 text-center',
        className,
      )}
    >
      {/* 텍스트가 아닌 장식 그래픽이라 팔레트 값을 직접 쓴다(시안과 동일). */}
      {icon ? <span className="text-ink-400">{icon}</span> : null}
      <span className="text-h3 font-semibold text-text-strong">{title}</span>
      {description ? (
        <span className="text-small text-text-muted">{description}</span>
      ) : null}
      {action}
    </div>
  )
}
