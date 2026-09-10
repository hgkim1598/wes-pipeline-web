import { Popover } from '@base-ui/react/popover'
import { Link } from 'react-router'

import { glossaryTerm } from '@/registries/glossary'
import { cx } from '@/lib/cx'

/**
 * 용어 도움말.
 *
 * ── 왜 popover인가 `[설계판단]` ─────────────────────────────────────────
 *
 * 담을 내용이 한두 문장이고, 읽고 나면 원래 보던 자리로 돌아가야 한다.
 *
 *   tooltip  hover에만 반응하면 터치·키보드에서 접근이 어렵고, 그 안의
 *            "자세히" 링크를 누를 수 없다
 *   dialog   화면 전체를 덮는다. 한 문장 때문에 맥락을 잃게 만든다
 *   popover  클릭·키보드로 열리고, 안의 링크를 누를 수 있고, Escape로 닫힌다  ✓
 *
 * Base UI Popover를 쓴다. 열림 상태·focus 이동·Escape·바깥 클릭·
 * aria 연결을 라이브러리가 담당한다. Tabs와 같은 정책이다.
 *
 * ── tooltip에 필수 정보를 숨기지 않는다 ─────────────────────────────────
 *
 * 이 컴포넌트는 **보조 설명**만 담는다. 화면을 이해하는 데 반드시 필요한
 * 사실은 열지 않아도 본문에 있어야 한다. 여기 있는 것은 "이 단어가 무슨
 * 뜻인가"이지 "무슨 일이 일어났는가"가 아니다.
 *
 * ── 등록되지 않은 용어 ──────────────────────────────────────────────────
 *
 * glossary에 없으면 **평범한 텍스트로 렌더링한다.** 누를 수 있어 보이는데
 * 아무 설명이 없는 것보다 낫고, 화면이 깨지지도 않는다.
 */

export interface HelpTermProps {
  /** glossary id. 없으면 children이 그대로 렌더링된다. */
  termId: string
  /** 화면 표기. 없으면 glossary의 label을 쓴다. */
  children?: React.ReactNode
  /** 기술 식별자는 mono로 둔다 (`bwa`, `PATH`). */
  mono?: boolean
  className?: string
}

export function HelpTerm({ termId, children, mono, className }: HelpTermProps) {
  const term = glossaryTerm(termId)
  const label = children ?? term?.label ?? termId

  if (!term) {
    return (
      <span className={cx(mono && 'font-mono text-data', className)}>
        {label}
      </span>
    )
  }

  return (
    <Popover.Root>
      {/*
        누를 수 있다는 것이 보여야 한다 `[설계판단]`

        이전에는 `border-dotted border-border-strong` 하나뿐이었고, 실제
        화면에서 본문 텍스트와 거의 구분되지 않았다. 문장 중간의 옅은 점선은
        밑줄이라기보다 렌더링 잡티처럼 보인다.

        세 가지를 함께 쓴다 — 색 하나에 의존하지 않는다(CLAUDE.md 27장).

          1. 점선 밑줄을 실제로 보이게 (border-b-2, text 색상 계열)
          2. 아주 작은 도움말 표식 하나
          3. hover/focus에서 밑줄이 실선 brand로 바뀜

        `?` 아이콘을 용어마다 큼직하게 붙이면 문장이 아이콘 밭이 되므로,
        표식은 위첨자 크기의 점 하나로 둔다. 화면 밀도를 지키면서 "여기 뭔가
        더 있다"는 신호는 준다.

        focus-visible ring은 Base UI가 button으로 렌더링하므로 전역 focus
        스타일이 그대로 적용된다. outline을 지우지 않는다.
      */}
      <Popover.Trigger
        className={cx(
          'inline cursor-help rounded-[2px]',
          'border-b-2 border-dotted border-text-muted',
          'hover:border-solid hover:border-brand hover:text-brand',
          'data-[popup-open]:border-solid data-[popup-open]:border-brand',
          mono && 'font-mono text-data',
          className,
        )}
      >
        {label}
        <span
          aria-hidden="true"
          className="ml-0.5 align-super text-[0.6em] leading-none text-text-muted"
        >
          ⓘ
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner sideOffset={6} className="z-50">
          {/*
            shadow-el-1은 실제로 떠 있는 레이어에만 쓴다(tokens.css).
            popover가 그 경우다 — 본문 위에 겹친다.
          */}
          <Popover.Popup className="max-w-80 rounded-md border border-border bg-surface p-4 shadow-el-1">
            <Popover.Title className="text-body font-medium text-text-strong">
              {term.label}
            </Popover.Title>
            <Popover.Description className="mt-1 text-small text-text">
              {term.description}
            </Popover.Description>
            {term.helpPath ? (
              <Link
                to={term.helpPath}
                className="mt-3 inline-flex min-h-6 items-center text-small font-medium"
              >
                자세히 보기
              </Link>
            ) : null}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  )
}
