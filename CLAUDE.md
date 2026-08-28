# WES Web Frontend Rebuild

## 1. 프로젝트 목적

이 저장소는 WES(Whole Exome Sequencing) 분석 파이프라인을
웹에서 실행하고 상태·결과·산출물·재현성 정보를 확인하기 위한 프로젝트입니다.

현재 FastAPI Backend와 `script/main.sh` 기반 WES pipeline이 존재합니다.

`frontend-develop` 브랜치에서는 기존 팀 Frontend를 개선하는 것이 아니라,
Frontend를 React + TypeScript 기반으로 처음부터 새로 구축합니다.

이번 재구축의 목표는 다음과 같습니다.

- 실제 Backend/API와 정확하게 연결되는 Frontend
- 긴 WES 분석 작업의 상태를 명확히 전달하는 UX
- 분석 결과와 재현성 정보를 쉽게 탐색할 수 있는 구조
- 바이오인포매틱스 분석 도구다운 차분하고 전문적인 UI
- 향후 결과 모듈과 Report/AI 기능을 확장할 수 있는 구조
- 포트폴리오에서 설계 근거와 구현 구조를 설명할 수 있는 코드베이스


## 2. 반드시 참조할 자료

작업 전 필요한 자료를 먼저 읽습니다.

### 기능 및 UX 설계

- `docs/WES_DESIGN_PLAN.md`
  - 현재 Frontend 정보 구조와 UX 설계의 기준
  - Backend 제약, 화면 구조, 상태 설계, 확장 전략 포함

### 최종 시각 디자인 reference

`docs/design/`은 Claude Design에서 export한 로컬 시각 참고자료입니다.

주요 파일:

- `docs/design/foundation.html`
  - color, typography, spacing, radius, surface 등 디자인 foundation
- `docs/design/components.html`
  - 공통 UI component 시각 기준
- `docs/design/prototype.html`
  - 전체적인 시각 방향과 화면 간 일관성 확인
- `docs/design/pipeline-tab.html`
  - Pipeline 화면 기준
- `docs/design/results-precheck.html`
  - precheck/check_only 결과 화면 기준
- `docs/design/results-full.html`
  - full 결과 화면의 시각 reference
- `docs/design/wizard.html`
  - New Analysis wizard 기준
- `docs/design/remaining-screens.html`
  - 나머지 화면과 상태 기준
- `docs/design/support.js`
  - export된 디자인 지원 파일

### archive

`docs/design/archive/`는 최종 선택 이전의 비교·실험 시안입니다.

새 구현의 디자인 기준으로 사용하지 않습니다.

최종 디자인과 충돌하면 항상 archive가 아닌
`docs/design/` 최상위의 최종 파일을 사용합니다.


## 3. 근거 우선순위

자료 간 내용이 충돌하면 다음 순서를 따릅니다.

1. 현재 Backend / pipeline의 실제 코드와 API 계약
2. `docs/WES_DESIGN_PLAN.md`
3. `docs/design/`의 최종 Claude Design 시안
4. 일반적인 구현 관례

중요:

`docs/design/*.html`은 시각적 reference이지
프로덕션 구현 코드가 아닙니다.

따라서:

- HTML DOM을 그대로 React로 복사하지 않습니다.
- HTML CSS 전체를 복사하지 않습니다.
- HTML 안의 mock 값을 실제 Backend 데이터라고 가정하지 않습니다.
- HTML에 존재하는 interaction을 실제 Backend 기능이라고 가정하지 않습니다.
- React component 구조와 application architecture는 새로 설계합니다.
- Backend가 지원하지 않는 기능은 디자인에 보이더라도 실제 기능처럼 구현하지 않습니다.


## 4. 기존 팀 Frontend에 대한 원칙

이 브랜치는 기존 팀 Frontend의 리팩터링 작업이 아닙니다.

