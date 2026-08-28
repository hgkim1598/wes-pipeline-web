import type { ButtonHTMLAttributes } from 'react'

import { cx } from '@/lib/cx'

/**
 * 버튼.
 *
 * 시안 근거 (prototype.html)
 *   height 32(--btn-h) · padding 0 16 · radius 4 · body 14/500
 *   primary   : brand-600 배경 + surface 글자
 *   secondary : surface 배경 + border-strong 1px + ink-900 글자
 *   disabled  : ink-100 배경 + ink-400 글자
 *
 * 크기 축을 두지 않았다. 시안 전체가 --btn-h 하나만 쓴다.
 * 아이콘은 children으로 넣으면 gap이 붙는다. 아이콘만 넣는 경우
 * aria-label로 이름을 주어야 한다.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'danger'

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    'bg-brand text-surface hover:bg-brand-hover active:bg-brand-active',
  // 시안이 secondary/danger의 눌림 상태를 정의하지 않아 hover까지만 둔다.
  secondary:
    'bg-surface text-text-strong border border-border-strong hover:bg-sunken',
  // 시안에 렌더링된 danger 버튼이 없어 기존 status-failure 토큰으로 구성했다.
  // 화면당 primary는 하나이므로 파괴적 동작도 solid가 아닌 outline으로 둔다.
  danger:
    'bg-surface text-status-failure-fg border border-status-failure-bd hover:bg-status-failure-bg',
}

const BASE_CLASS =
  'inline-flex h-8 items-center justify-center gap-2 rounded-sm px-4 text-body font-medium whitespace-nowrap ' +
  'disabled:cursor-not-allowed disabled:border-transparent disabled:bg-surface-disabled disabled:text-text-disabled'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

export function Button({
  variant = 'secondary',
  type = 'button',
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      // 명시하지 않으면 form 안에서 submit으로 동작한다. 기본을 button으로 둔다.
      type={type}
      className={cx(BASE_CLASS, VARIANT_CLASS[variant], className)}
      {...props}
    />
  )
}
