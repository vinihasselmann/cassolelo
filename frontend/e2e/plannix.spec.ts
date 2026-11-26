import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

import { runSeed } from './global-setup';

/**
 * Importar a planilha do Plannix (2026-11-24), na pilha real: obra E2E-PLX (P-06 com 6
 * pilares, V-02 com 2 vigas), planilha de backend/tests/e2e_plannix_xlsx.py. Prévia,
 * aplicar, datas só leitura na tabela de peças e Desfazer pelo aviso.
 */

const REAL = Boolean(process.env.E2E_REAL_VIEWER);
const FAKE_VIEWER = resolve(process.cwd(), 'e2e/fake-viewer/viewer3D.js');
const PIECES = [10, 11, 12, 13, 14, 15, 20, 21];

/** Gera a planilha do Plannix (Python + openpyxl, como a exportação real). */
function plannixFile(file: string): void {
  const q = (a: string) => (process.platform === 'win32' ? `"${a}"` : a);
  execFileSync('uv', ['run', 'python', '-m', 'tests.e2e_plannix_xlsx', q(file)], {
    cwd: resolve(process.cwd(), '../backend'),
    encoding: 'utf-8',
    shell: process.platform === 'win32',
  });
}

async function fabHeaders(page: Page): Promise<Record<string, string>> {
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
  return { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
}

interface Units {
  params: { def_id: number; name: string; source?: string }[];
  units: { number: number; plannix_code?: string | null; values: { def_id: number; value: unknown }[] }[];
}

/** Unidades da P-06 pela API. */
async function p06(page: Page, obra: string, version: string): Promise<Units> {
  const headers = await fabHeaders(page);
  const marks = (await (await page.request.get(`/api/versions/${version}/marks`, { headers })).json()) as {
    mark_id: number;
    code: string;
  }[];
  const markId = marks.find((m) => m.code === 'P-06')?.mark_id ?? 0;
  return (await (await page.request.get(`/api/obras/${obra}/marks/${String(markId)}/units`, { headers })).json()) as Units;
}

test.beforeEach(async ({ page }) => {
  if (REAL) return;
  await page.route('https://developer.api.autodesk.com/modelderivative/v2/viewers/**', (route) =>
    route.request().url().endsWith('viewer3D.min.js')
      ? route.fulfill({ path: FAKE_VIEWER, contentType: 'application/javascript' })
      : route.fulfill({ body: '', contentType: 'text/css' }),
  );
  await page.route('**/api/viewer-token', (route) =>
    route.fulfill({ json: { access_token: 'E2E', token_type: 'Bearer', expires_in: 600, region: 'US' } }),
  );
  await page.addInitScript((pieces) => {
    (window as unknown as { __E2E_PIECES: unknown }).__E2E_PIECES = pieces;
  }, PIECES.map((dbid) => ({ dbid, label: `Peça ${String(dbid)}` })));
});

test('Importar Plannix: liga as peças, grava as datas só leitura e desfaz', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  test.setTimeout(120_000);
  // estado zerado a cada projeto (tablet e desktop): sem Códigos, valores nem inclusões
  const ids = runSeed();
  const obra = String(ids.plx_obra_id);
  const version = String(ids.plx_version_id);
  testInfo.annotations.push({ type: 'obra', description: `E2E-PLX ${obra}` });
  const file = testInfo.outputPath('plannix.xlsx');
  plannixFile(file);

  await page.goto('/obras');
  const sel = page.getByLabel('Usuário (simulado)');
  await sel.selectOption((await sel.locator('option', { hasText: '(Fábrica)' }).first().getAttribute('value')) ?? '');
  await page.locator(`a[href="/obras/${obra}"]`).first().click();
  await page.getByRole('link', { name: 'Abrir modelo 3D' }).click();
  await expect(page.locator('[data-load="ready"]')).toBeVisible({ timeout: 15_000 });
  // 1ª abertura: os centros vão ao servidor e as peças são renumeradas pela montagem.
  // Importar antes disso dá 409 no Aplicar (a prévia ligou as linhas a outros números).
  const headers = await fabHeaders(page);
  await expect
    .poll(async () => {
      const s = (await (await page.request.get(`/api/versions/${version}/centroids`, { headers })).json()) as {
        numbering: string;
      };
      return s.numbering;
    }, { timeout: 15_000 })
    .toBe('sequence');

  // prévia
  await page.getByRole('button', { name: 'Importar Excel' }).click();
  const dialog = page.getByRole('dialog', { name: 'Importar valores do Excel' });
  await dialog.getByLabel('Arquivo (.xlsx)').setInputFiles(file);
  await expect(dialog.getByTestId('plannix-summary')).toContainText(
    'Planilha do Plannix · 9 peças lidas · 8 ligadas a peças do modelo (8 novas) · 1 recusada ignorada',
  );
  await expect(dialog.getByTestId('import-summary')).toContainText('9 campos a preencher');
  await expect(dialog.getByText('1 marca da planilha fora deste modelo')).toBeVisible();
  await expect(dialog.getByRole('checkbox', { name: /Também alterar/ })).toHaveCount(0);

  // aplicar
  await dialog.getByRole('button', { name: 'Aplicar 9 valores' }).click();
  await expect(dialog).toBeHidden();
  const toast = page.getByRole('status').filter({ hasText: 'Importação do Plannix: 9 valores gravados (4 peças).' });
  await expect(toast).toBeVisible();
  const after = await p06(page, obra, version);
  const first = after.units.find((u) => u.number === 1);
  expect(first?.plannix_code).toBe('9001');
  const plannixIds = new Set(after.params.filter((p) => p.source === 'plannix').map((p) => p.def_id));
  expect(plannixIds.size).toBe(6);
  expect(first?.values.filter((v) => plannixIds.has(v.def_id) && v.value === '2026-11-10')).toHaveLength(6);

  // na tabela de peças, as datas do Plannix são só leitura
  await page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 10' }).click();
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  const table = panel.getByRole('table', { name: 'Peças da marca' });
  await expect(table.getByRole('columnheader', { name: /Corte e dobra/ })).toContainText('Plannix');
  await expect(table.getByRole('row').filter({ hasText: 'P-06-1' })).toContainText('10/11/2026');
  await expect(table.getByRole('button', { name: /^Corte e dobra de P-06-1/ })).toHaveCount(0);

  // desfazer pelo aviso: as datas saem; os Códigos ficam
  await toast.getByRole('button', { name: 'Desfazer' }).click();
  await expect(page.getByText('Edição em lote desfeita.')).toBeVisible();
  const undone = await p06(page, obra, version);
  expect(undone.units.flatMap((u) => u.values).filter((v) => plannixIds.has(v.def_id) && v.value !== null)).toHaveLength(0);
  expect(undone.units.find((u) => u.number === 1)?.plannix_code).toBe('9001');
});
