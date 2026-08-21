import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base: '/' en Vercel (raíz) y '/futbol-edge/' en GitHub Pages (subruta).
// Se controla con la variable de entorno BASE_PATH en el build.
// https://vite.dev/config/
export default defineConfig({
  base: process.env.BASE_PATH || '/',
  plugins: [react()],
})
