# WES Frontend

WES 분석 파이프라인 Web Frontend (Vite + React + TypeScript).

프로젝트 규칙과 설계 근거는 저장소 루트의 `CLAUDE.md`와
`docs/WES_DESIGN_PLAN.md`를 따릅니다.

## 개발

```bash
npm install
npm run dev        # http://localhost:5173
```

개발 서버는 `/api` 요청을 `http://127.0.0.1:8000`(FastAPI backend)으로 proxy합니다.

## 검증

```bash
npm run typecheck  # tsc -b --force
npm run lint       # oxlint
npm run build      # tsc -b && vite build
```

## 구성

- Vite / React / TypeScript (strict)
- Tailwind CSS v4 (`@tailwindcss/vite`)
- React Router, TanStack Query, Zod
- Base UI, Lucide React, Sonner
- source alias: `@` → `src/`
