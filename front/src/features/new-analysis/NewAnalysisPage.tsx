import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Button } from '@/components/ui/Button'
import { useHealthQuery } from '@/features/health/useHealthQuery'
import { InputFilesStep } from '@/features/new-analysis/components/InputFilesStep'
import { ProfileStep } from '@/features/new-analysis/components/ProfileStep'
import { ReviewStep } from '@/features/new-analysis/components/ReviewStep'
import { SettingsStep } from '@/features/new-analysis/components/SettingsStep'
import { WizardProgress } from '@/features/new-analysis/components/WizardProgress'
import {
  ANALYSIS_PROFILES,
  DEFAULT_PROFILE_ID,
  findCaptureKit,
} from '@/features/new-analysis/catalog'
import { suggestSampleId, validateSampleId } from '@/features/new-analysis/fastq'
import { useCreateJobMutation } from '@/features/new-analysis/useCreateJobMutation'
import type { FastqUploadController } from '@/features/new-analysis/useFastqUpload'
import { useFastqUpload } from '@/features/new-analysis/useFastqUpload'

/*
  새 분석 마법사.

  단계는 ?step=n으로 표현한다. 뒤로가기·앞으로가기가 그대로 동작하고,
  주소를 새로고침해도 같은 단계로 돌아온다. 단계를 바꿔도 이 component는
  언마운트되지 않으므로 진행 중인 업로드가 끊기지 않는다.

  상태를 전역에 두지 않았다. 여기 있는 것은 이 화면 한 번의 제출에만 쓰이는
  값이고, 슬롯 상태는 useFastqUpload 인스턴스가 각자 갖는다. 나중에 샘플이
  여러 개가 되면 이 페이지가 슬롯 쌍을 더 만들면 된다 — 아래 어떤 코드도
  "샘플은 하나뿐"이라는 가정 위에 서 있지 않다.

  실제 제출은 POST /api/jobs 한 번이고, backend가 지금 샘플 하나만 받는다.
  여러 샘플은 각각의 Job이 되어야 하므로(worker가 Job 단위로 실행한다)
  그때도 이 요청을 샘플 수만큼 보내는 형태가 된다.
*/

const STEPS = [
  { id: 1, label: '분석' },
  { id: 2, label: '입력 파일' },
  { id: 3, label: '설정' },
  { id: 4, label: '확인' },
]

const FIRST_STEP = 1
const LAST_STEP = STEPS.length

