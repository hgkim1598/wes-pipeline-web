import { SectionHeader } from '@/components/ui/SectionHeader'

/*
  최근 로그.

  시안 근거 (docs/design/pipeline-tab.html · 최근 로그)
    log-bg 반전 표면 · radius 8 · padding 16 · mono 12.5 · 가로 스크롤
    time / step / body 3색 (--color-log-time / -step / -fg)
    캡션 "파이프라인 로그의 마지막 200줄입니다."

  시안에는 "전체 보기" 링크가 있지만 두지 않았다. 전체 로그를 주는 endpoint가
  backend에 없고(logTail 200줄이 유일한 경로), 없는 기능으로 링크를 만들면
  화면이 거짓말을 한다. 실제 full 실행에서 200줄이 부족하다고 확인되면 그때
  endpoint를 논의한다.

  줄을 파싱해 색을 입히지 않는다. main.sh의 로그 형식은 계약이 아니고, 화면이
  정규식으로 그것을 해석하기 시작하면 형식이 바뀔 때 조용히 깨진다. 여기서는
  서버가 준 줄을 그대로 등폭으로 보여준다.
*/

export interface LogPanelProps {
  lines: string[]
}

export function LogPanel({ lines }: LogPanelProps) {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        eyebrow="LOG"
        title="최근 로그"
        meta={
          lines.length > 0 ? (
            <>
              <span className="font-mono text-data">{lines.length}</span>줄
            </>
          ) : null
        }
      />

      {lines.length === 0 ? (
        <p className="text-body text-text-muted">
          아직 기록된 로그가 없습니다. 파이프라인이 시작되면 여기에 표시됩니다.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md bg-log-bg p-4">
            {/*
              pre가 아니라 div + whitespace-pre로 둔 이유: 각 줄이 개별 요소여야
              긴 로그에서 브라우저가 줄 단위로 렌더링을 최적화하고, 나중에 줄
              단위 강조(현재 단계 등)를 붙일 자리가 남는다.
            */}
            {lines.map((line, index) => (
              <div
                // 로그 줄은 같은 내용이 반복될 수 있어 내용만으로는 키가 되지 않는다.
                key={`${index}-${line}`}
                className="font-mono text-log whitespace-pre text-log-fg"
              >
                {line}
              </div>
            ))}
          </div>
          <p className="text-caption text-text-muted">
            파이프라인 로그의 마지막 200줄입니다. 전체 로그는 서버의 run
            디렉터리에 있습니다.
          </p>
        </>
      )}
    </section>
  )
}
