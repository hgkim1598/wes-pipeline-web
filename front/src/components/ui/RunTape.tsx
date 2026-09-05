import type { StatusTone } from '@/components/ui/StatusBadge'
import { TONE_FILL_CLASS } from '@/components/ui/statusFill'
import { cx } from '@/lib/cx'

/**
 * 파이프라인 진행 띠.
 *
 * 시안 근거 (docs/design/components.html C2 / RUNTAPE)
 *   "세로 체크리스트 타임라인을 대체하는 가로 띠. 셀 균등 폭 · 간격 2px가
 *    구분선 · 현재 단계는 하단 4px 정적 바 · 선택 단계는 상단 2px 점선."
 *   lg 셀 높이 40 + 라벨 + 소요시간 (파이프라인 탭)
 *   md 셀 높이 12, 라벨 없음        (run header)
 *
 * 형태 탐색 근거 (docs/design/archive/progress-indicator.html)
 *   T4 "연속 바형"은 채택하지 않았다. 시안 자신의 평가가 `"진행 바" 인상이
 *   가장 강해서 완료 비율을 시간 진행률로 오해할 위험도 가장 크다`이고,
 *   이 제품의 progress는 시간이 아니라 완료 단계 비율이다.
 *
 * ⚠️ 이 component는 backend 어휘를 모른다. 셀마다 이미 tone이 정해져서 온다.
 *    step status -> tone 변환은 features/run-detail/stepStatus.ts가 한다.
 *    StatusBadge와 같은 정책이다.
 *
 * 색만으로 상태를 전달하지 않는다. lg는 라벨을 함께 렌더링하고, md는 라벨이
 * 없으므로 각 셀에 aria-label을 붙인다 — 옆의 배지·단계 요약 텍스트가 같은
 * 정보를 시각적으로도 전달한다.
 */

export interface RunTapeCell {
  /** step ID 등 고유 키. */
  id: string
  tone: StatusTone
  /** lg에서 셀 아래 보이는 이름. */
  label?: string
  /** lg에서 라벨 아래 보이는 소요 시간 등. */
  meta?: string
  /** 지금 실행 중인 셀. 하단 바를 두껍게 그린다. */
  current?: boolean
  /** 계획에 있으나 건너뛸 수 있는 단계. 상단 점선. */
  optional?: boolean
  /** 스크린 리더용 전체 문장. "참조 유전체 정렬, 완료, 38분 12초" */
  ariaLabel: string
}

export interface RunTapeProps {
  cells: RunTapeCell[]
  size?: 'md' | 'lg'
  className?: string
}

const CELL_HEIGHT = {
  md: 'h-3',
  lg: 'h-10',
} as const

/*
  현재 단계 표시.

  하단 4px(lg) / 2px(md) 정적 바다. 애니메이션을 넣지 않는다 — 반복 모션은
  CLAUDE.md 23장이 금지하고, 여기서 움직여야 할 정보도 없다(단계 내부 진행률은
  backend에 존재하지 않는다).
*/
const CURRENT_BAR = {
  md: 'border-b-2',
  lg: 'border-b-4',
} as const

export function RunTape({ cells, size = 'lg', className }: RunTapeProps) {
  if (cells.length === 0) return null

  return (
    <ol className={cx('flex min-w-0 gap-0.5', className)}>
      {cells.map((cell) => (
        <li
          key={cell.id}
          aria-label={cell.ariaLabel}
          className={cx(
            'flex min-w-0 flex-1 flex-col items-center',
            size === 'lg' && 'gap-2',
          )}
        >
          <div
            aria-hidden="true"
            className={cx(
              'w-full rounded-sm',
              CELL_HEIGHT[size],
              TONE_FILL_CLASS[cell.tone],
              // 현재 단계의 하단 바. 채움색보다 진한 running fill을 쓴다.
              cell.current && `${CURRENT_BAR[size]} border-fill-running`,
              // 선택 단계는 상단 점선. 건너뛸 수 있는 단계라는 표시다.
              cell.optional && 'border-t-2 border-t-border border-dashed',
            )}
          />
          {size === 'lg' && cell.label ? (
            <span className="w-full truncate text-center text-caption text-text">
              {cell.label}
            </span>
          ) : null}
          {size === 'lg' && cell.meta ? (
            <span className="w-full truncate text-center font-mono text-caption text-text-muted">
              {cell.meta}
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  )
}
