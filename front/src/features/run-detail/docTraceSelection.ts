/*
  문서 구획에서 어떤 검색 기록을 보여 줄지 — 자동 이동 규칙 하나 (개발판단기록 29장).

  문제: 사용자가 "문서 검색"을 누르면 그 검색이 선택된다. 그 뒤 AI 설명을 요청하면
  서버(WES_AGENT_DOC_EVIDENCE=1)가 그 요청용 검색을 새로 저장하지만, 선택은 이전
  사용자 검색에 머물러 새 요청의 이력(C)이 보이지 않았다.

  규칙: 목록이 갱신되었을 때, **이전에 본 적 없는** 검색 중
    - Agent 요청이 만든 것(purpose === 'agentRequest')이고
    - 요청 기록이 실제로 연결된 것(agentRequest !== null)
  이 있으면 그중 가장 최근 것으로 이동한다. 그 외에는 아무것도 바꾸지 않는다.

    - 첫 목록(본 적 있는 집합이 없음): 이동하지 않는다. 기본 표시(가장 최근)를 그대로 쓴다.
    - 사용자 검색이 새로 생김: 이동하지 않는다(버튼 쪽이 직접 선택한다).
    - 연결되지 않은 Agent 검색(Trace 저장 실패 등): 이동하지 않는다. 잘못된 C를 띄우지 않는다.
    - 이미 본 기록만 있는 갱신: 이동하지 않는다. 사용자가 고른 과거 기록이 유지된다.

  Agent 검색은 POST /synthesis만 만들고, 이 목록은 그 요청이 끝났을 때만 다시 읽힌다
  (useRunSynthesis onSettled — 이전에는 RunSynthesisPanel 안에 있었다, staleTime Infinity). 그래서 "새 연결 Agent 검색"은
  곧 "방금 끝난 AI 설명 요청의 기록"이다.

  React·import 없이 순수 함수로 둔다: 저장소에 컴포넌트 테스트 도구가 없어서
  node --test로 이 규칙만 검증한다(scripts/doc-trace-selection.test.mjs).
*/

export interface TraceRunLike {
  searchId: string
  purpose: string
  agentRequest: unknown
}

export interface SeenSearches {
  jobId: string
  ids: ReadonlySet<string>
}

/** 이동할 검색 id, 또는 null(현재 선택 유지). `runs`는 최신순. */
export function newLinkedAgentSearch(
  seen: SeenSearches | null,
  jobId: string,
  runs: readonly TraceRunLike[],
): string | null {
  // 처음 보는 Run의 첫 목록은 비교 대상이 없다: 이동하지 않는다.
  if (seen === null || seen.jobId !== jobId) return null
  for (const run of runs) {
    if (seen.ids.has(run.searchId)) continue
    if (run.purpose === 'agentRequest' && run.agentRequest != null) return run.searchId
  }
  return null
}

export function seenFrom(jobId: string, runs: readonly TraceRunLike[]): SeenSearches {
  return { jobId, ids: new Set(runs.map((run) => run.searchId)) }
}