export function NewAnalysisPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [sampleId, setSampleId] = useState('')
  // 기본 선택을 두지 않는다. capture kit이 틀리면 분석 범위 자체가 달라지는데,
  // 미리 골라 두면 사용자가 확인하지 않고 지나갈 수 있다.
  const [captureKitId, setCaptureKitId] = useState('')

  const r1 = useFastqUpload('r1')
  const r2 = useFastqUpload('r2')

  const health = useHealthQuery()
  const createJob = useCreateJobMutation()

  const step = parseStep(searchParams.get('step'))
  const goToStep = (next: number) => {
    setSearchParams({ step: String(clampStep(next)) })
  }

  const profile = ANALYSIS_PROFILES.find((item) => item.id === DEFAULT_PROFILE_ID)
  const captureKit = findCaptureKit(captureKitId)

  /*
    R1을 고르면 파일 이름에서 샘플 이름을 제안한다. 이미 입력한 값이 있으면
    건드리지 않는다 — 사용자가 쓴 것을 파일 이름이 덮어쓰면 안 된다.
  */
  const r1WithSuggestion: FastqUploadController = {
    ...r1,
    select: (file, currentSampleId) => {
      const suggested = sampleId.trim() ? null : suggestSampleId(file.name)
      if (suggested) setSampleId(suggested)
      r1.select(file, suggested ?? currentSampleId)
    },
  }

  const blockers = collectBlockers({ sampleId, captureKitId, r1, r2 })
  const uploadSummary = summarizeUploads(r1, r2)

  const handleSubmit = () => {
    if (blockers.length > 0 || createJob.isPending) return
    // 토큰이 없으면 blockers가 이미 막았어야 한다. 방어적으로 한 번 더 본다.
    if (!r1.token || !r2.token) return

    createJob.mutate(
      {
        profileId: DEFAULT_PROFILE_ID,
        captureKitId,
        sampleId: sampleId.trim(),
        files: { r1: r1.token, r2: r2.token },
      },
      {
        // 목록 무효화는 mutation이 이미 했다. 여기서는 이동만 한다.
        onSuccess: () => navigate('/runs'),
      },
    )
  }

  return (
    <main className="mx-auto flex max-w-content flex-col gap-8 px-6 py-8">
      <div className="flex flex-col gap-4">
        <Link
          to="/runs"
          className="inline-flex min-h-6 items-center gap-1 self-start text-small text-text-muted no-underline hover:text-text hover:underline"
        >
          <ChevronLeft size={12} strokeWidth={1.5} aria-hidden="true" />
          실행 목록
        </Link>
        <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
          새 분석
        </h1>
        <WizardProgress steps={STEPS} currentStep={step} onSelect={goToStep} />
      </div>

      {step === 1 ? (
        <ProfileStep
          selectedProfileId={DEFAULT_PROFILE_ID}
          serverRunMode={health.data?.runMode}
        />
      ) : null}

      {step === 2 ? (
        <InputFilesStep
          sampleId={sampleId}
          onSampleIdChange={setSampleId}
          r1={r1WithSuggestion}
          r2={r2}
        />
      ) : null}

      {step === 3 ? (
        <SettingsStep
          captureKitId={captureKitId}
          onCaptureKitChange={setCaptureKitId}
        />
      ) : null}

      {step === 4 ? (
        <ReviewStep
          profileLabel={profile?.label ?? DEFAULT_PROFILE_ID}
          profileId={DEFAULT_PROFILE_ID}
          sampleId={sampleId.trim()}
          captureKit={captureKit}
          r1={r1}
          r2={r2}
          serverRunMode={health.data?.runMode}
          blockers={blockers}
          isSubmitting={createJob.isPending}
          submitError={createJob.error}
          onSubmit={handleSubmit}
          onEdit={goToStep}
        />
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-border pt-6">
        {/* 어느 단계에 있든 전송 상황이 보인다. 시안의 하단 바와 같은 역할이다. */}
        <p className="text-small text-text-muted">{uploadSummary}</p>
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            onClick={() => goToStep(step - 1)}
            disabled={step === FIRST_STEP}
          >
            <ChevronLeft size={16} strokeWidth={1.5} aria-hidden="true" />
            이전
          </Button>
          {step < LAST_STEP ? (
            <Button variant="primary" onClick={() => goToStep(step + 1)}>
              다음
              <ChevronRight size={16} strokeWidth={1.5} aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </div>
    </main>
  )
}

function parseStep(raw: string | null): number {
  const value = Number(raw)
  return Number.isInteger(value) ? clampStep(value) : FIRST_STEP
}

function clampStep(value: number): number {
  return Math.min(LAST_STEP, Math.max(FIRST_STEP, value))
}

/**
 * 제출을 막는 이유들. 화면에 그대로 보여주므로 문장으로 만든다.
 * 순서는 사용자가 고치러 가는 순서(앞 단계부터)다.
 */
function collectBlockers({
  sampleId,
  captureKitId,
  r1,
  r2,
}: {
  sampleId: string
  captureKitId: string
  r1: FastqUploadController
  r2: FastqUploadController
}): string[] {
  const blockers: string[] = []

  const sampleProblem = validateSampleId(sampleId)
  if (sampleProblem) blockers.push(sampleProblem)

  if (!captureKitId) {
    blockers.push('Capture kit을 선택해 주세요. (3단계)')
  }

  for (const upload of [r1, r2]) {
    const label = upload.slotId.toUpperCase()
    if (!upload.file) {
      blockers.push(`${label} FASTQ 파일을 선택해 주세요. (2단계)`)
    } else if (upload.status === 'uploading') {
      blockers.push(`${label} 업로드가 끝나면 시작할 수 있습니다.`)
    } else if (upload.status !== 'completed' || !upload.token) {
      blockers.push(`${label} 업로드가 완료되지 않았습니다. (2단계)`)
    }
  }

  if (
    r1.file &&
    r2.file &&
    r1.file.name === r2.file.name &&
    r1.file.size === r2.file.size
  ) {
    blockers.push('R1과 R2가 같은 파일입니다. 서로 다른 두 파일이 필요합니다.')
  }

  return blockers
}

/** 단계와 무관하게 하단에 계속 보이는 전송 요약. */
function summarizeUploads(
  r1: FastqUploadController,
  r2: FastqUploadController,
): string {
  const slots = [r1, r2]
  const selected = slots.filter((slot) => slot.file)
  if (selected.length === 0) return '선택한 파일이 없습니다'

  const failed = selected.filter((slot) => slot.status === 'failed').length
  const done = selected.filter((slot) => slot.status === 'completed').length
  const uploading = selected.filter((slot) => slot.status === 'uploading')

  if (uploading.length > 0) {
    const sent = uploading.reduce((sum, slot) => sum + slot.sentBytes, 0)
    const total = uploading.reduce((sum, slot) => sum + slot.totalBytes, 0)
    const percent = total > 0 ? Math.round((sent / total) * 100) : 0
    return `업로드 중 ${done + 1}/${slots.length} · ${percent}%`
  }

  if (failed > 0) return `업로드 실패 ${failed}건 · 전송 완료 ${done}/${slots.length}`
  return `업로드 완료 ${done}/${slots.length}`
}
