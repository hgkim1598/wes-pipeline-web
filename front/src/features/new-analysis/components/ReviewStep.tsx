import { Play } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/Button'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import type { CaptureKit } from '@/features/new-analysis/catalog'
import { describeRunMode } from '@/features/new-analysis/runMode'
import type { FastqUploadController } from '@/features/new-analysis/useFastqUpload'
import { formatBytes } from '@/lib/formatBytes'

/*
  4단계 — 확인 및 실행.

  시안(wizard.html STEP 4)의 라벨/값 목록과 같은 골격이다. 값마다 어느
  단계에서 고칠 수 있는지 버튼을 붙였다.

  제출을 막는 조건은 숨기지 않고 그대로 적는다. 버튼만 흐리게 두면 사용자는
  무엇이 부족한지 알 수 없다.
*/

export interface ReviewStepProps {
  profileLabel: string
  profileId: string
  sampleId: string
  captureKit: CaptureKit | undefined
  r1: FastqUploadController
  r2: FastqUploadController
  serverRunMode: string | undefined
  /** 제출을 막는 이유들. 비어 있으면 제출할 수 있다. */
  blockers: string[]
  isSubmitting: boolean
  submitError: unknown
  onSubmit: () => void
  onEdit: (step: number) => void
}

export function ReviewStep({
  profileLabel,
  profileId,
  sampleId,
  captureKit,
  r1,
  r2,
  serverRunMode,
  blockers,
  isSubmitting,
  submitError,
  onSubmit,
  onEdit,
}: ReviewStepProps) {
  const runMode = describeRunMode(serverRunMode)

  return (
    <div className="flex flex-col gap-8">
      {runMode ? (
        <MessageBlock tone={runMode.tone} title={runMode.title}>
          {runMode.description}
        </MessageBlock>
      ) : null}

      <section className="flex flex-col gap-4">
        <SectionHeader title="제출 내용" />
        <dl className="flex flex-col">
          <ReviewRow label="분석" onEdit={() => onEdit(1)}>
            <span className="text-body text-text-strong">{profileLabel}</span>
            <span className="font-mono text-caption text-text-muted">
              {profileId}
            </span>
          </ReviewRow>

          <ReviewRow label="샘플 이름" onEdit={() => onEdit(2)}>
            {sampleId ? (
              <code className="text-text-strong">{sampleId}</code>
            ) : (
              <span className="text-body text-status-failure-fg">
                입력되지 않았습니다
              </span>
            )}
          </ReviewRow>

          <ReviewRow label="Capture kit" onEdit={() => onEdit(3)}>
            {captureKit ? (
              <>
                <span className="text-body text-text-strong">
                  {captureKit.label}
                </span>
                <span className="font-mono text-caption text-text-muted">
                  {captureKit.id}
                </span>
              </>
            ) : (
              <span className="text-body text-status-failure-fg">
                선택되지 않았습니다
              </span>
            )}
          </ReviewRow>

          <ReviewRow label="입력 파일" onEdit={() => onEdit(2)}>
            <FileLine slot="R1" upload={r1} />
            <FileLine slot="R2" upload={r2} />
          </ReviewRow>

          <ReviewRow label="실행 모드">
            <span className="text-body text-text-strong">
              {runMode ? runMode.label : '확인하지 못했습니다'}
            </span>
            <span className="text-caption text-text-muted">
              서버 설정을 따릅니다. 제출할 때 선택하는 값이 아닙니다.
            </span>
          </ReviewRow>
        </dl>
      </section>

      {blockers.length > 0 ? (
        <MessageBlock tone="info" title="아직 분석을 시작할 수 없습니다">
          <ul className="flex list-disc flex-col gap-1 pl-4">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </MessageBlock>
      ) : null}

      {submitError ? <SubmitError error={submitError} /> : null}

      <div className="flex flex-col gap-2 border-t border-border pt-6">
        <Button
          variant="primary"
          onClick={onSubmit}
          disabled={blockers.length > 0 || isSubmitting}
        >
          <Play size={16} strokeWidth={1.5} aria-hidden="true" />
          {isSubmitting ? '제출하는 중' : '분석 시작'}
        </Button>
        <p className="text-caption text-text-muted">
          제출하면 서버의 실행 대기열에 들어갑니다. 제출 후에는 설정을 바꿀 수
          없습니다.
        </p>
      </div>
    </div>
  )
}

