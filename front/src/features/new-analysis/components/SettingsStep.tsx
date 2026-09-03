import { useId } from 'react'

import { SectionHeader } from '@/components/ui/SectionHeader'
import { CAPTURE_KITS, SERVER_ASSEMBLY } from '@/features/new-analysis/catalog'

/*
  3단계 — 설정.

  실제로 고를 수 있는 것은 capture kit 하나뿐이다. 시안에는 ACMG 자동 분류
  토글도 있지만 두지 않았다. backend는 run_acmg를 받아도 서버에 InterVar
  설정이 없으면 unsupportedOptions로 되돌리고(api/jobs.py), 지금 이 서버가
  지원하는지 확인할 방법이 frontend에 없다. 켤 수 없는 스위치를 보여주면
  화면이 지키지 못할 약속을 하게 된다.

  참조 유전체는 서버 bundle에 고정이라 선택이 아니라 사실로 적는다.
*/

export interface SettingsStepProps {
  captureKitId: string
  onCaptureKitChange: (value: string) => void
}

export function SettingsStep({
  captureKitId,
  onCaptureKitChange,
}: SettingsStepProps) {
  const selectId = useId()
  const hintId = useId()

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionHeader title="분석 설정" />

        <div className="flex flex-col gap-2">
          <label
            htmlFor={selectId}
            className="text-body font-medium text-text-strong"
          >
            Exome capture kit
          </label>
          <select
            id={selectId}
            value={captureKitId}
            onChange={(event) => onCaptureKitChange(event.target.value)}
            aria-describedby={hintId}
            className="h-9 w-full max-w-90 rounded-sm border border-border-strong bg-surface px-3 text-body text-text-strong"
          >
            <option value="">선택해 주세요</option>
            {CAPTURE_KITS.map((kit) => (
              <option key={kit.id} value={kit.id}>
                {kit.label}
              </option>
            ))}
          </select>
          <p id={hintId} className="text-caption text-text-muted">
            라이브러리를 만들 때 실제로 사용한 kit과 같은 것을 선택해 주세요. 이
            kit의 target 영역이 분석 범위를 결정합니다. 서버에 등록되어 검증된
            kit만 목록에 있습니다.
          </p>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader title="이 서버에 고정된 항목" level={2} />
        <dl className="flex flex-col">
          <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 py-1">
            <dt className="flex-none text-small text-text-muted md:w-45">
              참조 유전체
            </dt>
            <dd className="flex min-w-0 flex-1 basis-full flex-col gap-0.5 md:basis-0">
              <span className="text-body text-text-strong">
                {SERVER_ASSEMBLY}
              </span>
              <span className="text-caption text-text-muted">
                참조 FASTA · capture BED · known-sites가 모두 이 기준입니다.
                요청에 담아 보내지 않으며, 서버 설정과 다르면 제출이 거절됩니다.
              </span>
            </dd>
          </div>
          <div className="flex min-h-9 flex-wrap items-baseline gap-x-4 gap-y-1 py-1">
            <dt className="flex-none text-small text-text-muted md:w-45">
              품질·필터 기준
            </dt>
            <dd className="min-w-0 flex-1 basis-full md:basis-0">
              <span className="text-caption text-text-muted">
                최소 염기 품질 · read 길이 · 변이 호출 도구 · depth 기준은 현재
                pipeline이 고정값으로 실행합니다. 화면에서 조정할 수 없습니다.
              </span>
            </dd>
          </div>
        </dl>
      </section>
    </div>
  )
}
