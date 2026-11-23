/*
  어떤 단계가 기본 실행 계획에 들어가는가 — 웹 제출 기준.

  근거 (scripts/entry-model.test.mjs가 두 파일과 기계적으로 대조한다)
    script/main.sh                       OPTIONAL_STEPS=(08_filtering 10_annotation 11_intervar)
                                         build_step_plan(): 선택 단계는 설정이 true일 때만
    backend/app/services/config_builder.py
                                         optional_steps: filtering False · annotation False
                                         · intervar = run_acmg 요청 + 서버 InterVar 설정

  그래서 웹으로 제출한 실행에서 08·10은 실행되지 않고, 11은 조건부다.
  단계의 의미(label·purpose·tools)는 config/knowledge/wes_steps.json이 가진다.
  여기는 "계획에 들어가는가"만 가진다.

  React·경로 별칭을 쓰지 않는다: node 테스트가 직접 읽는다.
*/

export type StepPlanKind = 'core' | 'conditional' | 'notOnWeb'

const WEB_STEP_PLAN: Record<string, { kind: StepPlanKind; note: string }> = {
  '08_filtering': { kind: 'notOnWeb', note: '선택 단계 · 웹 제출에서는 실행하지 않음' },
  '10_annotation': { kind: 'notOnWeb', note: '선택 단계 · 웹 제출에서는 실행하지 않음' },
  '11_intervar': {
    kind: 'conditional',
    note: '선택 단계 · ACMG 분류를 요청하고 서버에 InterVar 설정이 있을 때만',
  },
}

/** main.sh의 OPTIONAL_STEPS와 같은 목록(테스트가 대조한다). */
export const OPTIONAL_STEP_IDS: readonly string[] = Object.keys(WEB_STEP_PLAN)

export function webStepPlan(stepId: string): { kind: StepPlanKind; note: string | null } {
  const entry = WEB_STEP_PLAN[stepId]
  return entry ? entry : { kind: 'core', note: null }
}
