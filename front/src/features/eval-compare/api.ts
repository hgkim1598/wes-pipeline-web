/*
  평가자 전용 A/B 비교 데이터 — backend/app/api/eval_compare.py.

  접근
  - backend는 WES_EVAL_COMPARE=1이고, 요청이 같은 PC(loopback)에서 왔고,
    X-WES-Eval-Token이 WES_EVAL_COMPARE_TOKEN과 같을 때만 답한다.
  - 꺼져 있거나 다른 PC면 404, 토큰이 없거나 틀리면 401, 서버에 토큰이
    설정돼 있지 않으면 503이다.
  - 토큰은 이 탭의 sessionStorage에만 둔다(탭을 닫으면 사라진다).

  상태와 결과(served / gateRejected / providerError / unclassified, 호출 상태)는
  backend가 evals/ab_compare/contract.py로 판정해 보낸다. 이 화면은 다시
  판정하지 않는다.

  답변에서 나온 값(served/gateRejected 구분, 자동 점수, 응답 시간, 모델, Tool
  사용)은 블라인드 해제 뒤, 식별자 검사를 통과한 호출에만 온다. 그 전에는 null
  이고, 답변을 받은 호출의 결과는 "answered"다(독립 리뷰 H3·M2, 2026-11-22).
  사람 채점은 backend가 complete로 완료 여부를 함께 보낸다(H2).

  이 화면은 모델을 부르지 않는다. 답변은 승인된 runner CLI(evals/ab_compare)가
  만들어 저장한 것이고, 여기서는 읽기, 사람 채점 추가, 블라인드 해제 기록만 한다.
*/

import { z } from 'zod'

import { ApiError, getJson, postJson } from '@/api/client'

export const EVAL_COMPARE_PATH = '/api/eval/compare'
const TOKEN_KEY = 'wes.evalCompare.token'
/** sessionStorage가 막힌 브라우저에서도 이 페이지 동안은 쓰이게. */
let memoryToken = ''

export function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function writeToken(value: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, value)
  } catch {
    /* 저장하지 못하면 이 페이지에서만 쓰인다 */
  }
  memoryToken = value
}

function authHeaders(): Record<string, string> {
  const token = readToken() || memoryToken
  return token ? { 'X-WES-Eval-Token': token } : {}
}

const Claim = z.object({
  statement: z.string(),
  evidenceRefs: z.array(z.string()),
})
export type AnswerClaim = z.infer<typeof Claim>

const Answer = z.object({
  summary: z.string().nullish(),
  importantFindings: z.array(Claim).default([]),
  limitations: z.array(Claim).default([]),
  nextChecks: z.array(Claim).default([]),
  uncertainties: z.array(Claim).default([]),
})
export type Answer = z.infer<typeof Answer>

const DetectorHit = z.object({
  detector: z.string(),
  metric: z.string(),
  where: z.string(),
  excerpt: z.string().optional(), // 블라인드 해제 전에는 보내지 않는다
})

const AnswerScores = z.object({
  measured: z.boolean(),
  claimCount: z.number().optional(),
  nonRunClaims: z.number().optional(),
  execContradictions: z.number().optional(),
  detectorHits: z.array(DetectorHit).optional(),
  wrongCauseCandidates: z.array(z.object({ candidate: z.string(), where: z.string(), excerpt: z.string().optional() })).optional(),
  requiredCauses: z
    .object({ mentioned: z.number(), required: z.number(), byCause: z.record(z.string(), z.boolean()) })
    .optional(),
  citedRefs: z.array(z.string()).optional(),
  citedBySource: z.record(z.string(), z.number()).optional(),
})
export type AnswerScores = z.infer<typeof AnswerScores>

const CallScores = z.object({
  served: AnswerScores,
  rejected: AnswerScores,
})

/** answered: 블라인드 해제 전, 답변을 받은 호출(served/gateRejected 구분은 숨김). */
export const OUTCOMES = ['served', 'gateRejected', 'answered', 'providerError', 'unclassified'] as const
export type Outcome = (typeof OUTCOMES)[number]
export const EXCLUSIONS = ['privacy', 'integrity', 'integrityUnchecked', 'providerError', 'unclassified'] as const
export type Exclusion = (typeof EXCLUSIONS)[number]

