/*
  Run 상세의 조회 정책 — 순수 함수만. (queries.ts · RunDetailPage가 쓴다)

  ── 왜 따로 두는가 ──────────────────────────────────────────────────────

  query마다 "언제까지 다시 읽을지"를 자기가 본 상태 하나로 따로 정했다.
  그래서 세 가지가 빠졌다.

  1. 전환의 순간. 실행이 끝나는 렌더에서 설명·산출물·단계 상세는 폴링을
     멈춘다. 마지막으로 받은 응답은 끝나기 전의 것이다. 방금 실패한 실행에
     "진행 중" 설명이 남는다. 단계 하나가 끝날 때(running → completed)도 같다.
  2. 없는 실행. 상세가 404여도 status가 없으니 "아직 모름"으로 보고 3초마다
     상세·설명·산출물을 계속 요청했다.
  3. 일시적 실패. 폴링 한 번이 실패하면(react-query는 data를 그대로 두고
     error를 채운다) 화면 전체를 오류로 바꿨다. 반대로 데이터를 남기면
     그것이 최신인 것처럼 보이면 안 된다.

  이 파일은 그 판단을 한 곳에 둔다. 상태 문자열이 terminal인지는
  features/runs/status.ts의 isTerminalStatus가 정하고, 여기서는 받기만 한다.
*/

/**
 * Run 상세가 지금 아는 것.
 *
 *   pending   아직 응답을 한 번도 받지 못함(첫 로딩, 또는 첫 요청부터 실패)
 *   missing   서버가 이 실행을 모른다(404). 다시 물어도 답이 바뀌지 않는다.
 *   active    실행 중(queued · running). 값이 바뀌므로 따라간다.
 *   terminal  끝남. 값이 더 바뀌지 않는다.
 */
export type RunPhase = 'pending' | 'missing' | 'active' | 'terminal'

export interface RunPhaseInput {
  /** 마지막으로 받은 상세의 status. 받은 적 없으면 undefined. */
  status: string | undefined
  /** status가 terminal인지(isTerminalStatus). status가 없으면 무시한다. */
  terminal: boolean
  /** 마지막 실패의 HTTP status. 실패가 없거나 HTTP 응답이 없으면 null. */
  errorStatus: number | null
}

export function runPhase({ status, terminal, errorStatus }: RunPhaseInput): RunPhase {
  // 한 번이라도 받은 상세가 있으면 그것이 기준이다. 그 뒤의 일시적 실패는
  // 실행의 단계를 바꾸지 않는다(연결 상태로 따로 표시한다).
  if (status !== undefined) return terminal ? 'terminal' : 'active'
  if (errorStatus === 404) return 'missing'
  return 'pending'
}

/** 상세 자신의 다음 요청 간격. 끝났거나 없는 실행은 다시 읽지 않는다. */
export function detailInterval(phase: RunPhase, ms: number): number | false {
  return phase === 'active' || phase === 'pending' ? ms : false
}

/**
 * 상세에 딸린 query(설명·산출물)를 요청해도 되는가.
 *
 * 실행이 있다는 것을 안 뒤에만 요청한다. 없는 실행(404)에 딸린 요청은
 * 의미가 없고, 첫 응답 전에는 기다려도 한 번의 왕복이다.
 */
export function dependentEnabled(phase: RunPhase): boolean {
  return phase === 'active' || phase === 'terminal'
}

/** 딸린 query의 폴링 간격. 실행 중에만 따라간다. */
export function dependentInterval(phase: RunPhase, ms: number): number | false {
  return phase === 'active' ? ms : false
}

/**
 * 실행이 방금 끝났는가 — 딸린 query를 마지막으로 한 번 다시 읽을 때.
 *
 * 폴링은 terminal을 본 렌더에서 멈추므로, 그 직전에 받은 설명·산출물·단계
 * 상세는 끝나기 전의 것이다. 처음부터 terminal로 연 화면(previous가
 * pending)은 이미 terminal 이후의 응답을 받으므로 해당하지 않는다.
 */
export function justSettled(previous: RunPhase, next: RunPhase): boolean {
  return previous === 'active' && next === 'terminal'
}

/**
 * 상세 query를 다시 시도할 만한가. 404는 다시 물어도 같은 답이다.
 * 그 밖의 실패는 한 번만 다시 시도한다(폴링이 이어서 다시 묻는다).
 */
export function shouldRetryDetail(failureCount: number, errorStatus: number | null): boolean {
  return errorStatus !== 404 && failureCount < 1
}

/**
 * 화면에 남아 있는 상세가 지금 서버와 연결된 값인가.
 *
 *   live          마지막 요청이 성공했다
 *   refreshing    요청 중이다
 *   disconnected  마지막 요청이 실패했다. 보이는 값은 lastUpdated 시점의 것이다.
 *
 * react-query는 다음 요청을 시작할 때 failureCount를 0으로 되돌리므로 그것만
 * 보면 "연결 끊김"이 재시도하는 1초 남짓만 보인다. 실패 상태(isError)는 다음
 * 성공까지 남으므로 그쪽을 기준으로 한다.
 */
export type ConnectionState = 'live' | 'refreshing' | 'disconnected'

export function connectionState(input: {
  isError: boolean
  failureCount: number
  isFetching: boolean
}): ConnectionState {
  if (input.isError || input.failureCount > 0) return 'disconnected'
  return input.isFetching ? 'refreshing' : 'live'
}
