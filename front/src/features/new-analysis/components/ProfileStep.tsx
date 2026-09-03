import { Check } from 'lucide-react'

import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { ANALYSIS_PROFILES } from '@/features/new-analysis/catalog'
import { describeRunMode } from '@/features/new-analysis/runMode'

/*
  1단계 — 분석.

  시안(wizard.html STEP 1)의 "사용 가능 / 준비 중" 두 묶음 중 아래쪽은 두지
  않았다. 준비 중 목록은 존재하지 않는 pipeline을 화면에 채우는 일이고,
  CLAUDE.md 35장이 금지한다.

  선택할 것이 하나뿐인 단계지만 건너뛰지 않는 이유는, 사용자가 수 GB를
  올리기 전에 이 서버가 실제로 무엇을 하는지 — 특히 사전 점검 모드인지 —
  알아야 하기 때문이다.
*/

export interface ProfileStepProps {
  selectedProfileId: string
  /** GET /api/health의 runMode. 아직 모르면 undefined. */
  serverRunMode: string | undefined
}

export function ProfileStep({
  selectedProfileId,
  serverRunMode,
}: ProfileStepProps) {
  const runMode = describeRunMode(serverRunMode)

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionHeader title="실행할 분석" />
        <ul className="flex flex-col gap-3">
          {ANALYSIS_PROFILES.map((profile) => {
            const selected = profile.id === selectedProfileId
            return (
              <li
                key={profile.id}
                className={
                  selected
                    ? 'rounded-md border border-brand bg-brand-faint p-6'
                    : 'rounded-md border border-border bg-surface p-6'
                }
              >
                <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
                  <div className="flex min-w-0 flex-col gap-2">
                    <h3 className="text-h2 font-semibold text-text-strong">
                      {profile.label}
                    </h3>
                    <p className="text-small text-text-muted">
                      {profile.facts.join(' · ')}
                    </p>
                  </div>
                  {selected ? (
                    <span className="flex flex-none items-center gap-2 rounded-pill bg-brand-selected px-[var(--pad-pill-x)] py-1 text-small font-medium text-brand">
                      <Check size={16} strokeWidth={2} aria-hidden="true" />
                      선택됨
                    </span>
                  ) : null}
                </div>
                <p className="mt-4 text-body text-text">{profile.description}</p>
                <p className="mt-2 font-mono text-caption text-text-muted">
                  {profile.id}
                </p>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader title="이 서버의 실행 모드" />
        {runMode ? (
          <MessageBlock tone={runMode.tone} title={runMode.title}>
            {runMode.description}
          </MessageBlock>
        ) : (
          <MessageBlock tone="info" title="실행 모드를 확인하지 못했습니다">
            서버 상태를 읽지 못해 이 서버가 사전 점검만 하는지 전체 분석을
            하는지 알 수 없습니다. 분석은 제출할 수 있지만, 어떤 단계가
            실행되는지는 실행 목록에서 확인해 주세요.
          </MessageBlock>
        )}
      </section>
    </div>
  )
}
