import { http, HttpResponse, delay } from 'msw'
import { PROFILES } from '@/features/analysis-profile/registry'

type MockStep = { stepId: string; status: string; elapsedSeconds: number; messages: string[] }
type MockJob = { status: string; progress: number; steps: MockStep[] }

const mockJobs = new Map<string, MockJob>()

const STEP_SEQUENCE = [
  '00_input_validation',
  '01_raw_qc',
  '02_preprocessing',
  '03_alignment',
  '04_processing',
  '05_coverage_qc',
  '06_variant_calling',
  '08_filtering',
  '10_annotation',
  '11_intervar',
  '99_finalization',
]

function makeMockJob(jobId: string) {
  mockJobs.set(jobId, {
    status: 'running',
    progress: 0,
    steps: STEP_SEQUENCE.map((stepId, i) => ({
      stepId,
      status: i === 0 ? 'running' : 'pending',
      elapsedSeconds: 0,
      messages: [],
    })),
  })

  let idx = 0
  const timer = setInterval(() => {
    const job = mockJobs.get(jobId)
    if (!job) { clearInterval(timer); return }

    job.steps[idx].status = 'completed'
    job.steps[idx].elapsedSeconds = 20 + idx * 5
    idx++

    if (idx < STEP_SEQUENCE.length) {
      job.steps[idx].status = 'running'
    } else {
      job.status = 'completed_with_warnings'
      clearInterval(timer)
    }

    job.progress = Math.round((idx / STEP_SEQUENCE.length) * 100)
  }, 1500)
}

export const handlers = [
  http.get('/api/profiles', async () => {
    await delay(200)
    return HttpResponse.json(PROFILES)
  }),

  http.post('/api/uploads', async () => {
    await delay(150)
    return HttpResponse.json({
      uploadId: 'mock-upload-' + Date.now(),
      chunkSize: 8 * 1024 * 1024,
    })
  }),

  http.get('/api/uploads/:id', async () => {
    return HttpResponse.json({ receivedChunks: [] })
  }),

  http.put('/api/uploads/:id/:index', async () => {
    await delay(50)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/uploads/:id/complete', async ({ params }) => {
    await delay(300)
    return HttpResponse.json({ path: '/mock/uploads/' + params.id + '.fastq.gz' })
  }),

  http.post('/api/jobs', async () => {
    await delay(300)
    const jobId = 'job-' + Date.now()
    makeMockJob(jobId)
    return HttpResponse.json({ jobId })
  }),

  http.get('/api/jobs/:id', async ({ params }) => {
    const job = mockJobs.get(params.id as string)
    if (!job) return new HttpResponse(null, { status: 404 })
    return HttpResponse.json({ jobId: params.id, status: job.status, progress: job.progress, steps: job.steps })
  }),

  http.post('/api/jobs/:id/cancel', async ({ params }) => {
    const job = mockJobs.get(params.id as string)
    if (job) job.status = 'cancelled'
    return new HttpResponse(null, { status: 204 })
  }),
]
