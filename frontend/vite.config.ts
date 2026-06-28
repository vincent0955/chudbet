import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/health': API_PROXY_TARGET,
      '/auth': API_PROXY_TARGET,
      '/accounts': API_PROXY_TARGET,
      '/games': API_PROXY_TARGET,
      '/teams': API_PROXY_TARGET,
      '/players': API_PROXY_TARGET,
      '/parlays': API_PROXY_TARGET,
      '/mlb': API_PROXY_TARGET,
    },
  },
})
