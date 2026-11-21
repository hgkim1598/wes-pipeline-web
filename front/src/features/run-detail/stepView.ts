/*
  파이프라인 워크스페이스의 단계 선택과 "실행되지 않음" 판단 — 순수 함수만.

  ── 기본 선택 ───────────────────────────────────────────────────────────

  오른쪽 상세 패널은 늘 하나의 단계를 보여 준다. URL(?step=)에 단계가 없거나
  이 실행의 계획에 없는 단계면 다음 순서로 고른다.

    1. 실패한 단계      "어디서 멈췄나"
    2. 지금 실행 중인 단계(backend currentStep, 없으면 status running)
    3. 경고가 있는 단계
    4. 첫 단계

  ── 실행되지 않은 단계 ────────────────────────────────────────────────

  backend는 계획에 있지만 끝나지 않은 단계를 `pending`으로 준다. 실행이 이미
  끝났는데(terminal) 단계가 pending이면 그 단계는 시작되지 않은 채 실행이
  끝난 것이다. "대기 중"이라고 쓰면 아직 돌 것처럼 읽히므로 "실행 안 됨"으로
  쓴다. 완료로는 절대 쓰지 않는다. 실행 중일 때의 pending은 그대로 "대기 중"이다.

  React·import 없이 둔다(node --test, scripts/workspace-view.test.mjs).
*/

export interface StepLike {
  stepId: string
  status: string
}

export function defaultStepId(
  steps: readonly StepLike[],
  currentStepId: string | null,
): string | null {
  const failed = steps.find((s) => s.status === 'failed')
  if (failed) return failed.stepId
  if (currentStepId && steps.some((s) => s.stepId === currentStepId)) return currentStepId
  const running = steps.find((s) => s.status === 'running')
  if (running) return running.stepId
  const warning = steps.find((s) => s.status === 'warning')
  if (warning) return warning.stepId
  return steps[0]?.stepId ?? null
}

/** URL 값이 이 실행의 단계면 그대로, 아니면 기본 선택. */
export function resolveStepId(
  raw: string | null,
  steps: readonly StepLike[],
  currentStepId: string | null,
): string | null {
  if (raw && steps.some((s) => s.stepId === raw)) return raw
  return defaultStepId(steps, currentStepId)
}

/**
 * 끝난 실행에서 시작되지 않은 단계.
 *
 * `execution`(backend 장부, factApplicability.ts)이 오면 그것만 본다 — 장부는
 * 취소 시점에 진행 중이던 단계나 기록이 빠진 단계를 "판정 불가"로 두는데,
 * pending만 보는 아래 규칙은 그것까지 "실행 안 됨"으로 썼다(2026-11-21).
 * 장부가 없는 이전 응답에서만 예전 규칙을 쓴다.
 */
export function isNotRun(status: string, terminal: boolean, execution?: string): boolean {
  if (execution !== undefined) {
    return (
      execution === 'notRunAfterFailure' ||
      execution === 'notRunCancelled' ||
      execution === 'notRunAfterStop'
    )
  }
  return terminal && status === 'pending'
}

/** 장부가 "기록으로 판정할 수 없음"이라고 한 단계. */
export function isUndetermined(execution?: string): boolean {
  return execution === 'unknown'
}

/** 실행되지 않은 단계에만 쓰는 상태 문구. 나머지는 stepStatus.ts의 라벨을 쓴다. */
export const NOT_RUN_LABEL = '실행 안 됨'

/** 장부가 판정할 수 없다고 한 단계의 상태 문구. */
export const UNDETERMINED_LABEL = '판정 불가'
