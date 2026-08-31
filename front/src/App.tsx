import { Inbox } from 'lucide-react'
import { Route, Routes } from 'react-router'

import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { MessageBlock } from '@/components/ui/MessageBlock'
import { SectionHeader } from '@/components/ui/SectionHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { TabsList, TabsPanel, TabsRoot, TabsTab } from '@/components/ui/Tabs'
import { HealthCheckPage } from '@/features/health/HealthCheckPage'

/*
  공통 primitive가 실제 브라우저에서 어떻게 렌더링되는지 확인하는
  개발용 화면이다. 제품 화면이 아니므로 shell / navigation / dashboard를
  만들지 않고, WES 데이터처럼 보이는 mock도 넣지 않는다.
*/
function Showcase() {
  return (
    <main className="mx-auto flex max-w-content flex-col gap-12 px-6 py-12">
      <div>
        <p className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
          WES Analysis · UI Primitives
        </p>
        <h1 className="mt-2 text-h1 font-semibold tracking-tight text-text-strong">
          Component check
        </h1>
        <p className="mt-3 text-body text-text">
          공통 UI 부품 확인용 개발 화면입니다.
        </p>
      </div>

      <section className="flex flex-col gap-4">
        <SectionHeader eyebrow="BUTTON" title="Button" meta="3 variants" />
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <Button variant="secondary" disabled>
            Disabled
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader eyebrow="STATUS" title="Status badge" meta="6 tones" />
        {/*
          surface 패널 위에서 렌더링한다. badge-shapes-2의 E안도
          `background:var(--surface)` 패널 안에 있고, cancelled의 배경이
          페이지 배경(paper)과 같은 값이라 paper 위에서는 알약이 사라진다.
          시안과 나란히 놓고 비교하기 위해 문구도 E안과 같은 한국어를 쓴다.
        */}
        <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-8">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone="idle">대기 중</StatusBadge>
            <StatusBadge tone="running">분석 중</StatusBadge>
            <StatusBadge tone="success">완료</StatusBadge>
            <StatusBadge tone="warning">완료 (경고 있음)</StatusBadge>
            <StatusBadge tone="failure">실패</StatusBadge>
            <StatusBadge tone="cancelled">취소됨</StatusBadge>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone="running" size="sm">
              분석 중
            </StatusBadge>
            <StatusBadge tone="success" size="sm">
              완료
            </StatusBadge>
            <StatusBadge tone="cancelled" size="sm">
              취소됨
            </StatusBadge>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader eyebrow="MESSAGE" title="Message block" meta="4 tones" />
        <div className="flex flex-col gap-3">
          <MessageBlock tone="info" title="Example information">
            제목과 본문을 함께 쓰는 기본 형태입니다.
          </MessageBlock>
          <MessageBlock tone="success" title="Example success">
            성공 상태 메시지입니다.
          </MessageBlock>
          <MessageBlock
            tone="warning"
            title="Example warning"
            action={<Button variant="secondary">Example action</Button>}
          >
            후속 동작이 있는 형태입니다.
          </MessageBlock>
          <MessageBlock tone="danger" title="Example failure">
            오류 메시지입니다. 기술 상세는 호출부에서 접어서 덧붙입니다.
          </MessageBlock>
          <MessageBlock tone="info">
            제목 없이 본문만 있는 고정 안내 블록입니다.
          </MessageBlock>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader eyebrow="TABS" title="Tabs" meta="keyboard" />
        <TabsRoot defaultValue="one">
          <TabsList>
            <TabsTab value="one">Tab one</TabsTab>
            <TabsTab value="two">Tab two</TabsTab>
            <TabsTab value="three">Tab three</TabsTab>
          </TabsList>
          <TabsPanel value="one">
            <p className="text-body text-text">First panel.</p>
          </TabsPanel>
          <TabsPanel value="two">
            <p className="text-body text-text">Second panel.</p>
          </TabsPanel>
          <TabsPanel value="three">
            <p className="text-body text-text">Third panel.</p>
          </TabsPanel>
        </TabsRoot>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeader
          eyebrow="EMPTY"
          title="Empty state"
          action={
            <a
              href="/"
              className="inline-flex min-h-6 items-center text-small font-medium"
            >
              Example link
            </a>
          }
        />
        <EmptyState
          icon={<Inbox size={32} strokeWidth={1.5} aria-hidden="true" />}
          title="Example empty title"
          titleLevel={3}
          description="다음에 무엇을 하면 되는지 적는 자리입니다."
          action={<Button variant="primary">Example action</Button>}
        />
      </section>
    </main>
  )
}

function App() {
  return (
    <Routes>
      {/* 공통 primitive 확인용 개발 화면. 제품 화면이 아니다. */}
      <Route path="/" element={<Showcase />} />
      {/* backend 연결 확인용 첫 vertical slice. */}
      <Route path="/health" element={<HealthCheckPage />} />
    </Routes>
  )
}

export default App
