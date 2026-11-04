import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const DEFAULT_API_TARGET = 'http://127.0.0.1:8000'

/*
  /api proxy가 향할 backend. 기본값은 같은 PC의 backend다.

  Ubuntu VM의 backend를 Windows 브라우저에서 쓰려면, VM 포트 포워딩으로 열린
  host 쪽 주소를 WES_API_PROXY_TARGET에 준다(셸 변수 또는 front/.env.local —
  *.local은 git에 들어가지 않는다). 주소를 코드에 적지 않는다: 포워딩 포트는
  PC마다 다르다.

  잘못된 값은 조용히 기본값으로 돌아가지 않고 dev server 시작을 멈춘다.
  그렇지 않으면 VM에 붙었다고 믿은 채 로컬 backend를 보게 된다.
*/
function apiProxyTarget(mode: string): string {
  const raw = loadEnv(mode, process.cwd(), 'WES_').WES_API_PROXY_TARGET?.trim()
  if (!raw) return DEFAULT_API_TARGET
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    throw new Error(`WES_API_PROXY_TARGET is not a URL: ${raw}`)
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`WES_API_PROXY_TARGET must be http(s): ${raw}`)
  }
  if (url.pathname !== '/' || url.search || url.hash) {
    // /api는 그대로 붙여 보낸다. 경로가 있으면 /x/api/...로 어긋난다.
    throw new Error(`WES_API_PROXY_TARGET must be an origin only (no path): ${raw}`)
  }
  return url.origin
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      /*
        저장소 최상위의 공용 도메인 지식. frontend와 backend가 **같은 파일**을
        읽는다(backend는 app/services/explanation/knowledge.py).
        front/ 아래로 복사하지 않는다 — 사본이 생기면 언젠가 어긋난다.
      */
      '@shared': fileURLToPath(new URL('../config', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    /*
      dev server가 front/ 밖의 파일을 서빙할 수 있게 한다. 기본값은 vite root
      (front/)이고, 위 @shared는 그 바깥이라 허용이 필요하다.
      build에는 영향이 없다 — rollup이 번들에 인라인한다.
    */
    fs: {
      allow: [fileURLToPath(new URL('..', import.meta.url))],
    },
    proxy: {
      // Dev-only proxy. build 산출물에는 영향이 없다(fetch는 상대경로 /api).
      '/api': {
        target: apiProxyTarget(mode),
        changeOrigin: true,
      },
    },
  },
}))
