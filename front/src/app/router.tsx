import { createBrowserRouter } from 'react-router-dom'
import HomePage from '@/pages/HomePage'
import SubmitPage from '@/pages/SubmitPage'
import JobPage from '@/pages/JobPage'
import ResultsPage from '@/pages/ResultsPage'

export const router = createBrowserRouter([
  { path: '/', element: <HomePage /> },
  { path: '/submit', element: <SubmitPage /> },
  { path: '/jobs/:jobId', element: <JobPage /> },
  { path: '/results/:jobId', element: <ResultsPage /> },
])
