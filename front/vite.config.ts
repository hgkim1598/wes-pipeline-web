import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
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
      // Dev-only proxy to the local FastAPI backend.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
