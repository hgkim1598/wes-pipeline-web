import { CheckCircle2, Circle, Loader2, AlertTriangle, XCircle, MinusCircle } from 'lucide-react'
import type { StepState, StepStatus } from './useJobStream'
import { stepLabel } from './useJobStream'
import { cn } from '@/lib/utils'

interface Props {
  steps: StepState[]
}

const ICON_MAP: Record<StepStatus, { Icon: typeof CheckCircle2; cls: string }> = {
  completed: { Icon: CheckCircle2, cls: 'text-emerald-600' },
  running:   { Icon: Loader2,      cls: 'text-teal-600 animate-spin' },
  warning:   { Icon: AlertTriangle, cls: 'text-amber-600' },
  failed:    { Icon: XCircle,      cls: 'text-red-600' },
  skipped:   { Icon: MinusCircle,  cls: 'text-slate-400' },
  pending:   { Icon: Circle,       cls: 'text-slate-300' },
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s}s`
}

export function StepTimeline({ steps }: Props) {
  if (steps.length === 0) {
    return <p className="text-sm text-slate-400">단계 정보를 불러오는 중...</p>
  }

  return (
    <ol className="space-y-0.5">
      {steps.map((step, i) => {
        const { Icon, cls } = ICON_MAP[step.status] ?? ICON_MAP.pending
        const isLast = i === steps.length - 1

        return (
          <li key={step.stepId} className="relative flex gap-3 pb-4">
            {!isLast && (
              <span
                className="absolute left-[9px] top-6 h-[calc(100%-8px)] w-px bg-slate-200
                           dark:bg-slate-700"
              />
            )}
            <Icon className={cn('mt-0.5 h-[18px] w-[18px] shrink-0', cls)} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span
                  className={cn(
                    'text-sm font-medium',
                    step.status === 'pending' ? 'text-slate-400' : 'text-slate-800 dark:text-slate-100',
                  )}
                >
                  {stepLabel(step.stepId)}
                </span>
                {step.elapsedSeconds > 0 && (
                  <span className="shrink-0 font-mono text-[11px] text-slate-400">
                    {formatElapsed(step.elapsedSeconds)}
                  </span>
                )}
              </div>
              {step.messages.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {step.messages.map((m, mi) => (
                    <li key={mi} className="text-xs text-amber-700 dark:text-amber-400">
                      {m}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
