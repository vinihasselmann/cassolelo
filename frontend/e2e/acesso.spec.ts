import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Fase 11.2: papéis e acesso por obra, na pilha real (backend + banco do E2E).
 *
 * - sem login a API responde 401;
 * - Fábrica não cria obra; Projetos não edita parâmetro;
 * - o admin restringe as obras de um usuário pela tela "Usuários" e ele deixa de ver as outras;
 * - a auditoria (histórico da marca) mostra o nome de quem alterou.
 *
 * O login aqui é o usuário simulado (APP_ENV=dev). O mesmo aceite com token Microsoft
 * de verdade (assinado por chave de teste) está em backend/tests/test_access_e2e.py.
 */

interface DevUser {
  id: number;
  name: string;
  role: string;
}

const env = (name: string): string => {
  const v = process.env[name];
  if (!v) throw new Error(`${name} não definido (rode pelo global-setup do Playwright).`);
  return v;
};

let users: Record<string, DevUser> = {};

const as = (role: string) => ({ 'X-Dev-User': String(users[role]?.id ?? '') });

async function firstMarkId(request: APIRequestContext): Promise<number> {
  const r = await request.get(`/api/versions/${env('E2E_VERSION_ID')}/marks`, { headers: as('leitura') });
  expect(r.ok()).toBeTruthy();
  const marks = (await r.json()) as { mark_id: number }[];
  const first = marks[0];
  if (!first) throw new Error('obra E2E-01 sem marcas');
  return first.mark_id;
}

/** Devolve a Lia (leitura) para "todas as obras": cada teste começa do padrão. */
async function resetLeitura(request: APIRequestContext): Promise<void> {
  const r = await request.patch(`/api/users/${String(users.leitura?.id)}`, {
    headers: as('admin'),
    data: { all_obras: true },
  });
  expect(r.ok()).toBeTruthy();
}

async function chooseUser(page: Page, name: RegExp): Promise<void> {
  const select = page.getByLabel('Usuário (simulado)');
  await expect(select.locator('option', { hasText: name })).toHaveCount(1);
  const value = await select.locator('option', { hasText: name }).getAttribute('value');
  await select.selectOption(value ?? '');
}

test.describe('acesso (11.2)', () => {
  test.beforeAll(async ({ request }) => {
    const r = await request.get('/api/dev/users');
    const list = (await r.json()) as DevUser[];
    users = Object.fromEntries(list.map((u) => [u.role, u]));
  });

  test.afterEach(async ({ request }) => {
    await resetLeitura(request);
  });

  test('sem login a API responde 401', async ({ request }) => {
    for (const url of ['/api/me', '/api/obras', `/api/obras/${env('E2E_OBRA_ID')}`, '/api/users']) {
      const r = await request.get(url);
      expect(r.status(), url).toBe(401);
    }
    expect((await request.post('/api/obras', { data: {} })).status()).toBe(401);
  });

  test('Fábrica não cria obra', async ({ request }) => {
    const acc = { hub_id: 'h', project_id: 'p', folder_id: 'f', item_id: 'i' };
    const r = await request.post('/api/obras', {
      headers: as('fabrica'),
      data: { code: 'E2E-NAO', name: 'Não pode', acc },
    });
    expect(r.status()).toBe(403);
    expect(((await r.json()) as { detail: string }).detail).toBe('Seu papel não permite esta ação.');
  });

  test('Projetos não edita parâmetro', async ({ request }) => {
    const markId = await firstMarkId(request);
    const url = `/api/obras/${env('E2E_OBRA_ID')}/marks/${String(markId)}/values`;
    const changes = [{ def_id: Number(env('E2E_PARAM_DEF_ID')), value: 'Metálica' }];
    const r = await request.put(url, { headers: as('projetos'), data: { changes } });
    expect(r.status()).toBe(403);
    expect((await request.get(url, { headers: as('projetos') })).status()).toBe(200);
  });

  test('admin restringe as obras na tela Usuários e o usuário deixa de ver as outras', async ({
    page,
    request,
  }) => {
    await page.goto('/obras');
    await chooseUser(page, /Ana Admin/);
    await page.getByRole('link', { name: 'Usuários' }).click();
    await expect(page.getByRole('heading', { name: 'Usuários' })).toBeVisible();

    await page.getByRole('button', { name: 'Editar Lia Leitura' }).click();
    const dialog = page.getByRole('dialog', { name: 'Editar Lia Leitura' });
    await dialog.getByRole('radio', { name: 'Só as obras escolhidas' }).check();
    await dialog.getByRole('checkbox', { name: /E2E-01/ }).check();
    await dialog.getByRole('button', { name: 'Salvar' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId('user-leitura@dev.local')).toContainText('E2E-01');

    // como a Lia: só a E2E-01 na lista; a E2E-PEC responde 404
    await page.getByRole('link', { name: /Cassol Elo/ }).click();
    await chooseUser(page, /Lia Leitura/);
    await expect(page.getByRole('link', { name: 'E2E-01' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'E2E-PEC' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Usuários' })).toHaveCount(0);
    const hidden = await request.get(`/api/obras/${env('E2E_PEC_OBRA_ID')}`, { headers: as('leitura') });
    expect(hidden.status()).toBe(404);
  });

  test('auditoria mostra o nome de quem alterou', async ({ request }) => {
    const markId = await firstMarkId(request);
    const base = `/api/obras/${env('E2E_OBRA_ID')}/marks/${String(markId)}`;
    const defId = Number(env('E2E_PARAM_DEF_ID'));
    const current = (await (await request.get(`${base}/values`, { headers: as('leitura') })).json()) as {
      values: { def_id: number; value: unknown }[];
    };
    const before = current.values.find((v) => v.def_id === defId)?.value ?? null;
    const value = before === 'F-12' ? 'F-13' : 'F-12';
    const put = await request.put(`${base}/values`, {
      headers: as('fabrica'),
      data: { changes: [{ def_id: defId, value }] },
    });
    expect(put.ok(), await put.text()).toBeTruthy();
    try {
      const history = (await (await request.get(`${base}/history`, { headers: as('leitura') })).json()) as {
        user_name: string | null;
        after: unknown;
      }[];
      // o mais recente primeiro
      expect(history[0]?.after).toBe(value);
      expect(history[0]?.user_name).toBe(users.fabrica?.name);
    } finally {
      await request.put(`${base}/values`, {
        headers: as('fabrica'),
        data: { changes: [{ def_id: defId, value: before }] },
      });
    }
  });
});
