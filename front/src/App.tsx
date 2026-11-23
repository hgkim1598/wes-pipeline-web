import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/layout/AppShell'
import { ComponentShowcase } from '@/features/dev/ComponentShowcase'
import { EntryPage } from '@/features/entry/EntryPage'
import { HealthCheckPage } from '@/features/health/HealthCheckPage'
import { EvalCompareListPage, EvalComparePage } from '@/features/eval-compare/EvalComparePage'
import { EvalGradePage } from '@/features/eval-compare/EvalGradePage'
import { SetupGuidePage } from '@/features/help/SetupGuidePage'
import { NewAnalysisPage } from '@/features/new-analysis/NewAnalysisPage'
import { RunDetailPage } from '@/features/run-detail/RunDetailPage'
import { RunListPage } from '@/features/runs/RunListPage'

function App() {
  return (
    <Routes>
      {/*
        진입 화면(다크). 서비스 사이드바 없이 전체 화면이다 — 작업 화면으로
        들어가는 문이고, 작업 화면의 이동은 그 안의 사이드바가 맡는다.
      */}
      <Route path="/" element={<EntryPage />} />
      {/* 그 밖의 모든 화면: 서비스 공통 사이드바(components/layout/AppShell.tsx). */}
      <Route path="*" element={<WorkspaceRoutes />} />
    </Routes>
  )
}

function WorkspaceRoutes() {
  return (
    <AppShell>
    <Routes>
      {/* 공통 primitive 확인용 개발 화면. 제품 화면이 아니다. */}
      <Route path="/dev/ui" element={<ComponentShowcase />} />
      {/* backend 연결 확인용 첫 vertical slice. */}
      <Route path="/health" element={<HealthCheckPage />} />
      {/* 첫 제품 화면. GET /api/jobs 하나에만 의존한다. */}
      <Route path="/runs" element={<RunListPage />} />
      {/* 업로드 + 제출. 단계는 ?step=n으로 표현한다. */}
      <Route path="/new" element={<NewAnalysisPage />} />
      {/*
        실행 상세 워크스페이스. 탭은 경로 세그먼트라 뒤로가기·새로고침·링크
        공유가 그대로 동작한다. 세그먼트가 없으면 파이프라인 탭이 기본이다.
      */}
      {/*
        한 Route(선택 세그먼트)로 둔다. 둘로 나뉘어 있으면 `/runs/:id`에서
        `/runs/:id/docs`로 갈 때 페이지가 새로 만들어져, 진행 중이던 AI 설명
        요청 상태(useRunSynthesis, component 안 mutation)가 사라진다.
        주소 모양은 이전과 같다.
      */}
      <Route path="/runs/:jobId/:tab?" element={<RunDetailPage />} />

      {/*
        앱 안의 준비 안내. 파이프라인 실패 메시지가 저장소 문서 경로를
        가리키는 대신 여기로 보낸다 — 웹으로 분석을 제출한 사용자는
        저장소를 열 수 없다.
      */}
      <Route path="/help/setup" element={<SetupGuidePage />} />

      {/*
        평가자 전용 A/B 비교(같은 Run · 두 코드 경로 · 실제 Claude 답변). backend가
        WES_EVAL_COMPARE=1일 때만 데이터를 준다. 꺼져 있으면 화면이 그렇게 말한다.
        모델을 부르지 않는다 — 답변은 승인 후 runner CLI(evals/ab_compare)가 만든다.
      */}
      <Route path="/eval/compare" element={<EvalCompareListPage />} />
      <Route path="/eval/compare/:experimentId" element={<EvalComparePage />} />
      <Route path="/eval/compare/:experimentId/grade" element={<EvalGradePage />} />
    </Routes>
    </AppShell>
  )
}

export default App
