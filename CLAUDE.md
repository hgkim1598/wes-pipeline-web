# WES 분석 웹 — 프론트엔드

## 프로젝트 개요
WES(전장 엑솜 시퀀싱) 분석 웹 도구입니다.
백엔드(FastAPI)와 분석 파이프라인(script/main.sh)은 이미 존재합니다.
프론트엔드만 새 브랜치에서 처음부터 작성합니다.

## 필수 참조 문서
작업 전 반드시 읽으세요.

- `docs/DESIGN_PLAN.md` — 설계 계획서.
  특히 1장(확정 사실)과 15장(하지 않을 것)
- `docs/design/prototype.html` — **최종 통합 프로토타입.
  구현의 기준이 되는 파일입니다.**
  라우팅·인터랙션·반응형이 모두 구현되어 있습니다.
- `docs/design/foundation.html` — 디자인 토큰 원본.
  :root의 CSS 변수를 여기서 그대로 가져옵니다.
- `docs/design/components.html` — 컴포넌트 카탈로그.
  StatusBadge, RunTape, MessageBlock, EmptyState,
  SectionHeader, CopyableId의 모든 변형이 있습니다.

화면별 상세가 필요하면 아래를 참조하세요.
- `docs/design/pipeline-tab.html`
- `docs/design/results-precheck.html`
- `docs/design/results-full.html`
- `docs/design/wizard.html`
- `docs/design/remaining-screens.html`

`docs/design/archive/` 는 선택이 끝난 비교 시안입니다. 참조하지 마세요.

## 기술 스택 (변경 금지)
- Vite + React + TypeScript
- react-router (createBrowserRouter, 중첩 라우트)
- TanStack Query (서버 상태, 3초 폴링)
- zod (API 응답 파싱)
- Tailwind CSS v4 (@theme으로 토큰 선언)
- Base UI (@base-ui/react) 위에 자체 프리미티브
- lucide-react (아이콘), sonner (토스트)
- 차트 라이브러리 없음. 폼 라이브러리 없음. 전역 상태 라이브러리 없음

개발 서버 포트는 5173 고정. 백엔드 CORS가 이 포트로 설정돼 있습니다.
`/api` 요청은 http://127.0.0.1:8000 으로 프록시합니다.

## 백엔드 제약 (매우 중요)
아래는 코드 조사로 확인된 사실입니다. UI가 이 범위를 넘으면 안 됩니다.

- 입력은 **샘플 1개 + paired-end FASTQ 한 쌍(R1/R2)**뿐입니다.
  lane을 여러 개 제출하는 경로가 없습니다.
- `.fastq.gz` / `.fq.gz`만 허용합니다.
- 기본 실행 모드가 `check_only`입니다.
  이 모드에서는 분석 산출물이 생성되지 않습니다.
- SSE가 없습니다. `GET /api/jobs/{id}/stream`은 항상 404입니다.
  3초 폴링만 씁니다.
- `progress`는 완료단계수 ÷ 계획단계수입니다. 시간 기반이 아닙니다.
  단계 안의 진행률은 존재하지 않습니다.
- 로그는 `pipeline.log` 마지막 200줄뿐입니다.
  전체 다운로드 기능을 만들지 마세요.
- 실행 목록 API(`GET /api/jobs`)가 없습니다. 로컬 저장으로 대체합니다.
- 프로파일의 gene list는 파이프라인에 전달되지 않습니다.
  "특정 유전자만 분석한다"는 표현을 쓰지 마세요.
- 조작 가능한 옵션은 capture kit과 ACMG 토글 2개뿐입니다.
  나머지 6개는 백엔드가 무시하고 `unsupportedOptions`에 기록만 합니다.
- 인증이 없습니다. 로그인·계정·권한 UI를 만들지 마세요.
- 대기열 순번, 앞선 실행 정보를 백엔드가 주지 않습니다.
- `--resume`을 백엔드가 전달하지 않습니다. 재시도 기능 대신
  "같은 설정으로 다시 제출"을 씁니다.

## 코드 규칙
1. 모든 API 응답은 zod로 파싱한 뒤 사용합니다.
   파싱 실패는 UI로 표면화합니다.
2. `registries/` 밖에서 `step_id` 문자열 리터럴을 쓰지 않습니다.
   `if (stepId === '03_alignment')` 같은 분기 금지.
3. 결과 섹션은 `registries/resultSections.tsx`를 순회해 렌더링합니다.
   `ResultsView.tsx`에 섹션 JSX를 나열하지 않습니다.
4. 예시 데이터는 `src/mocks/fixtures/`에만 둡니다.
   컴포넌트나 JSX에 숫자를 쓰지 않습니다.
5. 색·간격·반경은 `styles/tokens.css`의 CSS 변수만 씁니다. 하드코딩 금지.
6. 폰트 패밀리는 `var(--font-sans)` 등으로만 참조합니다. 직접 선언 금지.
7. localStorage 접근은 `lib/runHistory.ts`, `lib/uploadSession.ts`에만 둡니다.
8. terminal 상태(completed / completed_with_warnings / failed / cancelled)에
   도달하면 폴링을 중단합니다(`refetchInterval: false`).
9. `/results`가 409를 반환할 때 `artifactCount`를 0으로 표시하지 않습니다.
   "—"로 표시합니다. 실행 중 산출물 개수는 `/artifacts`에서 가져옵니다.

## 디자인 기준
시각적 판단이 필요할 때는 추측하지 말고
`docs/design/prototype.html` 을 읽고 그대로 따르세요.
색·간격·반경·폰트를 새로 정하지 마세요.

금지 사항
- 좌측 세로 accent bar (모든 컴포넌트)
- 카드 그림자 (오버레이 제외)
- 도넛·게이지·파이 차트
- 자동 재생 장식 애니메이션
  ※ 허용: RunTape 현재 단계 표시, 업로드 스피너,
    진행률 바 트랜지션, 드로어 슬라이드, chevron 회전
- 그라데이션
- 4px / 8px / pill 외의 반경
- viridis 색을 UI 껍데기에 사용
- 성공 축하 톤·이모지
- DNA·현미경 등 도메인 장식
- 마케팅 어휘 ("강력한", "혁신적인", "Explore" 등)

접근성
- 텍스트 대비 4.5:1 (실제 배경 기준)
- 상태는 아이콘 + 텍스트 + 색 3중
- 포커스 링 2px `--brand-600` + 2px offset. `outline: none` 금지
- 모든 조작 요소 히트 영역 24×24 이상 또는 24px 간격
- `prefers-reduced-motion: reduce`에서 모든 모션 정지
- 숫자는 `font-variant-numeric: tabular-nums`

## 작업 방식
- 한 번에 한 단계씩 작업합니다. 지시받지 않은 파일을 만들지 마세요.
- 작업 후 `npm run build`와 `npx tsc --noEmit`으로 검증하세요.
- 기존 파일을 수정할 때는 먼저 읽고, 규칙 위반이 없는지 확인하세요.
- `front-legacy/`는 기존 코드입니다. 참조만 하고 수정하지 마세요.