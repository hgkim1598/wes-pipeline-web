/*
  AI 설명 문장을 Run 상세의 어느 항목 옆에 보여 줄지 — 근거 id만으로 정한다.

  ── 무엇이 "확인된 대응"인가 `[설계판단]` ──────────────────────────────

  문장마다 붙은 evidenceRefs는 backend가 payload를 만들 때 발급한 id이고,
  발급되지 않은 id를 인용하면 답변 전체가 폐기된다(검사 3). 그래서 id가
  화면의 한 항목을 **하나로** 가리킬 때만 그 항목 옆에 문장을 둔다.

    fail:<code>   이 Run의 실패 중 그 code가 정확히 하나이고, 등록된 code일 때
    dx:<code>     이 Run의 진단 중 그 code가 정확히 하나이고(설명 응답과 화면
                  목록 양쪽에서), 등록된 code일 때
    lim:<code>    이 Run의 제한 사항 중 그 code가 정확히 하나일 때
    step:<id>     이 Run의 단계 중 그 id가 있을 때(Agent가 그 단계를 열었을
                  때만 발급된다)
    단계 행       위 fail·dx가 확인되었고, 그 기록의 actualStepId(backend가
                  기록한 발생 위치)가 있을 때. relatedSteps(일반 지식)는 쓰지
                  않는다.

  등록된 code만 받는 이유: `dx:`·`fail:` 뒤의 값은 원래 code가 아니라
  공개용 code다(backend contract.py `_public_codes`). 실행값이 섞인 code는
  가려지거나 `code_N`으로 바뀌므로, 미등록 code는 문자열이 같아도 같은
  기록이라고 확인할 수 없다. 등록된 code는 바뀌지 않는다.

  같은 code가 두 번 이상 기록되었으면(MULTIQC_MISSING은 00·01 두 단계에서
  날 수 있다) id 하나로 어느 기록인지 알 수 없다. 어느 쪽에도 붙이지 않는다.

  ── 지우지 않는다 ───────────────────────────────────────────────────────

  이 모듈은 위치만 정한다. 문장은 전부 `statements`에 원래 순서로 남고,
  "AI 종합 설명" 패널은 지금처럼 모든 문장을 보여 준다. 한 문장이 여러
  항목을 확인 가능하게 가리키면 각 항목에서 **같은 번호의 같은 문장**을
  참조한다 — 한 응답에서 온 것이므로 서로 충돌하지 않는다.

  summary에는 근거 id가 없어서 어디에도 붙지 않는다(응답 계약의 한계).

  React·import 없이 순수 함수로 둔다: node --test로 검증한다
  (scripts/synthesis-placement.test.mjs).
*/

export type StatementGroup =
  | 'importantFindings'
  | 'limitations'
  | 'nextChecks'
  | 'uncertainties'

export const STATEMENT_GROUPS: readonly StatementGroup[] = [
  'importantFindings',
  'limitations',
  'nextChecks',
  'uncertainties',
]

export interface StatementLike {
  statement: string
  evidenceRefs: readonly string[]
}

export type SynthesisLike = Record<StatementGroup, readonly StatementLike[]>

/** 화면에 있는 기록 하나. stepId는 backend가 기록한 발생 위치이며 없으면 null. */
export interface RecordLike {
  code: string
  stepId: string | null
}

export interface PlacementInput {
  synthesis: SynthesisLike
  /** 실패 카드가 그리는 목록(explanation.failures). */
  failures: readonly RecordLike[]
  /** 설명 응답의 진단(explanation.diagnostics). 발생 위치는 여기서만 읽는다. */
  diagnostics: readonly RecordLike[]
  /** 실패 카드가 실제로 그리는 진단 code 목록(출처가 /results일 수 있다). */
  shownDiagnosticCodes: readonly string[]
  /** explanation.limitations의 code. */
  limitationCodes: readonly string[]
  /** 이 Run의 단계 id. */
  stepIds: readonly string[]
  isRegisteredDiagnostic: (code: string) => boolean
  isRegisteredFailure: (code: string) => boolean
}

export interface PlacedStatement {
  /** 응답 순서의 1부터 시작하는 번호. 패널과 각 위치가 같은 번호를 쓴다. */
  number: number
  group: StatementGroup
  /** 그 묶음 안에서의 위치. */
  index: number
  statement: string
  evidenceRefs: readonly string[]
}

export type UnplacedReason =
  /** 실패·진단·제한·단계를 가리키는 id가 없다(run:·doc:·src: 등만 인용). */
  | 'noTargetRef'
  /** 가리키는 code·id가 이 Run의 화면 목록에 없거나 등록되지 않았다. */
  | 'unconfirmedTarget'
  /** 같은 code가 여러 번 기록되어 어느 기록인지 정할 수 없다. */
  | 'ambiguousTarget'

export interface StatementPlacement {
  statements: PlacedStatement[]
  /** key는 code(또는 단계 id), 값은 statements의 번호 목록. */
  byFailure: Map<string, number[]>
  byDiagnostic: Map<string, number[]>
  byLimitation: Map<string, number[]>
  byStep: Map<string, number[]>
  /** 어느 위치에도 붙지 않은 문장과 그 이유. 패널에는 그대로 있다. */
  unplaced: { number: number; reasons: UnplacedReason[] }[]
  /** 붙은 문장 수(위치 수가 아니라 문장 수). */
  placedCount: number
}

