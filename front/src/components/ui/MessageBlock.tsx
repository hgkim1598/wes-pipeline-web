import { Check, Info, Triangle, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cx } from '@/lib/cx'

/**
 * 안내·경고·오류 블록.
 *
 * 시안 근거 (components.html C3)
 *   옅은 semantic 배경 · radius 4 · padding 16 · 아이콘 16 + 본문 gap 8
 *   제목 body 14/500 ink-900 · 본문 body 14/400 ink-700
 *   info는 파랑을 쓰지 않고 중립 톤(sunken)이다.
 *
 * 시안과 의도적으로 다른 점: 시안은 좌측 3px 세로 바 + 테두리 없음이지만,
 * CLAUDE.md 24항이 "두꺼운 왼쪽 세로 accent bar로 상태를 표현하지 않는다"와
 * "1px subtle border"를 명시해서 1px 전체 테두리로 구현했다.
 * 배경 tint + 아이콘 + 텍스트로 상태를 전달하는 것은 동일하다.
 *
 * role은 기본값이 없다. 정적 안내문에 role="alert"를 붙이면 스크린 리더가
 * 매번 낭독을 가로챈다. 폴링 결과로 새로 나타나는 오류처럼 즉시 알려야 하는
 * 경우에만 호출부가 alert/status를 넘긴다.
 */
export type MessageTone = 'info' | 'success' | 'warning' | 'danger'

const TONE_CLASS: Record<MessageTone, string> = {
  info: 'bg-status-info-bg border-status-info-bd',
  success: 'bg-status-success-bg border-status-success-bd',
  warning: 'bg-status-warning-bg border-status-warning-bd',
  danger: 'bg-status-failure-bg border-status-failure-bd',
}

const TONE_ICON_CLASS: Record<MessageTone, string> = {
  info: 'text-status-info-fg',
  success: 'text-status-success-fg',
  warning: 'text-status-warning-fg',
  danger: 'text-status-failure-fg',
}

const TONE_ICON: Record<MessageTone, LucideIcon> = {
  info: Info,
  success: Check,
  warning: Triangle,
  danger: X,
}

export interface MessageBlockProps {
  tone: MessageTone
  /** 없으면 본문만 있는 고정 안내 블록이 된다. */
  title?: ReactNode
  children?: ReactNode
  /** 버튼 등 후속 동작. 본문 아래에 놓인다. */
  action?: ReactNode
  /** 즉시 알려야 하는 메시지에만 지정한다. 기본값 없음. */
  role?: 'alert' | 'status'
  className?: string
}

export function MessageBlock({
  tone,
  title,
  children,
  action,
  role,
  className,
}: MessageBlockProps) {
  const Icon = TONE_ICON[tone]

  return (
    <div
      role={role}
      className={cx(
        'flex items-start gap-2 rounded-sm border p-4',
        TONE_CLASS[tone],
        className,
      )}
    >
      <Icon
        size={16}
        strokeWidth={1.5}
        aria-hidden="true"
        className={cx('mt-1 shrink-0', TONE_ICON_CLASS[tone])}
      />
      <div className="flex min-w-0 flex-col items-start gap-3">
        <div className="flex flex-col gap-1">
          {title ? (
            <span className="text-body font-medium text-text-strong">
              {title}
            </span>
          ) : null}
          {children ? (
            <div className="text-body text-text">{children}</div>
          ) : null}
        </div>
        {action}
      </div>
    </div>
  )
}