`khg` 브랜치에 존재했던 기존 `front/` 구현은
새 Frontend의 구현 참고자료로 사용하지 않습니다.

다음 행위를 하지 않습니다.

- 기존 React component 복사
- 기존 CSS 복사
- 기존 upload hook 복사
- 기존 utility 복사
- 기존 registry 복사
- 기존 화면 구조를 유지하려는 구현
- Git history에서 과거 Frontend 코드를 찾아 재사용
- 과거 Frontend 구현을 기준으로 새로운 구조를 결정

새 Frontend가 이어받는 것은 다음뿐입니다.

- 현재 Backend API contract
- 현재 WES pipeline contract
- 현재 config / capture-kit 구조
- 프로젝트의 분석 도메인 의미

Frontend 구현은 완전히 새로 작성합니다.


## 5. Frontend 기술 스택

새 Frontend는 `front/` 아래에 구축합니다.

기본 기술 스택:

- Vite
- React
- TypeScript
- React Router
- TanStack Query
- Zod
- Tailwind CSS v4
- Base UI (`@base-ui/react`)
- Lucide React
- Sonner

테스트:

- Vitest
- Testing Library
- MSW

원칙:

- 서버 상태는 TanStack Query로 관리합니다.
- 단순 UI state는 React local state를 우선합니다.
- 명확한 필요가 확인되기 전에는 별도 global state library를 추가하지 않습니다.
- 새로운 dependency는 필요성을 설명할 수 있을 때만 추가합니다.
- 이미 정한 기술을 다른 library로 임의 교체하지 않습니다.


## 6. 개발 서버 기본 계약

Frontend 개발 서버:

- port: `5173`

Backend:

- `http://127.0.0.1:8000`

개발 환경에서는:

- `/api`
  → `http://127.0.0.1:8000`

으로 proxy합니다.

Frontend source alias:

- `@`
  → `src/`


## 7. 현재 Backend에서 실제 지원하는 API

현재 코드에 존재하는 기능만 실제 기능으로 취급합니다.

### Health

- `GET /api/health`

### Upload

- `POST /api/uploads`
- `GET /api/uploads/{upload_id}`
- `PUT /api/uploads/{upload_id}/{chunk_index}`
- `POST /api/uploads/{upload_id}/complete`

