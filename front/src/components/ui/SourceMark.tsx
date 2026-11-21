import type { ReactNode } from 'react'
import { BookOpen, ClipboardList, Library, Sparkles } from 'lucide-react'

import { cx } from '@/lib/cx'

/*
  출처 표시 — 이 내용이 어디서 왔는가.

    record     이 Run의 기록        파이프라인·backend가 남긴 관측 사실
    ai         AI 생성              모델이 쓴 문장
    doc        공식 문서            검색된 공식 문서 발췌·매뉴얼 구간
    knowledge  등록된 지식          저장소에 등록된 일반 설명

  색 하나로 구분하지 않는다(CLAUDE.md 24장): 아이콘 + 글자 + 테두리 모양.
  AI만 점선 테두리다 — 각 항목 옆 AI 해설(AiNote)의 점선 구분선과 같은 신호다.
  semantic 색(성공·실패 등)은 쓰지 않는다. 출처는 상태가 아니다.
*/

export type SourceKind = 'record' | 'ai' | 'doc' | 'knowledge'

const SOURCE: Record<SourceKind, { label: string; Icon: typeof Sparkles; className: string }> = {
  record: {
    label: '이 Run의 기록',
    Icon: ClipboardList,
    className: 'border-border bg-sunken text-text',
  },
  ai: {
    label: 'AI 생성',
    Icon: Sparkles,
    className: 'border-dashed border-border-strong bg-surface text-text',
  },
  doc: {
    label: '공식 문서',
    Icon: BookOpen,
    className: 'border-border bg-surface text-text',
  },
  knowledge: {
    label: '등록된 지식',
    Icon: Library,
    className: 'border-border bg-surface text-text-muted',
  },
}

export function SourceMark({
  kind,
  children,
  className,
}: {
  kind: SourceKind
  /** 기본 이름 뒤에 붙는 짧은 정보(건수 등). */
  children?: ReactNode
  className?: string
}) {
  const { label, Icon, className: tone } = SOURCE[kind]
  return (
    <span
      className={cx(
        'inline-flex h-5 flex-none items-center gap-1 rounded-sm border px-1.5 text-caption whitespace-nowrap',
        tone,
        className,
      )}
    >
      <Icon size={12} strokeWidth={1.5} aria-hidden="true" />
      {label}
      {children}
    </span>
  )
}
