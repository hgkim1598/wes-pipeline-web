import { SectionHeader } from '@/components/ui/SectionHeader'
import type {
  ResourceBundleCause,
  ResourceBundleDiagnosis,
} from '@/features/run-detail/api'
import {
  causeKindKnowledge,
  causeRoleKnowledge,
  sourceKnowledge,
} from '@/registries/knowledge'
import type { CauseStatement } from '@/registries/knowledge'

/*
  리소스 검사 실패 원인 — "왜 멈췄나"와 "다음에 무엇을 보나".

  ── 무엇을 보여주나 ─────────────────────────────────────────────────────

  backend가 00_input_validation 단계 상세에 실어 보내는 resourceBundleDiagnosis
  (P0-1, ADR-001)다. 고정 규칙표가 실패 문장을 한 줄씩 분류한 결과이며,
  **모델이 만든 것이 아니다.** 이전 화면은 이 필드를 Zod에서 버리고 있어서
  "참조 데이터 구성을 확인하지 못했습니다"라는 일반 문장만 남았다.

  왼쪽은 기록된 원인(무엇이 어떤 리소스에서), 오른쪽은 그 종류에 등록된 점검
  문장(wes_cause_kinds.json)이다. 점검 문장은 "보는" 일만 담고, 바꾸는 일은
  승인자를 붙여 따로 둔다 — 지식 파일의 구분을 그대로 따른다.

  ── 만들지 않는 것 ──────────────────────────────────────────────────────

  원인 사이의 선후 관계(root cause)를 쓰지 않는다. 규칙표는 그것을 판단하지
  않으며(resource_bundle_causes.py 머리말), 화면이 지어내면 사용자가 엉뚱한
  것부터 고친다. 대신 "하나를 고쳐도 나머지는 남을 수 있다"를 적는다.

  state가 parsed가 아니거나 원인이 없으면 아무것도 그리지 않는다. 실패 사실은
  위 AttentionSection이 이미 말하고 있다.
*/

export interface ResourceCauseSectionProps {
  diagnosis: ResourceBundleDiagnosis | null | undefined
}

interface CauseGroup {
  kind: string
  title: string
  causes: ResourceBundleCause[]
}

