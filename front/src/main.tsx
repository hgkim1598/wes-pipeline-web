import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './index.css'

/**
 * MSW is opt-in through VITE_USE_MOCK so the same dev server can run against
 * either the mock handlers or the real FastAPI backend.
 *
 *   VITE_USE_MOCK=true   mocks/handlers.ts answers /api/*  (frontend-only work)
 *   VITE_USE_MOCK=false  requests go through the Vite /api proxy to FastAPI
 *
 * .env.development sets false so integration work talks to the real backend.
 * To keep working against mocks, put VITE_USE_MOCK=true in .env.local, which is
 * git-ignored and overrides .env.development.
 */
async function enableMocking() {
  if (import.meta.env.VITE_USE_MOCK !== 'true') return
  const { worker } = await import('./mocks/browser')
  return worker.start({ onUnhandledRequest: 'bypass' })
}

enableMocking().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
