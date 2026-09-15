import { useCallback, useEffect, useMemo, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { UploadCloud, X, Trash2, AlertTriangle, HelpCircle, CheckCircle2 } from 'lucide-react'
import type { InputSpec } from '@/features/analysis-profile/types'
import {
  buildBatchAssignment,
  formatBytes,
  FORMAT_HELP,
  type BatchAssignmentResult,
} from './pairDetection'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

interface Props {
  spec: InputSpec
  onChange: (result: BatchAssignmentResult) => void
}

// ── 말머리 툴팁: 어떤 형식/파일명을 올려야 하는지 설명 ───────────────────────
function FormatHelpTip({ spec }: { spec: InputSpec }) {
  const help = FORMAT_HELP[spec.mode]
  return (
    <Tooltip>
      <TooltipTrigger
        aria-label="파일 형식 설명"
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center
                   rounded-full bg-sky-50 text-sky-700 transition-colors
                   hover:bg-sky-100 focus:outline-none focus:ring-2
                   focus:ring-sky-400 dark:bg-sky-950 dark:text-sky-300"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-sm leading-relaxed">
        <p className="mb-1 text-xs font-semibold">{help.title}</p>
        <ul className="space-y-0.5 text-xs">
          {help.body.map((line, i) => (
            <li key={i} className={line.startsWith('  ') ? 'font-mono text-[10px] opacity-90' : ''}>
              {line}
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-[10px] opacity-75">
          허용 확장자: {spec.accept.join(', ')} · 파일당 최대 {spec.maxFileSizeGb}GB
        </p>
      </TooltipContent>
    </Tooltip>
  )
}

export function UploadZone({ spec, onChange }: Props) {
  const [files, setFiles] = useState<File[]>([])

  const result = useMemo(() => buildBatchAssignment(files, spec), [files, spec])

  // 그룹핑 결과가 바뀔 때마다 부모에게 알림 (렌더 중이 아니라 커밋 후에)
  useEffect(() => {
    onChange(result)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result])

  const onDrop = useCallback((accepted: File[]) => {
    setFiles((prev) => {
      const key = (f: File) => `${f.name}__${f.size}`
      const existing = new Set(prev.map(key))
      const merged = [...prev]
      for (const f of accepted) {
        if (!existing.has(key(f))) merged.push(f)
      }
      return merged
    })
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, multiple: true })

  function removeFile(target: File) {
    setFiles((prev) => prev.filter((f) => !(f.name === target.name && f.size === target.size)))
  }

  function removeGroup(sampleId: string) {
    const group = result.groups.find((g) => g.sampleId === sampleId)
    if (!group) return
    const toRemove = new Set(Object.values(group.slots).map((f) => `${f.name}__${f.size}`))
    setFiles((prev) => prev.filter((f) => !toRemove.has(`${f.name}__${f.size}`)))
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-slate-500">업로드 형식</span>
        <FormatHelpTip spec={spec} />
      </div>

      {/* 드롭존 */}
      <div
        {...getRootProps()}
        className={cn(
          'cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors',
          isDragActive
            ? 'border-teal-500 bg-teal-50 dark:bg-teal-950'
            : 'border-slate-300 bg-slate-50 hover:border-teal-400 dark:border-slate-700 dark:bg-slate-900',
        )}
      >
        <input {...getInputProps()} />
        <UploadCloud className="mx-auto h-8 w-8 text-slate-400" />
        <p className="mt-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          파일을 드래그하거나 클릭하여 선택 (여러 샘플 동시 업로드 가능)
        </p>
        <p className="mt-1 text-xs text-slate-400">
          허용 형식: {spec.accept.join(', ')} · 최대 {spec.maxFileSizeGb}GB
        </p>
      </div>

      {/* 정상 인식된 샘플 세트 */}
      {result.groups.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-slate-500">
            인식된 샘플 {result.groups.length}개
          </p>
          {result.groups.map((group) => (
            <div
              key={group.sampleId}
              className="rounded-lg border border-emerald-200 bg-emerald-50 p-3
                         dark:border-emerald-800 dark:bg-emerald-950"
            >
              <div className="mb-1.5 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-sm font-medium
                                 text-emerald-800 dark:text-emerald-200">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {group.sampleId}
                </span>
                <button
                  type="button"
                  onClick={() => removeGroup(group.sampleId)}
                  className="text-emerald-700 hover:text-emerald-900 dark:text-emerald-300"
                  aria-label={`${group.sampleId} 세트 전체 삭제`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="space-y-1">
                {Object.entries(group.slots).map(([slotId, file]) => (
                  <div
                    key={slotId}
                    className="flex items-center justify-between rounded bg-white/70
                               px-2 py-1 text-xs dark:bg-black/20"
                  >
                    <span className="font-mono text-slate-600 dark:text-slate-300">
                      {slotId.toUpperCase()}: {file.name}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-slate-400">{formatBytes(file.size)}</span>
                      <button
                        type="button"
                        onClick={() => removeFile(file)}
                        className="text-slate-400 hover:text-red-500"
                        aria-label={`${file.name} 삭제`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 문제 있는 파일 */}
      {result.problemFiles.length > 0 && (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium
                        text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            문제 있는 파일 {result.problemFiles.length}개
          </p>
          {result.problemFiles.map(({ file, reason }, i) => (
            <div
              key={`${file.name}-${i}`}
              className="flex items-center justify-between rounded-lg border
                         border-amber-200 bg-amber-50 px-3 py-2 text-xs
                         dark:border-amber-800 dark:bg-amber-950"
            >
              <div>
                <span className="font-mono text-amber-900 dark:text-amber-200">{file.name}</span>
                <span className="ml-2 text-slate-400">({formatBytes(file.size)})</span>
                <p className="mt-0.5 text-amber-700 dark:text-amber-400">{reason}</p>
              </div>
              <button
                type="button"
                onClick={() => removeFile(file)}
                className="shrink-0 text-amber-500 hover:text-red-600"
                aria-label={`${file.name} 삭제`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
