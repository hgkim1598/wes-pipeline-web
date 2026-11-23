/*
  "지금 어디인가"를 한 문장으로 (RunHeader · RunFacts가 함께 쓴다).

  실패한 실행은 currentStep이 null이라 예전 헤더는 "1/8단계"만 보여주고 어디서
  멈췄는지 말하지 않았다. 단계 상태에서 직접 찾는다 — backend가 준 값만 쓴다.

  2026-11-23 화면 점검: 완료(경고)로 끝난 실행에서 일부 단계의 상태 파일이 없으면
  pending으로 남아 "기록 없음"이 나왔다. 실행은 끝났는데 위치가 없다고 읽힌다.
  끝난 완료 실행은 "실행이 끝났습니다"라고 말하고, 기록이 없는 단계 수를 따로
  적는다 — 그 단계들이 실행됐다고도, 안 됐다고도 지어내지 않는다.

  같은 날 리뷰: 프로세스가 끝났는데 run_status.json이 running으로 남은 실행은
  backend가 failed로 보고하고(job_state 규칙 2) 어떤 단계도 failed·running이 아니다.
  이 경우도 "기록 없음"이 나왔다. "실행이 중단되었습니다"라고 말하고, 어느 단계였는지는
  지어내지 않는다. 취소된 실행의 "n단계는 실행되지 않았습니다"도 진행 중이던 단계까지
  세고 있어 "완료 기록이 없습니다"로 바꿨다.

  React·경로 별칭을 쓰지 않는다: scripts/run-detail-copy.test.mjs가 node로
  직접 읽는다. 단계 이름은 호출하는 쪽이 넘긴다(registries/steps).
*/

export interface PositionInput {
  status: string
  currentStep: string | null
  steps: readonly { stepId: string; status: string }[]
}

export interface Position {
  headline: string
  detail: string | null
}

const COMPLETED = new Set(['completed', 'completed_with_warnings'])

export function describePosition(
  job: PositionInput,
  labelOf: (stepId: string) => string,
): Position {
  const steps = job.steps
  const failed = steps.find((step) => step.status === 'failed')
  const waiting = steps.filter((step) => step.status === 'pending').length

  if (failed) {
    return {
      headline: `${labelOf(failed.stepId)}에서 멈춤`,
      detail: waiting > 0 ? `이후 ${waiting}단계는 실행되지 않았습니다` : null,
    }
  }
  if (job.currentStep) {
    const index = steps.findIndex((step) => step.stepId === job.currentStep)
    const next = index >= 0 ? steps[index + 1] : undefined
    return {
      headline: `${labelOf(job.currentStep)} 진행 중`,
      detail: next ? `다음: ${labelOf(next.stepId)}` : '마지막 단계입니다',
    }
  }
  if (job.status === 'queued') {
    return { headline: '시작 대기 중', detail: null }
  }
  if (job.status === 'cancelled') {
    return { headline: '취소됨', detail: waiting > 0 ? `${waiting}단계는 완료 기록이 없습니다` : null }
  }
  if (job.status === 'failed') {
    return {
      headline: '실행이 중단되었습니다',
      detail: '어느 단계에서 멈췄는지 단계 기록에 남지 않았습니다',
    }
  }
  if (COMPLETED.has(job.status)) {
    return {
      headline: '실행이 끝났습니다',
      detail: waiting > 0 ? `${waiting}단계는 단계 기록이 남지 않았습니다` : null,
    }
  }
  if (steps.length > 0 && waiting === 0) {
    return { headline: '모든 단계가 끝났습니다', detail: null }
  }
  return { headline: '기록 없음', detail: null }
}
