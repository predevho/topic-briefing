import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // GitHub Pages 프로젝트 사이트는 /<repo>/ 하위에 올라간다.
  // 이 값이 틀리면 JS·CSS 경로가 404가 되어 **빈 화면**이 뜬다.
  base: '/topic-briefing/',

  build: {
    // GitHub Pages가 docs/를 서빙한다.
    outDir: '../docs',

    // **반드시 false다.** docs/에는 .nojekyll, robots.txt, 404.html이
    // 같이 있는데 기본값(true)이면 빌드가 그것들을 지우고 사이트가
    // 조용히 깨진다 — 404.html이 없으면 /2026-11-17 같은 경로가 죽는다.
    emptyOutDir: false,
  },
})
