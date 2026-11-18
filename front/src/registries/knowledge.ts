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

import causeKindsDoc from '@shared/knowledge/wes_cause_kinds.json'
import conceptsDoc from '@shared/knowledge/wes_concepts.json'
import diagnosticsDoc from '@shared/knowledge/wes_diagnostics.json'
import failuresDoc from '@shared/knowledge/wes_failures.json'
import passagesDoc from '@shared/knowledge/wes_doc_passages.public.json'
import sourcesDoc from '@shared/knowledge/wes_sources.json'
import stepsDoc from '@shared/knowledge/wes_steps.json'
import termsDoc from '@shared/knowledge/wes_terms.json'

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

/*
  실패 code의 curated 지식.

  ── grounding을 여기서 모델링하지 않는다 `[설계판단]` ───────────────────

  shared 파일에는 `grounding`(possibleCauses·scope·checks·actions)이 함께 들어
  있지만 이 schema는 그것을 선언하지 않는다. Zod object는 모르는 key를 무시하므로
  검증은 통과하고, 화면은 title·meaning만 쓴다.

  이유는 소비자가 다르기 때문이다. grounding은 backend의 설명 계층이 읽는
  근거 자료이고, 그쪽 loader가 Pydantic으로 전수 검증하면서 **모든 claim의
  sourceIds가 실제로 존재하는지까지** 확인한다. 화면이 쓰지도 않는 구조를
  TypeScript로 한 번 더 옮겨 적으면, 두 schema가 갈라질 때 무엇이 옳은지
  판단할 근거가 없어진다.

  화면이 근거를 실제로 표시하게 되면 그때 여기에 추가한다.

  ── closedSet ──────────────────────────────────────────────────────────

  이 목록은 전수가 아니다. main.sh가 일부 failure code를 실행 값으로 조립한다.
  등록되지 않은 code는 결함이 아니라 정상이며, 호출부가 실행 원문을 그대로
  보여준다.
*/
export const FailureKnowledgeSchema = z.object({
  code: z.string().min(1),
  title: z.string().min(1),
  meaning: z.string().min(1),
})

export type FailureKnowledge = z.infer<typeof FailureKnowledgeSchema>

const FailuresDocSchema = z.object({
  schemaVersion: z.string(),
  // literal(false)로 고정한다. 이 값이 true로 바뀌면 "등록되지 않은 code는
  // 결함"이라는 규칙이 성립하는데, 실행 값으로 조립되는 code가 있는 한
  // 그것은 참일 수 없다. 조용히 넘어가지 않고 로드에서 실패한다.
  closedSet: z.literal(false),
  failures: z.array(FailureKnowledgeSchema),
})

/*
  근거 출처와 해석 개념.

  ── 왜 이제 와서 읽는가 ────────────────────────────────────────────────

  `knowledge.ts`는 지금까지 이 두 파일을 읽지 않았고, 그 이유를 아래
  `grounding` 주석에 적어 뒀다 — 화면이 근거를 표시하지 않으니 backend만
  읽으면 된다는 것이었다. 2차 polish에서 AI 설명의 `evidenceRefs`를 사람이
  읽는 이름으로 바꾸기로 하면서 **화면이 실제 소비자가 됐다.**

  새 이름을 frontend에 하드코딩하지 않는다. `src:sam-tags-spec`의 이름은
  `wes_sources.json`의 `title`이고, `concept:...`의 이름은 `label`이다.
  둘 다 canonical source에 이미 있다.

  `grounding`은 여전히 모델링하지 않는다. 화면이 쓰는 것은 title/label뿐이고,
  claim 본문까지 TypeScript로 옮기면 backend와 갈라질 표면만 늘어난다.
*/
export const SourceKnowledgeSchema = z.object({
  id: z.string().min(1),
  /** spec · tool-doc · pipeline · project-doc. 화면은 분류로만 쓴다. */
  type: z.string().min(1),
  title: z.string().min(1),
  locator: z.string().min(1),
})

export type SourceKnowledge = z.infer<typeof SourceKnowledgeSchema>

