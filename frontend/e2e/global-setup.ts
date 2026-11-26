import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

interface SeedIds {
  obra_id: number;
  version_id: number;
  param_def_id: number;
  rev_obra_id: number;
  rev_version_id: number;
  pec_obra_id: number;
  pec_version_id: number;
  pec_param_def_id: number;
  pecrev_obra_id: number;
  pecrev_version_id: number;
  plx_obra_id: number;
  plx_version_id: number;
}

/** Roda o seed das obras de teste (E2E-01 e E2E-REV) e devolve os ids. Também usado
 * pelos testes que precisam do estado inicial de novo (ex.: reconciliação). */
export function runSeed(): SeedIds {
  const backend = resolve(process.cwd(), '../backend');
  const out = execFileSync('uv', ['run', 'python', '-m', 'tests.e2e_seed'], {
    cwd: backend,
    encoding: 'utf-8',
    shell: process.platform === 'win32',
  });
  const lastLine = out.trim().split('\n').at(-1) ?? '{}';
  return JSON.parse(lastLine) as SeedIds;
}

/** Modo padrão: semeia as obras de teste e passa os ids aos testes por variáveis E2E_*. */
export default function globalSetup(): void {
  if (process.env.E2E_REAL_VIEWER) {
    if (!process.env.E2E_OBRA_ID) {
      throw new Error('E2E_REAL_VIEWER=1 exige E2E_OBRA_ID (obra com versão pronta no Docs).');
    }
    return;
  }
  // banco próprio do E2E (DATABASE_URL vem do playwright.config.ts): cria e migra
  execFileSync('uv', ['run', 'python', '-m', 'tests.e2e_db'], {
    cwd: resolve(process.cwd(), '../backend'),
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
  const ids = runSeed();
  process.env.E2E_OBRA_ID = String(ids.obra_id);
  process.env.E2E_VERSION_ID = String(ids.version_id);
  process.env.E2E_PARAM_DEF_ID = String(ids.param_def_id);
  process.env.E2E_REV_OBRA_ID = String(ids.rev_obra_id);
  process.env.E2E_REV_VERSION_ID = String(ids.rev_version_id);
  process.env.E2E_PEC_OBRA_ID = String(ids.pec_obra_id);
  process.env.E2E_PEC_VERSION_ID = String(ids.pec_version_id);
  process.env.E2E_PEC_PARAM_DEF_ID = String(ids.pec_param_def_id);
  process.env.E2E_PECREV_OBRA_ID = String(ids.pecrev_obra_id);
  process.env.E2E_PLX_OBRA_ID = String(ids.plx_obra_id);
  process.env.E2E_PLX_VERSION_ID = String(ids.plx_version_id);
}
