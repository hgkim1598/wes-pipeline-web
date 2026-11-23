/*
  평가 채점 화면의 채점자 이름 — 이 브라우저에서만 기억하는 편의 기능.

  CLAUDE.md §20: localStorage 접근은 지정된 모듈 안으로 제한한다. 이전에는
  EvalGradePage.tsx 안에 있었다(log 61). 저장소가 막힌 브라우저(사생활 보호 창,
  차단된 사이트 데이터)에서도 채점은 되어야 하므로 실패는 조용히 빈 값이 된다.
  채점 기록 자체는 서버(eval-compare API)에 append-only로 저장된다.
*/

const GRADER_KEY = 'wes.evalCompare.grader'

export function readGrader(): string {
  try {
    return localStorage.getItem(GRADER_KEY) ?? ''
  } catch {
    return ''
  }
}

export function writeGrader(value: string): void {
  try {
    localStorage.setItem(GRADER_KEY, value)
  } catch {
    /* 저장하지 못해도 채점은 된다 */
  }
}
