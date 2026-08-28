import { Route, Routes } from 'react-router'

function Placeholder() {
  return (
    <main className="min-h-dvh bg-neutral-50 px-6 py-16 text-neutral-900">
      <div className="mx-auto max-w-2xl">
        <h1 className="text-xl font-semibold tracking-tight">
          WES Analysis Workspace
        </h1>
        <p className="mt-2 text-sm text-neutral-600">
          Frontend foundation ready
        </p>
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
