import { Sparkles } from 'lucide-react'

import { SourceMark } from '@/components/ui/SourceMark'
import { revealStatement, shownStatement } from '@/features/run-detail/aiStatement'
import type { LocatorResolver } from '@/features/run-detail/locators'
import type {
  PlacedStatement,
  StatementGroup,
} from '@/features/run-detail/synthesisPlacement'

/*
  한 항목(실패·진단·단계·제한 사항) 옆의 AI 해설.

  ── 관찰 사실과 구분한다 ───────────────────────────────────────────────

  이 줄 위는 파이프라인 기록과 결정론적 설명이고, 이 줄은 모델이 쓴 문장이다.
  점선 구분선 + "AI 해설" 표시 + 패널과 같은 번호로 구분한다. 색 띠·배경
  강조는 쓰지 않는다(CLAUDE.md 23장).

  문장은 "AI 종합 설명" 패널에 있는 것과 같은 문자열이다(shownStatement).
  여기서 고치거나 줄이지 않는다. 어느 항목에 붙는지는 synthesisPlacement.ts가
  근거 id만으로 정한다.
*/

const GROUP_LABEL: Record<StatementGroup, string | null> = {
  importantFindings: null,
  limitations: '이 결과가 말하지 않는 것',
  nextChecks: '다음으로 확인할 수 있는 것',
  uncertainties: '알 수 없는 것',
}

export function AiNote({
  statements,
  locators,
}: {
  statements: PlacedStatement[]
  locators: LocatorResolver
}) {
  if (statements.length === 0) return null
  return (
    <div className="flex max-w-prose flex-col gap-1.5 border-t border-dashed border-border pt-2">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-text-muted">
        {/* 패널·공식 문서 구획과 같은 출처 표시(SourceMark). 점선 = AI. */}
        <SourceMark kind="ai" />
        <span>
          <span className="font-medium">AI 해설</span> · Claude가 생성한 설명이며 위의 기록이
          아닙니다
        </span>
      </p>
      <ul className="flex flex-col gap-2">
        {statements.map((item) => {
          const group = GROUP_LABEL[item.group]
          return (
            <li key={item.number} className="flex flex-col gap-0.5">
              {group ? (
                <span className="text-caption text-text-muted">{group}</span>
              ) : null}
              <span className="text-small text-text">
                <span className="mr-1.5 font-mono text-caption text-text-muted">
                  #{item.number}
                </span>
                {shownStatement(item, locators)}
              </span>
              <button
                type="button"
                onClick={() => revealStatement(item.number)}
                className="inline-flex min-h-6 w-fit items-center text-caption text-text-muted underline underline-offset-2 hover:text-brand"
              >
                전체 설명에서 근거 보기
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** 단계 표 한 행에 쓰는 짧은 표시. 문장은 레일에서 읽는다. */
export function AiNoteCount({ count }: { count: number }) {
  if (count === 0) return null
  return (
    <p className="flex items-center gap-1 text-caption text-text-muted">
      <Sparkles size={12} strokeWidth={1.5} aria-hidden="true" />
      AI 해설 {count}개 · 상세에서 보기
    </p>
  )
}
