/*
  Shared WES domain knowledge — frontend loader.

  canonical source
    config/knowledge/wes_diagnostics.json
    config/knowledge/wes_steps.json

  두 파일은 **저장소 최상위의 config/ 아래**에 있다. frontend 전용도 backend
  전용도 아니다. backend는 같은 파일을 `backend/app/services/explanation/
  knowledge.py`에서 읽는다 — 사본이 아니라 같은 파일이다.

  ── 왜 여기서 검증하는가 ────────────────────────────────────────────────

  JSON은 타입이 없다. `import`만 하면 TypeScript는 그 구조를 그대로 믿고,
  값이 어긋나도 화면이 조용히 잘못된 것을 보여준다. 이 저장소는 API 응답에
  같은 정책을 쓰고 있으므로(각 feature api.ts의 Zod parse) knowledge에도
  같은 규율을 적용한다.

  검증은 **모듈 로드 시 한 번** 일어난다. 실패하면 throw한다 — 잘못된 지식으로
  화면을 그리는 것보다 즉시 드러나는 편이 낫다. 이 데이터는 사용자 입력이
  아니라 저장소가 소유한 파일이므로, 실패는 런타임 사고가 아니라 배포 전에
  잡혀야 할 결함이다(build와 test가 이 경로를 통과한다).

  ── 여기에 없는 것 ─────────────────────────────────────────────────────

  kind · "자동 복구" 같은 라벨 · icon · tone · 표시 순서는 이 파일에 없다.
  전부 presentation이고 diagnostics.ts / steps.ts가 소유한다.
  severity·resolution을 frontend 상수로 다시 복사하지 않는다.
*/

import { z } from 'zod'

import diagnosticsDoc from '@shared/knowledge/wes_diagnostics.json'
import stepsDoc from '@shared/knowledge/wes_steps.json'

/** 확인이 필요한 사건인가. 사건의 무게. */
export const DiagnosticSeveritySchema = z.enum(['attention', 'info'])
export type DiagnosticSeverity = z.infer<typeof DiagnosticSeveritySchema>

/**
 * 파이프라인이 이 사건을 이미 처리했는가. severity와 독립된 축이다.
 *
 * nullable이지만 optional은 아니다 — 키를 생략할 수 있게 두면
 * "복구 없음"과 "아직 분류하지 않음"이 구분되지 않는 세 번째 상태가 생긴다.
 */
export const DiagnosticResolutionSchema = z.enum(['repaired']).nullable()
export type DiagnosticResolution = z.infer<typeof DiagnosticResolutionSchema>

/**
 * `legacy`는 파이프라인이 더 이상 emit하지 않는 code다. 지우면 옛 Run을 읽을 수
 * 없으므로 표시만 해 둔다. 예: `UNCOVERED_TARGETS`.
 */
export const DiagnosticStatusSchema = z.enum(['active', 'legacy'])

export const DiagnosticKnowledgeSchema = z.object({
  code: z.string().min(1),
  severity: DiagnosticSeveritySchema,
  resolution: DiagnosticResolutionSchema,
  /**
   * 이 진단이 **발생할 수 있는** 단계. 이번 Run에서 실제로 발생한 위치가
   * 아니다 — 그것은 `warnings[].stepId`가 말한다. 한 code가 여러 단계에서
   * 나올 수 있어 배열이다(`MULTIQC_MISSING`은 00과 01 양쪽).
   */
  relatedSteps: z.array(z.string()),
  status: DiagnosticStatusSchema,
  title: z.string().min(1),
  meaning: z.string().min(1),
})

export type DiagnosticKnowledge = z.infer<typeof DiagnosticKnowledgeSchema>

export const StepKnowledgeSchema = z.object({
  stepId: z.string().min(1),
  label: z.string().min(1),
  purpose: z.string().min(1),
  /**
   * 이 단계의 실질적인 작업을 수행하는 도구의 canonical 이름.
   * 분석 도구를 실행하지 않는 단계는 빈 배열이다(00·99).
   * 화면 부제는 여기서 만들지 않는다 — steps.ts가 따로 소유한다.
   */
  tools: z.array(z.string()),
})

export type StepKnowledge = z.infer<typeof StepKnowledgeSchema>

const DiagnosticsDocSchema = z.object({
  schemaVersion: z.string(),
  diagnostics: z.array(DiagnosticKnowledgeSchema),
})

const StepsDocSchema = z.object({
  schemaVersion: z.string(),
  steps: z.array(StepKnowledgeSchema),
})

function parseOrThrow<T>(schema: z.ZodType<T>, doc: unknown, source: string): T {
  const parsed = schema.safeParse(doc)
  if (!parsed.success) {
    // 조용히 잘못된 지식을 쓰지 않는다. 이 데이터는 저장소가 소유하므로
    // 여기서 실패하면 배포 전에 고쳐야 할 결함이다.
    throw new Error(
      `${source} does not match the shared knowledge contract:\n${z.prettifyError(parsed.error)}`,
    )
  }
  return parsed.data
}

function indexBy<T>(rows: T[], key: (row: T) => string, source: string): Map<string, T> {
  const map = new Map<string, T>()
  for (const row of rows) {
    const id = key(row)
    // 중복 키는 조용히 덮어쓰지 않는다. 한쪽이 사라진 것을 알 수 없게 된다.
    if (map.has(id)) throw new Error(`${source} has a duplicate key: ${id}`)
    map.set(id, row)
  }
  return map
}

const diagnostics = parseOrThrow(
  DiagnosticsDocSchema,
  diagnosticsDoc,
  'config/knowledge/wes_diagnostics.json',
)
const steps = parseOrThrow(
  StepsDocSchema,
  stepsDoc,
  'config/knowledge/wes_steps.json',
)

const DIAGNOSTIC_BY_CODE = indexBy(
  diagnostics.diagnostics,
  (row) => row.code,
  'wes_diagnostics.json',
)
const STEP_BY_ID = indexBy(steps.steps, (row) => row.stepId, 'wes_steps.json')

/** 등록된 진단 지식. 없으면 undefined — 호출부가 fallback을 정한다. */
export function diagnosticKnowledge(code: string): DiagnosticKnowledge | undefined {
  return DIAGNOSTIC_BY_CODE.get(code)
}

/** 등록된 단계 지식. 없으면 undefined — 호출부가 fallback을 정한다. */
export function stepKnowledge(stepId: string): StepKnowledge | undefined {
  return STEP_BY_ID.get(stepId)
}

/** 전수 조회. 테스트와 향후 목록 화면이 쓴다. */
export function allDiagnosticKnowledge(): DiagnosticKnowledge[] {
  return diagnostics.diagnostics
}

export function allStepKnowledge(): StepKnowledge[] {
  return steps.steps
}
