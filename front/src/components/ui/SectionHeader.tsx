import type { ReactNode } from 'react'

import { cx } from '@/lib/cx'

/**
 * 섹션 제목.
 *
 * 시안 근거 (components.html C5)
 *   하단 1px ink-100 구분선 · padding-bottom 16
 *   eyebrow(선택) · 제목 h2 크기 600 · 부가 정보 small ink-500 · 우측 액션
 *
 * 제목 태그는 화면의 문서 구조에 맞춰 level로 고른다. 크기는 h2 스케일로
 * 고정되어 있어서 태그를 바꿔도 시각 결과는 같다.
 *
 * 알려진 미구현: 시안은 "한글 eyebrow는 Condensed 대신 본문 서체 600 ·
 * 12px · 자간 +0.06em"이라는 별도 규칙을 둔다. 지금은 영문·숫자 eyebrow
 * 처리만 있고, 한글 eyebrow가 실제로 필요한 화면에서 이 축을 추가한다.
 */
export interface SectionHeaderProps {
  /** 영문·숫자 라벨. Condensed + 대문자로 렌더링된다. */
  eyebrow?: ReactNode
  title: ReactNode
  /** 개수나 부제처럼 제목 옆에 붙는 짧은 정보. */
  meta?: ReactNode
  action?: ReactNode
  level?: 2 | 3
  className?: string
}

export function SectionHeader({
  eyebrow,
  title,
  meta,
  action,
  level = 2,
  className,
}: SectionHeaderProps) {
  const Heading = level === 2 ? 'h2' : 'h3'

  return (
    <div
      className={cx(
        'flex items-baseline justify-between gap-4 border-b border-border-subtle pb-4',
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        {eyebrow ? (
          <span className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
            {eyebrow}
          </span>
        ) : null}
        <div className="flex items-baseline gap-3">
          <Heading className="text-h2 font-semibold text-text-strong">
            {title}
          </Heading>
          {meta ? (
            <span className="text-small text-text-muted">{meta}</span>
          ) : null}
        </div>
      </div>
      {action}
    </div>
  )
}