const SourcesDocSchema = z.object({
  schemaVersion: z.string(),
  sources: z.array(SourceKnowledgeSchema),
})

export const ConceptKnowledgeSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  summary: z.string().min(1),
})

export type ConceptKnowledge = z.infer<typeof ConceptKnowledgeSchema>

const ConceptsDocSchema = z.object({
  schemaVersion: z.string(),
  concepts: z.array(ConceptKnowledgeSchema),
})

/*
  초보자 용어 (`wes_terms.json`).

  AI 설명이 `term:<id>`를 근거로 인용할 수 있다. 화면이 쓰는 것은 그 근거의
  **이름(label)뿐**이라 id와 label만 모델링한다. 정의·오해·사용 조건은
  backend가 payload에 넣는 내용이고, 여기에 옮기면 같은 정의가 두 곳에 생긴다.
  화면 popover 문구(glossary.ts)와도 합치지 않는다 — 그쪽은 별도 작업이다.
*/
export const TermKnowledgeSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
})

export type TermKnowledge = z.infer<typeof TermKnowledgeSchema>

const TermsDocSchema = z.object({
  schemaVersion: z.string(),
  terms: z.array(TermKnowledgeSchema),
})

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
const failures = parseOrThrow(
  FailuresDocSchema,
  failuresDoc,
  'config/knowledge/wes_failures.json',
)

const DIAGNOSTIC_BY_CODE = indexBy(
  diagnostics.diagnostics,
  (row) => row.code,
  'wes_diagnostics.json',
)
const STEP_BY_ID = indexBy(steps.steps, (row) => row.stepId, 'wes_steps.json')
const FAILURE_BY_CODE = indexBy(
  failures.failures,
  (row) => row.code,
  'wes_failures.json',
)

const sources = parseOrThrow(
  SourcesDocSchema,
  sourcesDoc,
  'config/knowledge/wes_sources.json',
)
const concepts = parseOrThrow(
  ConceptsDocSchema,
  conceptsDoc,
  'config/knowledge/wes_concepts.json',
)

const terms = parseOrThrow(TermsDocSchema, termsDoc, 'config/knowledge/wes_terms.json')

const TERM_BY_ID = indexBy(terms.terms, (row) => row.id, 'wes_terms.json')

const SOURCE_BY_ID = indexBy(sources.sources, (row) => row.id, 'wes_sources.json')
const CONCEPT_BY_ID = indexBy(
  concepts.concepts,
  (row) => row.id,
  'wes_concepts.json',
)

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

/**
 * 등록된 실패 지식. 없으면 undefined.
 *
 * **undefined가 흔한 경우다.** 실패 code는 닫힌 집합이 아니므로, 호출부는
 * 이것을 "아직 안 채운 빈칸"이 아니라 "지식이 없는 code"로 다뤄야 하고
 * 실행이 기록한 원문을 대신 보여줘야 한다.
 */
export function failureKnowledge(code: string): FailureKnowledge | undefined {
  return FAILURE_BY_CODE.get(code)
}

export function allFailureKnowledge(): FailureKnowledge[] {
  return failures.failures
}

/** 인용된 출처. 없으면 undefined — 호출부가 raw id를 그대로 보여준다. */
export function sourceKnowledge(id: string): SourceKnowledge | undefined {
  return SOURCE_BY_ID.get(id)
}

/** 해석 개념. 없으면 undefined. */
export function conceptKnowledge(id: string): ConceptKnowledge | undefined {
  return CONCEPT_BY_ID.get(id)
}

/** 초보자 용어. 없으면 undefined — 호출부가 raw id를 그대로 보여준다. */
export function termKnowledge(id: string): TermKnowledge | undefined {
  return TERM_BY_ID.get(id)
}

/*
  공식 문서 발췌(로컬 RAG, 개발판단기록 18장). `doc:<id>`로 인용된다.

  제목과 링크는 발췌 파일에 없다. `sourceId`로 wes_sources.json에서 가져온다 —
  backend(doc_retrieval.source_title / source_url)와 같은 규칙이라, Agent가 봤다고
  기록된 문서와 화면이 여는 링크가 같은 문서다.
*/
const DocPassageSchema = z.object({
  id: z.string().min(1),
  sourceId: z.string().min(1),
  heading: z.string().min(1),
  quote: z.string().min(1),
})

