import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5175,
    proxy: {
      '/api/open/llm': process.env.VITE_LLM_API_TARGET || 'http://127.0.0.1:6001',
      '/api': process.env.VITE_API_TARGET || 'http://127.0.0.1:6000'
    }
  }
})
