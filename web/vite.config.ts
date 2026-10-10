import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: the React app on :5173 proxies /api to the FastAPI server on :8000.
// Build: `npm run build` writes dist/, which FastAPI serves at / (one command, offline).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
