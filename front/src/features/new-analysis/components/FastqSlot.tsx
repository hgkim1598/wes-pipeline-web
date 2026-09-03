import { RefreshCw, Upload, X } from 'lucide-react'
import { useId, useRef } from 'react'

import { Button } from '@/components/ui/Button'
import { ALLOWED_FASTQ_SUFFIXES } from '@/features/new-analysis/fastq'
import type { FastqUploadController } from '@/features/new-analysis/useFastqUpload'
import { formatBytes } from '@/lib/formatBytes'
import { cx } from '@/lib/cx'

/*
  R1 / R2 슬롯 한 칸.

  시안 근거 (docs/design/wizard.html · STEP 2 입력 파일)
    슬롯 코드(mono, 32px) · 파일명 · 크기 · 제거
    아래 진행 바 6px + 퍼센트(mono) + 상태 문구

  시안의 dropzone은 만들지 않았다. 파일 2개를 한 번에 받아 R1/R2로 나누려면
  파일 이름에서 슬롯을 추측해야 하는데, 추측이 틀리면 R1과 R2가 뒤바뀐 채로
  분석이 끝까지 돌아간다. 슬롯마다 사용자가 직접 고르는 편이 안전하다.

  진행 바는 옆의 퍼센트를 그림으로 옮긴 것이라 aria-hidden이고,
  상태 문구만 live region으로 알린다. 퍼센트까지 읽어 주면 전송 내내
  스크린 리더가 숫자를 계속 낭독한다.
*/

const SLOT_LABEL: Record<string, string> = {
  r1: 'R1',
  r2: 'R2',
}

const FILL_CLASS: Record<string, string> = {
  uploading: 'bg-fill-running',
  completed: 'bg-fill-success',
  failed: 'bg-fill-failure',
  empty: 'bg-fill-idle',
}

export interface FastqSlotProps {
  upload: FastqUploadController
  /** 업로드를 시작할 때 서버에 함께 기록되는 값. */
  sampleId: string | null
  description: string
}

export function FastqSlot({ upload, sampleId, description }: FastqSlotProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const statusId = useId()
  const label = SLOT_LABEL[upload.slotId] ?? upload.slotId.toUpperCase()

  return (
    <div className="flex gap-3 border-b border-border-subtle p-4 last:border-b-0">
      <span className="w-8 flex-none pt-0.5 font-mono text-data text-text-muted">
        {label}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {upload.file ? (
            <>
              <span className="min-w-0 flex-1 truncate text-body text-text-strong">
                {upload.file.name}
              </span>
              <span className="flex-none font-mono text-data text-text-muted">
                {formatBytes(upload.file.size)}
              </span>
            </>
          ) : (
            <span className="min-w-0 flex-1 text-body text-text-muted">
              {description}
            </span>
          )}

          {/*
            input은 화면에 두지 않고 버튼이 대신 연다. 파일 입력의 기본
            렌더링은 브라우저마다 다르고 이 디자인 언어와 맞지 않는다.
            키보드 조작은 버튼이 담당하므로 input은 탐색 대상에서 뺀다.
          */}
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            tabIndex={-1}
            accept={ALLOWED_FASTQ_SUFFIXES.join(',')}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) upload.select(file, sampleId)
              // 같은 파일을 다시 고를 수 있도록 값을 비운다.
              event.target.value = ''
            }}
          />

          <span className="flex flex-none items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => inputRef.current?.click()}
              aria-label={`${label} FASTQ 파일 ${upload.file ? '변경' : '선택'}`}
            >
              <Upload size={16} strokeWidth={1.5} aria-hidden="true" />
              {upload.file ? '변경' : '파일 선택'}
            </Button>
            {upload.file ? (
              <Button
                variant="secondary"
                onClick={upload.clear}
                aria-label={`${label} 파일 제거`}
              >
                <X size={16} strokeWidth={1.5} aria-hidden="true" />
              </Button>
            ) : null}
          </span>
        </div>

        {upload.file && upload.status !== 'failed' ? (
          <div className="flex items-center gap-3">
            <span
              aria-hidden="true"
              className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-sm bg-fill-idle"
            >
              <span
                className={cx('block h-full', FILL_CLASS[upload.status])}
                style={{ width: `${upload.percent}%` }}
              />
            </span>
            <span className="flex-none font-mono text-data text-text-strong">
              {upload.percent}%
            </span>
          </div>
        ) : null}

        <p
          id={statusId}
          role="status"
          className={cx(
            'text-caption',
            upload.status === 'failed'
              ? 'text-status-failure-fg'
              : 'text-text-muted',
          )}
        >
          {upload.status === 'uploading' ? (
            <>
              전송 중 · {formatBytes(upload.sentBytes)} /{' '}
              {formatBytes(upload.totalBytes)}
            </>
          ) : null}
          {upload.status === 'completed' ? '업로드 완료' : null}
          {upload.status === 'empty' ? (
            <>{ALLOWED_FASTQ_SUFFIXES.join(' · ')}</>
          ) : null}
          {upload.status === 'failed' && upload.error
            ? `${upload.error.summary} ${upload.error.hint}`
            : null}
        </p>

        {upload.status === 'failed' && upload.error ? (
          <div className="flex flex-col items-start gap-2">
            {upload.error.detail ? (
              <code className="break-all text-caption text-text-muted">
                {upload.error.detail}
              </code>
            ) : null}
            {upload.error.retryable ? (
              <Button variant="secondary" onClick={() => upload.retry(sampleId)}>
                <RefreshCw size={16} strokeWidth={1.5} aria-hidden="true" />
                다시 시도
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
