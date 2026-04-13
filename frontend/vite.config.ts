import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendUrl = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'
const backendWsUrl = backendUrl.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/ws': {
        target: backendWsUrl,
        ws: true,
      },
    },
  },
})
