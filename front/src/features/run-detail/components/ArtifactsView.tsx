import { Download, FolderOpen } from 'lucide-react'

import { EmptyState } from '@/components/ui/EmptyState'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import type { ArtifactList, NotReady } from '@/features/run-detail/api'
import { artifactDownloadUrl, isNotReady } from '@/features/run-detail/api'
import { describeStep } from '@/registries/steps'
import { formatBytes } from '@/lib/formatBytes'

/*
  산출물.

  시안 근거 (docs/design/remaining-screens.html · FILES TAB)
    단계별 그룹 머리글(STEP 06 + 이름 + 개수·용량) + 파일 행
    파일 행: 이름 mono / 종류·크기 / 다운로드

  표시하지 않는 것: manifestConsistent. full 실행에서 구조적으로 false가 되므로
  (backend/app/schemas.py, CLAUDE.md 15장) 사용자에게 경고로 보이면 안 된다.
  반대로 suppressedCount는 실제 누락이므로 0보다 크면 알린다.

  다운로드는 평범한 링크다. 수 GB BAM을 fetch로 받아 Blob으로 만들 수 없고,
  브라우저가 이미 잘하는 일이다.
*/

export interface ArtifactsViewProps {
  data: ArtifactList | NotReady | undefined
  isPending: boolean
  error: unknown
  jobId: string
  /** 아직 실행 중인지. 개수가 더 늘어날 수 있다는 안내에 쓴다. */
  running: boolean
}

export function ArtifactsView({
  data,
  isPending,
  error,
  jobId,
  running,
}: ArtifactsViewProps) {
  if (isPending) {
    return (
      <p role="status" className="text-body text-text-muted">
        산출물 목록을 불러오는 중입니다.
      </p>
    )
  }

  if (error) {
    return (
      <MessageBlock tone="danger" title="산출물 목록을 불러오지 못했습니다">
        서버가 목록을 주지 못했습니다. 파일이 없다는 뜻은 아닙니다.
      </MessageBlock>
    )
  }

  if (!data) return null

  if (isNotReady(data)) {
    return (
      <MessageBlock tone="info" role="status" title="산출물이 아직 없습니다">
        <div className="flex flex-col gap-2">
          <p>
            이 실행은 아직 산출물을 등록하지 않았습니다. 단계가 끝날 때마다
            추가됩니다. 0개로 확정된 것이 아닙니다.
          </p>
          {data.reason ? (
            <code className="break-all text-text-muted">{data.reason}</code>
          ) : null}
        </div>
      </MessageBlock>
    )
  }

  if (data.artifacts.length === 0) {
    return (
      <EmptyState
        icon={<FolderOpen size={32} strokeWidth={1.5} aria-hidden="true" />}
        title="등록된 산출물이 없습니다"
        titleLevel={3}
        description={
          running
            ? '실행이 진행 중입니다. 단계가 끝나면 산출물이 등록됩니다.'
            : '이 실행은 산출물을 만들지 않았습니다. 사전 점검 모드에서는 정상입니다.'
        }
      />
    )
  }

  // 단계별 그룹. 순서는 backend가 준 순서를 유지한다 — artifact_reader가 이미
  // 단계 순으로 정렬해 주고, 화면이 다시 정렬하면 두 순서가 어긋난다.
  const groups: { stepId: string; entries: typeof data.artifacts }[] = []
  for (const entry of data.artifacts) {
    const last = groups[groups.length - 1]
    if (last && last.stepId === entry.stepId) {
      last.entries.push(entry)
    } else {
      groups.push({ stepId: entry.stepId, entries: [entry] })
    }
  }

  const totalBytes = data.artifacts.reduce(
    (sum, entry) => sum + (entry.sizeBytes ?? 0),
    0,
  )

  return (
    <div className="flex flex-col gap-8">
      <SectionHeader
        title="산출물"
        meta={
          <>
            <span className="font-mono text-data">{data.artifactCount}</span>개
            {totalBytes > 0 ? ` · ${formatBytes(totalBytes)}` : ''}
          </>
        }
      />

      {data.suppressedCount > 0 ? (
        <MessageBlock
          tone="warning"
          title={`목록에서 제외된 항목이 ${data.suppressedCount}건 있습니다`}
        >
          형식이 잘못되었거나 run 디렉터리 밖을 가리켜 제외되었습니다. 파이프라인
          산출물 등록을 확인해야 합니다.
        </MessageBlock>
      ) : null}

      {running ? (
        <p className="text-caption text-text-muted">
          실행이 진행 중입니다. 단계가 끝날 때마다 목록이 늘어납니다.
        </p>
      ) : null}

      {groups.map((group) => (
        <section key={group.stepId} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <span className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
              {group.stepId || 'UNASSIGNED'}
            </span>
            <h3 className="text-h3 font-semibold text-text-strong">
              {describeStep(group.stepId).label}
            </h3>
            <span className="text-caption text-text-muted">
              {group.entries.length}개
            </span>
          </div>

          <ul className="overflow-hidden rounded-md border border-border bg-surface">
            {group.entries.map((entry) => (
              <li
                key={entry.fileId}
                className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border-subtle p-3 last:border-b-0"
              >
                <div className="flex min-w-0 flex-1 basis-full flex-col gap-1 md:basis-0">
                  <code className="min-w-0 break-all text-data text-text-strong">
                    {entry.displayName || entry.relativePath}
                  </code>
                  <span className="text-caption text-text-muted">
                    {[
                      entry.kind,
                      entry.sizeBytes !== null ? formatBytes(entry.sizeBytes) : null,
                      entry.description || null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {entry.relativePath !== entry.displayName ? (
                    <code className="min-w-0 break-all text-caption text-text-muted">
                      {entry.relativePath}
                    </code>
                  ) : null}
                </div>

                {entry.sha256 ? (
                  <code className="flex-none text-caption text-text-muted">
                    {entry.sha256.slice(0, 4)}…{entry.sha256.slice(-4)}
                  </code>
                ) : null}

                {!entry.available ? (
                  <span className="flex-none text-caption text-status-warning-fg">
                    파일 없음
                  </span>
                ) : entry.downloadable ? (
                  <a
                    href={artifactDownloadUrl(jobId, entry.fileId)}
                    className="inline-flex h-8 flex-none items-center gap-2 rounded-sm border border-border-strong bg-surface px-4 text-body font-medium whitespace-nowrap text-text-strong no-underline hover:bg-sunken hover:no-underline"
                  >
                    <Download size={16} strokeWidth={1.5} aria-hidden="true" />
                    내려받기
                    <span className="sr-only">
                      {entry.displayName || entry.relativePath}
                    </span>
                  </a>
                ) : (
                  <span className="flex-none text-caption text-text-muted">
                    내려받을 수 없음
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