/** contract.evaluation_of — 이 기록이 무엇에 세어지는가, 안 세어지면 왜. */
const Evaluation = z.object({
  outcome: z.enum(OUTCOMES),
  category: z.string().nullish(),
  answerProduced: z.boolean().nullable(),
  exclusion: z.enum(EXCLUSIONS).nullable(),
  countsForGate: z.boolean(),
  /** 해제 전 답변 받은 호출은 null: false면 "답이 파싱되지 않은 Gate 거부"라는 뜻이라 보내지 않는다. */
  countsForContent: z.boolean().nullable(),
  integrityChecked: z.boolean(),
})
export type Evaluation = z.infer<typeof Evaluation>

const Integrity = z.object({
  ok: z.boolean(),
  checks: z.record(z.string(), z.boolean()),
  notInCallPathImported: z.array(z.string()).default([]),
})

const CallSummary = z.object({
  callId: z.string(),
  attempt: z.number(),
  attempts: z.number(),
  arm: z.enum(['A', 'B']),
  case: z.string(),
  repeat: z.number(),
  seq: z.number(),
  blindCode: z.string().nullable(),
  mock: z.boolean(),
  startedAt: z.string().nullish(),
  promptHash: z.string().nullish(),
  knowledgeHash: z.string().nullish(),
  payloadDigest: z.string().nullish(),
  privacyOk: z.boolean(),
  evaluation: Evaluation,
  integrity: Integrity.nullish(),
  /** 답변에서 나온 값을 왜 보내지 않았나: blind(해제 전) · privacy(식별자 검사 걸림) · null(보냄). */
  answerDerivedWithheld: z.enum(['blind', 'privacy']).nullish(),
  // --- 답변에서 나온 값: answerDerivedWithheld가 있으면 null ---
  models: z.array(z.string()).nullish(),
  toolUse: z
    .object({
      toolUsed: z.boolean().nullish(),
      openedStepIds: z.array(z.string()),
      callCount: z.number().nullish(),
    })
    .nullish(),
  durationMs: z.number().nullish(),
  wallMs: z.number().nullish(),
  scores: CallScores.nullish(),
})
export type CallSummary = z.infer<typeof CallSummary>

const ClaimGrade = z.object({
  section: z.string(),
  index: z.number(),
  verdict: z.enum(['supported', 'contradicted', 'undetermined']).nullable(),
  source: z.enum(['record', 'doc', 'knowledge', 'none']).nullable(),
  nonRunClaim: z.boolean(),
  execContradiction: z.boolean(),
  unsupportedCause: z.boolean(),
})
export type ClaimGrade = z.infer<typeof ClaimGrade>

const Grade = z.object({
  code: z.string(),
  grader: z.string(),
  savedAt: z.string(),
  claims: z.array(ClaimGrade),
  requiredCauses: z.record(z.string(), z.boolean().nullable()),
  understanding: z.number().nullable(),
  usefulness: z.number().nullable(),
  notes: z.string(),
  /** 저장할 때 블라인드였는가. 첫 판 기록에는 없다(그때는 해제 기능이 없었다). */
  blind: z.boolean().optional(),
  versions: z.number().optional(),
  /** backend가 판정한 완료 여부. 없거나 false면 채점 완료로 세지 않는다. */
  complete: z.boolean().optional(),
  /** 미완료일 때 빠진 것: claims · requiredCauses · understanding · usefulness · answer. */
  missing: z.array(z.string()).optional(),
})
export type Grade = z.infer<typeof Grade>

const Fact = z.object({ stepId: z.string(), state: z.string(), label: z.string(), source: z.string() })
const Cause = z.object({ id: z.string(), label: z.string(), source: z.string() })
const CaseSpec = z.object({
  case: z.string(),
  kind: z.string().optional(),
  label: z.string(),
  synthetic: z.boolean(),
  role: z.string().optional(),
  facts: z.object({
    steps: z.array(Fact),
    requiredCauses: z.array(Cause),
    notes: z.array(z.object({ text: z.string(), source: z.string() })).default([]),
  }),
})
export type CaseSpec = z.infer<typeof CaseSpec>

const Criterion = z.object({
  id: z.string(),
  metric: z.string(),
  rule: z.string(),
  source: z.enum(['auto', 'human']),
  label: z.string(),
})
export type Criterion = z.infer<typeof Criterion>

const ArmInfo = z.object({
  label: z.string(),
  source: z.object({ kind: z.string(), commit: z.string().optional() }),
  headAtSnapshot: z.string().optional(),
  fileCount: z.number().optional(),
  manifestSha256: z.string().optional(),
})

