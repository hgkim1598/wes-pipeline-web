import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { StatusBadge } from '@/components/ui/StatusBadge'
import type { StepDetail } from '@/features/run-detail/api'
import { describeStepStatus } from '@/features/run-detail/stepStatus'
import { formatDuration, formatTimestamp } from '@/features/runs/time'
import { describeStep } from '@/registries/steps'
import { formatBytes } from '@/lib/formatBytes'

/*
  선택한 단계의 상세.

  시안 근거 (docs/design/pipeline-tab.html · 우측 레일)
    제목 h2 + mono "03_alignment · BWA-MEM" + 배지 + 소요시간
    지표     라벨(small ink-500) / 값(mono ink-900 우측) 행, 하단 1px
    검증     [PASS] mono + 이름
    접기     입력/출력 · 산출물 · 경고·실패 (건수와 함께)

  metrics를 한국어로 바꾸지 않는다. 첫 full 실행 결과를 아직 본 적이 없어서
  어떤 키가 오는지 모르고, 지어낸 라벨·단위는 잘못된 정보다. 키를 그대로 mono로
  두고 실제 값을 본 뒤 registry를 만드는 것이 순서다.

  data는 부모가 아니라 이 component가 자기 query로 가져온다 — 열릴 때만 요청하고
  (enabled), 실행 중인 단계만 폴링한다.
*/

export interface StepDetailRailProps {
  stepId: string
  detail: StepDetail | undefined
  isPending: boolean
  error: unknown
}

