import { useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router'
import type { LucideIcon } from 'lucide-react'
import {
  BookOpenCheck,
  GitCompareArrows,
  Activity,
  ListChecks,
  Menu,
  PlusCircle,
  Workflow,
  X,
} from 'lucide-react'

import { useEvalCompareAvailable } from '@/features/eval-compare/queries'
import { useHealthQuery } from '@/features/health/useHealthQuery'
import { cx } from '@/lib/cx'

/*
  앱 공통 사이드바 (2026-11-20 사용자 승인 밝은 워크스페이스 시안 · 개발판단기록 41장).

  ── 역할 구분 ───────────────────────────────────────────────────────────

  사이드바는 **서비스 전체** 이동이다(실행 목록 · 새 분석 · 서버 상태 · 준비
  안내). Run 하나 안의 개요·파이프라인·공식 문서·AI 설명·파일은 Run 헤더 아래
  탭이 맡는다. 시안의 사이드바에는 Run 탭과 같은 항목이 있었지만, 같은 이동을
  두 곳에 두면 무엇이 무엇을 바꾸는지 흐려져 사용자 결정(5)대로 나눴다.

  실제로 있는 경로만 둔다(App.tsx). 시안의 공유·내보내기·다시 실행 같은 없는
  기능은 만들지 않는다.

  ── 아래 상태 줄 ────────────────────────────────────────────────────────

  GET /api/health의 실제 응답만 말한다(polling 없음). 응답이 없으면 "서버 응답
  없음"이다. "운영 중" 같은 지어낸 문구를 쓰지 않는다.

  ── 작은 화면 ───────────────────────────────────────────────────────────

  lg(70rem) 미만에서는 사이드바 대신 위쪽 한 줄 + "메뉴" 버튼이 같은 목록을
  펼친다.
*/

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** 이 경로 아래(예: /runs/:id)도 같은 항목으로 표시한다. */
  matchPrefix?: boolean
}

const NAV: readonly NavItem[] = [
  { to: '/runs', label: '실행 목록', icon: ListChecks, matchPrefix: true },
  { to: '/new', label: '새 분석', icon: PlusCircle },
  { to: '/health', label: '서버 상태', icon: Activity },
  { to: '/help/setup', label: '준비 안내', icon: BookOpenCheck },
]

/*
  평가자 전용 항목. backend가 WES_EVAL_COMPARE=1로 비교 데이터를 줄 때만 보인다
  (GET /api/eval/compare가 404면 그리지 않는다). 일반 서비스에는 나타나지 않는다.
*/
const EVAL_NAV: NavItem = { to: '/eval/compare', label: '비교 분석', icon: GitCompareArrows, matchPrefix: true }

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  // 메뉴에서 이동하면 닫는다. 경로가 바뀐 것을 렌더 중 비교한다(effect 안 setState 금지).
  const [lastPath, setLastPath] = useState(location.pathname)
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname)
    if (open) setOpen(false)
  }

  return (
    <div className="flex min-h-dvh bg-paper">
      <aside
        aria-label="서비스 메뉴"
        className="sticky top-0 hidden h-dvh w-sidebar flex-none flex-col bg-sidebar text-sidebar-text lg:flex"
      >
        <Brand />
        <NavList />
        <div className="mt-auto border-t border-sidebar-line px-4 py-4">
          <ServerStatus />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 작은 화면의 위쪽 줄 */}
        <div className="sticky top-0 z-20 flex items-center justify-between gap-3 bg-sidebar px-4 py-2 text-sidebar-text lg:hidden">
          <Brand compact />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="mobile-service-menu"
            className="inline-flex min-h-9 items-center gap-1.5 rounded-sm px-2 text-small text-sidebar-strong hover:bg-sidebar-hover"
          >
            {open ? (
              <X size={16} strokeWidth={1.75} aria-hidden="true" />
            ) : (
              <Menu size={16} strokeWidth={1.75} aria-hidden="true" />
            )}
            메뉴
          </button>
        </div>
        {open ? (
          <div
            id="mobile-service-menu"
            className="sticky top-[3.25rem] z-20 border-b border-sidebar-line bg-sidebar pb-3 text-sidebar-text lg:hidden"
          >
            <NavList />
            <div className="px-4 pt-2">
              <ServerStatus />
            </div>
          </div>
        ) : null}

        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  )
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <NavLink
      to="/runs"
      className={cx(
        'flex items-center gap-2.5 text-sidebar-strong no-underline hover:no-underline',
        compact ? 'py-1' : 'border-b border-sidebar-line px-5 py-5',
      )}
    >
      <Workflow size={compact ? 20 : 26} strokeWidth={1.75} aria-hidden="true" className="flex-none text-brand-100" />
      <span className={cx('leading-tight font-semibold', compact ? 'text-body' : 'text-h3')}>
        WES Analysis
        {compact ? ' ' : <br />}
        Workspace
      </span>
    </NavLink>
  )
}

function NavList() {
  const { pathname } = useLocation()
  const items = useEvalCompareAvailable() ? [...NAV, EVAL_NAV] : NAV
  return (
    <nav aria-label="서비스 이동" className="px-3 py-4">
      <ul className="flex flex-col gap-1">
        {items.map((item) => {
          const active = item.matchPrefix
            ? pathname === item.to || pathname.startsWith(`${item.to}/`)
            : pathname === item.to
          const Icon = item.icon
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                aria-current={active ? 'page' : undefined}
                className={cx(
                  'flex min-h-10 items-center gap-3 rounded-md px-3 text-body no-underline hover:no-underline',
                  active
                    ? 'bg-sidebar-active font-medium text-sidebar-strong ring-1 ring-brand-500/60 ring-inset'
                    : 'text-sidebar-text hover:bg-sidebar-hover hover:text-sidebar-strong',
                )}
              >
                <Icon size={18} strokeWidth={1.75} aria-hidden="true" className="flex-none" />
                {item.label}
              </NavLink>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function ServerStatus() {
  const health = useHealthQuery()
  const state = health.isPending
    ? { label: '서버 확인 중', dot: 'bg-ink-400' }
    : health.isError
      ? { label: '서버 응답 없음', dot: 'bg-fill-failure' }
      : health.data?.status === 'ok'
        ? { label: '서버 연결됨', dot: 'bg-fill-success' }
        : { label: `서버 상태: ${health.data?.status ?? '알 수 없음'}`, dot: 'bg-fill-warning' }
  return (
    <NavLink
      to="/health"
      className="flex items-center gap-2 text-small text-sidebar-text no-underline hover:text-sidebar-strong hover:no-underline"
    >
      <span aria-hidden="true" className={cx('size-2 flex-none rounded-pill', state.dot)} />
      <span className="flex flex-col leading-tight">
        <span className="font-medium text-sidebar-strong">WES 서버</span>
        <span className="text-caption">{state.label}</span>
      </span>
    </NavLink>
  )
}