const DocPassagesDocSchema = z.object({
  passages: z.array(DocPassageSchema),
})

const passages = parseOrThrow(
  DocPassagesDocSchema,
  passagesDoc,
  'document passage corpus',
)
const PASSAGE_BY_ID = indexBy(passages.passages, (row) => row.id, 'wes_doc_passages.json')

export interface DocPassageKnowledge {
  id: string
  heading: string
  quote: string
  source: SourceKnowledge
}

/** 공식 문서 발췌와 그 출처. 출처가 등록돼 있지 않으면 undefined. */
export function docPassageKnowledge(id: string): DocPassageKnowledge | undefined {
  const row = PASSAGE_BY_ID.get(id)
  const source = row ? SOURCE_BY_ID.get(row.sourceId) : undefined
  if (!row || !source) return undefined
  return { id: row.id, heading: row.heading, quote: row.quote, source }
}

/*
  리소스 검사 실패 원인 종류별 점검 지식 (`wes_cause_kinds.json`, P1).

  backend는 같은 파일을 Agent의 단계 근거(causeGuidance)에 넣는다. 화면은
  단계 상세의 resourceBundleDiagnosis가 준 kind·resourceRole을 **키로 그대로
  찾기만** 한다 — 검색도 순위도 없다. 문장을 화면에서 다시 쓰지 않는다.

  cautions·remedies는 모든 종류에 있지 않다. 1차 근거가 없는 종류는 파일이
  일부러 비워 두었으므로(파일 _comment) 없음은 빈 배열로 읽는다.
*/
const CauseStatementSchema = z.object({
  statement: z.string().min(1),
  sourceIds: z.array(z.string().min(1)),
})

export type CauseStatement = z.infer<typeof CauseStatementSchema>

const CauseRemedySchema = CauseStatementSchema.extend({
  /** 무엇을 바꾸는 일인가. */
  changes: z.string().min(1),
  /** 누가 승인하는가. Agent·화면은 제안만 한다. */
  approval: z.string().min(1),
})

export type CauseRemedy = z.infer<typeof CauseRemedySchema>

const CauseKindKnowledgeSchema = z.object({
  kind: z.string().min(1),
  title: z.string().min(1),
  checks: z.array(CauseStatementSchema),
  cautions: z.array(CauseStatementSchema).optional(),
  remedies: z.array(CauseRemedySchema).optional(),
})

export type CauseKindKnowledge = z.infer<typeof CauseKindKnowledgeSchema>

const CauseRoleKnowledgeSchema = z.object({
  role: z.string().min(1),
  title: z.string().min(1),
  checks: z.array(CauseStatementSchema),
})

export type CauseRoleKnowledge = z.infer<typeof CauseRoleKnowledgeSchema>

const CauseKindsDocSchema = z.object({
  schemaVersion: z.string(),
  causeKinds: z.array(CauseKindKnowledgeSchema),
  roles: z.array(CauseRoleKnowledgeSchema),
})

const causeKinds = parseOrThrow(
  CauseKindsDocSchema,
  causeKindsDoc,
  'config/knowledge/wes_cause_kinds.json',
)
const CAUSE_KIND_BY_KIND = indexBy(
  causeKinds.causeKinds,
  (row) => row.kind,
  'wes_cause_kinds.json causeKinds',
)
const CAUSE_ROLE_BY_ROLE = indexBy(
  causeKinds.roles,
  (row) => row.role,
  'wes_cause_kinds.json roles',
)

/** 원인 종류의 점검 지식. `unknown`이나 미등록 종류는 undefined. */
export function causeKindKnowledge(kind: string): CauseKindKnowledge | undefined {
  return CAUSE_KIND_BY_KIND.get(kind)
}

/** 대상 리소스의 점검 지식. `unknown`이나 미등록 역할은 undefined. */
export function causeRoleKnowledge(role: string): CauseRoleKnowledge | undefined {
  return CAUSE_ROLE_BY_ROLE.get(role)
}
