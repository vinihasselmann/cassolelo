import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import { DEV_HEADERS, PREVIEW_HEADERS } from './security-headers';

// Em dev, /api é repassado ao backend (sem CORS; credenciais APS ficam no backend).
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: apiTarget } },
    headers: DEV_HEADERS, // CSP compatível com o Viewer (10.2)
  },
  preview: {
    proxy: { '/api': { target: apiTarget } },
    headers: PREVIEW_HEADERS, // a mesma CSP de produção
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