export function StepDetailRail({
  stepId,
  detail,
  isPending,
  error,
}: StepDetailRailProps) {
  const definition = describeStep(stepId)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2 border-b border-border pb-4">
        <h2 className="text-h2 font-semibold text-text-strong">
          {definition.label}
        </h2>
        <p className="font-mono text-data text-text-muted">
          {stepId}
          {definition.tool ? ` · ${definition.tool}` : ''}
        </p>
        {detail ? (
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={describeStepStatus(detail.status).tone} size="sm">
              {describeStepStatus(detail.status).label}
            </StatusBadge>
            {detail.elapsedSeconds > 0 ? (
              <span className="font-mono text-data text-text">
                {formatDuration(detail.elapsedSeconds)}
              </span>
            ) : null}
            {detail.exitCode !== null ? (
              <span className="font-mono text-caption text-text-muted">
                exit {detail.exitCode}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {isPending ? (
        <p role="status" className="text-body text-text-muted">
          단계 정보를 불러오는 중입니다.
        </p>
      ) : null}

      {error ? <StepDetailError error={error} /> : null}

      {detail ? (
        <>
          {detail.failures.length > 0 ? (
            <MessageBlock
              tone="danger"
              title={`이 단계에서 ${detail.failures.length}건 실패`}
            >
              <ul className="flex flex-col gap-2">
                {detail.failures.map((failure, index) => (
                  <li key={`${failure.code}-${index}`} className="flex flex-col gap-1">
                    {failure.code ? (
                      <code className="text-caption">{failure.code}</code>
                    ) : null}
                    <span>{failure.message}</span>
                  </li>
                ))}
              </ul>
            </MessageBlock>
          ) : null}

          {detail.warnings.length > 0 ? (
            <MessageBlock
              tone="warning"
              title={`경고 ${detail.warnings.length}건`}
            >
              <ul className="flex flex-col gap-2">
                {detail.warnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`} className="flex flex-col gap-1">
                    {warning.code ? (
                      <code className="text-caption">{warning.code}</code>
                    ) : null}
                    <span>{warning.message}</span>
                    {warning.impact ? (
                      <span className="text-caption text-text-muted">
                        {warning.impact}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </MessageBlock>
          ) : null}

          <RailSection title="시간">
            <KeyValue label="시작" value={formatIso(detail.startedAt)} />
            <KeyValue label="종료" value={formatIso(detail.finishedAt)} />
            <KeyValue
              label="다음 단계 준비"
              value={detail.nextStepReady ? '예' : '아니오'}
            />
          </RailSection>

          <RailSection
            title="지표"
            meta={Object.keys(detail.metrics).length === 0 ? '없음' : undefined}
          >
            {Object.entries(detail.metrics).map(([key, value]) => (
              <KeyValue key={key} label={key} value={formatMetric(value)} mono />
            ))}
          </RailSection>

          <RailSection
            title="검증"
            meta={
              detail.validation.results.length > 0
                ? `${detail.validation.results.length}건`
                : '없음'
            }
          >
            {detail.validation.results.map((check) => (
              <div
                key={check.name}
                className="flex min-h-9 flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border-subtle py-1 last:border-b-0"
              >
                <code
                  className={
                    check.status.toUpperCase() === 'PASS'
                      ? 'flex-none text-caption text-status-success-fg'
                      : check.status.toUpperCase() === 'WARN'
                        ? 'flex-none text-caption text-status-warning-fg'
                        : 'flex-none text-caption text-status-failure-fg'
                  }
                >
                  [{check.status.toUpperCase()}]
                </code>
                <code className="min-w-0 flex-1 break-all text-caption text-text">
                  {check.name}
                </code>
                {check.detail ? (
                  <span className="basis-full text-caption text-text-muted">
                    {check.detail}
                  </span>
                ) : null}
              </div>
            ))}
          </RailSection>

          <RailFoldout
            title="입력 / 출력"
            count={detail.inputs.length + detail.outputs.length}
          >
            {[
              ...detail.inputs.map((io) => ({ ...io, direction: '입력' })),
              ...detail.outputs.map((io) => ({ ...io, direction: '출력' })),
            ].map((io, index) => (
              <div
                key={`${io.direction}-${io.path}-${index}`}
                className="flex flex-col gap-0.5 border-b border-border-subtle py-1 last:border-b-0"
              >
                <span className="text-caption text-text-muted">
                  {io.direction}
                  {io.type ? ` · ${io.type}` : ''}
                </span>
                <code className="break-all text-caption text-text">{io.path}</code>
              </div>
            ))}
          </RailFoldout>

          <RailFoldout title="산출물" count={detail.artifacts.length}>
            {detail.artifacts.map((artifact) => (
              <div
                key={artifact.fileId}
                className="flex flex-col gap-0.5 border-b border-border-subtle py-1 last:border-b-0"
              >
                <code className="break-all text-caption text-text-strong">
                  {artifact.displayName || artifact.relativePath}
                </code>
                <span className="text-caption text-text-muted">
                  {artifact.kind}
                  {artifact.sizeBytes !== null
                    ? ` · ${formatBytes(artifact.sizeBytes)}`
                    : ''}
                  {artifact.available ? '' : ' · 파일 없음'}
                </span>
              </div>
            ))}
          </RailFoldout>
        </>
      ) : null}
    </div>
  )
}

function RailSection({
  title,
  meta,
  children,
}: {
  title: string
  meta?: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline gap-3">
        <h3 className="text-h3 font-semibold text-text-strong">{title}</h3>
        {meta ? <span className="text-small text-text-muted">{meta}</span> : null}
      </div>
      <div className="flex flex-col">{children}</div>
    </section>
  )
}

/** 접기. 건수가 0이면 열 것이 없으므로 제목만 흐리게 둔다. */
function RailFoldout({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: ReactNode
}) {
  if (count === 0) {
    return (
      <div className="flex items-center justify-between gap-3 border-t border-border-subtle py-3">
        <span className="text-body font-medium text-text-muted">{title}</span>
        <span className="text-small text-text-muted">0건</span>
      </div>
    )
  }

  return (
    <details className="border-t border-border-subtle">
      <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 py-3">
        <span className="text-body font-medium text-text-strong">{title}</span>
        <span className="text-small text-text-muted">{count}건</span>
      </summary>
      <div className="flex flex-col pb-3">{children}</div>
    </details>
  )
}

function KeyValue({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex min-h-9 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border-subtle py-1 last:border-b-0">
      <span
        className={
          mono
            ? 'min-w-0 flex-1 truncate font-mono text-caption text-text-muted'
            : 'flex-none text-small text-text-muted'
        }
      >
        {label}
      </span>
      <span className="min-w-0 text-right font-mono text-data text-text-strong">
        {value}
      </span>
    </div>
  )
}

function formatIso(value: string | null): string {
  const formatted = formatTimestamp(value)
  return formatted ? formatted.full : '—'
}

/** metric 값은 해석하지 않는다. 객체·배열이면 JSON 그대로 보여준다. */
function formatMetric(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/*
  단계 상세를 읽지 못한 경우.

  step endpoint는 실패한 단계에도 200을 준다(api/steps.py). 따라서 여기 오는
  오류는 단계의 실패가 아니라 통신·계약 문제다. 둘을 섞어 보여주면 사용자가
  "분석이 실패했다"로 오독한다.
*/
function StepDetailError({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return (
        <MessageBlock tone="info" title="이 단계의 기록이 없습니다">
          이 실행의 계획에 없는 단계이거나, 아직 기록이 만들어지지 않았습니다.
        </MessageBlock>
      )
    }
    return (
      <MessageBlock tone="danger" title="단계 정보를 불러오지 못했습니다">
        <div className="flex flex-col gap-2">
          <p>
            {error.kind === 'network'
              ? '서버에 연결하지 못했습니다.'
              : error.kind === 'malformed'
                ? '응답 형식이 frontend가 아는 계약과 다릅니다.'
                : `서버가 HTTP ${error.status}로 응답했습니다.`}
          </p>
          {error.detail ? (
            <code className="break-all text-caption text-text-muted">
              {error.detail}
            </code>
          ) : null}
        </div>
      </MessageBlock>
    )
  }
  return (
    <MessageBlock tone="danger" title="단계 정보를 불러오지 못했습니다">
      알 수 없는 오류입니다.
    </MessageBlock>
  )
}
