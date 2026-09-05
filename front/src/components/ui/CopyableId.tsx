import { Check, Copy } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { cx } from '@/lib/cx'

/**
 * 복사 가능한 식별자.
 *
 * 시안 근거 (docs/design/components.html C6 / COPYABLEID)
 *   "전체가 하나의 버튼. 히트 영역 최소 24×24를 투명 패딩으로 확보합니다."
 *   전체 표시(실행 상세 헤더) · 축약 표시(sha256 앞4 뒤4, 표 셀) ·
 *   라벨 동반(상세 레일 메타 목록) 3형태. hover에서 아이콘이 ink-700.
 *
 * run ID와 sha256은 사람이 눈으로 옮겨 적을 값이 아니다. 로그·서버 경로·문의에
 * 그대로 붙여야 하므로 복사가 기본 동작이어야 한다.
 *
 * clipboard API는 안전하지 않은 컨텍스트나 권한 거부로 실패할 수 있다. 그때
 * 조용히 아무 일도 없는 것처럼 두지 않고 상태를 되돌린다 — 사용자는 복사되지
 * 않았다는 것을 알아야 한다.
 */

export interface CopyableIdProps {
  /** 복사될 실제 값. 표시가 축약되더라도 전체가 복사된다. */
  value: string
  /** 값 앞에 붙는 라벨. 시안의 "라벨 동반" 형태. */
  label?: string
  /** 앞 4자 + 뒤 4자로 줄인다. sha256처럼 긴 값에 쓴다. */
  truncate?: boolean
  className?: string
}

function shorten(value: string): string {
  return value.length <= 12 ? value : `${value.slice(0, 4)}…${value.slice(-4)}`
}

export function CopyableId({
  value,
  label,
  truncate = false,
  className,
}: CopyableIdProps) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    },
    [],
  )

  const copy = useCallback(() => {
    void navigator.clipboard
      ?.writeText(value)
      .then(() => {
        setCopied(true)
        if (timerRef.current !== null) window.clearTimeout(timerRef.current)
        timerRef.current = window.setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => {
        // 실패를 성공처럼 보이게 하지 않는다.
        setCopied(false)
      })
  }, [value])

  return (
    <button
      type="button"
      onClick={copy}
      // 투명 패딩으로 24px 히트 영역 확보 (WCAG 2.2 SC 2.5.8, 시안 C6과 동일)
      className={cx(
        'group inline-flex min-h-6 items-center gap-2 rounded-sm py-1 text-left',
        className,
      )}
      // 보이는 텍스트가 값이라, 버튼의 이름은 동작을 설명해야 한다.
      aria-label={`${label ? `${label} ` : ''}${value} 복사`}
    >
      {label ? (
        <span className="text-small text-text-muted">{label}</span>
      ) : null}
      <span className="min-w-0 truncate font-mono text-data text-text">
        {truncate ? shorten(value) : value}
      </span>
      {copied ? (
        <Check
          size={14}
          strokeWidth={2}
          aria-hidden="true"
          className="shrink-0 text-status-success-fg"
        />
      ) : (
        <Copy
          size={14}
          strokeWidth={1.5}
          aria-hidden="true"
          className="shrink-0 text-ink-400 group-hover:text-text"
        />
      )}
      {/* 복사 결과는 시각 아이콘만으로 전달하지 않는다. */}
      <span aria-live="polite" className="sr-only">
        {copied ? '복사했습니다' : ''}
      </span>
    </button>
  )
}
