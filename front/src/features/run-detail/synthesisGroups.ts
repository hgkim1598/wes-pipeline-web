/*
  AI 설명 문장을 진단 기록별로 묶는다.

  ── 무엇을 기준으로 묶나 ────────────────────────────────────────────────

  문장마다 붙은 `evidenceRefs`의 `dx:<code>`(진단)와 `fail:<code>`(실패)만
  본다. 그 id는 backend가 payload를 만들 때 발급한 것이고, 모델이 발급되지
  않은 id를 인용하면 응답 전체가 폐기된다(registries/evidence.ts). 즉 묶는
  기준은 모델의 문장 해석이 아니라 **모델이 직접 인용한 근거**다.

  ── 한 문장은 정확히 한 번 나온다 `[설계판단]` ──────────────────────────

  한 문장이 진단 두 개를 인용할 수 있다. 두 그룹에 모두 그리면 같은 문장이
  두 번 읽히고, 사용자는 문장이 두 개라고 생각한다. 그래서 문장은 순위가
  가장 높은(rank 값이 가장 작은) 진단 하나에만 들어가고, 나머지 진단은
  `related`로 함께 표시한다. 순위가 같으면 문장이 먼저 인용한 쪽이다.

  진단을 하나도 인용하지 않은 문장은 `ungrouped`에 원래 순서대로 남는다.
  어떤 경우에도 입력의 모든 문장이 결과에 정확히 한 번 들어간다 — 그
  불변식이 이 모듈의 계약이다.

  순위는 호출부가 준다. 진단의 종류(확인 필요 · 자동 복구 …)는 shared
  knowledge가 정하고, 이 모듈은 knowledge를 import하지 않는다. 그래서 이
  파일은 의존성 없이 단독으로 검증할 수 있다.

  문장 문자열은 건드리지 않는다. 묶는 것은 위치뿐이다.
*/

export interface DiagnosticRef {
  prefix: 'dx' | 'fail'
  code: string
  /** 원본 evidenceRef 문자열 그대로. 그룹의 key이기도 하다. */
  ref: string
}

export interface GroupedEntry<T> {
  /** 입력 배열에서의 위치. 원래 순서를 복원하거나 key로 쓴다. */
  index: number
  item: T
  /** 이 문장이 함께 인용한 다른 진단. 그 그룹에는 다시 그리지 않는다. */
  related: DiagnosticRef[]
}

export interface DiagnosticGroup<T> {
  diagnostic: DiagnosticRef
  entries: GroupedEntry<T>[]
}

export interface SynthesisGrouping<T> {
  groups: DiagnosticGroup<T>[]
  ungrouped: { index: number; item: T }[]
}

/** evidenceRefs에서 진단·실패 id만, 처음 나온 순서대로, 중복 없이. */
export function diagnosticRefsOf(refs: readonly string[]): DiagnosticRef[] {
  const seen = new Set<string>()
  const out: DiagnosticRef[] = []
  for (const ref of refs) {
    const separator = ref.indexOf(':')
    if (separator < 0) continue
    const prefix = ref.slice(0, separator)
    const code = ref.slice(separator + 1)
    if (code === '' || seen.has(ref)) continue
    if (prefix === 'dx' || prefix === 'fail') {
      seen.add(ref)
      out.push({ prefix, code, ref })
    }
  }
  return out
}

/**
 * 문장을 진단별로 묶는다.
 *
 * 그룹 순서는 rank 오름차순, 같으면 그 그룹의 첫 문장이 나온 순서다.
 * 그룹 안의 문장과 ungrouped는 입력 순서를 유지한다.
 */
export function groupByDiagnostic<T extends { evidenceRefs: readonly string[] }>(
  items: readonly T[],
  rank: (diagnostic: DiagnosticRef) => number,
): SynthesisGrouping<T> {
  const byRef = new Map<string, { group: DiagnosticGroup<T>; first: number }>()
  const ungrouped: { index: number; item: T }[] = []

  items.forEach((item, index) => {
    const diagnostics = diagnosticRefsOf(item.evidenceRefs)
    if (diagnostics.length === 0) {
      ungrouped.push({ index, item })
      return
    }

    let primary = diagnostics[0]
    for (const candidate of diagnostics) {
      if (rank(candidate) < rank(primary)) primary = candidate
    }

    let slot = byRef.get(primary.ref)
    if (!slot) {
      slot = { group: { diagnostic: primary, entries: [] }, first: index }
      byRef.set(primary.ref, slot)
    }
    slot.group.entries.push({
      index,
      item,
      related: diagnostics.filter((d) => d.ref !== primary.ref),
    })
  })

  const groups = [...byRef.values()]
    .sort(
      (a, b) =>
        rank(a.group.diagnostic) - rank(b.group.diagnostic) || a.first - b.first,
    )
    .map((slot) => slot.group)

  return { groups, ungrouped }
}

/**
 * 문장 목록을 "주어진 근거 중 하나라도 인용했는가"로 둘로 나눈다.
 *
 * 진단과 연결되지 않은 문장 중 실행 상태를 말하는 것(예: `run:status`를
 * 인용한 문장)을 요약 옆으로 올리는 데 쓴다. 기준은 역시 모델이 인용한
 * 근거뿐이고, 모든 문장은 둘 중 정확히 한쪽에 원래 순서대로 들어간다.
 */
export function partitionByRefs<E extends { item: { evidenceRefs: readonly string[] } }>(
  entries: readonly E[],
  refs: ReadonlySet<string>,
): { matched: E[]; rest: E[] } {
  const matched: E[] = []
  const rest: E[] = []
  for (const entry of entries) {
    if (entry.item.evidenceRefs.some((ref) => refs.has(ref))) matched.push(entry)
    else rest.push(entry)
  }
  return { matched, rest }
}
