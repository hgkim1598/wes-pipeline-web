import { Tabs } from '@base-ui/react/tabs'
import type { ReactNode } from 'react'

import { cx } from '@/lib/cx'

/**
 * 탭.
 *
 * 시안 근거 (prototype.html 워크스페이스 탭)
 *   목록 : 하단 1px ink-200 구분선 · gap 24 · 가로 스크롤
 *   탭   : min-height 24(hit) · padding 12/0 · body 14/500
 *   선택 : ink-900 글자 + 2px brand 밑줄 (색과 밑줄 두 채널)
 *
 * roving tabindex, 좌우/Home/End 키 이동, aria-selected, panel 연결은
 * Base UI가 담당한다. div + onClick으로 흉내내지 않는다.
 *
 * 좁은 화면(md 48rem 미만 — 이 프로젝트는 sm 구간이 없다, tokens.css)에서는 간격을 16으로 줄인다(2026-11-23, 개발판단기록 54장).
 * 390px에서 Run 탭 다섯 개가 한 줄에 모두 들어가게 해 "파일" 탭이 스크롤 밖에
 * 숨지 않게 한다. 가로 스크롤은 더 좁은 화면을 위한 마지막 안전장치로 남긴다
 * (키보드로 탭에 포커스가 가면 브라우저가 그 탭을 보이는 곳으로 옮긴다).
 *
 * 실제 라우팅 연결(워크스페이스 5개 탭)은 App Shell 단계에서 한다.
 * 여기서는 표현과 키보드 동작만 감싼다.
 */

export function TabsRoot({
  value,
  defaultValue,
  onValueChange,
  className,
  children,
}: {
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  className?: string
  children: ReactNode
}) {
  return (
    <Tabs.Root
      value={value}
      defaultValue={defaultValue}
      onValueChange={(next) => {
        // Base UI의 값 타입은 any이고, 선택할 수 있는 탭이 없을 때
        // 자동 변경(reason: initial/disabled/missing)으로 null이 올 수 있다.
        // String()으로 감싸면 그 null이 "null" 문자열이 되어 탭 id처럼
        // 흘러간다. 이 wrapper는 문자열 탭 id만 밖으로 내보낸다.
        if (typeof next === 'string') {
          onValueChange?.(next)
        }
      }}
      className={className}
    >
      {children}
    </Tabs.Root>
  )
}

export function TabsList({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <Tabs.List
      className={cx(
        'flex items-end gap-4 overflow-x-auto border-b border-border md:gap-6',
        className,
      )}
    >
      {children}
    </Tabs.List>
  )
}

export function TabsTab({
  value,
  className,
  children,
}: {
  value: string
  className?: string
  children: ReactNode
}) {
  return (
    <Tabs.Tab
      value={value}
      className={cx(
        // 밑줄은 비활성일 때도 자리를 차지해서 선택 시 레이아웃이 밀리지 않는다.
        'min-h-6 flex-none border-b-2 border-transparent py-3 text-body font-medium whitespace-nowrap',
        'text-text-muted hover:text-text-strong',
        'data-[active]:border-brand data-[active]:text-text-strong',
        // 목록이 가로 스크롤 컨테이너라 overflow-y가 visible이 될 수 없고,
        // 바깥으로 나가는 포커스 링은 위아래가 잘린다. 링을 안쪽으로 그린다.
        'focus-visible:-outline-offset-2',
        className,
      )}
    >
      {children}
    </Tabs.Tab>
  )
}

export function TabsPanel({
  value,
  className,
  children,
}: {
  value: string
  className?: string
  children: ReactNode
}) {
  return (
    <Tabs.Panel value={value} className={cx('pt-4', className)}>
      {children}
    </Tabs.Panel>
  )
}
