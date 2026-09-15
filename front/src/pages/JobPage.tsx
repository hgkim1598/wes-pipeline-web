import { useParams, useLocation, useNavigate } from 'react-router-dom'
import { useJobStream } from '@/features/job/useJobStream'
import { StepTimeline } from '@/features/job/StepTimeline'
import { LogViewer } from '@/features/job/LogViewer'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { AlertCircle } from 'lucide-react'

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  queued:                  { text: '대기 중',          cls: 'bg-slate-100 text-slate-600' },
  running:                 { text: '분석 중',          cls: 'bg-teal-50 text-teal-700' },
  completed:               { text: '완료',             cls: 'bg-emerald-50 text-emerald-700' },
  completed_with_warnings: { text: '완료 (경고 있음)', cls: 'bg-amber-50 text-amber-700' },
  failed:                  { text: '실패',             cls: 'bg-red-50 text-red-700' },
  cancelled:               { text: '취소됨',           cls: 'bg-slate-100 text-slate-500' },
}

const TERMINAL = ['completed', 'completed_with_warnings', 'failed', 'cancelled']

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const profileLabel = (location.state as { profileLabel?: string } | null)?.profileLabel

  const { job, cancel } = useJobStream(jobId ?? null)

  const statusMeta = STATUS_LABEL[job.status] ?? STATUS_LABEL.queued
  const isTerminal = TERMINAL.includes(job.status)
  const isRunning = job.status === 'running' || job.status === 'queued'

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-8">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">
            {profileLabel ?? '분석 진행 상황'}
          </h1>
          <Badge className={statusMeta.cls} variant="secondary">
            {statusMeta.text}
          </Badge>
        </div>
        <p className="mt-1 font-mono text-xs text-slate-400">Job ID: {jobId}</p>
      </div>

      {/* 전체 진행률 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>전체 진행률</span>
          <span>{job.progress}%</span>
        </div>
        <Progress value={job.progress} />
      </div>

      {/* 단계별 타임라인 */}
      <div className="rounded-xl border border-slate-200 bg-white p-6
                      dark:border-slate-700 dark:bg-slate-900">
        <h2 className="mb-4 text-sm font-semibold">단계별 진행 상황</h2>
        <StepTimeline steps={job.steps} />
      </div>

      {/* 로그 */}
      <LogViewer lines={job.logTail} transport={job.transport} />

      {job.error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200
                        bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{job.error}</span>
        </div>
      )}

      {/* 액션 버튼 */}
      <div className="flex justify-end gap-2">
        {isRunning && (
          <Button variant="outline" onClick={cancel}>
            분석 취소
          </Button>
        )}
        {isTerminal && (
          <Button onClick={() => navigate(`/results/${jobId}`)}>
            결과 보기
          </Button>
        )}
      </div>
    </div>
  )
}