const TARGET_PREFIXES = new Set(['fail', 'dx', 'lim', 'step'])

function count(values: readonly string[]): Map<string, number> {
  const out = new Map<string, number>()
  for (const value of values) out.set(value, (out.get(value) ?? 0) + 1)
  return out
}

function push(map: Map<string, number[]>, key: string, number: number): void {
  const list = map.get(key)
  if (!list) map.set(key, [number])
  else if (!list.includes(number)) list.push(number)
}

function split(ref: string): { prefix: string; value: string } | null {
  const at = ref.indexOf(':')
  if (at <= 0 || at === ref.length - 1) return null
  return { prefix: ref.slice(0, at), value: ref.slice(at + 1) }
}

/** 모든 문장에 번호를 붙인다. 순서는 응답 그대로(묶음 순서 → 묶음 안 순서). */
export function numberStatements(synthesis: SynthesisLike): PlacedStatement[] {
  const out: PlacedStatement[] = []
  for (const group of STATEMENT_GROUPS) {
    synthesis[group].forEach((item, index) => {
      out.push({
        number: out.length + 1,
        group,
        index,
        statement: item.statement,
        evidenceRefs: item.evidenceRefs,
      })
    })
  }
  return out
}

/** 묶음과 묶음 안 위치로 번호를 찾는다. 패널이 같은 번호를 표시할 때 쓴다. */
export function statementNumber(
  statements: readonly PlacedStatement[],
  group: StatementGroup,
  index: number,
): number | null {
  const found = statements.find((s) => s.group === group && s.index === index)
  return found ? found.number : null
}

export function placeStatements(input: PlacementInput): StatementPlacement {
  const statements = numberStatements(input.synthesis)

  const failureCount = count(input.failures.map((f) => f.code))
  const diagnosticCount = count(input.diagnostics.map((d) => d.code))
  const shownCount = count(input.shownDiagnosticCodes)
  const limitationCount = count(input.limitationCodes)
  const steps = new Set(input.stepIds)

  const byFailure = new Map<string, number[]>()
  const byDiagnostic = new Map<string, number[]>()
  const byLimitation = new Map<string, number[]>()
  const byStep = new Map<string, number[]>()
  const unplaced: StatementPlacement['unplaced'] = []
  let placedCount = 0

  /** 발생 위치가 기록된 단계이면 그 단계, 아니면 null. */
  const stepOf = (record: RecordLike | undefined): string | null =>
    record && record.stepId !== null && steps.has(record.stepId)
      ? record.stepId
      : null

  for (const item of statements) {
    const reasons = new Set<UnplacedReason>()
    let placed = false
    let sawTarget = false

    for (const ref of item.evidenceRefs) {
      const parts = split(ref)
      if (!parts || !TARGET_PREFIXES.has(parts.prefix)) continue
      sawTarget = true
      const { prefix, value } = parts

      if (prefix === 'fail') {
        const n = failureCount.get(value) ?? 0
        if (n > 1) reasons.add('ambiguousTarget')
        else if (n === 0 || !input.isRegisteredFailure(value)) reasons.add('unconfirmedTarget')
        else {
          push(byFailure, value, item.number)
          const step = stepOf(input.failures.find((f) => f.code === value))
          if (step) push(byStep, step, item.number)
          placed = true
        }
      } else if (prefix === 'dx') {
        const n = diagnosticCount.get(value) ?? 0
        const shown = shownCount.get(value) ?? 0
        if (n > 1 || shown > 1) reasons.add('ambiguousTarget')
        else if (n === 0 || shown === 0 || !input.isRegisteredDiagnostic(value)) {
          reasons.add('unconfirmedTarget')
        } else {
          push(byDiagnostic, value, item.number)
          const step = stepOf(input.diagnostics.find((d) => d.code === value))
          if (step) push(byStep, step, item.number)
          placed = true
        }
      } else if (prefix === 'lim') {
        const n = limitationCount.get(value) ?? 0
        if (n > 1) reasons.add('ambiguousTarget')
        else if (n === 0) reasons.add('unconfirmedTarget')
        else {
          push(byLimitation, value, item.number)
          placed = true
        }
      } else {
        // step:<id>. id는 step id에서 결정적으로 만들어진다(agent/step_evidence.py).
        if (steps.has(value)) {
          push(byStep, value, item.number)
          placed = true
        } else reasons.add('unconfirmedTarget')
      }
    }

    if (placed) placedCount += 1
    else {
      if (!sawTarget) reasons.add('noTargetRef')
      unplaced.push({ number: item.number, reasons: [...reasons] })
    }
  }

  return { statements, byFailure, byDiagnostic, byLimitation, byStep, unplaced, placedCount }
}

/** 번호 목록을 문장으로. 없는 번호는 건너뛴다. */
export function pick(
  placement: StatementPlacement,
  numbers: readonly number[] | undefined,
): PlacedStatement[] {
  if (!numbers || numbers.length === 0) return []
  const wanted = new Set(numbers)
  return placement.statements.filter((s) => wanted.has(s.number))
}
