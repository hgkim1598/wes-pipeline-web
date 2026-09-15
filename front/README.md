# WES Frontend

WES(Whole Exome Sequencing, 전장 엑솜 시퀀싱) 분석을 웹에서 실행하기 위한 사용자 화면입니다.
React로 만든 단일 페이지 웹 앱이며, 실제 분석은 하지 않고 Backend에 요청만 보냅니다.

## 역할

사용자가 브라우저에서 다음을 할 수 있습니다.

- 분석 프로필 선택 — 어떤 종류의 분석을 할지 고르는 것 (예: Illumina WES germline)
- FASTQ R1/R2 파일 업로드 — FASTQ는 시퀀싱 장비가 뱉어낸 원시 염기서열 파일입니다. R1/R2는 DNA 한 조각의 양쪽 끝을 읽은 한 쌍입니다
- 분석 옵션 확인 (기본값이 채워져 있어 그대로 실행 가능)
- 분석 시작
- Job 진행 상태 확인 — Job은 "사용자가 요청한 분석 작업 한 건"을 뜻합니다

## 기술 스택

`package-lock.json`에 잠긴 실제 버전입니다.

| 구분 | 버전 |
|---|---|
| React / React DOM | 19.2.8 |
| TypeScript | 6.0.3 |
| Vite | 8.2.0 |
| @vitejs/plugin-react | 6.0.5 |
| react-router-dom | 7.18.2 |
| Tailwind CSS | 4.3.3 |
| react-dropzone | 19.3.0 |
| MSW (Mock Service Worker) | 2.15.0 |
| Node.js | 22 (`.nvmrc`) |

> `@tanstack/react-query`, `zustand`, `react-hook-form`, `zod`, `recharts`도 설치되어 있지만
> 현재 화면 코드에서는 아직 사용하지 않습니다.

## 실행 방법

최초 1회 설치 (`package-lock.json`에 잠긴 버전 그대로 설치합니다):

```bash
cd front
npm ci
```

개발 서버 실행:

```bash
npm run dev
```

접속:

```
http://127.0.0.1:5173
```

기타 명령:

```bash
npm run build     # 타입 검사(tsc -b) 후 프로덕션 빌드
npm run lint      # ESLint
npm run preview   # 빌드 결과 미리보기
```

## Backend 연결

이 앱은 API를 항상 상대 경로(`fetch('/api/...')`)로 호출합니다.
API(Application Programming Interface)는 프론트엔드와 백엔드가 요청과 결과를 주고받는 통신 창구입니다.

`vite.config.ts`의 프록시 설정이 그 요청을 Backend로 넘겨줍니다.

```
브라우저  ──▶  Vite 개발 서버 :5173  ──▶  FastAPI :8000
                   /api/*                   /api/*
```

```ts
// vite.config.ts
server: {
  port: 5173,
  proxy: {
    '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
  },
}
```

따라서 Backend를 먼저 띄워 두어야 합니다 (`backend/README.md` 참고).

## Mock / 실제 Backend 전환

`VITE_USE_MOCK` 환경 변수로 전환합니다.

| 값 | 동작 |
|---|---|
| `false` | 실제 FastAPI Backend를 사용합니다 (Vite 프록시 경유) |
| `true` | MSW가 가짜 API 응답을 돌려줍니다 |

MSW(Mock Service Worker)는 **Backend가 없어도 프론트 화면을 개발할 수 있도록 가짜 API 응답을 제공하는 개발용 도구**입니다.
가짜 응답 코드는 `src/mocks/handlers.ts`에 있으며 삭제하지 않았습니다.

현재 저장소에 커밋된 기본값은 실제 Backend 사용입니다.

```
front/.env.development
VITE_USE_MOCK=false
```

Backend 없이 화면만 만들고 싶다면, `front/.env.local` 파일(git에 올라가지 않음)을 만들고
`VITE_USE_MOCK=true`를 넣으면 기본값을 덮어씁니다.

> 실제 Backend와 연결됐는지 확인하는 방법: Job 화면 주소가 `/jobs/wes-20260813-...` 형태면 실제 Backend,
> `/jobs/job-1760...` 형태면 MSW 가짜 응답입니다.

## 화면 구성

| 경로 | 화면 | 하는 일 |
|---|---|---|
| `/` | HomePage | 서비스 소개, 분석 시작 버튼 |
| `/submit` | SubmitPage | 프로필 선택 → 파일 업로드 → 옵션 → 분석 시작 |
| `/jobs/:jobId` | JobPage | 단계별 진행 상황, 실행 로그, 취소 버튼 |
| `/results/:jobId` | ResultsPage | 결과 화면 (아직 미구현) |

## 현재 실제 동작하는 흐름

```
분석 프로필 선택
   ↓
FASTQ R1/R2 드래그 앤 드롭
   ↓  파일 이름으로 R1/R2와 샘플을 자동으로 짝지음 (src/features/upload/pairDetection.ts)
   ↓
[분석 시작]
   ↓  파일을 8MB 조각(chunk)으로 나눠 순서대로 업로드
   ↓  POST /api/jobs 로 분석 요청
   ↓
JobPage 자동 이동
   ↓  3초마다 상태를 다시 물어봄 (polling)
   ↓
단계별 상태 · 실패 사유 · 실행 로그 표시
```

**Polling**은 일정한 간격으로 Backend에 작업 상태를 다시 물어보는 방식입니다.
`useJobStream`은 먼저 SSE(실시간 스트리밍) 연결을 시도하고, 실패하면 자동으로 polling으로 전환합니다.
현재 Backend는 SSE 주소에 404를 돌려주므로 항상 polling으로 동작합니다.

## 현재 제한

실제 코드 기준입니다.

- **결과 화면은 미구현입니다.** `src/features/results/registry.tsx`에는 탭 제목·설명 같은 메타데이터만 있고 실제 그래프/표 컴포넌트는 없습니다. JobPage의 `[결과 보기]` 버튼을 눌러도 "결과 뷰 구성을 불러올 수 없습니다" 안내만 나옵니다.
- **한 번에 한 샘플만 제출할 수 있습니다.** 화면에서는 여러 샘플을 올릴 수 있지만, 분석 파이프라인이 실행 1건당 생물학적 샘플 1개를 요구하므로 Backend가 400 오류와 함께 이유를 알려줍니다.
- **SSE(실시간 스트리밍)는 사용하지 않습니다.** polling으로만 동작합니다.
- **일부 분석 옵션은 아직 파이프라인에 전달되지 않습니다.** 화면에는 표시되지만 현재 파이프라인 설정에 대응하는 항목이 없는 옵션(`min_base_quality`, `min_read_length`, `min_depth`, `min_gq`, `gnomad_maf_cutoff`, `variant_caller`)은 Backend가 기록만 하고 무시합니다. 실제로 전달되는 것은 capture kit, assembly, ACMG 분류 여부입니다.
- **로그인/인증이 없습니다.** 로컬 개발 환경(127.0.0.1)에서만 사용하세요.
- `test_file/test_R1.fastq.gz`, `test_file/test_R2.fastq.gz`는 **0바이트 빈 파일**이라 업로드 테스트에 사용할 수 없습니다.
- `npm run lint`는 현재 실패합니다 (기존 코드에 남아 있는 규칙 위반 8건). 빌드와 실행에는 영향이 없습니다.
