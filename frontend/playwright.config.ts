import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

/**
 * E2E (Playwright). Dois modos:
 *
 * - padrão: pilha real (backend FastAPI + Postgres do `make up` + Vite) com a obra de
 *   teste semeada por `backend/tests/e2e_seed.py` e um Viewer FALSO no lugar do CDN
 *   (roda sem APS).
 * - E2E_REAL_VIEWER=1: Viewer v7 real e APS real; exige E2E_OBRA_ID (obra com versão
 *   pronta) e mede o tempo até o modelo aparecer (limite E2E_MAX_LOAD_MS, padrão 15000).
 *
 * E2E_BASE_URL aponta para um ambiente já no ar (ex.: o servidor da fábrica, para medir
 * na rede real); sem ela, backend e Vite sobem aqui.
 */
const external = process.env.E2E_BASE_URL;
const baseURL = external ?? 'http://127.0.0.1:5174';

/** Valor do ambiente ou de infra/.env (o mesmo que o backend lê). */
function envOrDotenv(name: string): string | undefined {
  if (process.env[name]) return process.env[name];
  try {
    const line = readFileSync(resolve(process.cwd(), '../infra/.env'), 'utf-8')
      .split('\n')
      .find((l) => l.startsWith(`${name}=`));
    return line?.slice(name.length + 1).trim();
  } catch {
    return undefined;
  }
}

/**
 * Modo padrão (pilha local): banco `bim_e2e` e Redis db 1 só do E2E, para que dados
 * criados à mão no banco de dev (ex.: parâmetros globais) não mudem os resultados e o
 * E2E não suje o dev. O global-setup cria/migra o banco; seeds e backend herdam o env.
 * O modo E2E_REAL_VIEWER usa as obras reais do banco de dev.
 */
if (!external && !process.env.E2E_REAL_VIEWER) {
  const db = envOrDotenv('DATABASE_URL');
  if (db) process.env.DATABASE_URL = db.replace(/\/[^/?]+(\?.*)?$/, '/bim_e2e$1');
  const redis = envOrDotenv('REDIS_URL') ?? 'redis://127.0.0.1:6379/0';
  process.env.REDIS_URL = redis.replace(/\/\d+$/, '') + '/1';
}

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    // Tablet na horizontal (o uso principal na fábrica) e desktop.
    { name: 'tablet', use: { ...devices['Galaxy Tab S4 landscape'], defaultBrowserType: 'chromium' } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: external
    ? []
    : [
        {
          command: 'uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001',
          cwd: '../backend',
          url: 'http://127.0.0.1:8001/api/health',
          reuseExistingServer: true,
          timeout: 60_000,
        },
        {
          command: 'npx vite --host 127.0.0.1 --port 5174 --strictPort',
          url: 'http://127.0.0.1:5174',
          env: { VITE_API_TARGET: 'http://127.0.0.1:8001' },
          reuseExistingServer: true,
          timeout: 60_000,
        },
      ],
});
