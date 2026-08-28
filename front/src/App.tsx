import { Route, Routes } from 'react-router'

/*
  foundation이 실제로 적용되는지 확인하기 위한 placeholder다.
  제품 화면이 아니므로 shell / header / navigation / card를 만들지 않는다.
*/
function Placeholder() {
  return (
    <main className="mx-auto max-w-content px-6 py-12">
      <p className="font-cond text-eyebrow font-semibold tracking-wide text-text-muted uppercase">
        WES Analysis · Frontend Foundation
      </p>

      <h1 className="mt-2 text-h1 font-semibold tracking-tight text-text-strong">
        WES Analysis Workspace
      </h1>

      <p className="mt-3 text-body text-text">Frontend foundation ready</p>

      <div className="mt-8 border-t border-border pt-4">
        <p className="text-small text-text-muted">
          디자인 토큰과 전역 base style만 적용된 상태입니다. 화면 구현은 다음
          단계입니다.
        </p>
        <p className="mt-2 font-mono text-data text-text-muted">
          tokens.css · globals.css · Tailwind CSS v4
        </p>
        <a
          href="/"
          className="mt-4 inline-block rounded-sm text-small font-medium"
        >
          포커스 링 확인 (Tab)
        </a>
      </div>
    </main>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Placeholder />} />
    </Routes>
  )
}

export default App
