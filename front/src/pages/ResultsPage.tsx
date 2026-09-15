import { useParams, useLocation } from 'react-router-dom'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { resolveViews } from '@/features/results/registry'
import { getProfile } from '@/features/analysis-profile/registry'

export default function ResultsPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const location = useLocation()
  const profileId = (location.state as { profileId?: string } | null)?.profileId
  const profile = profileId ? getProfile(profileId) : undefined

  // profile 정보가 없을 때(새로고침 등)는 백엔드에서 jobId로 profileId를 조회해야 함
  // -> /api/jobs/:id 응답에 profileId를 포함시켜 달라고 백엔드에 요청 필요
  const views = profile ? resolveViews(profile.resultViews) : []

  if (views.length === 0) {
    return (
      <div className="mx-auto max-w-4xl p-8">
        <h1 className="text-xl font-semibold">분석 결과</h1>
        <p className="mt-2 font-mono text-xs text-slate-400">Job ID: {jobId}</p>
        <p className="mt-6 text-sm text-muted-foreground">
          결과 뷰 구성을 불러올 수 없습니다. (프로파일 정보 누락 — 백엔드 연동 후 해결 예정)
        </p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <div>
        <h1 className="text-xl font-semibold">분석 결과</h1>
        <p className="mt-1 font-mono text-xs text-slate-400">Job ID: {jobId}</p>
      </div>

      <Tabs defaultValue={views[0].id}>
        <TabsList>
          {views.map((v) => (
            <TabsTrigger key={v.id} value={v.id}>{v.title}</TabsTrigger>
          ))}
        </TabsList>

        {views.map((v) => (
          <TabsContent key={v.id} value={v.id} className="pt-4">
            <p className="mb-3 text-sm text-muted-foreground">{v.description}</p>
            <div className="rounded-lg border border-dashed border-slate-300 p-8
                            text-center text-sm text-slate-400">
              백엔드 결과 데이터 연동 대기 중
              <br />
              <span className="text-xs">
                필요 API: GET /api/jobs/{'{jobId}'}/results/{v.id}
              </span>
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