export function ResourceCauseSection({ diagnosis }: ResourceCauseSectionProps) {
  if (!diagnosis || diagnosis.state !== 'parsed' || diagnosis.causes.length === 0) {
    return null
  }

  const groups = groupByKind(diagnosis.causes)
  const checks = collectChecks(diagnosis.causes)
  const cautions = uniqueStatements(
    groups.flatMap((group) => causeKindKnowledge(group.kind)?.cautions ?? []),
  )
  const remedies = uniqueStatements(
    groups.flatMap((group) => causeKindKnowledge(group.kind)?.remedies ?? []),
  )

  return (
    <section className="flex flex-col gap-4" aria-labelledby="resource-cause-heading">
      <SectionHeader
        eyebrow="DIAGNOSIS"
        title={<span id="resource-cause-heading">참조 데이터 검사에서 기록된 원인</span>}
        meta={`원인 ${diagnosis.causes.length}건 · 고정 규칙표로 분류 · AI 생성 아님`}
      />

      <div className="grid grid-cols-1 rounded-md border border-border bg-surface lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* --- 왼쪽: 기록된 원인 ------------------------------------------- */}
        <div className="flex min-w-0 flex-col gap-4 p-4">
          <h3 className="text-small font-medium text-text-strong">
            무엇이 문제였나
          </h3>
          <ul className="flex flex-col gap-4">
            {groups.map((group) => (
              <li key={group.kind} className="flex flex-col gap-2">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-body font-medium text-text-strong">
                    {group.title}
                  </span>
                  <span className="text-caption text-text-muted">
                    {group.causes.length}건
                  </span>
                </div>
                <ul className="flex flex-col gap-2 border-t border-border-subtle pt-2">
                  {group.causes.map((cause, index) => (
                    <CauseRow key={`${group.kind}-${index}`} cause={cause} />
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          <Notes diagnosis={diagnosis} />
        </div>

        {/* --- 오른쪽: 다음에 확인할 것 ------------------------------------ */}
        <div className="flex min-w-0 flex-col gap-4 border-t border-border p-4 lg:border-t-0 lg:border-l">
          <h3 className="text-small font-medium text-text-strong">
            다음에 확인할 것
          </h3>
          {checks.length > 0 ? (
            <ol className="flex flex-col gap-3">
              {checks.map((check, index) => (
                <li key={check.statement} className="flex gap-3">
                  <span className="w-5 flex-none text-right font-mono text-data text-text-muted">
                    {index + 1}
                  </span>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    {check.subject ? (
                      <span className="text-caption text-text-muted">
                        {check.subject}
                      </span>
                    ) : null}
                    <span className="text-small text-text">{check.statement}</span>
                    <SourceLine ids={check.sourceIds} />
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-small text-text-muted">
              이 원인 종류에는 등록된 점검 안내가 없습니다. 왼쪽의 원문을 기준으로
              확인하세요.
            </p>
          )}

          {remedies.length > 0 ? (
            <div className="flex flex-col gap-2 border-t border-border-subtle pt-3">
              <h4 className="text-small font-medium text-text-strong">
                해결 방향 <span className="font-normal text-text-muted">승인이 필요한 변경</span>
              </h4>
              <ul className="flex flex-col gap-3">
                {remedies.map((remedy) => (
                  <li key={remedy.statement} className="flex flex-col gap-0.5">
                    <span className="text-small text-text">{remedy.statement}</span>
                    <span className="text-caption text-text-muted">
                      바뀌는 것: {remedy.changes} · 승인: {remedy.approval}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {cautions.length > 0 ? (
            <div className="flex flex-col gap-2 border-t border-border-subtle pt-3">
              <h4 className="text-small font-medium text-text-strong">하지 말 것</h4>
              <ul className="flex flex-col gap-2">
                {cautions.map((caution) => (
                  <li key={caution.statement} className="text-small text-text">
                    {caution.statement}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className="border-t border-border-subtle pt-3 text-caption text-text-muted">
            이 화면은 확인할 곳을 안내할 뿐 파일을 고치거나 다시 실행하지 않습니다.
          </p>
        </div>
      </div>
    </section>
  )
}

function CauseRow({ cause }: { cause: ResourceBundleCause }) {
  const role = causeRoleKnowledge(cause.resourceRole)
  return (
    <li className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="text-small text-text">
          {role
            ? role.title
            : cause.resourceRole === 'unknown'
              ? '대상 리소스가 문장에 표시되지 않음'
              : cause.resourceRole}
        </span>
        {cause.tool ? (
          <span className="text-caption text-text-muted">
            도구 <code className="font-mono">{cause.tool}</code>
          </span>
        ) : null}
        {cause.ruleId ? (
          <code className="font-mono text-caption text-text-muted">{cause.ruleId}</code>
        ) : null}
      </div>
      {cause.evidenceText ? (
        <code className="block rounded-sm bg-sunken px-2 py-1 font-mono text-caption break-words whitespace-pre-wrap text-text">
          {cause.evidenceText}
        </code>
      ) : (
        <span className="text-caption text-text-muted">
          원문은 공개 규칙에 따라 표시하지 않습니다. 분류는 그대로 유효합니다.
        </span>
      )}
    </li>
  )
}

function Notes({ diagnosis }: { diagnosis: ResourceBundleDiagnosis }) {
  const notes: string[] = []
  if (diagnosis.causes.length > 1) {
    notes.push(
      '기록에는 원인 사이의 선후 관계가 없습니다. 하나를 해결해도 나머지 원인은 남을 수 있습니다.',
    )
  }
  if (diagnosis.truncated) {
    notes.push('기록이 길어 목록이 잘렸을 수 있습니다. 여기에 없는 원인이 더 있을 수 있습니다.')
  }
  if (diagnosis.withheldTextCount > 0) {
    notes.push(`원문 ${diagnosis.withheldTextCount}건은 경로·식별자 노출을 막기 위해 숨겼습니다.`)
  }
  notes.push(
    diagnosis.source === 'report'
      ? '출처: 입력 검증 단계의 검사 보고서'
      : diagnosis.source === 'pipeline_log'
        ? '출처: 파이프라인 로그 (검사 보고서를 읽을 수 없어 대신 사용)'
        : '출처: 기록 없음',
  )
  return (
    <ul className="flex flex-col gap-1 border-t border-border-subtle pt-3">
      {notes.map((note) => (
        <li key={note} className="text-caption text-text-muted">
          {note}
        </li>
      ))}
    </ul>
  )
}

function SourceLine({ ids }: { ids: string[] }) {
  const titles = ids.map((id) => sourceKnowledge(id)?.title ?? id)
  if (titles.length === 0) return null
  return <span className="text-caption text-text-muted">근거: {titles.join(' · ')}</span>
}

/** 같은 종류를 묶는다. 순서는 backend가 준 첫 등장 순서를 따른다. */
function groupByKind(causes: ResourceBundleCause[]): CauseGroup[] {
  const groups = new Map<string, CauseGroup>()
  for (const cause of causes) {
    let group = groups.get(cause.kind)
    if (!group) {
      const knowledge = causeKindKnowledge(cause.kind)
      group = {
        kind: cause.kind,
        // 미등록 종류는 지어내지 않고 원래 어휘를 보여준다.
        title: knowledge?.title ?? (cause.kind === 'unknown' ? '규칙표에 없는 원인' : cause.kind),
        causes: [],
      }
      groups.set(cause.kind, group)
    }
    group.causes.push(cause)
  }
  return [...groups.values()]
}

interface CheckItem extends CauseStatement {
  /** 대상 리소스별 점검이면 그 리소스 이름. 종류 전체의 점검이면 null. */
  subject: string | null
}

/**
 * 점검 순서: 원인 종류의 점검(무엇을 봐야 하나) → 대상 리소스의 점검(그
 * 리소스가 무엇인가). 같은 문장은 한 번만 — 같은 종류가 여러 VCF에 한 줄씩
 * 기록되기 때문이다.
 */
function collectChecks(causes: ResourceBundleCause[]): CheckItem[] {
  const items: CheckItem[] = []
  const seen = new Set<string>()
  const push = (statement: CauseStatement, subject: string | null) => {
    if (seen.has(statement.statement)) return
    seen.add(statement.statement)
    items.push({ ...statement, subject })
  }
  for (const kind of new Set(causes.map((cause) => cause.kind))) {
    for (const check of causeKindKnowledge(kind)?.checks ?? []) push(check, null)
  }
  for (const roleId of new Set(causes.map((cause) => cause.resourceRole))) {
    const role = causeRoleKnowledge(roleId)
    for (const check of role?.checks ?? []) push(check, role?.title ?? null)
  }
  return items
}

function uniqueStatements<T extends CauseStatement>(rows: T[]): T[] {
  const seen = new Set<string>()
  return rows.filter((row) => {
    if (seen.has(row.statement)) return false
    seen.add(row.statement)
    return true
  })
}
