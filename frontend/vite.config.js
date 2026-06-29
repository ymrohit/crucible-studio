import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Dev server proxies the SSE + compare endpoints to the FastAPI backend on :8000,
// so `npm run dev` (frontend) + `python -m crucible.ui.server` (backend) just work together.
export default defineConfig({
  base: './',
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      '/run_stream': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/compare': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
