/**
 * results/registry.tsx
 * ============================================================================
 * 결과 뷰 메타데이터 레지스트리 (현재는 메타 정보만 — 실제 컴포넌트는 미구현)
 *
 * [상태] 백엔드 결과 데이터 스키마가 확정되지 않아, 아직 각 뷰의 실제
 *        컴포넌트(CoverageSummary, VariantTable 등)는 만들지 않았다.
 *        지금은 탭 구조(제목/설명/순서)만 제공한다.
 *
 * [다음 단계] 백엔드가 GET /api/jobs/:id/results/:view 스키마를 확정하면:
 *   1. features/results/views/<Name>.tsx 파일들을 만든다
 *   2. 아래 RESULT_VIEWS 각 항목에 `component: lazy(() => import('./views/<Name>'))` 를 추가한다
 *   3. ResultsPage.tsx 에서 <Component jobId=... /> 로 실제 렌더링하도록 바꾼다
 * ============================================================================
 */

export interface ResultViewMeta {
  id: string
  /** 탭 제목 */
  title: string
  /** 한 줄 설명 */
  description: string
  /** 화면 배치 순서 (작을수록 위) */
  order: number
}

export const RESULT_VIEWS: Record<string, ResultViewMeta> = {
  'coverage-summary': {
    id: 'coverage-summary',
    title: 'Coverage 요약',
    description: '타깃 영역의 평균 depth와 커버리지 분포',
    order: 10,
  },
  'variant-table': {
    id: 'variant-table',
    title: '변이 목록',
    description: '검출된 변이 전체 목록과 주석',
    order: 20,
  },
  'acmg-donut': {
    id: 'acmg-donut',
    title: 'ACMG 분류 분포',
    description: 'Pathogenic / VUS / Benign 5단계 비율',
    order: 30,
  },
  'gene-lollipop': {
    id: 'gene-lollipop',
    title: '유전자별 변이 위치',
    description: '단백질 도메인 상의 변이 분포 (lollipop plot)',
    order: 40,
  },
  'tmb-card': {
    id: 'tmb-card',
    title: 'TMB (종양 변이 부담)',
    description: 'Mb당 비동의 체세포 변이 수',
    order: 30,
  },
  'signature-plot': {
    id: 'signature-plot',
    title: '돌연변이 시그니처',
    description: 'COSMIC SBS 시그니처 기여도',
    order: 50,
  },
  'sv-table': {
    id: 'sv-table',
    title: '구조 변이 (SV)',
    description: '50bp 이상 삽입/결실/역위/전좌',
    order: 25,
  },
}

/** 프로파일의 resultViews 배열을 실제 메타 목록으로 변환 (순서 정렬 포함) */
export function resolveViews(ids: string[]): ResultViewMeta[] {
  return ids
    .map((id) => RESULT_VIEWS[id])
    .filter((v): v is ResultViewMeta => Boolean(v))
    .sort((a, b) => a.order - b.order)
}
