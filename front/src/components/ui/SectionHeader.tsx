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
        // 좁은 화면에서 액션이 다음 줄로 내려갈 수 있게 wrap을 허용한다.
        // 한 줄일 때의 간격(gap-x-4)은 그대로 두고, 줄이 나뉘었을 때만
        // 세로 간격이 생긴다.
        'flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-border-subtle pb-4',
        className,
      )}
    >
      {/*
        basis-64가 줄바꿈 기준이다. 제목 영역에 이만큼도 남지 않으면
        제목을 몇 글자로 찌그러뜨리는 대신 액션이 아래로 내려간다.
        min-w-0이 있어야 긴 문자열이 부모 밖으로 밀고 나가지 않는다.
      */}
      <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
        {eyebrow ? (
          <span className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
            {eyebrow}
          </span>
        ) : null}
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          {/*
            run id·파일명처럼 공백 없는 식별자가 들어온다. truncate로 정보를
            숨기지 않고 줄을 넘긴다. break-all이 아니라 overflow-wrap이라
            끊을 곳이 있으면 단어 단위를 지킨다.

            min-w-0이 flex item에도 필요하다. 없으면 min-width:auto가
            min-content(=끊기지 않는 문자열 전체 폭)로 풀려서 break-words가
            동작할 기회 자체가 없고 페이지가 가로로 밀린다.
          */}
          <Heading className="min-w-0 text-h2 font-semibold break-words text-text-strong">
            {title}
          </Heading>
          {meta ? (
            <span className="min-w-0 text-small break-words text-text-muted">
              {meta}
            </span>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}
