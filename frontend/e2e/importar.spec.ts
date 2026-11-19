import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

/**
 * Importar valores pelo Excel (2026-11-19), na pilha real: exporta pelo botão, preenche
 * um campo vazio no arquivo (openpyxl, como a fábrica faria no Excel), importa pela
 * janela, confere a prévia, aplica e desfaz pelo aviso.
 */

const REAL = Boolean(process.env.E2E_REAL_VIEWER);
const obraId = () => process.env.E2E_OBRA_ID ?? '';
const FAKE_VIEWER = resolve(process.cwd(), 'e2e/fake-viewer/viewer3D.js');

interface DevUser {
  id: number;
  role: string;
}

async function fabHeaders(page: Page): Promise<Record<string, string>> {
  const users = (await (await page.request.get('/api/dev/users')).json()) as DevUser[];
  return { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
}

/** Preenche a 1ª célula vazia da coluna no Excel baixado. Devolve a marca. */
function fillFirstEmpty(file: string, column: string, value: string): string {
  // com shell (Windows) os argumentos com espaço ("Tipo de forma") precisam de aspas
  const q = (a: string) => (process.platform === 'win32' ? `"${a}"` : a);
  const out = execFileSync('uv', ['run', 'python', '-m', 'tests.e2e_edit_xlsx', q(file), q(column), q(value)], {
    cwd: resolve(process.cwd(), '../backend'),
    encoding: 'utf-8',
    shell: process.platform === 'win32',
  });
  return (JSON.parse(out.trim().split('\n').at(-1) ?? '{}') as { mark: string }).mark;
}

// Viewer falso no lugar do CDN (como em modelo.spec.ts); as peças ganham a caixa padrão.
test.beforeEach(async ({ page }) => {
  if (REAL) return;
  await page.route('https://developer.api.autodesk.com/modelderivative/v2/viewers/**', (route) => {
    const url = route.request().url();
    if (url.endsWith('viewer3D.min.js')) {
      return route.fulfill({ path: FAKE_VIEWER, contentType: 'application/javascript' });
    }
    return route.fulfill({ body: '', contentType: 'text/css' });
  });
  await page.route('**/api/viewer-token', (route) =>
    route.fulfill({ json: { access_token: 'E2E', token_type: 'Bearer', expires_in: 600, region: 'US' } }),
  );
  await page.addInitScript((pieces) => {
    (window as unknown as { __E2E_PIECES: unknown }).__E2E_PIECES = pieces;
  }, [10, 11, 12, 13, 20, 21, 30].map((dbid) => ({ dbid, label: `Peça ${String(dbid)}` })));
});

test('Importar Excel: preenche um campo vazio pelo arquivo exportado e desfaz', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  const headers = await fabHeaders(page);
  const defId = process.env.E2E_PARAM_DEF_ID ?? '0';
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers })
  ).json()) as { mark_id: number; code: string }[];
  const setAll = (codes: string[], value: string | null) =>
    page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
      headers,
      data: {
        mark_ids: marks.filter((m) => codes.includes(m.code)).map((m) => m.mark_id),
        changes: { [defId]: value },
        mode: 'overwrite',
      },
    });
  // estado: só a PP001 com Tipo de forma
  expect((await setAll(marks.map((m) => m.code), null)).ok()).toBe(true);
  expect((await setAll(['PP001'], 'F-12')).ok()).toBe(true);

  // abre o modelo como fábrica
  await page.goto('/obras');
  const userSelect = page.getByLabel('Usuário (simulado)');
  const fab = await userSelect.locator('option', { hasText: '(Fábrica)' }).first().getAttribute('value');
  await userSelect.selectOption(fab ?? '');
  await page.locator(`a[href="/obras/${obraId()}"]`).first().click();
  await page.getByRole('link', { name: 'Abrir modelo 3D' }).click();
  await expect(page.locator('[data-load="ready"]')).toBeVisible({ timeout: 15_000 });

  // exporta e preenche o arquivo
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Exportar Excel' }).click(),
  ]);
  const file = testInfo.outputPath('importar.xlsx');
  await download.saveAs(file);
  const filled = fillFirstEmpty(file, 'Tipo de forma', 'F-13');
  expect(filled).not.toBe('PP001');

  // importa: prévia e aplicar
  await page.getByRole('button', { name: 'Importar Excel' }).click();
  const dialog = page.getByRole('dialog', { name: 'Importar valores do Excel' });
  await dialog.getByLabel('Arquivo (.xlsx)').setInputFiles(file);
  await expect(dialog.getByTestId('import-summary')).toContainText('1 campo a preencher');
  await dialog.getByText('Ver o campo a preencher').click();
  const row = dialog.getByRole('table', { name: 'Campos a preencher' }).getByRole('row', { name: new RegExp(filled) });
  await expect(row).toContainText('F-13');
  await dialog.getByRole('button', { name: 'Aplicar 1 valor' }).click();
  await expect(dialog).toBeHidden();

  const toast = page.getByRole('status').filter({ hasText: 'Importação: 1 valor gravado (1 marca).' });
  await expect(toast).toBeVisible();
  const markId = marks.find((m) => m.code === filled)?.mark_id ?? 0;
  const valueOf = async () => {
    const r = await page.request.get(`/api/obras/${obraId()}/marks/${String(markId)}/values`, { headers });
    const body = (await r.json()) as { values: { def_id: number; value: unknown }[] };
    return body.values.find((v) => v.def_id === Number(defId))?.value ?? null;
  };
  expect(await valueOf()).toBe('F-13');

  // desfazer pelo aviso
  await toast.getByRole('button', { name: 'Desfazer' }).click();
  await expect(page.getByText('Edição em lote desfeita.')).toBeVisible();
  expect(await valueOf()).toBeNull();
});