function ReviewRow({
  label,
  children,
  onEdit,
}: {
  label: string
  children: ReactNode
  onEdit?: () => void
}) {
  return (
    <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border-subtle py-3 last:border-b-0">
      <dt className="flex-none text-small text-text-muted md:w-45">{label}</dt>
      <dd className="flex min-w-0 flex-1 basis-full flex-col gap-1 md:basis-0">
        {children}
      </dd>
      {onEdit ? (
        <button
          type="button"
          onClick={onEdit}
          className="min-h-6 flex-none text-small font-medium text-brand"
        >
          수정<span className="sr-only"> — {label}</span>
        </button>
      ) : null}
    </div>
  )
}

function FileLine({
  slot,
  upload,
}: {
  slot: string
  upload: FastqUploadController
}) {
  return (
    <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="flex-none font-mono text-data text-text-muted">
        {slot}
      </span>
      {upload.file ? (
        <>
          <span className="min-w-0 flex-1 truncate font-mono text-data text-text-strong">
            {upload.file.name}
          </span>
          <span className="flex-none font-mono text-data text-text-muted">
            {formatBytes(upload.file.size)}
          </span>
          <span
            className={
              upload.status === 'completed'
                ? 'flex-none text-caption text-status-success-fg'
                : 'flex-none text-caption text-text-muted'
            }
          >
            {upload.status === 'completed'
              ? '업로드 완료'
              : upload.status === 'uploading'
                ? `전송 중 ${upload.percent}%`
                : upload.status === 'failed'
                  ? '업로드 실패'
                  : ''}
          </span>
        </>
      ) : (
        <span className="text-body text-status-failure-fg">
          선택되지 않았습니다
        </span>
      )}
    </span>
  )
}

/*
  제출 실패.

  backend는 400에 읽을 만한 이유를 담아 준다(capture kit 상태, 업로드 토큰
  문제, sample id 규칙 등). 그 문장을 감추면 사용자는 무엇을 고쳐야 하는지
  알 수 없다. 그대로 보여주되 traceback처럼 보이지 않게 문장과 상세를
  분리한다.
*/
function SubmitError({ error }: { error: unknown }) {
  let summary = '분석을 제출하지 못했습니다.'
  let hint = '잠시 후 다시 시도해 주세요.'
  let detail: string | null = null

  if (error instanceof ApiError) {
    detail = error.detail
    if (error.kind === 'network') {
      hint =
        '요청이 서버에 도달하지 못했습니다. 업로드한 파일은 서버에 남아 있으므로, 연결을 확인한 뒤 다시 시작하면 됩니다.'
    } else if (error.kind === 'http') {
      summary = `서버가 제출을 받지 않았습니다 (HTTP ${error.status}).`
      hint =
        error.status === 400
          ? '아래 사유를 확인하고 해당 항목을 고친 뒤 다시 제출해 주세요.'
          : '서버에서 처리하지 못했습니다. 서버 로그를 확인해 주세요.'
    } else {
      summary = '제출은 되었지만 응답을 읽지 못했습니다.'
      hint =
        '분석이 만들어졌을 수 있습니다. 실행 목록에서 확인한 뒤 다시 제출해 주세요.'
    }
  } else if (error instanceof Error) {
    detail = error.message
  }

  return (
    <MessageBlock tone="danger" role="alert" title={summary}>
      <div className="flex flex-col gap-2">
        <p>{hint}</p>
        {detail ? (
          <code className="break-all text-text-muted">{detail}</code>
        ) : null}
      </div>
    </MessageBlock>
  )
}
