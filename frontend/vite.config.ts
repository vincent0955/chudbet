import path from 'node:path'
import type { IncomingMessage } from 'node:http'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

/** Let React Router paths (e.g. /games/101) serve the SPA instead of proxying to FastAPI. */
function bypassApiProxy(req: IncomingMessage) {
  const accept = req.headers.accept ?? ''
  if (accept.includes('text/html')) {
    return req.url
  }
}

const apiProxy = () => ({
  target: API_PROXY_TARGET,
  bypass: bypassApiProxy,
})

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/health': apiProxy(),
      '/auth': apiProxy(),
      '/accounts': apiProxy(),
      '/games': apiProxy(),
      '/teams': apiProxy(),
      '/players': apiProxy(),
      '/parlays': apiProxy(),
      '/mlb': apiProxy(),
    },
  },
})
