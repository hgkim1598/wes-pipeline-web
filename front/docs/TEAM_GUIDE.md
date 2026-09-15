# WES 프론트엔드 — 2인 개발 가이드

## 0. 역할 분담 원칙

두 명이 같은 파일을 동시에 만지면 merge conflict로 시간을 다 쓴다.
**수직 분할(vertical slice)** 로 나눈다. 화면 단위로 쪼개면 파일이 거의 겹치지 않는다.

| | A (입력 측) | B (출력 측) |
|---|---|---|
| 담당 화면 | 홈, 분석 선택, 파일 업로드, 옵션 설정, 제출 | 진행 상황, 결과 조회, 리포트 다운로드 |
| 담당 폴더 | `features/analysis-profile/`<br>`features/upload/`<br>`pages/SubmitPage.tsx` | `features/job/`<br>`features/results/`<br>`pages/JobPage.tsx`<br>`pages/ResultsPage.tsx` |
| 핵심 난이도 | 청크 업로드, 동적 폼 | SSE 스트리밍, 차트 |

### 공동 작업 구간 (첫 2~3일)

분할하기 전에 **둘이 같이** 아래를 확정한다. 여기서 합의가 안 되면 나중에 전부 갈아엎어야 한다.

1. `features/analysis-profile/types.ts` — 프로파일/옵션 타입
2. `shared/api/types.ts` — 백엔드 응답 타입
3. `shared/components/ui/` — shadcn 컴포넌트 설치
4. 라우팅 구조 (`app/router.tsx`)

이 4개가 끝나면 각자 자기 폴더에서 독립적으로 작업 가능하다.

---

## 1. 기술 스택과 선정 이유

### 프레임워크: React 18 + Vite 5 + TypeScript

**Vite를 쓰는 이유**
- 개발 서버 기동이 1초 이내. Webpack 기반 CRA는 30초 이상 걸린다
- HMR이 파일 크기와 무관하게 빠르다 (ESM 네이티브)
- CRA는 2023년 공식 지원 중단됨

**Next.js를 안 쓰는 이유**
- SSR/SEO가 필요 없는 내부 분석 도구다
- 작업 상태 폴링 같은 클라이언트 상태가 무거워 SPA가 더 적합
- 러닝커브가 2인 팀에 부담

**TypeScript가 필수인 이유**
- 두 사람이 API 응답 구조를 서로 다르게 가정하면 통합 시점에 터진다
- `shared/api/types.ts` 하나로 계약을 강제한다

### UI: shadcn/ui + Tailwind CSS

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| **shadcn/ui** | 소스가 내 프로젝트에 복사됨, 완전 커스터마이즈, Radix 접근성 | 컴포넌트를 직접 관리 | **채택** |
| MUI | 성숙, 컴포넌트 많음 | 번들 크고 Material 느낌 강함 | 미채택 |
| Mantine | 올인원, DX 좋음 | 디자인 커스터마이즈 제약 | 차선 |
| Chakra | 쉬움 | 대규모에서 성능 이슈 | 미채택 |

ResFinder 같은 과학 도구는 Material Design 느낌이 안 어울린다. shadcn은 라이브러리가 아니라 **코드 복사** 방식이라 원하는 대로 고칠 수 있다.

필요한 컴포넌트가 전부 있다.
- `Tooltip` → 말머리 설명
- `Accordion` → 고급 옵션 접기
- `Slider` → 임계값 스케일바
- `Select` → 분석 유형 선택
- `Progress`, `Table`, `Badge`, `Tabs`

### 상태 관리

| 용도 | 도구 | 이유 |
|---|---|---|
| 서버 상태 | TanStack Query | 캐싱·재시도·폴링을 직접 안 짜도 됨 |
| 클라이언트 상태 | Zustand | Redux 대비 보일러플레이트가 1/10 |
| 폼 상태 | React Hook Form + Zod | 비제어 방식이라 리렌더 적음, 스키마로 검증 |

### 파일 업로드

**react-dropzone** — 드래그앤드롭 + 파일탐색기
**직접 구현한 청크 업로더** — 12GB FASTQ 대응

