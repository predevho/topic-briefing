import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // Vercel은 도메인 **루트**에서 서빙한다.
  //
  // GitHub Pages 프로젝트 사이트를 쓸 때는 '/topic-briefing/'이었고,
  // 그게 틀리면 JS·CSS가 404가 되어 빈 화면이 뜨는 함정이었다.
  // 루트로 오면서 그 함정이 사라진다 — 그리고 호스트 루트가 앱 자체가
  // 되므로 카카오 메시지 하단의 앱 바로가기도 브리핑으로 간다.
  base: '/',

  // outDir을 비워 기본값(web/dist)을 쓴다. Vercel이 푸시를 받고 직접
  // 빌드하므로 산출물을 커밋하지 않는다 — docs/로 내보내고 커밋하던
  // 구조와 emptyOutDir·prebuild 같은 곁가지가 전부 없어진다.
})
