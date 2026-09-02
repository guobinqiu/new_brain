import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api/open/llm': 'http://llm:6001',
      '/api/open/rag': 'http://rag:6000'
    }
  }
})