const PayloadCheck = z.object({
  payloadEqual: z.boolean(),
  constraintsEqual: z.boolean(),
  promptHashEqual: z.boolean(),
  privacy: z.record(z.string(), z.string()),
  leaks: z.record(z.string(), z.number()),
})

export const CALL_STATES = [
  'planned',
  'recorded',
  'recoverable',
  'running',
  'uncertain',
  'notInvoked',
  'inFlightOrUncertain',
  'inFlightOrNotInvoked',
  'unreadableRecord',
] as const
export type CallState = (typeof CALL_STATES)[number]

const PlanItem = z.object({
  callId: z.string(),
  case: z.string(),
  arm: z.enum(['A', 'B']),
  repeat: z.number(),
  seq: z.number(),
  state: z.enum(CALL_STATES),
  outcome: z.enum(OUTCOMES).nullable(),
  attempts: z.number(),
  history: z.array(z.object({ attempt: z.number(), outcome: z.enum(OUTCOMES) })).default([]),
})
export type PlanItem = z.infer<typeof PlanItem>

const ExperimentDetail = z.object({
  experimentId: z.string(),
  mock: z.boolean(),
  createdAt: z.string(),
  protocolSha256: z.string(),
  protocol: z.object({
    title: z.string(),
    fixedAt: z.string(),
    protocolVersion: z.number(),
    note: z.array(z.string()),
    conditions: z.record(z.string(), z.unknown()),
    repeats: z.number(),
    order: z.string(),
    cases: z.array(CaseSpec),
    claimUnit: z.string(),
    metrics: z.array(z.object({ id: z.string(), label: z.string(), auto: z.string().nullable(), human: z.string().nullable() })),
    successCriteria: z.array(Criterion),
    intendedDifference: z.array(z.string()),
    outcomeContract: z.array(z.string()),
    evaluationRule: z.string().nullish(),
    modelIdentity: z.string().nullish(),
    detectors: z.array(z.object({ id: z.string(), metric: z.string(), label: z.string() })),
    wrongCauseCandidates: z.array(z.object({ id: z.string(), label: z.string() })),
  }),
  arms: z.object({ A: ArmInfo, B: ArmInfo }),
  armDiff: z.object({
    changed: z.array(z.string()),
    added: z.array(z.string()),
    removed: z.array(z.string()).default([]),
    harnessIdentical: z.boolean().optional(),
    gateAndPromptCodeIdentical: z.boolean().optional(),
  }),
  diffClassification: z
    .object({
      byPath: z.record(z.string(), z.object({ class: z.string(), reason: z.string() })),
      unclassified: z.array(z.string()),
    })
    .nullish(),
  sharedLocalInputs: z.array(z.string()),
  payloadChecks: z.record(z.string(), PayloadCheck).nullable(),
  blind: z.object({
    unblinded: z.boolean(),
    unblindedAt: z.string().nullish(),
    gradable: z.number(),
    /** 완료된 채점만. */
    graded: z.number(),
    gradedIncomplete: z.number().default(0),
    /** 해제 전: 짝(같은 사례·반복의 A·B)이 다 갖춰지지 않아 블라인드 채점에서 빠진 답변 수. */
    heldUntilUnblind: z.number().default(0),
    gradedAfterUnblind: z.number(),
  }),
  approvals: z.array(
    z.object({
      approvalId: z.string(),
      mode: z.string().nullish(),
      calls: z.array(z.string()),
      maxCliCalls: z.number().nullish(),
      approvedAt: z.string().nullish(),
      usedAtMost: z.number(),
    }),
  ),
  plan: z.array(PlanItem),
  calls: z.array(CallSummary),
  grades: z.record(z.string(), Grade),
})
export type ExperimentDetail = z.infer<typeof ExperimentDetail>

const CallDetail = CallSummary.extend({
  available: z.boolean().nullish(),
  errorCategory: z.string().nullish(),
  checks: z.object({
    deterministicPassed: z.boolean().nullish(),
    results: z.array(
      z.object({ name: z.string().nullish(), kind: z.string().nullish(), outcome: z.string().nullish(), detail: z.string().nullish() }),
    ),
  }),
  withheldForPrivacy: z.boolean(),
  withheldForBlind: z.boolean(),
  output: Answer.nullable(),
  rejected: z
    .object({ category: z.string().nullish(), findings: z.array(z.unknown()), answer: Answer.nullable() })
    .nullable(),
})
export type CallDetail = z.infer<typeof CallDetail>

