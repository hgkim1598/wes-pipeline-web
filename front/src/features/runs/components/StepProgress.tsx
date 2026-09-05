import type { StatusTone } from '@/components/ui/StatusBadge'
import { TONE_FILL_CLASS } from '@/components/ui/statusFill'
import { cx } from '@/lib/cx'

/*
  단계 진행 표시.

  backend가 목록에서 주는 진행 정보는 두 숫자뿐이다
  (backend/app/schemas.py JobListItem).

    plannedStepCount    실행을 만들 때 기록된 계획 단계 수
    completedStepCount  pipeline이 완료로 기록한 단계 수

  그래서 여기서 만들 수 있는 것도 "몇 단계 중 몇 단계"까지다.
  시안(remaining-screens.html)의 8칸 분할 막대는 **단계별 상태**를 색으로
  구분하는데, 그 배열은 GET /api/jobs/{id}에만 있고 목록 응답에는 없다.
  없는 정보를 칸으로 그려내는 대신 채움 하나로 비율만 보여준다.

  시간 진행률이 아니다 — 남은 시간이나 단계 내부 진행률은 backend에 없고
  만들지도 않는다(CLAUDE.md 13장).

  막대는 옆의 숫자를 그대로 옮긴 그림이라 aria-hidden이다. 의미는 텍스트가
  전부 전달하므로 스크린 리더에서 같은 정보가 두 번 읽히지 않는다.
*/

export interface StepProgressProps {
  completedStepCount: number
  plannedStepCount: number
  tone: StatusTone
  className?: string
}

export function StepProgress({
  completedStepCount,
  plannedStepCount,
  tone,
  className,
}: StepProgressProps) {
  // 계획이 0이면 비율 자체가 정의되지 않는다. 0으로 나누지 않고,
  // 진행 중이라고 오해할 여지도 남기지 않는다.
  const planned = Math.max(0, Math.trunc(plannedStepCount))
  if (planned === 0) {
    return (
      <span className={cx('text-caption text-text-muted', className)}>
        단계 정보 없음
      </span>
    )
  }

  const completed = Math.min(planned, Math.max(0, Math.trunc(completedStepCount)))
  const percent = Math.round((completed / planned) * 100)

  return (
    <div className={cx('flex flex-col gap-1', className)}>
      <div
        aria-hidden="true"
        className="h-1.5 w-full overflow-hidden rounded-sm bg-fill-idle"
      >
        <div
          className={cx('h-full', TONE_FILL_CLASS[tone])}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="text-caption text-text-muted">
        <span className="font-mono text-caption text-text">
          {completed}/{planned}
        </span>
        단계
      </span>
    </div>
  )
}