### Job

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`

### Results

- `GET /api/jobs/{job_id}/results`

### Artifacts

- `GET /api/jobs/{job_id}/artifacts`
- `GET /api/jobs/{job_id}/artifacts/{file_id}/download`

### Step detail

- `GET /api/jobs/{job_id}/steps/{step_id}`

### SSE

다음 endpoint는 route 자체는 존재하지만
실제 streaming API가 아닙니다.

- `GET /api/jobs/{job_id}/stream`
  → 현재 의도적으로 404

따라서 현재 Frontend에서는 SSE를 구현하지 않습니다.

### 현재 없는 API

현재 다음 기능은 Backend API가 없습니다.

- `GET /api/jobs` 형태의 전체 Job 목록 API

Backend에 없는 API를 있다고 가정해서 구현하지 않습니다.


## 8. 현재 Web 입력 계약

현재 Web Backend의 실제 입력 단위는:

**one biological sample + one paired R1/R2**

입니다.

즉:

- sample 1개
- R1 FASTQ 1개
- R2 FASTQ 1개

만 제출합니다.

현재 Web UI에서 다음 기능을 만들지 않습니다.

- multi-sample submission
- multi-lane submission
- 한 sample에 여러 R1/R2 pair 등록

pipeline 내부의 일반적인 lane 처리 가능성과
현재 Web Backend의 입력 계약을 혼동하지 않습니다.


## 9. FASTQ 계약

현재 Backend가 허용하는 확장자는:

- `.fastq.gz`
- `.fq.gz`

입니다.

다음 확장자는 현재 Web upload UI에서 허용하지 않습니다.

- `.fastq`
- `.fq`

gzip 압축 FASTQ만 허용합니다.


## 10. Profile 관련 제약

`profileId`는 Job 정보에 저장될 수 있지만,
현재 Backend에서 profile별 gene list가 pipeline 실행을 변경하는 구조는 확인되지 않았습니다.

따라서 다음과 같은 표현을 사용하지 않습니다.

- "BRCA1/2만 분석"
- "유방암 8개 유전자 분석"
- 특정 profile을 선택하면 특정 gene만 분석된다는 설명

현재 실제 분석 기능은 일반적인:

**Illumina WES Germline variant analysis**

범위로 표현합니다.

Backend 동작이 실제로 추가되기 전에는
profile metadata를 분석 기능처럼 과장하지 않습니다.


## 11. Capture kit / ACMG / InterVar

현재 Web submission에서 Backend에 의미 있게 전달되는 주요 설정은:

- capture kit
- `run_acmg`

입니다.

단:

`run_acmg=true`라고 해서 항상 InterVar가 실행되는 것은 아닙니다.

서버에 필요한 InterVar 설정이 없으면
Backend가 이를 `unsupportedOptions`에 기록할 수 있습니다.

따라서 Frontend는 서버 capability를 확인하지 못한 상태에서
ACMG/InterVar가 반드시 지원된다고 표현하지 않습니다.

Backend가 반환하는 실제 상태를 기준으로 UI를 구성합니다.


## 12. Run mode

Backend의 `WES_RUN_MODE`는:

- `check_only`
- `full`

을 사용합니다.

기본값은 현재 `check_only`입니다.

### check_only

환경·입력·reference 등을 확인하는 precheck 중심 실행입니다.

분석 산출물이 생성되지 않을 수 있습니다.

### full

전체 WES pipeline 실행 모드입니다.

중요:

현재 프로젝트에서 full WES 성공 실행 전체가 검증됐다고 가정하지 않습니다.

실제 검증되지 않은 BAM / VCF / coverage / annotation 결과를
제품의 실제 결과처럼 표시하지 않습니다.


## 13. Job 상태와 polling

현재 SSE가 없으므로 Job 상태는 polling으로 확인합니다.

기본 polling interval:

- 3초

terminal 상태에 도달하면 polling을 중단합니다.

terminal 상태 예:

- `completed`
- `completed_with_warnings`
- `failed`
- `cancelled`

Backend의 실제 enum/schema를 확인하고 최종 코드를 작성합니다.

`progress`는 실제 시간 기반 진행률이 아닙니다.

현재 progress의 의미는 계획된 pipeline step 중
완료된 단계 비율에 가깝습니다.

따라서 다음을 만들지 않습니다.

- 가짜 ETA
- 단계 내부의 가짜 %
- 시간 기반이라고 오해하게 만드는 progress
- 근거 없는 "몇 분 남음"

사용자가 실제로 알 수 있는 정보만 표시합니다.


## 14. Results 응답 처리

`/results`는 실행 상태에 따라 아직 제공할 수 없을 경우
409를 반환할 수 있습니다.

이 경우:

- 결과가 0개라고 표현하지 않습니다.
- `artifactCount = 0`이라고 임의 표시하지 않습니다.
- 아직 준비되지 않은 상태와 실제 0을 구분합니다.

실행 중 artifact 개수는 가능한 경우 `/artifacts` 응답을 기준으로 표시합니다.

데이터가 아직 준비되지 않았으면:

- `—`
- "준비 중"

등의 표현을 사용합니다.


## 15. Artifact 관련 규칙

Artifacts는 실제 Backend 응답을 기준으로 표시합니다.

`manifestConsistent: false` 자체만으로
사용자에게 오류 또는 경고를 표시하지 않습니다.

현재 pipeline 구조에서는 finalization과 manifest 등록 순서 때문에
이 값이 구조적으로 false가 될 수 있습니다.

반면:

- `suppressedCount > 0`

과 같이 실제 누락/억제 artifact를 의미하는 정보는
필요한 경우 사용자에게 명확히 표시합니다.


## 16. API contract와 Zod

모든 JSON API 응답은 사용 전에 Zod로 파싱합니다.

권장 흐름:

Backend response
→ Zod schema
→ parsed data
→ TypeScript type
→ React component

가능하면 TypeScript type은 Zod schema에서 추론합니다.

예:

```ts
export type Job = z.infer<typeof JobSchema>;
```

API 응답 parsing 실패는 조용히 무시하지 않습니다.

사용자 또는 개발자가 문제를 알 수 있도록
정규화된 error state로 표면화합니다.


## 17. TypeScript 규칙

TypeScript strict mode를 사용합니다.

다음 방식으로 type error를 숨기지 않습니다.

- `any`
- `as any`
- `@ts-ignore`
- `@ts-expect-error`

예외가 정말 필요하면 이유를 먼저 설명하고
명시적인 승인을 받은 뒤 사용합니다.

타입 오류는 우회하지 않고:

- API schema
- domain type
- nullable/optional 처리
- component props

중 무엇이 잘못됐는지 확인해서 수정합니다.

불필요한 type assertion도 최소화합니다.


## 18. Registry 기반 확장 구조

Pipeline step, Result section, Artifact category처럼
도메인 종류가 늘어날 수 있는 구조는 registry를 사용합니다.

예상 registry:

- `registries/steps.ts`
- `registries/resultSections.tsx`
- `registries/artifactCategories.ts`
- 필요 시 `registries/profiles.ts`

### Step

step label / description / category / ordering 등은
Step Registry에서 관리합니다.

registry 외부에서 step ID 문자열을 반복하지 않습니다.

금지 예:

```ts
if (stepId === "03_alignment") {
  ...
}
```

이런 분기는 registry 기반 metadata 또는 renderer mapping으로 해결합니다.

### Result

Results page에 결과 section JSX를 직접 나열하지 않습니다.

Result Section Registry를 순회해 렌더링하는 구조를 사용합니다.

### Artifact

알 수 없는 artifact category도 화면이 깨지지 않도록
`other` fallback을 제공합니다.


## 19. Canonical domain model

향후 다음 소비자가 생길 수 있습니다.

- Web Results
- Report
- AI / RAG
- API clients

이들이 동일한 분석 의미를 공유하도록
canonical domain model / section contract를 유지합니다.

단:

모든 데이터를 하나의 거대한 `/results` response에
강제로 넣는 구조를 만들지 않습니다.

데이터 규모와 용도에 따라 향후:

- summary
- detail
- paginated endpoint
- artifact endpoint

로 나뉠 수 있습니다.


## 20. Local storage 사용

Backend에는 현재 전체 Job list API가 없습니다.

필요한 local history는 브라우저 localStorage를 사용할 수 있습니다.

localStorage 접근은 지정된 utility/module 안으로 제한합니다.

예:

- `lib/runHistory.ts`
- `lib/uploadSession.ts`

React component 안에서 직접 localStorage를 여기저기 호출하지 않습니다.


## 21. Mock / Fixture 규칙

Backend에서 아직 제공하지 않는 화면 상태를
디자인 확인이나 개발 테스트 목적으로 만들 수 있습니다.

이 경우 mock은 반드시 명확하게 격리합니다.

예:

- `src/mocks/fixtures/`

실제 component 안에 임의 숫자나 fake domain data를 직접 넣지 않습니다.

Mock 결과를 실제 분석 결과처럼 표현하지 않습니다.

특히 다음은 실제 검증 없이 제품 데이터로 만들지 않습니다.

- variant count
- coverage value
- BAM/VCF 생성 성공
- ACMG result
- pathogenic variant
- gene-specific result
- benchmark result


## 22. Design 원칙

이 제품은 SaaS marketing dashboard가 아니라
바이오인포매틱스 분석 도구입니다.

시각 방향:

- clean
- precise
- scientific
- calm
- data-dense but readable
- professional genomics workstation

장식보다 다음을 우선합니다.

- 정보 위계
- 현재 분석 상태
- 문제 원인
- 다음 행동
- 결과 해석 가능성
- 재현성 정보


## 23. 디자인 금지 사항

다음 패턴을 사용하지 않습니다.

- 카드 한쪽의 두꺼운 accent border / left rail
- 의미 없는 card shadow
- glow
- gradient
- 과도하게 둥근 SaaS-style card
- DNA / 현미경 / 염기서열 등의 장식 이미지
- 장식용 chart
- 의미 없는 KPI card
- donut chart
- gauge chart
- pie chart
- 자동 재생 장식 animation
- 반복 scanline animation
- 과도한 skeleton animation
- viridis를 UI shell 색상으로 사용
- 성공 축하 UI
- emoji 기반 상태 표현
- 마케팅 문구
- "혁신적인"
- "강력한"
- "Explore"
- 근거 없는 AI 기능 표현


## 24. 상태성 메시지 디자인

상태 card / alert / callout의 기본 방향:

- 아주 옅은 semantic tint background
- 1px subtle border
- 명확한 status icon
- 제목
- 짧은 설명
- 필요한 경우 action

두꺼운 왼쪽 세로 accent bar로 상태를 표현하지 않습니다.

상태는 색 하나에만 의존하지 않습니다.

항상 가능한 경우:

- icon
- text
- color

를 함께 사용합니다.


## 25. 색상 사용

UI shell은 neutral surface 중심으로 구성합니다.

Brand color는 절제해서 사용합니다.

Semantic color는 의미가 있을 때만 사용합니다.

예:

- info
- running
- success
- warning
- failure
- cancelled

Coverage visualization처럼 순서형 수치 데이터에는
필요한 경우 viridis 계열을 사용할 수 있습니다.

단, viridis는 일반 버튼·카드·navigation 등
UI decoration에 사용하지 않습니다.


## 26. Card / Surface

기본 surface는 다음을 우선합니다.

- neutral background
- subtle border
- spacing
- typography hierarchy

Card shadow로 계층을 만들지 않습니다.

Overlay, modal처럼 실제 elevation이 필요한 경우에만
제한적으로 shadow를 사용할 수 있습니다.


## 27. Accessibility

최소한 다음을 지킵니다.

### Contrast

일반 텍스트:

- 실제 배경 기준 최소 4.5:1

### Status

색만으로 상태를 표현하지 않습니다.

- icon
- text
- color

를 함께 사용합니다.

### Focus

keyboard focus가 명확하게 보여야 합니다.

`outline: none`으로 focus indicator를 제거하지 않습니다.

기본 방향:

- 2px brand focus ring
- 적절한 offset

### Target size

실제 interactive target이
가능하면 최소 24×24 CSS px 이상이 되도록 합니다.

행 높이나 주변 container 크기로
target size 충족을 대신 주장하지 않습니다.

### Motion

`prefers-reduced-motion: reduce`를 존중합니다.

불필요한 continuous animation은 애초에 만들지 않습니다.


## 28. Error UX

Error message는 단순 error code가 아니라
사용자가 복구할 수 있는 정보여야 합니다.

가능한 경우 다음을 제공합니다.

- 무엇이 잘못됐는지
- 왜 문제가 되는지
- 사용자가 무엇을 하면 되는지

Form validation에서는:

- 상단 error summary
- 문제 field 근처 inline error

를 함께 사용할 수 있습니다.

Backend raw error가 필요한 경우
사용자 메시지와 기술 상세를 구분합니다.


## 29. Loading / Long-running UX

WES 분석은 오래 걸릴 수 있습니다.

사용자에게 다음을 보여주는 것을 우선합니다.

- 현재 상태
- 현재 pipeline step
- 완료된 step
- 남은 step
- warning / failure
- 최근 log
- available artifact

Backend가 제공하지 않는 정보는 만들지 않습니다.

특히 가짜 ETA를 만들지 않습니다.


## 30. 개발 구조 원칙

새 코드는 역할별로 분리합니다.

예상 방향:

```text
front/src/
  api/
  registries/
  ui/
  components/
  features/
  pages/
  lib/
  mocks/
  styles/
