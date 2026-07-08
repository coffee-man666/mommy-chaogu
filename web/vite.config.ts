import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 8080,
    host: '0.0.0.0',
    proxy: {
      '/api': { target: 'http://localhost:8765', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8765', ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'static',
  },
})
