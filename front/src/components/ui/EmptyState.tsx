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
  /**
   * 제목. heading으로 렌더링되므로 markup이 아닌 문자열만 받는다.
   * ReactNode를 받으면 호출부가 heading을 넘겨 span > h2 같은 구조가 생긴다.
   */
  title: string
  /**
   * 제목의 heading 단계. 이 화면의 문서 구조에 맞춰 고른다.
   * 페이지 본문을 통째로 대신하면 2, 이미 섹션 제목이 있는 안쪽이면 3.
   */
  titleLevel?: 2 | 3
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon,
  title,
  titleLevel = 2,
  description,
  action,
  className,
}: EmptyStateProps) {
  const Heading = titleLevel === 3 ? 'h3' : 'h2'

  return (
    <div
      className={cx(
        'flex flex-col items-center gap-3 rounded-md border border-border-subtle px-6 py-16 text-center',
        className,
      )}
    >
      {/* 텍스트가 아닌 장식 그래픽이라 팔레트 값을 직접 쓴다(시안과 동일). */}
      {icon ? <span className="text-ink-400">{icon}</span> : null}
      {/* 크기는 h3 스케일로 고정이라 heading 단계를 바꿔도 시각 결과는 같다. */}
      <Heading className="text-h3 font-semibold text-text-strong">
        {title}
      </Heading>
      {description ? (
        <span className="text-small text-text-muted">{description}</span>
      ) : null}
      {action}
    </div>
  )
}