일반 `FormData` 업로드로는 12GB 파일을 못 보낸다. 브라우저 메모리가 터지거나 nginx `client_max_body_size`에 걸린다.
`useChunkedUpload.ts`가 8MB씩 잘라서 보내고, 끊기면 이어받는다.

### 시각화: Recharts

- React 네이티브 통합 (D3를 직접 다룰 필요 없음)
- 파이/막대/라인 차트로 ACMG 분포, coverage 그래프 커버 가능
- Lollipop plot처럼 특수한 건 SVG를 직접 그리는 게 더 빠르다

---

## 2. 확장성 설계 — 이 프로젝트의 핵심

### 문제

지금은 "Illumina WES germline 유방암" 하나지만, 나중에:
- PacBio HiFi → 입력이 단일 FASTQ, 정렬 도구가 pbmm2
- Somatic → tumor/normal 4개 파일, VAF 슬라이더, TMB 결과
- 다른 패널 → 유전자 목록만 다름

이걸 `if (platform === 'pacbio')` 로 분기하기 시작하면 6개월 뒤 코드가 지옥이 된다.

### 해결: 레지스트리 패턴

```
registry.ts (데이터)          →  화면 컴포넌트 (로직 없음)
─────────────────────────        ────────────────────────
AnalysisProfile[]            →  ProfileSelector      (목록 렌더링)
  .options: OptionField[]    →  DynamicOptionForm    (폼 자동 생성)
  .input.slots[]             →  UploadZone           (슬롯 개수만큼 드롭존)
  .resultViews: string[]     →  ResultsPage          (뷰 조합)
```

**새 분석 추가 = registry.ts 에 객체 하나 추가.**
화면 코드는 한 줄도 안 바뀐다.

### 실제 확인 방법

`registry.ts`에 PacBio와 Somatic 프로파일이 이미 `coming-soon`으로 들어가 있다.
`status`를 `available`로 바꾸기만 하면 UI에 즉시 나타나고, 옵션 폼도 자동 생성된다.

### 백엔드 전환

초기에는 프론트에 하드코딩된 배열을 쓰다가, 백엔드가 준비되면:

```ts
// registry.ts — 이 함수 본문만 교체
export async function fetchProfiles(): Promise<AnalysisProfile[]> {
  return (await fetch('/api/profiles')).json();
}
```

호출부는 수정 불필요. 타입이 같기 때문이다.

---

## 3. 화면 구성 (ResFinder 벤치마킹)

```
┌─────────────────────────────────────────────────────┐
│  헤더 (로고 · 메뉴)                                    │
├─────────────────────────────────────────────────────┤
│  Hero (서비스 한 줄 설명 · 배지)                        │
├─────────────────────────────────────────────────────┤
│  Step 1 ─── Step 2 ─── Step 3 ─── Step 4            │  ← Progress
├──────────┬──────────────────────────────────────────┤
│          │  [분석 선택]                              │
│  사이드바  │    변이유형 · 플랫폼 · 범위 필터            │
│          │    → 프로파일 카드 목록                     │
│  진행상태  │                                          │
│  ✓ 완료   │  [파일 업로드]                            │
│  ● 진행중 │    드래그앤드롭 · R1/R2 자동 감지           │
│  ○ 대기   │                                          │
│          │  [분석 옵션]                              │
│  대상     │    라벨 (?) ─────── [선택]                │
│  유전자   │    슬라이더 ───●─────  20x                │
│  배지     │    ▸ 고급 옵션 (3)                        │
│          │                                          │
│          │  [ 분석 시작 ]                            │
└──────────┴──────────────────────────────────────────┘
```

### ResFinder에서 가져올 것

1. **파라미터 옆 `?` 툴팁** — 초보자도 쓸 수 있게
2. **기본값이 항상 채워져 있음** — 아무것도 안 건드리고 실행 가능
3. **결과가 같은 페이지 아래에 나타남** — 페이지 이동 없이
4. **탭으로 결과 분류** — 요약 / 상세 / 다운로드

### ResFinder보다 개선할 것

