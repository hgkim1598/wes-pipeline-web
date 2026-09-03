import { Check } from 'lucide-react'

import { cx } from '@/lib/cx'

/*
  4단계 표시.

  시안 근거 (docs/design/wizard.html)
    24px 원형 노드(mono 번호) · 아래 caption 라벨 · 노드 사이 2px 연결선
    완료 노드는 fill-success, 현재 노드는 brand, 남은 노드는 ink-100

  각 단계는 버튼이다. 시안은 "완료한 단계만 클릭"이지만, 이 마법사는 값을
  잃지 않고 어느 단계로든 오갈 수 있다(업로드는 계속 진행된다). 앞 단계를
  막으면 업로드가 도는 동안 설정을 미리 볼 수 없을 뿐이다.

  현재 단계는 aria-current="step"으로 알린다. 색과 굵기만으로 현재 위치를
  전달하지 않는다.
*/

export interface WizardStep {
  id: number
  label: string
}

export interface WizardProgressProps {
  steps: WizardStep[]
  currentStep: number
  onSelect: (step: number) => void
}

export function WizardProgress({
  steps,
  currentStep,
  onSelect,
}: WizardProgressProps) {
  return (
    <ol className="flex flex-wrap items-start gap-y-2">
      {steps.map((step, index) => {
        const done = step.id < currentStep
        const current = step.id === currentStep

        return (
          <li key={step.id} className="flex items-start">
            <button
              type="button"
              onClick={() => onSelect(step.id)}
              aria-current={current ? 'step' : undefined}
              className="flex w-16 flex-col items-center gap-2 rounded-sm py-1"
            >
              <span
                aria-hidden="true"
                className={cx(
                  'flex size-6 items-center justify-center rounded-pill font-mono text-caption font-medium',
                  done && 'bg-fill-success text-surface',
                  current && 'bg-brand text-surface',
                  !done && !current && 'bg-border-subtle text-text-muted',
                )}
              >
                {done ? (
                  <Check size={12} strokeWidth={2} aria-hidden="true" />
                ) : (
                  step.id
                )}
              </span>
              <span
                className={cx(
                  'text-caption whitespace-nowrap',
                  current
                    ? 'font-semibold text-text-strong'
                    : done
                      ? 'text-text'
                      : 'text-text-muted',
                )}
              >
                {step.label}
              </span>
            </button>
            {index < steps.length - 1 ? (
              <span
                aria-hidden="true"
                className={cx(
                  'mt-4 h-0.5 w-6 md:w-12',
                  done ? 'bg-fill-success' : 'bg-border-subtle',
                )}
              />
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