```

단, 폴더를 미리 대량 생성하지 않습니다.

실제로 필요한 단계에서 필요한 구조만 추가합니다.

추상화는 실제 중복이나 확장 지점이 확인될 때 만듭니다.

과도한 abstraction을 피합니다.


## 31. 작업 방식

한 번에 전체 Frontend를 만들지 않습니다.

작업은 작은 단계로 나눕니다.

예:

1. Vite + React + TypeScript scaffold
2. 개발 환경 및 design token
3. API contract / Zod
4. registry
5. 공통 UI
6. app shell / routing
7. Run Overview
8. Pipeline
9. Results
10. Files
11. Reproducibility
12. New Analysis wizard
13. Run history
14. responsive / accessibility / polish

현재 요청받은 범위를 넘어
다음 단계까지 임의로 구현하지 않습니다.


## 32. 수정 전 원칙

기존 파일을 수정할 때는 먼저 읽습니다.

다음 내용을 확인합니다.

- 현재 역할
- 사용 위치
- dependency
- API contract
- design reference
- 변경 영향 범위

추측으로 파일을 덮어쓰지 않습니다.


## 33. 작업 후 검증

Frontend 구현 작업 후 가능한 범위에서 다음을 실행합니다.

```bash
npx tsc --noEmit
npm run build
```

test가 구성된 이후에는 관련 test도 실행합니다.

오류가 발생하면:

- 오류를 숨기지 않습니다.
- config를 느슨하게 바꿔 통과시키지 않습니다.
- type safety를 낮추지 않습니다.
- 원인을 확인해 수정합니다.


## 34. 시각 검증

Build 성공만으로 작업 완료라고 판단하지 않습니다.

UI 작업에서는 실제 browser rendering을 확인하고
해당 `docs/design/*.html` reference와 비교합니다.

점검 항목:

- layout
- alignment
- spacing
- typography hierarchy
- density
- border
- radius
- semantic color
- responsive behavior
- focus state
- empty/loading/error state

Reference와 다를 경우
왜 다른지 설명할 수 있어야 합니다.


## 35. 현재 구현하지 않을 것

Backend가 지원하기 전까지 다음을 실제 기능처럼 만들지 않습니다.

- authentication / login
- account / permission UI
- real SSE
- queue position
- fake ETA
- multi-sample submission
- multi-lane Web submission
- gene-specific analysis profile
- clinical diagnosis
- 검증되지 않은 variant interpretation
- fake report generation
- fake AI assistant
- fake RAG
- fake benchmark
- fake IGV integration
- fake full WES result

향후 기능을 위한 구조적 확장성은 열어둘 수 있지만,
disabled card나 fake data로 미리 화면을 채우지 않습니다.


## 36. RUO 원칙

이 프로젝트는 Research Use Only 관점의 분석 도구입니다.

UI와 문구에서 임상 진단을 암시하지 않습니다.

ACMG/InterVar 결과가 향후 표시되더라도
자동 판정이 최종 임상 판단을 대체하는 것처럼 표현하지 않습니다.


## 37. 가장 중요한 원칙

기능을 만들어내지 않습니다.

Backend가 주는 사실을 정확하게 보여주고,
사용자가 현재 분석이 어디까지 진행됐는지,
결과를 얼마나 신뢰할 수 있는지,
무엇을 확인해야 하는지를 이해하도록 돕는 Frontend를 만듭니다.