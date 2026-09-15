import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export default function HomePage() {
  return (
    <div className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">유방암 소인 Germline 변이 분석</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Illumina WES 데이터를 업로드하면 BRCA1/2 등 8개 유전자의 변이를 자동 분석합니다.
      </p>
      <Button render={<Link to="/submit" />} className="mt-6">
        분석 시작
      </Button>
    </div>
  )
}