1. **작업 큐** — 12GB 업로드 + 5시간 분석이라 페이지를 닫아도 유지돼야 함
2. **진행 상황 실시간 표시** — ResFinder는 그냥 기다리게 함
3. **분석 유형 계층 선택** — ResFinder는 도구가 하나뿐이라 이게 없음

---

## 4. 개발 순서 (제안 4주)

### 1주차 — 공동 작업
- [ ] `setup.sh` 실행, 둘 다 동일 환경 확인
- [ ] `types.ts` 확정 (같이 리뷰)
- [ ] shadcn 컴포넌트 설치
- [ ] 라우팅 뼈대 (`/`, `/submit`, `/jobs/:id`, `/results/:id`)
- [ ] Mock API 만들기 (MSW 또는 단순 JSON) ← **백엔드 없이 개발하기 위해 필수**

### 2주차 — 분할 시작
**A**: ProfileSelector + DynamicOptionForm 완성
**B**: JobPage 뼈대 + StepTimeline + 로그 뷰어

### 3주차
**A**: 업로드 (드롭존 + 청크 업로더 + 페어 감지)
**B**: 결과 뷰 3종 (coverage, variant table, ACMG donut)

### 4주차 — 통합
- [ ] 백엔드 연결
- [ ] 에러 처리 통일
- [ ] 반응형 확인
- [ ] 빌드 최적화

---

## 5. Mock API 먼저 만들기

백엔드가 준비되기 전에 프론트를 개발하려면 mock이 필수다.

```bash
npm install -D msw
npx msw init public/
```

```ts
// src/mocks/handlers.ts
import { http, HttpResponse } from 'msw';
import { PROFILES } from '@/features/analysis-profile/registry';

export const handlers = [
  http.get('/api/profiles', () => HttpResponse.json(PROFILES)),

  http.get('/api/jobs/:id', ({ params }) =>
    HttpResponse.json({
      jobId: params.id,
      status: 'running',
      progress: 45,
      steps: [
        { stepId: '00_input_validation', status: 'completed', elapsedSeconds: 20, messages: [] },
        { stepId: '03_alignment',        status: 'running',   elapsedSeconds: 1200, messages: [] },
      ],
    }),
  ),
];
```

이러면 백엔드 담당자가 API를 만드는 동안 프론트는 계속 진행할 수 있다.

---

## 6. Git 협업 규칙

```bash
# 브랜치 전략 (2인이면 이 정도로 충분)
main            # 배포 가능 상태
  ├─ feat/submit-flow      (A)
  └─ feat/job-results      (B)

# 커밋 컨벤션
feat: 분석 프로파일 선택 UI 추가
fix: R2 파일 자동 감지 실패 수정
refactor: 옵션 폼 스키마 기반으로 전환
docs: 팀 가이드 업데이트
```

**매일 아침 `main`에서 rebase**하면 conflict가 쌓이지 않는다.

```bash
git fetch origin
git rebase origin/main
```

---

## 7. 백엔드에 요청해야 할 API

프론트 개발 전에 백엔드 담당자와 합의할 목록.

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/profiles` | 분석 프로파일 목록 |
| POST | `/api/uploads` | 업로드 세션 생성 → `{uploadId, chunkSize}` |
| GET | `/api/uploads/:id` | 이어받기용 수신 청크 목록 |
| PUT | `/api/uploads/:id/:index` | 청크 전송 |
| POST | `/api/uploads/:id/complete` | 병합 → `{path}` |
| POST | `/api/jobs` | 분석 제출 → `{jobId}` |
| GET | `/api/jobs/:id` | 작업 상태 (폴링용) |
| GET | `/api/jobs/:id/stream` | SSE 실시간 로그 |
| POST | `/api/jobs/:id/cancel` | 작업 취소 |
| GET | `/api/jobs/:id/results/:view` | 결과 뷰별 데이터 |
| GET | `/api/jobs/:id/download/:format` | CSV/PDF 다운로드 |

**SSE 이벤트 형식** (백엔드가 main.sh 로그를 파싱해서 보냄)

```
event: step
data: {"stepId":"03_alignment","status":"running","elapsedSeconds":1200,"messages":[]}

event: log
data: [2026-07-30 10:02:14] START 04_processing

event: status
data: {"status":"completed_with_warnings","progress":100}
```