const ExperimentList = z.object({
  experiments: z.array(
    z.object({
      experimentId: z.string(),
      title: z.string(),
      mock: z.boolean(),
      createdAt: z.string(),
      planned: z.number(),
      recorded: z.number(),
      answered: z.number(),
    }),
  ),
})
export type ExperimentList = z.infer<typeof ExperimentList>

const PayloadArm = z.object({
  payloadDigest: z.string().nullish(),
  constraintsDigest: z.string().nullish(),
  promptHash: z.string().nullish(),
  knowledgeHash: z.string().nullish(),
  allowedRefCount: z.number().nullish(),
  withheldForPrivacy: z.boolean(),
  payload: z.unknown(),
})
const Payloads = z.object({ case: z.string(), arms: z.object({ A: PayloadArm, B: PayloadArm }) })
export type Payloads = z.infer<typeof Payloads>

const BlindClaim = z.object({ section: z.string(), index: z.number(), statement: z.string(), evidenceRefs: z.array(z.string()) })
export type BlindClaim = z.infer<typeof BlindClaim>
const Blind = z.object({
  experimentId: z.string(),
  mock: z.boolean(),
  unblinded: z.boolean(),
  cases: z.array(CaseSpec.pick({ case: true, label: true, synthetic: true, facts: true })),
  answers: z.array(
    z.object({ code: z.string(), case: z.string(), caseLabel: z.string(), summary: z.string().nullish(), claims: z.array(BlindClaim) }),
  ),
  /** 해제 전에는 짝이 다 갖춰진 답변만 온다. 나머지 수(어느 경로인지는 없음). */
  heldUntilUnblind: z.number().default(0),
  grades: z.record(z.string(), Grade),
})
export type Blind = z.infer<typeof Blind>

function parse<T>(schema: z.ZodType<T>, payload: unknown, what: string): T {
  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new ApiError(`${what} 응답이 예상한 형식과 다릅니다.`, {
      kind: 'malformed',
      detail: z.prettifyError(parsed.error),
      cause: parsed.error,
    })
  }
  return parsed.data
}

const enc = encodeURIComponent
const get = (path: string, signal?: AbortSignal) => getJson(path, { signal, headers: authHeaders() })
const post = (path: string, body: unknown) => postJson(path, body, { headers: authHeaders() })

export async function fetchExperiments(signal?: AbortSignal): Promise<ExperimentList> {
  return parse(ExperimentList, await get(EVAL_COMPARE_PATH, signal), '비교 실험 목록')
}

export async function fetchExperiment(id: string, signal?: AbortSignal): Promise<ExperimentDetail> {
  return parse(ExperimentDetail, await get(`${EVAL_COMPARE_PATH}/${enc(id)}`, signal), '비교 실험')
}

export async function fetchCall(id: string, callId: string, signal?: AbortSignal): Promise<CallDetail> {
  return parse(CallDetail, await get(`${EVAL_COMPARE_PATH}/${enc(id)}/calls/${enc(callId)}`, signal), '호출 기록')
}

export async function fetchPayloads(id: string, caseName: string, signal?: AbortSignal): Promise<Payloads> {
  return parse(Payloads, await get(`${EVAL_COMPARE_PATH}/${enc(id)}/payloads/${enc(caseName)}`, signal), '모델 입력')
}

export async function fetchBlind(id: string, signal?: AbortSignal): Promise<Blind> {
  return parse(Blind, await get(`${EVAL_COMPARE_PATH}/${enc(id)}/blind`, signal), '블라인드 채점')
}

export interface GradeInput {
  grader: string
  claims: ClaimGrade[]
  requiredCauses: Record<string, boolean | null>
  understanding: number | null
  usefulness: number | null
  notes: string
}

export async function saveGrade(id: string, code: string, grade: GradeInput): Promise<Grade> {
  return parse(Grade, await post(`${EVAL_COMPARE_PATH}/${enc(id)}/grades/${enc(code)}`, grade), '채점 저장')
}

const UnblindRecord = z.object({ unblindedAt: z.string(), by: z.string() })

export async function unblind(id: string, by: string): Promise<z.infer<typeof UnblindRecord>> {
  return parse(UnblindRecord, await post(`${EVAL_COMPARE_PATH}/${enc(id)}/unblind`, { confirm: 'unblind', by }), '블라인드 해제')
}
