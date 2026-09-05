/*
  Run의 진단 사건을 단계별로 모은다.

  ── 출처를 /results로 고른 이유 ────────────────────────────────────────

  같은 사건이 세 endpoint에 서로 다른 모양으로 실려 온다.

    GET /api/jobs/{id}          steps[].messages: string[]
                                "[NM_MD_REPAIRED] NM and MD tags were ..."
                                code와 message가 한 문자열로 합쳐져 있고
                                warning인지 failure인지도 구분되지 않는다
                                (backend/app/services/run_status_reader.py
                                 _step_messages).

    GET .../steps/{stepId}      warnings[] · failures[]  구조 보존. 단, 한
                                단계씩만.

    GET .../results             warnings[] · failures[]  구조 보존 + stepId.
                                full 실행은 core_summary.json이 각 warning에
                                step_id를 붙여 두므로(script/main.sh:4616)
                                한 번의 요청으로 전 단계를 덮는다.

  그래서 /results를 쓴다. messages 문자열에서 정규식으로 code를 뽑아내는
  선택지는 버렸다 — backend의 문자열 포맷에 화면이 종속되고, 그 포맷은
  계약이 아니라 로그용 표현이다.

  ── 실행 중에는 severity를 주장하지 않는다 ─────────────────────────────

  /results는 실행이 끝나기 전에는 409다(backend/app/api/results.py). 따라서
  실행 중에는 이 모듈이 빈 결과를 준다. 그때 단계 표는 backend가 준
  messages 원문을 중립적으로 한 줄 보여준다 — "확인 필요"인지 "참고"인지
  단정하지 않는다. 아직 모르는 것을 아는 척하지 않는 편이 맞다.

  선택한 단계의 상세는 /steps/{stepId}를 직접 쓰므로 실행 중에도 구조화된
  진단을 볼 수 있다.
*/

import type {
  NotReady,
  PipelineFailure,
  PipelineWarning,
  Results,
} from '@/features/run-detail/api'
import { isNotReady } from '@/features/run-detail/api'
import type { DiagnosticKind, DiagnosticView } from '@/registries/diagnostics'
import { describeDiagnostic, describeFailure } from '@/registries/diagnostics'

export interface RunDiagnostic {
  /** 목록 key. 같은 code가 여러 단계에서 날 수 있어 stepId를 함께 쓴다. */
  key: string
  stepId: string | null
  code: string
  /** backend 원문. registry에 없는 code일 때 제목 자리를 대신한다. */
  message: string
  /** backend의 impact 원문. 전문가용 Layer 3. warning에만 있다. */
  impact: string
  view: DiagnosticView
}

export interface DiagnosticCollection {
  /** stepId -> 그 단계의 진단. 순서는 backend가 준 순서를 유지한다. */
  byStep: Map<string, RunDiagnostic[]>
  /** 단계를 특정할 수 없는 진단. 화면은 이것도 버리지 않는다. */
  unattributed: RunDiagnostic[]
  all: RunDiagnostic[]
  /** kind별 건수. 헤더 요약이 쓴다. */
  counts: Record<DiagnosticKind, number>
}

const EMPTY: DiagnosticCollection = {
  byStep: new Map(),
  unattributed: [],
  all: [],
  counts: { repaired: 0, attention: 0, note: 0, failure: 0 },
}

export function toDiagnostic(
  item: PipelineWarning | PipelineFailure,
  isFailure: boolean,
  index: number,
): RunDiagnostic {
  const impact = 'impact' in item ? item.impact : ''
  return {
    key: `${item.stepId ?? 'run'}-${item.code || 'no-code'}-${index}`,
    stepId: item.stepId,
    code: item.code,
    message: item.message,
    impact,
    view: isFailure ? describeFailure() : describeDiagnostic(item.code),
  }
}

/**
 * 결과 응답에서 진단을 모은다.
 *
 * `plannedSteps`는 stepId가 비어 있는 진단을 귀속시키는 데만 쓴다.
 * --check-only 실행의 계획은 00_input_validation 하나뿐이고
 * (backend/app/services/config_builder.py planned_steps), 그때 backend는
 * 그 단계의 warning을 step_id 없이 돌려준다(result_reader._read_precheck는
 * step 문서를 직접 읽으므로 step_id 키가 없다). 계획된 단계가 정확히 하나일
 * 때만 귀속시키고, 그 외에는 추측하지 않고 unattributed로 남긴다.
 */
export function collectDiagnostics(
  results: Results | NotReady | undefined,
  plannedSteps: string[],
): DiagnosticCollection {
  if (results === undefined || isNotReady(results)) return EMPTY

  const soleStep = plannedSteps.length === 1 ? plannedSteps[0] : null

  const all: RunDiagnostic[] = [
    ...results.failures.map((item, i) => toDiagnostic(item, true, i)),
    ...results.warnings.map((item, i) => toDiagnostic(item, false, i)),
  ].map((diagnostic) =>
    diagnostic.stepId === null && soleStep !== null
      ? { ...diagnostic, stepId: soleStep }
      : diagnostic,
  )

  const byStep = new Map<string, RunDiagnostic[]>()
  const unattributed: RunDiagnostic[] = []
  const counts: Record<DiagnosticKind, number> = {
    repaired: 0,
    attention: 0,
    note: 0,
    failure: 0,
  }

  for (const diagnostic of all) {
    counts[diagnostic.view.kind] += 1
    if (diagnostic.stepId === null) {
      unattributed.push(diagnostic)
      continue
    }
    const bucket = byStep.get(diagnostic.stepId)
    if (bucket) bucket.push(diagnostic)
    else byStep.set(diagnostic.stepId, [diagnostic])
  }

  return { byStep, unattributed, all, counts }
}

/**
 * 한 단계의 진단을 화면에 내보낼 순서로 정렬한다.
 *
 * 실패 → 확인 필요 → 자동 복구 → 참고. 사용자가 먼저 읽어야 하는 것이
 * 위로 온다. 같은 kind 안에서는 backend 순서를 유지한다.
 */
const KIND_ORDER: Record<DiagnosticKind, number> = {
  failure: 0,
  attention: 1,
  repaired: 2,
  note: 3,
}

export function byPriority(a: RunDiagnostic, b: RunDiagnostic): number {
  return KIND_ORDER[a.view.kind] - KIND_ORDER[b.view.kind]
}

/** 이 단계에서 사용자가 확인해야 할 것이 있는가. 표에서 강조할지 판단한다. */
export function needsAttention(diagnostics: RunDiagnostic[]): boolean {
  return diagnostics.some(
    (d) => d.view.kind === 'failure' || d.view.kind === 'attention',
  )
}
