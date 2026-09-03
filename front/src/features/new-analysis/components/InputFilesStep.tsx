import { useId } from 'react'

import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { FastqSlot } from '@/features/new-analysis/components/FastqSlot'
import { validateSampleId } from '@/features/new-analysis/fastq'
import type { FastqUploadController } from '@/features/new-analysis/useFastqUpload'

/*
  2단계 — 입력 파일.

  시안(wizard.html STEP 2)과 같은 구성이다. 샘플 이름 · R1/R2 슬롯 두 칸.
  샘플 이름이 파일보다 위에 있는 것은 순서가 아니라 의미 때문이다.
  업로드를 시작할 때 서버에 함께 기록되는 값이라 먼저 정해지는 편이 낫다.

  파일을 고르면 곧바로 전송이 시작된다. "업로드" 버튼을 따로 두지 않는 이유는,
  수 GB 파일에서 그 버튼이 하는 일이 "지금부터 몇 분 기다리세요"뿐이라서다.
  단계를 옮겨 다녀도 전송은 계속된다.
*/

export interface InputFilesStepProps {
  sampleId: string
  onSampleIdChange: (value: string) => void
  r1: FastqUploadController
  r2: FastqUploadController
}

export function InputFilesStep({
  sampleId,
  onSampleIdChange,
  r1,
  r2,
}: InputFilesStepProps) {
  const inputId = useId()
  const hintId = useId()
  const errorId = useId()

  // 입력하는 동안 빨간 글씨를 띄우지 않는다. 비어 있는 것은 아직 안 쓴 것이다.
  const sampleIdProblem = sampleId ? validateSampleId(sampleId) : null
  const sameFile =
    r1.file && r2.file && r1.file.name === r2.file.name && r1.file.size === r2.file.size

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionHeader title="샘플" />
        <div className="flex flex-col gap-2">
          <label htmlFor={inputId} className="text-body font-medium text-text-strong">
            샘플 이름
          </label>
          <input
            id={inputId}
            value={sampleId}
            onChange={(event) => onSampleIdChange(event.target.value)}
            aria-describedby={sampleIdProblem ? errorId : hintId}
            aria-invalid={sampleIdProblem ? true : undefined}
            spellCheck={false}
            autoComplete="off"
            placeholder="예: NA12878"
            className="h-9 w-full max-w-90 rounded-sm border border-border-strong bg-surface px-3 font-mono text-data text-text-strong placeholder:font-sans placeholder:text-body placeholder:text-text-disabled"
          />
          {sampleIdProblem ? (
            <p id={errorId} className="text-caption text-status-failure-fg">
              {sampleIdProblem}
            </p>
          ) : (
            <p id={hintId} className="text-caption text-text-muted">
              samplesheet와 결과 파일 이름에 그대로 쓰입니다. 영문자·숫자로
              시작하고 마침표·밑줄·하이픈까지 쓸 수 있습니다.
            </p>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader
          title="paired-end FASTQ"
          meta="R1 · R2 각 1개"
        />
        <p className="text-body text-text">
          한 번의 분석에 샘플 1개, 파일 한 쌍을 처리합니다. 파일을 고르면 바로
          전송을 시작하고, 다른 단계로 이동해도 계속 전송합니다.
        </p>

        {sameFile ? (
          <MessageBlock tone="warning" title="R1과 R2가 같은 파일로 보입니다">
            이름과 크기가 같은 파일이 두 슬롯에 들어 있습니다. paired-end
            분석에는 서로 다른 두 파일이 필요합니다.
          </MessageBlock>
        ) : null}

        <div className="rounded-md border border-border bg-surface">
          <FastqSlot
            upload={r1}
            sampleId={sampleId || null}
            description="Read 1 파일을 선택해 주세요"
          />
          <FastqSlot
            upload={r2}
            sampleId={sampleId || null}
            description="Read 2 파일을 선택해 주세요"
          />
        </div>
      </section>
    </div>
  )
}
