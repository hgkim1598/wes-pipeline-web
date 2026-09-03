import { ChevronLeft } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { MessageBlock } from '@/components/ui/MessageBlock'

/*
  /runs/:jobId 자리표.

  목록의 행은 상세 화면으로 가는 것이 자연스러운 조작이고 시안도 그렇게
  설계돼 있다. 상세 화면 자체는 다음 단계 작업이라, 지금은 어디에도 닿지
  않는 링크를 만드는 대신 "아직 없다"고 말하는 화면을 둔다.

  없는 기능을 있는 것처럼 보이는 껍데기를 만들지 않는다. 여기서 실행 정보를
  조회하지도 않는다 — 그것이 곧 상세 화면이고, 이 파일의 일이 아니다.
*/

export function RunDetailPlaceholderPage() {
  const { jobId } = useParams<{ jobId: string }>()

  return (
    <main className="mx-auto flex max-w-content flex-col gap-6 px-6 py-8">
      <div className="flex flex-col gap-3">
        <Link
          to="/runs"
          className="inline-flex min-h-6 items-center gap-1 self-start text-small text-text-muted no-underline hover:text-text hover:underline"
        >
          <ChevronLeft size={12} strokeWidth={1.5} aria-hidden="true" />
          실행 목록
        </Link>
        <h1 className="text-h1 font-semibold tracking-tight text-text-strong">
          실행 상세
        </h1>
      </div>

      <MessageBlock tone="info" title="실행 상세 화면은 아직 구현되지 않았습니다">
        <div className="flex flex-col gap-2">
          <p>
            선택한 실행의 식별자는 <code>{jobId ?? '—'}</code>입니다.
          </p>
          <p>
            단계 진행 · 결과 · 산출물 · 재현성 화면은 다음 단계에서 구현합니다.
            지금은 실행 목록에서 상태와 진행 단계를 확인할 수 있습니다.
          </p>
        </div>
      </MessageBlock>
    </main>
  )
}
