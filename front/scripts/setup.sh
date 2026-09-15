#!/usr/bin/env bash
# =============================================================================
#  setup.sh — WES 분석 웹 프론트엔드 초기 셋업
#
#  실행: bash setup.sh [프로젝트명]
#  기본 프로젝트명: wes-frontend
#
#  두 명이 각자 로컬에서 이 스크립트를 돌리면 동일한 환경이 만들어진다.
# =============================================================================
set -euo pipefail

PROJECT="${1:-wes-frontend}"

echo "=================================================="
echo "  WES 프론트엔드 셋업: ${PROJECT}"
echo "=================================================="

# ── 0) Node 버전 확인 ────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo "[ERROR] Node.js가 설치되어 있지 않습니다."
  echo "  nvm 설치 후 진행하세요:"
  echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  echo "    source ~/.bashrc && nvm install 20 && nvm use 20"
  exit 1
fi

NODE_MAJOR=$(node -v | sed 's/v\([0-9]*\).*/\1/')
if (( NODE_MAJOR < 18 )); then
  echo "[ERROR] Node 18 이상이 필요합니다 (현재: $(node -v))"
  exit 1
fi
echo "[OK] Node $(node -v)"

# ── 1) Vite + React + TypeScript 프로젝트 생성 ──────────────────────────────
echo ""
echo "[1/6] Vite 프로젝트 생성..."
npm create vite@latest "${PROJECT}" -- --template react-ts
cd "${PROJECT}"

# ── 2) 기본 의존성 ──────────────────────────────────────────────────────────
echo ""
echo "[2/6] 핵심 라이브러리 설치..."
npm install

npm install \
  react-router-dom \
  @tanstack/react-query \
  @tanstack/react-query-devtools \
  zustand \
  react-hook-form \
  zod \
  @hookform/resolvers \
  react-dropzone \
  recharts \
  lucide-react \
  clsx \
  tailwind-merge \
  date-fns

# ── 3) Tailwind CSS ─────────────────────────────────────────────────────────
echo ""
echo "[3/6] Tailwind CSS 설정..."
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

cat > tailwind.config.js <<'TWEOF'
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1.5rem', screens: { '2xl': '1400px' } },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'D2Coding', 'Consolas', 'monospace'],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
TWEOF

npm install -D tailwindcss-animate

# ── 4) 경로 별칭 (@/ → src/) ────────────────────────────────────────────────
echo ""
echo "[4/6] 경로 별칭 설정..."
npm install -D @types/node

cat > vite.config.ts <<'VITEEOF'
import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      // 백엔드(FastAPI)로 프록시 — CORS 설정 없이 개발 가능
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
VITEEOF

# tsconfig 에 paths 추가
python3 - <<'PYEOF'
import json, re, pathlib

for name in ('tsconfig.json', 'tsconfig.app.json'):
    p = pathlib.Path(name)
    if not p.exists():
        continue
    raw = p.read_text()
    # JSON with comments 제거
    clean = re.sub(r'//.*', '', raw)
    clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.S)
    try:
        cfg = json.loads(clean)
    except json.JSONDecodeError:
        continue
    opts = cfg.setdefault('compilerOptions', {})
    opts['baseUrl'] = '.'
    opts['paths'] = {'@/*': ['./src/*']}
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(f'  updated {name}')
PYEOF

# ── 5) shadcn/ui 초기화 + 컴포넌트 설치 ─────────────────────────────────────
echo ""
echo "[5/6] shadcn/ui 설치..."
echo "  (대화형 프롬프트가 나오면: Style=Default, Base color=Slate, CSS variables=Yes)"

npx shadcn@latest init -d || npx shadcn-ui@latest init -d

# 이 프로젝트에서 실제로 쓰는 컴포넌트만 설치
npx shadcn@latest add -y \
  button card select slider switch input label \
  tooltip accordion tabs table badge progress \
  dialog alert separator scroll-area sonner \
  || echo "  [WARN] 일부 컴포넌트 설치 실패 — 개별로 npx shadcn@latest add <name> 실행"

# ── 6) 개발 도구 ────────────────────────────────────────────────────────────
echo ""
echo "[6/6] 개발 도구 설정..."
npm install -D \
  prettier \
  eslint-config-prettier \
  vitest \
  @testing-library/react \
  @testing-library/jest-dom \
  jsdom

cat > .prettierrc <<'PEOF'
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 96,
  "tabWidth": 2
}
PEOF

# 폴더 구조 생성
mkdir -p src/{app,shared/{api,lib,hooks,components/ui},features/{analysis-profile,upload,job,results/views},pages}

# npm scripts 추가
python3 - <<'PYEOF'
import json, pathlib
p = pathlib.Path('package.json')
pkg = json.loads(p.read_text())
pkg['scripts'].update({
    'dev': 'vite',
    'build': 'tsc -b && vite build',
    'preview': 'vite preview',
    'lint': 'eslint .',
    'format': 'prettier --write "src/**/*.{ts,tsx,css}"',
    'test': 'vitest',
})
p.write_text(json.dumps(pkg, indent=2, ensure_ascii=False))
PYEOF

echo ""
echo "=================================================="
echo "  셋업 완료"
echo "=================================================="
echo ""
echo "  cd ${PROJECT}"
echo "  npm run dev        # http://localhost:5173"
echo ""
echo "  다음 단계:"
echo "   1. src/features/ 아래에 제공된 파일들을 복사"
echo "   2. 백엔드를 localhost:8000 에 띄우면 /api 프록시가 연결됨"
echo ""
