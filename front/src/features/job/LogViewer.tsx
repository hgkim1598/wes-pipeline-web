import { useEffect, useRef } from 'react'
import { Terminal } from 'lucide-react'

interface Props {
  lines: string[]
  transport: 'sse' | 'polling' | 'disconnected'
}

export function LogViewer({ lines, transport }: Props) {
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight })
  }, [lines])

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-950 dark:border-slate-700">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Terminal className="h-3 w-3" />
          실행 로그
        </span>
        <span className="text-[10px] text-slate-500">
          {transport === 'sse' ? '실시간 연결' : transport === 'polling' ? '주기적 갱신' : '연결 대기 중'}
        </span>
      </div>
      <div ref={boxRef} className="max-h-64 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed">
        {lines.length === 0 ? (
          <p className="text-slate-600">
            {transport === 'polling'
              ? '주기적 갱신 모드에서는 상세 로그가 표시되지 않습니다. 단계별 진행 상황을 참고하세요.'
              : '로그를 기다리는 중...'}
          </p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap text-slate-300">
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
