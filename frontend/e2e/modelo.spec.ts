import { resolve } from 'node:path';

import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Fase 4.2: abrir a obra de teste, clicar numa peça e conferir marca, quantidade e
 * grupos de propriedades; medir o tempo até o modelo aparecer.
 * Modos: veja playwright.config.ts.
 */
const REAL = Boolean(process.env.E2E_REAL_VIEWER);
const MAX_LOAD_MS = Number(process.env.E2E_MAX_LOAD_MS ?? 15_000);
const FAKE_VIEWER = resolve(process.cwd(), 'e2e/fake-viewer/viewer3D.js');

// Peças do modelo de teste (backend/tests/fixtures/aps/models/validacao). Geometria no
// Viewer falso (pés, mundo): pilar 10 com seção 40x40 cm e 6 m, base em z = -2 pés; viga 20
// de 8 m ao longo de X, seção 30x60 cm, eixo em y = 30 e z = 9,84252 pés. As outras peças
// ganham uma caixa padrão (fake-viewer/viewer3D.js).
const GEOMETRY: Record<number, { category: string; geom: { origin: number[]; a: number[]; b: number[]; c: number[] } }> = {
  10: {
    category: 'Pilares estruturais',
    geom: { origin: [10, 20, -2], a: [1.312336, 0, 0], b: [0, 1.312336, 0], c: [0, 0, 19.68504] },
  },
  20: {
    category: 'Quadro estrutural',
    geom: { origin: [10, 29.507874, 8.858268], a: [26.24672, 0, 0], b: [0, 0.984252, 0], c: [0, 0, 1.968504] },
  },
};
const PIECES = [10, 11, 12, 13, 20, 21, 30].map((dbid) => ({ dbid, label: `Peça ${dbid}`, ...GEOMETRY[dbid] }));

function obraId(): string {
  const id = process.env.E2E_OBRA_ID;
  if (!id) throw new Error('E2E_OBRA_ID não definido (o global-setup deveria preencher).');
  return id;
}

type CspWindow = Window & { __CSP_VIOLATIONS?: string[] };

// 10.2: a página roda com a CSP do app (security-headers.ts). Qualquer violação, com o
// Viewer falso ou o real, reprova o teste. Exceção: a telemetria de uso que o Viewer
// manda ao Mixpanel é bloqueada DE PROPÓSITO (não afeta o modelo; nada de uso da
// fábrica sai para terceiros).
const EXPECTED_BLOCKS = [/^connect-src bloqueou https:\/\/api-js\.mixpanel\.com\//];
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as CspWindow;
    w.__CSP_VIOLATIONS = [];
    document.addEventListener('securitypolicyviolation', (e) => {
      w.__CSP_VIOLATIONS?.push(`${e.effectiveDirective} bloqueou ${e.blockedURI || '(inline)'}`);
    });
  });
});

test.afterEach(async ({ page }) => {
  if (page.isClosed()) return;
  const all = await page.evaluate(() => (window as CspWindow).__CSP_VIOLATIONS ?? []);
  const violations = all.filter((v) => !EXPECTED_BLOCKS.some((re) => re.test(v)));
  expect(violations, 'violações de CSP').toEqual([]);
});

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
  }, PIECES);
});

/** Escolhe o usuário da fábrica, entra na obra e abre o modelo. Devolve o tempo (ms) até ele aparecer. */
async function openModel(page: Page, testInfo: TestInfo): Promise<number> {
  await page.goto('/obras');
  const userSelect = page.getByLabel('Usuário (simulado)');
  const fabrica = await userSelect.locator('option', { hasText: '(Fábrica)' }).first().getAttribute('value');
  await userSelect.selectOption(fabrica ?? '');
  await page.locator(`a[href="/obras/${obraId()}"]`).first().click();
  const open = page.getByRole('link', { name: 'Abrir modelo 3D' });

  const started = Date.now();
  await open.click();
  await expect(page.locator('[data-load="ready"]')).toBeVisible({ timeout: REAL ? MAX_LOAD_MS + 30_000 : 15_000 });
  const elapsed = Date.now() - started;

  testInfo.annotations.push({ type: 'tempo até o modelo aparecer', description: `${elapsed} ms` });
  console.log(`[${testInfo.project.name}] tempo até o modelo aparecer: ${elapsed} ms${REAL ? '' : ' (Viewer falso)'}`);
  return elapsed;
}

const header = (page: Page) => page.getByRole('complementary', { name: 'Peça selecionada' }).getByRole('heading', { level: 3 });

// ------------------------------------------------------------------ F3: barra inferior e filtro
const viewerBar = (page: Page) => page.getByRole('toolbar', { name: 'Barra do visualizador' });
const filterPop = (page: Page) => page.getByRole('dialog', { name: 'Filtro' });

/** Abre o popover "Filtro" (se ainda não estiver aberto) e devolve-o. */
async function openFilter(page: Page) {
  if (!(await filterPop(page).isVisible())) await viewerBar(page).getByRole('button', { name: /^Filtro/ }).click();
  await expect(filterPop(page)).toBeVisible();
  return filterPop(page);
}

/** Fecha os popovers da barra (Esc), para liberar o 3D aos cliques. */
async function closePopovers(page: Page) {
  await page.keyboard.press('Escape');
  await expect(filterPop(page)).toBeHidden();
}

/** "Pesquisar por objetos" no popover Filtro. */
async function searchObjects(page: Page, text: string) {
  const pop = await openFilter(page);
  await pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }).fill(text);
}

/** Aplica um filtro salvo pelo nome (sistema, compartilhados ou meus). */
async function applySaved(page: Page, name: string) {
  const pop = await openFilter(page);
  await pop.getByRole('button', { name, exact: true }).click();
  await expect(pop.getByRole('button', { name: new RegExp(name) })).toHaveAttribute('aria-pressed', 'true');
}

async function removeFilters(page: Page) {
  await viewerBar(page).getByRole('button', { name: 'Remover filtros' }).click();
  await expect(viewerBar(page).getByRole('button', { name: 'Remover filtros' })).toBeHidden();
}

/** Abre o popover "Colorir" (se ainda não estiver aberto) e devolve-o. */
async function colorPop(page: Page) {
  const pop = page.getByRole('dialog', { name: 'Colorir' });
  if (!(await pop.isVisible())) await viewerBar(page).getByRole('button', { name: 'Colorir' }).click();
  await expect(pop).toBeVisible();
  return pop;
}

/** "Colorir" por um campo da lista (busca pelo nome). */
async function colorByField(page: Page, name: string) {
  const pop = await colorPop(page);
  await pop.getByRole('searchbox', { name: 'Buscar parâmetro' }).fill(name);
  await pop.getByRole('button', { name: new RegExp(`^${name}`) }).first().click();
  return pop;
}

/** Zera o "Tipo de forma" e preenche só PP001 = F-11 (estado conhecido para as cores). */
async function formaOnlyPP001(page: Page) {
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
  const fab = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers: fab })
  ).json()) as { mark_id: number; code: string }[];
  const defId = process.env.E2E_PARAM_DEF_ID ?? '0';
  const apply = (codes: string[], value: string | null) =>
    page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
      headers: fab,
      data: { mark_ids: marks.filter((m) => codes.includes(m.code)).map((m) => m.mark_id), changes: { [defId]: value }, mode: 'overwrite' },
    });
  expect((await apply(['PP002', 'V-01'], null)).ok()).toBe(true);
  expect((await apply(['PP001'], 'F-11')).ok()).toBe(true);
}

test('a página do app vem com a CSP e os cabeçalhos de segurança', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop' || Boolean(process.env.E2E_BASE_URL), 'cabeçalhos do Vite local');
  const res = await page.goto('/obras');
  const headers = res?.headers() ?? {};
  expect(headers['content-security-policy']).toContain("frame-ancestors 'none'");
  expect(headers['content-security-policy']).toContain('https://developer.api.autodesk.com');
  expect(headers['x-content-type-options']).toBe('nosniff');
  const api = await page.request.get('/api/health');
  expect(api.headers()['content-security-policy']).toContain("default-src 'none'");
});

test('clicar numa peça destaca a marca inteira e mostra marca, quantidade e propriedades', async ({ page }, testInfo) => {
  const elapsed = await openModel(page, testInfo);
  if (REAL) expect(elapsed, `o modelo deve aparecer em até ${MAX_LOAD_MS} ms`).toBeLessThanOrEqual(MAX_LOAD_MS);

  if (REAL) {
    if (testInfo.project.use.hasTouch) {
      // O toque emulado do Chromium não chega ao reconhecedor de gestos do Viewer: aqui a
      // seleção é pela lista (o Viewer seleciona os dbIds do banco). Toque: tablet real.
      const first = page.getByRole('list', { name: /^Marcas/ }).getByRole('button').first();
      await first.click();
      await expect(header(page)).toHaveText(/^.+ · .+ · \d+ peças?$/);
      console.log(`[${testInfo.project.name}] selecionada pela lista: ${(await header(page).textContent()) ?? ''}`);
      return;
    }
    // Procura uma peça: clica numa grade de pontos da área do modelo até o painel mostrar
    // uma marca. "Peça clicada" só aparece se o dbId do Viewer existe no banco do app
    // (prova de que elements.dbid = dbId do Viewer no SVF2 do Docs).
    await page.getByRole('button', { name: 'Ampliar tudo' }).click();
    await page.waitForTimeout(2000);
    const box = await page.getByTestId('viewer-container').boundingBox();
    if (!box) throw new Error('viewer sem área visível');
    const clicked = page.getByText(/^Peça clicada:/);
    // dbIds que o app conhece (peças e membros), na versão aberta
    const fabricaId = await page.getByLabel('Usuário (simulado)').inputValue();
    const api = (path: string) => page.request.get(`/api${path}`, { headers: { 'X-Dev-User': fabricaId } });
    const versions = (await (await api(`/obras/${obraId()}/versions`)).json()) as { id: number; status: string }[];
    const active = versions.find((v) => v.status === 'ready');
    const marks = (await (await api(`/versions/${active?.id ?? 0}/marks`)).json()) as {
      dbids: number[];
      member_dbids?: number[];
    }[];
    const known = new Set(marks.flatMap((m) => [...m.dbids, ...(m.member_dbids ?? [])]));
    // Varre a tela pedindo ao Viewer o dbId de cada ponto e clica num que seja peça ou
    // membro de peça (modelos grandes ocupam pouco da tela; a grade às cegas batia no
    // vazio). No .nwd da 9480 os Ambientes do Revit ficam na frente: ver docs/montagens.md.
    const points = await page.evaluate(
      ([w, h]) => {
        type V = { clientToWorld: (x: number, y: number) => { dbId?: number } | null };
        const v = (window as unknown as { NOP_VIEWER?: V }).NOP_VIEWER;
        const out: [number, number, number][] = [];
        for (let fy = 0.05; fy <= 0.95; fy += 0.02) {
          for (let fx = 0.05; fx <= 0.95; fx += 0.02) {
            const hitId = v?.clientToWorld(w * fx, h * fy)?.dbId;
            if (typeof hitId === 'number') out.push([fx, fy, hitId]);
          }
        }
        return out;
      },
      [box.width, box.height] as const,
    );
    const target = points.find(([, , hitId]) => known.has(hitId));
    expect(target, `nenhum ponto da tela cai numa peça (${points.length} pontos com geometria)`).toBeDefined();
    const [fx, fy, id] = target ?? [0, 0, 0];
    console.log(`[${testInfo.project.name}] clique no dbId ${id} (${marks.some((m) => m.dbids.includes(id)) ? 'peça' : 'membro'})`);
    await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
    await expect(clicked).toBeVisible({ timeout: 10_000 });
    await expect(header(page)).toHaveText(/^(.+ · .+ · \d+ peças?|Peça sem Marca)$/);
    await expect(page.getByRole('button', { name: /\(\d+\)$/ }).first()).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('modelo-real.png') });
    console.log(`[${testInfo.project.name}] peça selecionada: ${(await header(page).textContent()) ?? ''}`);
    return;
  }

  const fake3d = page.getByTestId('fake-3d');
  await fake3d.getByRole('button', { name: 'Peça 11' }).click();

  // Marca e quantidade no painel; as duas peças do PP001 destacadas no "3D".
  await expect(header(page)).toHaveText('PP001 · Structural Columns · 2 peças');
  await expect(fake3d.getByRole('button', { name: 'Peça 10' })).toHaveAttribute('aria-pressed', 'true');
  await expect(fake3d.getByRole('button', { name: 'Peça 11' })).toHaveAttribute('aria-pressed', 'true');
  await expect(fake3d.getByRole('button', { name: 'Peça 12' })).toHaveAttribute('aria-pressed', 'false');

  // Grupos de propriedades do modelo, somente leitura.
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  for (const group of ['Dados de identidade', 'Dimensões', 'Other']) {
    await expect(panel.getByRole('button', { name: new RegExp(String.raw`^${group} \(\d+\)$`) })).toBeVisible();
  }
  await expect(panel.getByLabel('Dimensões')).toContainText('Altura50.0 cm');
  await expect(panel.getByText('Parâmetros da fábrica')).toBeVisible();

  // Filtro de propriedades.
  await panel.getByRole('searchbox', { name: 'Filtrar propriedades' }).fill('largura');
  await expect(panel.getByLabel('Dimensões')).toHaveText('Largura40.0 cm');

  // Peça sem Marca.
  await fake3d.getByRole('button', { name: 'Peça 30' }).click();
  await expect(header(page)).toHaveText('Peça sem Marca');
});

test('Isolar e Limpar seleção', async ({ page }, testInfo) => {
  test.skip(REAL, 'só com o Viewer falso (estado das peças visível no DOM)');
  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  await fake3d.getByRole('button', { name: 'Peça 20' }).click();
  await expect(header(page)).toHaveText('V-01 · Structural Framing · 2 peças');

  await page.getByRole('button', { name: 'Isolar' }).click();
  await expect(fake3d.getByRole('button', { name: 'Peça 10' })).toBeHidden();
  await expect(fake3d.getByRole('button', { name: 'Peça 21' })).toBeVisible();
  await page.getByRole('button', { name: 'Isolar' }).click();
  await expect(fake3d.getByRole('button', { name: 'Peça 10' })).toBeVisible();

  await page.getByRole('button', { name: 'Limpar seleção' }).click();
  await expect(fake3d.getByRole('button', { name: 'Peça 20' })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByText('Toque numa peça no modelo, ou escolha uma marca na lista, para ver e preencher os parâmetros da fábrica.')).toBeVisible();
});

test('Ctrl+clique acumula marcas (desktop)', async ({ page }, testInfo) => {
  test.skip(REAL || testInfo.project.name !== 'desktop', 'Ctrl+clique é do desktop');
  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  await fake3d.getByRole('button', { name: 'Peça 10' }).click();
  await fake3d.getByRole('button', { name: 'Peça 20' }).click({ modifiers: ['Control'] });
  await expect(header(page)).toHaveText('2 marcas · 4 peças');
  for (const dbid of [10, 11, 20, 21]) {
    await expect(fake3d.getByRole('button', { name: `Peça ${dbid}` })).toHaveAttribute('aria-pressed', 'true');
  }
});

test('Seleção múltipla por toque (tablet)', async ({ page }, testInfo) => {
  test.skip(REAL, 'só com o Viewer falso');
  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  await page.getByRole('button', { name: 'Seleção múltipla' }).click();
  await fake3d.getByRole('button', { name: 'Peça 12' }).click();
  await fake3d.getByRole('button', { name: 'Peça 21' }).click();
  await expect(header(page)).toHaveText('2 marcas · 4 peças');
  await fake3d.getByRole('button', { name: 'Peça 13' }).click(); // de novo no PP002: sai
  await expect(header(page)).toHaveText('V-01 · Structural Framing · 2 peças');
});

test('pesquisar PP001 destaca a marca e Isolar mostra todas as peças dela e só elas', async ({ page }, testInfo) => {
  test.skip(REAL, 'só com o Viewer falso (estado das peças visível no DOM)');
  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  const state = (dbid: number) => fake3d.getByRole('button', { name: `Peça ${dbid}` });

  await searchObjects(page, 'PP001');
  const list = page.getByRole('list', { name: /^Marcas \(1\)/ });
  await expect(list.getByRole('button')).toHaveText([/PP001.*2 de 2 peças/]);
  await closePopovers(page);

  // Texto: resultado em destaque, restante esmaecido.
  for (const dbid of [10, 11]) await expect(state(dbid)).toHaveAttribute('data-state', 'normal');
  for (const dbid of [12, 13, 20, 21, 30]) await expect(state(dbid)).toHaveAttribute('data-state', 'esmaecida');

  // Isolar: só as peças do PP001 continuam visíveis.
  await page.getByRole('button', { name: 'Isolar' }).click();
  for (const dbid of [10, 11]) await expect(state(dbid)).toBeVisible();
  for (const dbid of [12, 13, 20, 21, 30]) await expect(state(dbid)).toBeHidden();

  // Desfaz o isolamento e remove o filtro: modelo normal.
  await page.getByRole('button', { name: 'Isolar' }).click();
  await removeFilters(page);
  for (const dbid of [10, 12, 20, 30]) await expect(state(dbid)).toHaveAttribute('data-state', 'normal');
});

test('pesquisa por seção e menu rápido de nível refletem no 3D', async ({ page }, testInfo) => {
  test.skip(REAL, 'só com o Viewer falso');
  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  const state = (dbid: number) => fake3d.getByRole('button', { name: `Peça ${dbid}` });

  await searchObjects(page, '40x50'); // seção, vinda do Tipo
  await expect(page.getByRole('list', { name: /^Marcas \(1\)/ }).getByRole('button')).toHaveText([/PP001.*1 de 2 peças/]);
  await expect(state(11)).toHaveAttribute('data-state', 'normal');
  await expect(state(10)).toHaveAttribute('data-state', 'esmaecida');

  const pop = await openFilter(page);
  await pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }).fill('');
  await pop.getByRole('button', { name: /^Nível/ }).click();
  await pop.getByRole('group', { name: 'Nível' }).getByRole('checkbox', { name: /TÉRREO/ }).check();
  await expect(page.getByRole('list', { name: /^Marcas \(2\)/ })).toBeVisible();
  await expect(pop.getByRole('list', { name: 'Filtros ativos' })).toContainText('Nível: TÉRREO');
  // Isolar (modo padrão das regras): o resto some
  for (const dbid of [10, 11, 20]) await expect(state(dbid)).toHaveAttribute('data-state', 'normal');
  for (const dbid of [12, 13, 21]) await expect(state(dbid)).toBeHidden() /* oculta */;
});

/** Volta o "Tipo de forma" do PP001 para vazio (pela API), para o teste começar do zero. */
async function resetPP001(page: Page): Promise<void> {
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
  const fab = String(users.find((u) => u.role === 'fabrica')?.id ?? '');
  const headers = { 'X-Dev-User': fab };
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers })
  ).json()) as { mark_id: number; code: string }[];
  const pp001 = marks.find((m) => m.code === 'PP001')?.mark_id;
  const url = `/api/obras/${obraId()}/marks/${String(pp001)}/values`;
  const current = (await (await page.request.get(url, { headers })).json()) as {
    values: { def_id: number; name: string; row_version: number | null }[];
  };
  const forma = current.values.find((v) => v.name === 'Tipo de forma');
  if (forma?.row_version != null) {
    const r = await page.request.put(url, {
      headers,
      data: { changes: [{ def_id: forma.def_id, value: null, row_version: forma.row_version }] },
    });
    expect(r.ok()).toBe(true);
  }
}

test('salvar F-12 numa peça do PP001 vale para todas as peças da marca e persiste após recarregar', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  await resetPP001(page);
  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  const values = panel.getByLabel('Valores da marca');

  await fake3d.getByRole('button', { name: 'Peça 10' }).click();
  await expect(header(page)).toHaveText('PP001 · Structural Columns · 2 peças');
  await expect(values).toContainText('Tipo de forma *—');

  await panel.getByRole('button', { name: 'Editar' }).click();
  await panel.getByLabel(/Tipo de forma/).selectOption('F-12');
  await panel.getByRole('button', { name: 'Salvar' }).click();
  await expect(values).toContainText('Tipo de forma *F-12');
  await expect(panel.getByText(/Última alteração: Fábio Fábrica · /)).toBeVisible();

  // Outra peça da MESMA marca mostra o mesmo valor (valores são da marca, não da peça).
  await fake3d.getByRole('button', { name: 'Peça 20' }).click();
  await expect(header(page)).toHaveText('V-01 · Structural Framing · 2 peças');
  await expect(values).toContainText('Tipo de forma *—');
  await fake3d.getByRole('button', { name: 'Peça 11' }).click();
  await expect(header(page)).toHaveText('PP001 · Structural Columns · 2 peças');
  await expect(values).toContainText('Tipo de forma *F-12');

  // Persiste após recarregar a página.
  await page.reload();
  await openModel(page, testInfo);
  await page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 11' }).click();
  await expect(values).toContainText('Tipo de forma *F-12');
  await panel.getByRole('button', { name: 'Histórico' }).click();
  await expect(panel.getByRole('list', { name: 'Histórico da marca' }).getByRole('listitem').first()).toContainText(
    'Tipo de forma: F-12',
  );
});

/** Valores do "Tipo de forma" por código de marca (pela API). */
async function formaByMark(page: Page): Promise<Record<string, unknown>> {
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
  const headers = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers })
  ).json()) as { mark_id: number; code: string }[];
  const out: Record<string, unknown> = {};
  for (const m of marks) {
    const body = (await (await page.request.get(`/api/obras/${obraId()}/marks/${String(m.mark_id)}/values`, { headers })).json()) as {
      values: { name: string; value: unknown }[];
    };
    out[m.code] = body.values.find((v) => v.name === 'Tipo de forma')?.value ?? null;
  }
  return out;
}

test('edição em lote: Só nas vazias não mexe na marca preenchida e Desfazer volta ao estado anterior', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
  const headers = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers })
  ).json()) as { mark_id: number; code: string }[];
  const id = (code: string) => marks.find((m) => m.code === code)?.mark_id ?? 0;
  const defId = Number(process.env.E2E_PARAM_DEF_ID ?? 0);
  // Estado inicial: PP002 = F-11, V-01 vazia (sobrescreve o que houver).
  for (const [code, value] of [['PP002', 'F-11'], ['V-01', null]] as const) {
    const r = await page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
      headers,
      data: { mark_ids: [id(code)], changes: { [defId]: value }, mode: 'overwrite' },
    });
    expect(r.ok()).toBe(true);
  }

  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  await page.getByRole('button', { name: 'Seleção múltipla' }).click();
  await fake3d.getByRole('button', { name: 'Peça 12' }).click();
  await fake3d.getByRole('button', { name: 'Peça 21' }).click();
  await expect(header(page)).toHaveText('2 marcas · 4 peças');
  await expect(panel.getByText('2 marcas selecionadas')).toBeVisible();
  await expect(panel.getByRole('note')).toContainText('A seleção mistura categorias');
  const values = panel.getByLabel('Valores das marcas selecionadas');
  await expect(values).toContainText('Tipo de forma *(valores mistos)');

  await panel.getByRole('button', { name: 'Editar em lote' }).click();
  await panel.getByLabel(/Tipo de forma/).selectOption('F-13');
  await panel.getByRole('button', { name: 'Aplicar' }).click();
  const dialog = page.getByRole('dialog', { name: 'Aplicar às marcas selecionadas' });
  await expect(dialog).toContainText('1 marca já tem outro valor.');
  await dialog.getByRole('button', { name: 'Só nas vazias' }).click();

  const toast = page.getByRole('status').filter({ hasText: 'Valores aplicados a 1 marca.' });
  await expect(toast).toBeVisible();
  const after = await formaByMark(page);
  expect([after['PP002'], after['V-01']]).toEqual(['F-11', 'F-13']);

  await toast.getByRole('button', { name: 'Desfazer' }).click();
  await expect(page.getByText('Edição em lote desfeita.')).toBeVisible();
  const undone = await formaByMark(page);
  expect([undone['PP002'], undone['V-01']]).toEqual(['F-11', null]);
  await expect(values).toContainText('Tipo de forma *(valores mistos)');
});

test('aceite da Fase 6: cores, legenda, progresso e atalhos acompanham marca, lote, desfazer e edição simultânea', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string; name: string }[];
  const as = (role: string) => ({ 'X-Dev-User': String(users.find((u) => u.role === role)?.id ?? '') });
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers: as('fabrica') })
  ).json()) as { mark_id: number; code: string }[];
  const defId = Number(process.env.E2E_PARAM_DEF_ID ?? 0);
  // Começa com todas as marcas vazias ("Tipo de forma" é obrigatório e vale para as 3).
  const reset = await page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
    headers: as('fabrica'),
    data: { mark_ids: marks.map((m) => m.mark_id), changes: { [defId]: null }, mode: 'overwrite' },
  });
  expect(reset.ok()).toBe(true);

  await openModel(page, testInfo);
  const fake3d = page.getByTestId('fake-3d');
  const piece = (dbid: number) => fake3d.getByRole('button', { name: `Peça ${dbid}` });
  const legend = page.getByRole('region', { name: 'Legenda' });
  const bar = page.getByRole('progressbar', { name: 'Progresso de Tipo de forma' });
  const foot = page.getByRole('region', { name: 'Progresso' });
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  const GRAY = '#B9BEC6';
  const GREEN = '#33A06F';

  await expect(legend.getByRole('button', { name: 'Pendente: 3 marcas' })).toBeVisible();
  await expect(piece(10)).toHaveAttribute('data-base-color', GRAY);
  await expect(piece(30)).toHaveAttribute('data-base-color', '#9AA0A6'); // sem Marca: "Sem marca" (cinza)
  await expect(foot).toContainText('0/3 marcas · 0/6 peças (0%)');

  // 1. uma marca
  await piece(10).click();
  await panel.getByRole('button', { name: 'Editar' }).click();
  await panel.getByLabel(/Tipo de forma/).selectOption('F-12');
  await panel.getByRole('button', { name: 'Salvar' }).click();
  await expect(legend.getByRole('button', { name: 'Completa: 1 marca' })).toBeVisible();
  await expect(piece(10)).toHaveAttribute('data-base-color', GREEN); // base: a peça está selecionada (grafite por cima)
  await expect(piece(11)).toHaveAttribute('data-base-color', GREEN); // a marca inteira
  await expect(foot).toContainText('1/3 marcas · 2/6 peças (33%)');
  await expect(bar).toHaveAttribute('aria-valuenow', '33');

  // filtro de sistema Pendentes (antigo atalho)
  await applySaved(page, 'Pendentes');
  await expect(page.getByRole('heading', { name: 'Marcas (2)' })).toBeVisible();
  await removeFilters(page);

  // 2. lote (legenda seleciona as pendentes) e 3. desfazer
  await legend.getByRole('button', { name: 'Pendente: 2 marcas' }).click();
  await expect(header(page)).toHaveText('2 marcas · 4 peças');
  await panel.getByRole('button', { name: 'Editar em lote' }).click();
  await panel.getByLabel(/Tipo de forma/).selectOption('F-11');
  await panel.getByRole('button', { name: 'Aplicar' }).click();
  await page.getByRole('dialog', { name: 'Aplicar às marcas selecionadas' }).getByRole('button', { name: 'Sobrescrever todas' }).click();
  await expect(legend.getByRole('button', { name: 'Completa: 3 marcas' })).toBeVisible();
  await expect(piece(21)).toHaveAttribute('data-base-color', GREEN);
  await expect(foot).toContainText('3/3 marcas · 6/6 peças (100%)');
  await page.getByRole('status').filter({ hasText: 'Valores aplicados a 2 marcas.' }).getByRole('button', { name: 'Desfazer' }).click();
  await expect(page.getByText('Edição em lote desfeita.')).toBeVisible();
  await expect(legend.getByRole('button', { name: 'Completa: 1 marca' })).toBeVisible();
  await expect(piece(21)).toHaveAttribute('data-base-color', GRAY);
  await expect(foot).toContainText('1/3 marcas · 2/6 peças (33%)');

  // Colorir por parâmetro e por categoria (popover "Colorir" da barra inferior)
  const colors = await colorByField(page, 'Tipo de forma');
  await expect(legend.getByRole('button', { name: 'F-12: 1 marca' })).toBeVisible();
  await expect(legend.getByRole('button', { name: 'Sem valor: 2 marcas' })).toBeVisible();
  await colors.getByRole('button', { name: 'Categoria' }).click();
  await expect(legend.getByRole('button', { name: 'Structural Columns: 2 marcas' })).toBeVisible();
  await colors.getByRole('button', { name: 'Status' }).click();
  await page.keyboard.press('Escape');

  // 4. edição simultânea: outro usuário salva enquanto a fábrica edita -> aviso, nada sobrescrito
  await piece(10).click();
  await expect(header(page)).toHaveText('PP001 · Structural Columns · 2 peças');
  await panel.getByRole('button', { name: 'Editar' }).click();
  await panel.getByLabel(/Tipo de forma/).selectOption('F-13');
  const pp001 = marks.find((m) => m.code === 'PP001')?.mark_id ?? 0;
  const url = `/api/obras/${obraId()}/marks/${String(pp001)}/values`;
  const current = (await (await page.request.get(url, { headers: as('admin') })).json()) as {
    values: { def_id: number; row_version: number | null }[];
  };
  const other = await page.request.put(url, {
    headers: as('admin'),
    data: { changes: [{ def_id: defId, value: 'F-11', row_version: current.values.find((v) => v.def_id === defId)?.row_version ?? null }] },
  });
  expect(other.ok()).toBe(true);
  await panel.getByRole('button', { name: 'Salvar' }).click();
  await expect(panel.getByRole('alert')).toContainText('alterou esta marca');
  await panel.getByRole('button', { name: 'Recarregar' }).click();
  await expect(panel.getByLabel('Valores da marca')).toContainText('Tipo de forma *F-11');
});

test('aceite da Fase 7: versão nova com revisar (40x60 → 40x80), órfãs religadas/arquivadas e atalhos', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  test.setTimeout(90_000);
  const { runSeed } = await import('./global-setup');
  const rev = String(runSeed().rev_obra_id); // estado inicial: v2 acabou de chegar
  // Peças da revisao_v2 no Viewer falso.
  await page.addInitScript((pieces) => {
    (window as unknown as { __E2E_PIECES: unknown }).__E2E_PIECES = pieces;
  }, [10, 11, 14, 15, 16, 17, 19, 20, 21, 30, 40, 41].map((dbid) => ({ dbid, label: `Peça ${dbid}` })));
  page.on('dialog', (d) => { void d.accept(); }); // confirmação do Arquivar

  await page.goto('/obras');
  const userSelect = page.getByLabel('Usuário (simulado)');
  const fabrica = await userSelect.locator('option', { hasText: '(Fábrica)' }).first().getAttribute('value');
  await userSelect.selectOption(fabrica ?? '');
  await page.locator(`a[href="/obras/${rev}"]`).first().click();
  await page.getByRole('link', { name: 'Abrir modelo 3D' }).click();
  await expect(page.locator('[data-load="ready"]')).toBeVisible({ timeout: 15_000 });
  testInfo.annotations.push({ type: 'obra', description: `E2E-REV ${rev}` });

  const fake3d = page.getByTestId('fake-3d');
  const piece = (dbid: number) => fake3d.getByRole('button', { name: `Peça ${dbid}` });
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  const banner = page.getByRole('region', { name: 'Versão nova' });
  const legend = page.getByRole('region', { name: 'Legenda' });
  const ORANGE = '#E8743B';
  const GREEN = '#33A06F';

  // Banner da versão nova
  await expect(banner).toContainText('V2 comparada com a V1:');
  await expect(banner).toContainText(/2 novas\s*·\s*1 a revisar\s*·\s*2 órfãs/);

  // Marca com seção alterada: laranja e o diff 40x60 → 40x80
  await expect(piece(10)).toHaveAttribute('data-base-color', ORANGE);
  await expect(piece(11)).toHaveAttribute('data-base-color', ORANGE);
  await expect(legend.getByRole('button', { name: 'Revisar: 1 marca' })).toBeVisible();
  await piece(10).click();
  await expect(header(page)).toHaveText('PP001 · Structural Columns · 2 peças');
  const alert = panel.getByRole('region', { name: 'Revisar' });
  await expect(alert).toContainText('Seção: 40x60 → 40x80');
  await expect(alert).toContainText('Altura: 60.0 cm → 80.0 cm');

  // Atalho A revisar (pelo banner)
  await banner.getByRole('button', { name: '1 a revisar' }).click();
  await expect(page.getByRole('heading', { name: 'Marcas (1)' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Marcas (1)' })).toContainText('PP001');

  // Manter valores: sai de revisão, fica verde (Tipo de forma preenchido)
  await alert.getByRole('button', { name: 'Manter valores' }).click();
  await expect(alert).toBeHidden();
  await expect(piece(10)).toHaveAttribute('data-base-color', GREEN);
  await expect(banner).toContainText(/0 a revisar/);

  // Filtro de sistema "Novas na versão"
  await applySaved(page, 'Novas na versão');
  await expect(page.getByRole('list', { name: 'Marcas (2)' })).toContainText('PP004A');
  await expect(page.getByRole('list', { name: 'Marcas (2)' })).toContainText('PP007');
  // Filtro de sistema "Órfãs"
  await applySaved(page, 'Órfãs');
  await expect(page.getByRole('list', { name: 'Marcas (2)' })).toContainText('PP005');
  await removeFilters(page);

  // Órfãs: religar PP004 → PP004A clicando no 3D (peça 17)
  await page.getByRole('button', { name: /^Gerenciar/ }).click(); // gestão recolhida no "Gerenciar"
  await page.getByRole('button', { name: 'Marcas órfãs' }).click();
  const dialog = page.getByRole('dialog', { name: 'Marcas órfãs' });
  await expect(dialog).toContainText('PP004');
  await expect(dialog).toContainText('Tipo de forma: F-12');
  await dialog.getByRole('button', { name: 'Religar PP004' }).click();
  await expect(page.getByRole('status', { name: 'Religar órfã' })).toContainText('Religar PP004');
  await piece(17).click();
  const confirm = page.getByRole('dialog', { name: 'Religar órfã' });
  await expect(confirm).toContainText('Religar PP004 (Structural Columns) → PP004A (Structural Columns)?');
  await confirm.getByRole('button', { name: 'Religar' }).click();
  await expect(page.getByText('PP004 religada a PP004A: 1 valor copiado.')).toBeVisible();
  await expect(piece(17)).toHaveAttribute('data-base-color', GREEN);
  await expect(panel.getByLabel('Valores da marca')).toContainText('Tipo de forma *F-12');

  // Arquivar PP005: a fila esvazia
  await page.getByRole('button', { name: /^Gerenciar/ }).click(); // gestão recolhida no "Gerenciar"
  await page.getByRole('button', { name: 'Marcas órfãs' }).click();
  await dialog.getByRole('button', { name: 'Arquivar PP005' }).click();
  await expect(dialog.getByText('Nenhuma órfã pendente.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Fechar' }).click();
  await expect(banner).toContainText(/0 órfãs/);
});

test('Fase 7 com o Viewer real: R02 chega e o PP005 (60x60 → 80x80) fica a revisar', async ({ page }, testInfo) => {
  const rec = process.env.E2E_REC_OBRA_ID;
  test.skip(!REAL || !rec, 'modo real com E2E_REC_OBRA_ID (obra criada por tests.real_revisions)');
  test.setTimeout(120_000);
  await page.goto('/obras');
  const userSelect = page.getByLabel('Usuário (simulado)');
  const fabrica = await userSelect.locator('option', { hasText: '(Fábrica)' }).first().getAttribute('value');
  await userSelect.selectOption(fabrica ?? '');
  await page.locator(`a[href="/obras/${rec ?? ''}"]`).first().click();
  await page.getByRole('link', { name: 'Abrir modelo 3D' }).click();
  await expect(page.locator('[data-load="ready"]')).toBeVisible({ timeout: MAX_LOAD_MS + 30_000 });
  const banner = page.getByRole('region', { name: 'Versão nova' });
  await expect(banner).toContainText(/1 a revisar/);
  await expect(page.getByRole('region', { name: 'Legenda' }).getByRole('button', { name: 'Revisar: 1 marca' })).toBeVisible();
  await banner.getByRole('button', { name: '1 a revisar' }).click();
  await page.getByRole('list', { name: 'Marcas (1)' }).getByRole('button', { name: /^PP005/ }).click();
  const alert = page.getByRole('complementary', { name: 'Peça selecionada' }).getByRole('region', { name: 'Revisar' });
  await expect(alert).toContainText('SEÇÃO-Largura: 60.000 cm → 80.000 cm');
  await expect(alert).toContainText('PEÇA-Comprimento: 660.000 cm → 690.000 cm');
  await page.waitForTimeout(1500); // deixa o Viewer enquadrar
  await testInfo.attach('pp005-a-revisar', { body: await page.screenshot(), contentType: 'image/png' });
  await page.screenshot({ path: testInfo.outputPath('pp005-a-revisar.png') });
});

test('tempo real: dois navegadores, a edição de um aparece no outro sem recarregar', async ({ browser, page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  test.skip(testInfo.project.name !== 'desktop', 'um perfil basta (dois contextos no mesmo teste)');
  // Estado inicial: PP002 sem "Tipo de forma".
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string; name: string }[];
  const fab = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers: fab })
  ).json()) as { mark_id: number; code: string }[];
  const pp002 = marks.find((m) => m.code === 'PP002')?.mark_id ?? 0;
  const reset = await page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
    headers: fab,
    data: { mark_ids: [pp002], changes: { [process.env.E2E_PARAM_DEF_ID ?? '0']: null }, mode: 'overwrite' },
  });
  expect(reset.ok()).toBe(true);

  async function open(p: Page, who: string): Promise<void> {
    await p.goto('/obras');
    const sel = p.getByLabel('Usuário (simulado)');
    const value = await sel.locator('option', { hasText: who }).first().getAttribute('value');
    await sel.selectOption(value ?? '');
    await p.locator(`a[href="/obras/${obraId()}"]`).first().click();
    await p.getByRole('link', { name: 'Abrir modelo 3D' }).click();
    await expect(p.locator('[data-load="ready"]')).toBeVisible({ timeout: 15_000 });
  }

  // A: projetos, olhando o PP002
  const ctxA = await browser.newContext();
  const a = await ctxA.newPage();
  await a.route('https://developer.api.autodesk.com/modelderivative/v2/viewers/**', (route) =>
    route.request().url().endsWith('viewer3D.min.js')
      ? route.fulfill({ path: FAKE_VIEWER, contentType: 'application/javascript' })
      : route.fulfill({ body: '', contentType: 'text/css' }),
  );
  await a.route('**/api/viewer-token', (route) =>
    route.fulfill({ json: { access_token: 'E2E', token_type: 'Bearer', expires_in: 600, region: 'US' } }),
  );
  await a.addInitScript((pieces) => {
    (window as unknown as { __E2E_PIECES: unknown }).__E2E_PIECES = pieces;
  }, PIECES);
  await open(a, '(Projetos)');
  await a.getByTestId('fake-3d').getByRole('button', { name: 'Peça 12' }).click();
  const panelA = a.getByRole('complementary', { name: 'Peça selecionada' });
  await expect(panelA.getByLabel('Valores da marca')).toContainText('Tipo de forma *—');
  await expect(a.getByTestId('fake-3d').getByRole('button', { name: 'Peça 12' })).toHaveAttribute('data-base-color', '#B9BEC6');

  // B: fábrica edita o PP002 (página padrão do teste)
  await open(page, '(Fábrica)');
  await page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 12' }).click();
  const panelB = page.getByRole('complementary', { name: 'Peça selecionada' });
  await panelB.getByRole('button', { name: 'Editar' }).click();
  await panelB.getByLabel(/Tipo de forma/).selectOption('F-13');
  await panelB.getByRole('button', { name: 'Salvar' }).click();
  await expect(panelB.getByLabel('Valores da marca')).toContainText('Tipo de forma *F-13');

  // A recebe sem recarregar: aviso, valor, cor e progresso
  const fabName = users.find((u) => u.role === 'fabrica')?.name ?? '';
  await expect(a.getByRole('log', { name: 'Atualizações da obra' })).toContainText(`${fabName} alterou PP002`, { timeout: 10_000 });
  await expect(panelA.getByLabel('Valores da marca')).toContainText('Tipo de forma *F-13');
  await expect(a.getByTestId('fake-3d').getByRole('button', { name: 'Peça 12' })).toHaveAttribute('data-base-color', '#33A06F');
  // B não recebe aviso da própria edição
  await expect(page.getByRole('log', { name: 'Atualizações da obra' })).not.toContainText('alterou PP002');
  await ctxA.close();
});

// ------------------------------------------------------------------ Fase 8.2

/** Viewer falso + token simulado numa página (para contextos extras). */
async function fakeViewerOn(p: Page, dbids: number[]): Promise<void> {
  await p.route('https://developer.api.autodesk.com/modelderivative/v2/viewers/**', (route) =>
    route.request().url().endsWith('viewer3D.min.js')
      ? route.fulfill({ path: FAKE_VIEWER, contentType: 'application/javascript' })
      : route.fulfill({ body: '', contentType: 'text/css' }),
  );
  await p.route('**/api/viewer-token', (route) =>
    route.fulfill({ json: { access_token: 'E2E', token_type: 'Bearer', expires_in: 600, region: 'US' } }),
  );
  await p.addInitScript((pieces) => {
    (window as unknown as { __E2E_PIECES: unknown }).__E2E_PIECES = pieces;
  }, dbids.map((dbid) => ({ dbid, label: `Peça ${String(dbid)}` })));
}

/** Peças da E2E-REV (v1 ∪ v2). */
const REV_PIECES = [10, 11, 14, 15, 16, 17, 18, 19, 20, 21, 22, 30, 40, 41];

async function openRev(p: Page, rev: string, who: '(Fábrica)' | '(Projetos)'): Promise<void> {
  await p.goto('/obras');
  const sel = p.getByLabel('Usuário (simulado)');
  const value = await sel.locator('option', { hasText: who }).first().getAttribute('value');
  await sel.selectOption(value ?? '');
  await p.locator(`a[href="/obras/${rev}"]`).first().click();
  await p.getByRole('link', { name: 'Abrir modelo 3D' }).click();
  await expect(p.locator('[data-load="ready"]')).toBeVisible({ timeout: 15_000 });
}

test('troca de versão: a anterior abre em modo consulta (somente leitura) e volta para a ativa', async ({ page }) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  test.setTimeout(90_000);
  const { runSeed } = await import('./global-setup');
  const rev = String(runSeed().rev_obra_id);
  await fakeViewerOn(page, REV_PIECES);
  await openRev(page, rev, '(Fábrica)');

  const select = page.getByRole('combobox', { name: 'Versão ativa' });
  await expect(select.locator('option:checked')).toHaveText(/^V2.* \(ativa\)$/);
  await expect(page.getByRole('region', { name: 'Modo consulta' })).toBeHidden();
  const panel = page.getByRole('complementary', { name: 'Peça selecionada' });
  const fake3d = page.getByTestId('fake-3d');

  // V1: modo consulta
  const rev01 = (await select.locator('option', { hasText: 'V1 ' }).textContent()) ?? '';
  await select.selectOption({ label: rev01 });
  const banner = page.getByRole('region', { name: 'Modo consulta' });
  await expect(banner).toContainText('Visualizando V1 · somente leitura');
  await expect(page.locator('[data-load="ready"]')).toBeVisible();
  // PP005 só existe na V1 (sumiu na V2): consultável, com os valores atuais da marca
  await fake3d.getByRole('button', { name: 'Peça 18' }).click();
  await expect(header(page)).toHaveText('PP005 · Structural Columns · 1 peça');
  await expect(panel.getByRole('note')).toContainText('valem para a versão ativa (V2)');
  await expect(panel.getByLabel('Valores da marca')).toContainText('Tipo de forma *F-13');
  await expect(panel.getByRole('button', { name: 'Editar' })).toHaveCount(0);
  await page.getByRole('button', { name: /^Gerenciar/ }).click(); // gestão recolhida no "Gerenciar"
  await expect(page.getByRole('button', { name: '+ Novo parâmetro' })).toHaveCount(0);
  // PP001 na V1: em revisão, mas sem ações; propriedades da V1 (40x60)
  await fake3d.getByRole('button', { name: 'Peça 10' }).click();
  await expect(panel.getByRole('region', { name: 'Revisar' })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Manter valores' })).toHaveCount(0);
  await panel.getByLabel('Filtrar propriedades').fill('Seção');
  await expect(panel.getByLabel('Dados de identidade')).toContainText('40x60');

  // Voltar para a versão ativa
  await banner.getByRole('button', { name: 'Voltar para a versão ativa' }).click();
  await expect(banner).toBeHidden();
  await expect(select.locator('option:checked')).toHaveText(/^V2 /);
  await expect(page.locator('[data-load="ready"]')).toBeVisible();
  await fake3d.getByRole('button', { name: 'Peça 10' }).click();
  await panel.getByLabel('Filtrar propriedades').fill('Seção');
  await expect(panel.getByLabel('Dados de identidade')).toContainText('40x80');
  await expect(panel.getByRole('button', { name: 'Manter valores' })).toBeVisible();
});

test('aceite da Fase 8: dois navegadores recebem a versão nova e as edições sem recarregar', async ({ browser, page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  test.skip(testInfo.project.name !== 'desktop', 'um perfil basta (dois contextos no mesmo teste)');
  test.setTimeout(120_000);
  const { runSeed } = await import('./global-setup');
  const rev = String(runSeed().rev_obra_id);

  // A: projetos (outro navegador) · B: fábrica
  const ctxA = await browser.newContext();
  const a = await ctxA.newPage();
  await fakeViewerOn(a, REV_PIECES);
  await fakeViewerOn(page, REV_PIECES);
  await openRev(a, rev, '(Projetos)');
  await openRev(page, rev, '(Fábrica)');

  // Chega a V3 (processada como o worker faz, com eventos no Redis)
  const childProcess = await import('node:child_process');
  childProcess.execFileSync('uv', ['run', 'python', '-m', 'tests.e2e_new_version'], {
    cwd: resolve(process.cwd(), '../backend'),
    encoding: 'utf-8',
    shell: process.platform === 'win32',
  });
  for (const p of [a, page]) {
    const banner = p.getByRole('region', { name: 'Nova versão disponível' });
    await expect(banner).toContainText('Nova versão disponível: V3 acabou de ficar pronta.', { timeout: 15_000 });
    // a versão aberta (V2) virou anterior: modo consulta, sem trocar o modelo sozinho
    await expect(p.getByRole('region', { name: 'Modo consulta' })).toContainText('Visualizando V2 · somente leitura');
    await banner.getByRole('button', { name: 'Carregar' }).click();
    await expect(p.getByRole('region', { name: 'Modo consulta' })).toBeHidden();
    await expect(p.getByRole('combobox', { name: 'Versão ativa' }).locator('option:checked')).toHaveText(/^V3.* \(ativa\)$/);
    await expect(p.locator('[data-load="ready"]')).toBeVisible();
  }

  // B edita o PP007 na V3; A vê sem recarregar
  const fakeA = a.getByTestId('fake-3d');
  await fakeA.getByRole('button', { name: 'Peça 19' }).click();
  const panelA = a.getByRole('complementary', { name: 'Peça selecionada' });
  await expect(panelA.getByLabel('Valores da marca')).toContainText('Tipo de forma *—');
  await page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 19' }).click();
  const panelB = page.getByRole('complementary', { name: 'Peça selecionada' });
  await panelB.getByRole('button', { name: 'Editar' }).click();
  await panelB.getByLabel(/Tipo de forma/).selectOption('F-12');
  await panelB.getByRole('button', { name: 'Salvar' }).click();
  await expect(a.getByRole('log', { name: 'Atualizações da obra' })).toContainText('alterou PP007', { timeout: 10_000 });
  await expect(panelA.getByLabel('Valores da marca')).toContainText('Tipo de forma *F-12');
  await expect(fakeA.getByRole('button', { name: 'Peça 19' })).toHaveAttribute('data-base-color', '#33A06F');
  await ctxA.close();
  runSeed(); // tira a V3 (estado limpo para os próximos testes)
});

// ------------------------------------------------------------------ Fase 9.1

test('Exportar Excel: o arquivo tem as mesmas marcas, quantidades e valores da tela (com filtro)', async ({ page }, testInfo) => {
  test.skip(REAL, 'usa a obra de teste semeada');
  // Estado: PP001 = F-12, demais sem valor
  const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
  const fab = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
  const marks = (await (
    await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers: fab })
  ).json()) as { mark_id: number; code: string }[];
  const defId = process.env.E2E_PARAM_DEF_ID ?? '0';
  const apply = (codes: string[], value: string | null) =>
    page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
      headers: fab,
      data: { mark_ids: marks.filter((m) => codes.includes(m.code)).map((m) => m.mark_id), changes: { [defId]: value }, mode: 'overwrite' },
    });
  expect((await apply(['PP001', 'PP002', 'V-01'], null)).ok()).toBe(true);
  expect((await apply(['PP001'], 'F-12')).ok()).toBe(true);

  await openModel(page, testInfo);
  await searchObjects(page, 'PP');
  const list = page.getByRole('list', { name: 'Marcas (2)' });
  await expect(list).toBeVisible();
  await closePopovers(page);
  const onScreen = await list.locator('.mark-item').evaluateAll((items) =>
    items.map((el) => {
      const code = el.querySelector('.mark-item__code')?.textContent ?? '';
      const qty = /\d+/.exec(el.querySelector('.mark-item__qty')?.textContent ?? '')?.[0] ?? '';
      return `${code} ${qty}`;
    }),
  );
  await page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 10' }).click();
  await expect(page.getByRole('complementary', { name: 'Peça selecionada' }).getByLabel('Valores da marca')).toContainText('Tipo de forma *F-12');

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Exportar Excel' }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^E2E-01_V1_\d{4}-\d{2}-\d{2}\.xlsx$/);
  const file = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(file);
  const { execFileSync } = await import('node:child_process');
  const out = execFileSync('uv', ['run', 'python', '-m', 'tests.read_xlsx', file], {
    cwd: resolve(process.cwd(), '../backend'),
    encoding: 'utf-8',
    shell: process.platform === 'win32',
  });
  const book = JSON.parse(out.trim().split('\n').at(-1) ?? '{}') as Record<string, unknown>;
  const rows = book.Marcas as Record<string, unknown>[];
  // mesmas linhas da lista (busca "PP"): marca e quantidade de peças, na mesma ordem
  expect(onScreen).toEqual(['PP001 2', 'PP002 2']);
  expect(rows.map((r) => `${String(r.Marca)} ${String(r['Peças'])}`)).toEqual(onScreen);
  // mesmos valores do painel
  expect(rows.find((r) => r.Marca === 'PP001')?.['Tipo de forma']).toBe('F-12');
  expect(rows.find((r) => r.Marca === 'PP002')?.['Tipo de forma']).toBeNull();
  expect(rows.find((r) => r.Marca === 'PP001')?.Status).toBe('Completa');
  expect((book.Peças as unknown[]).length).toBe(4);
  expect(book['Marcas:layout']).toEqual({ freeze: 'A2', filter: 'A1:J3' }); // + coluna Data de expedição (F3)
  expect((book.Sobre as Record<string, unknown>).Filtros).toBe('texto "PP"');
});

// ------------------------------------------------------------------ F3: filtros no estilo Dalux

test.describe('Filtros (F3)', () => {
  test.skip(REAL, 'usa a obra de teste semeada (filtros salvos e Data de expedição)');
  const piece = (page: Page, dbid: number) => page.getByTestId('fake-3d').getByRole('button', { name: `Peça ${dbid}` });
  const rows = (page: Page) => page.getByRole('list', { name: /^Marcas/ }).getByRole('button');

  test('aplicar um filtro salvo', async ({ page }, testInfo) => {
    // Estado conhecido: PP001 com Tipo de forma (completa), PP002 e V-01 vazias (pendentes)
    const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
    const fab = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
    const marks = (await (
      await page.request.get(`/api/versions/${process.env.E2E_VERSION_ID ?? ''}/marks`, { headers: fab })
    ).json()) as { mark_id: number; code: string }[];
    const defId = process.env.E2E_PARAM_DEF_ID ?? '0';
    const apply = (codes: string[], value: string | null) =>
      page.request.post(`/api/obras/${obraId()}/marks/batch-apply`, {
        headers: fab,
        data: { mark_ids: marks.filter((m) => codes.includes(m.code)).map((m) => m.mark_id), changes: { [defId]: value }, mode: 'overwrite' },
      });
    expect((await apply(['PP002', 'V-01'], null)).ok()).toBe(true);
    expect((await apply(['PP001'], 'F-11')).ok()).toBe(true);

    await openModel(page, testInfo);
    await applySaved(page, 'Pendentes'); // de sistema: Destacar o status Pendente
    const pop = filterPop(page);
    await expect(pop.getByRole('list', { name: 'Filtros ativos' })).toContainText('Destacar · Status de produção: é igual a Pendente');
    await expect(rows(page)).toHaveText([/PP002.*2 de 2 peças/, /V-01.*2 de 2 peças/]);
    await closePopovers(page);
    for (const dbid of [12, 13, 20, 21]) await expect(piece(page, dbid)).toHaveAttribute('data-state', 'normal');
    await expect(piece(page, 10)).toHaveAttribute('data-state', 'esmaecida');
    // destacar: o que não bate fica esmaecido, nada oculto; a peça sem marca não tem status
    await expect(piece(page, 30)).toHaveAttribute('data-state', 'esmaecida');
    await expect(viewerBar(page).getByRole('button', { name: 'Remover filtros' })).toBeVisible();
  });

  test('regra de data "no mês atual" num parâmetro da fábrica', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const pop = await openFilter(page);
    await pop.getByRole('button', { name: '+ Adicionar filtro' }).click();
    const picker = page.getByRole('dialog', { name: 'Selecionar parâmetro' });
    await picker.getByRole('searchbox', { name: 'Buscar parâmetro' }).fill('expedicao');
    await picker.getByRole('region', { name: 'Fábrica' }).getByRole('button', { name: /Data de expedição/ }).click();
    const step = page.getByRole('dialog', { name: 'Data de expedição' });
    await expect(step.getByRole('combobox', { name: 'Operador' })).toHaveValue('this_month');
    await step.getByRole('button', { name: 'Adicionar' }).click();
    await expect(pop.getByRole('list', { name: 'Filtros ativos' })).toContainText('Data de expedição: no mês atual');
    // só o PP001 foi expedido neste mês (V-01: há um ano)
    await expect(rows(page)).toHaveText([/PP001.*2 de 2 peças/]);
    await closePopovers(page);
    for (const dbid of [10, 11]) await expect(piece(page, dbid)).toHaveAttribute('data-state', 'normal');
    for (const dbid of [12, 13, 20, 21, 30]) await expect(piece(page, dbid)).toBeHidden() /* oculta */;
  });

  test('salvar como filtro pessoal e reabrir', async ({ page }, testInfo) => {
    const name = `Térreo ${testInfo.project.name}`;
    await openModel(page, testInfo);
    const pop = await openFilter(page);
    await pop.getByRole('button', { name: /^Nível/ }).click();
    await pop.getByRole('group', { name: 'Nível' }).getByRole('checkbox', { name: /TÉRREO/ }).check();
    await pop.getByRole('button', { name: 'Salvar' }).click();
    await pop.getByRole('menuitem', { name: 'Salvar como novo…' }).click();
    const save = page.getByRole('dialog', { name: 'Salvar filtro' });
    await save.getByRole('textbox', { name: 'Nome' }).fill(name);
    await expect(save.getByRole('checkbox', { name: /Compartilhar/ })).not.toBeChecked(); // pessoal por padrão
    await save.getByRole('button', { name: 'Salvar' }).click();
    await expect(pop.getByText(`Filtro "${name}" salvo.`)).toBeVisible();
    await expect(pop.getByRole('list', { name: 'Meus' }).getByRole('button', { name: new RegExp(name) })).toHaveAttribute('aria-pressed', 'true');

    // Reabre a tela do zero e aplica o filtro salvo
    await removeFilters(page);
    await openModel(page, testInfo); // de novo, pela lista de obras (o usuário simulado fica só em memória)
    await applySaved(page, name);
    await expect(filterPop(page).getByRole('list', { name: 'Filtros ativos' })).toContainText('Nível: TÉRREO');
    await expect(page.getByRole('list', { name: /^Marcas \(2\)/ })).toBeVisible();
  });

  test('remover filtros volta tudo ao normal', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const pop = await openFilter(page);
    await pop.getByRole('button', { name: 'Avançado' }).click();
    const editor = page.getByRole('dialog', { name: 'Editar filtro' });
    await editor.getByRole('combobox', { name: 'Modo da nova regra' }).selectOption('hide');
    await editor.getByRole('combobox', { name: 'Parâmetro da nova regra' }).selectOption({ label: 'Categoria' });
    await editor.getByRole('combobox', { name: 'Valor da regra 1' }).fill('Structural Framing');
    await editor.getByRole('button', { name: 'Aplicar' }).click();
    await expect(pop.getByRole('list', { name: 'Filtros ativos' })).toContainText('Ocultar · Categoria: é igual a Structural Framing');
    await closePopovers(page);
    for (const dbid of [20, 21]) await expect(piece(page, dbid)).toBeHidden() /* oculta */;
    await expect(page).toHaveURL(/[?&]f=/);

    await removeFilters(page);
    for (const dbid of [10, 11, 12, 13, 20, 21, 30]) await expect(piece(page, dbid)).toHaveAttribute('data-state', 'normal');
    await expect(rows(page)).toHaveCount(3);
    await expect(rows(page).first()).toHaveText(/^PP001.*2 peças(, (Pendente|Parcial|Completa|Revisar))?$/); // o status vai no fim (leitor de tela)
    await expect(page).not.toHaveURL(/[?&]f=/);
  });

  test('um link com filtro abre já filtrado', async ({ page, browser }, testInfo) => {
    await openModel(page, testInfo);
    await searchObjects(page, 'V-01');
    await expect(rows(page)).toHaveText([/V-01.*2 de 2 peças/]);
    await expect(page).toHaveURL(/[?&]f=/);
    const link = page.url();

    // outro navegador (sem estado), mesmo usuário: o link abre filtrado
    const other = await browser.newContext();
    const second = await other.newPage();
    await second.route('https://developer.api.autodesk.com/modelderivative/v2/viewers/**', (route) =>
      route.request().url().endsWith('viewer3D.min.js')
        ? route.fulfill({ path: FAKE_VIEWER, contentType: 'application/javascript' })
        : route.fulfill({ body: '', contentType: 'text/css' }),
    );
    await second.route('**/api/viewer-token', (route) =>
      route.fulfill({ json: { access_token: 'E2E', token_type: 'Bearer', expires_in: 600, region: 'US' } }),
    );
    await second.addInitScript((pieces) => {
      (window as unknown as { __E2E_PIECES: unknown }).__E2E_PIECES = pieces;
    }, PIECES);
    // o usuário simulado fica só em memória: escolhe-o na lista de obras e segue o link
    await second.goto('/obras');
    const userSelect = second.getByLabel('Usuário (simulado)');
    const fabrica = await userSelect.locator('option', { hasText: '(Fábrica)' }).first().getAttribute('value');
    await userSelect.selectOption(fabrica ?? '');
    await second.evaluate((url) => {
      history.pushState({}, '', url);
      dispatchEvent(new PopStateEvent('popstate'));
    }, link);
    await expect(second.locator('[data-load="ready"]')).toBeVisible({ timeout: 15_000 });
    await expect(rows(second)).toHaveText([/V-01.*2 de 2 peças/]);
    await expect(viewerBar(second).getByRole('button', { name: 'Remover filtros' })).toBeVisible();
    for (const dbid of [20, 21]) await expect(piece(second, dbid)).toHaveAttribute('data-state', 'normal');
    await expect(piece(second, 10)).toHaveAttribute('data-state', 'esmaecida');
    await other.close();
  });
});

// ------------------------------------------------------------------ F4: coloração

test.describe('Coloração (F4)', () => {
  test.skip(REAL, 'usa a obra de teste semeada');
  const piece = (page: Page, dbid: number) => page.getByTestId('fake-3d').getByRole('button', { name: `Peça ${dbid}` });
  const legend = (page: Page) => page.getByRole('region', { name: 'Legenda' });
  const SELECTED = '#3C3C3C';

  test('colorir por um parâmetro da fábrica e conferir a legenda; a seleção fica grafite por cima', async ({ page }, testInfo) => {
    await formaOnlyPP001(page);
    await openModel(page, testInfo);
    await colorByField(page, 'Tipo de forma');
    await page.keyboard.press('Escape');
    await expect(legend(page).getByRole('heading')).toHaveText('Tipo de forma');
    const f11 = legend(page).getByRole('button', { name: 'F-11: 1 marca · 2 peças' });
    const none = legend(page).getByRole('button', { name: /^Sem valor: 2 marcas · 5 peças/ });
    await expect(f11).toBeVisible();
    await expect(none).toBeVisible(); // PP002, V-01 e a peça sem marca
    const f11Color = await f11.locator('.legend__dot').evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(f11Color).toMatch(/^rgb\(/);
    for (const dbid of [12, 13, 20, 21, 30]) await expect(piece(page, dbid)).toHaveAttribute('data-color', '#9AA0A6');
    const pp001 = await piece(page, 10).getAttribute('data-color');
    expect(pp001).not.toBe('#9AA0A6');
    await expect(piece(page, 11)).toHaveAttribute('data-color', pp001 ?? '');

    // clicar no item seleciona as peças do valor; a seleção fica grafite por cima da cor
    await f11.click();
    await expect(header(page)).toHaveText('PP001 · Structural Columns · 2 peças');
    for (const dbid of [10, 11]) await expect(piece(page, dbid)).toHaveAttribute('data-color', SELECTED);
    await page.getByRole('button', { name: 'Limpar seleção' }).click();
    await expect(piece(page, 10)).toHaveAttribute('data-color', pp001 ?? '');

    // retrair a legenda (pílula com resumo), expandir, e "Remover coloração" volta às cores originais
    await legend(page).getByRole('button', { name: 'Retrair legenda' }).click();
    await expect(legend(page)).toBeHidden();
    await page.getByRole('button', { name: /^Expandir legenda: Tipo de forma · / }).click();
    await expect(legend(page)).toBeVisible();
    await viewerBar(page).getByRole('button', { name: 'Remover coloração' }).click();
    await expect(legend(page)).toBeHidden();
    for (const dbid of [10, 12, 30]) await expect(piece(page, dbid)).not.toHaveAttribute('data-color', /.+/);
  });

  test('esquema com 2 regras: a ordem define a prioridade', async ({ page }, testInfo) => {
    await formaOnlyPP001(page); // pendentes: PP002 (12, 13) e V-01 (20, 21)
    await openModel(page, testInfo);
    await (await colorPop(page)).getByRole('button', { name: 'Editar cores' }).click(); // fica no popover Colorir
    const cores = page.getByRole('dialog', { name: 'Cores' });

    // regra 1: filtro salvo de sistema "Pendentes", vermelho
    await cores.getByRole('button', { name: 'Adicionar' }).click();
    let rule = page.getByRole('dialog', { name: 'Adicionar regra' });
    await rule.getByRole('combobox', { name: 'Filtro salvo' }).selectOption({ label: 'Pendentes (sistema)' });
    await rule.getByLabel('Cor').fill('#ff0000');
    await rule.getByRole('button', { name: 'OK' }).click();

    // regra 2: filtro NOVO "Térreo" (Nível = TÉRREO), verde
    const terreo = `Térreo cores ${testInfo.project.name}`;
    await cores.getByRole('button', { name: 'Adicionar' }).click();
    rule = page.getByRole('dialog', { name: 'Adicionar regra' });
    await rule.getByRole('radio', { name: 'Novo filtro' }).click();
    await rule.getByRole('textbox', { name: 'Nome do filtro' }).fill(terreo);
    await rule.getByRole('searchbox', { name: 'Buscar parâmetro' }).fill('nivel');
    await rule.getByRole('button', { name: /^Nível/ }).first().click();
    await rule.getByRole('combobox', { name: 'Valor' }).fill('TÉRREO');
    await rule.getByLabel('Cor').fill('#00ff00');
    await rule.getByRole('button', { name: 'OK' }).click();
    await expect(rule).toBeHidden();

    // prévia: a peça 20 (pendente E térreo) fica com a 1ª regra
    const counts = cores.locator('tbody tr').locator('td:last-child');
    await expect(counts).toHaveText(['4', '2']); // Pendentes: 12,13,20,21 · Térreo: 10,11 (a 20 já foi)
    await cores.getByRole('button', { name: 'Mover para cima' }).click(); // a 2ª está selecionada
    await expect(counts).toHaveText(['3', '3']); // Térreo: 10,11,20 · Pendentes: 12,13,21

    await cores.getByRole('textbox', { name: 'Nome do esquema' }).fill(`Prioridade ${testInfo.project.name}`);
    await cores.getByRole('button', { name: 'Salvar' }).click();
    await expect(cores).toBeHidden();
    await expect(legend(page).getByRole('heading')).toHaveText(`Prioridade ${testInfo.project.name}`);
    await expect(legend(page).getByRole('button', { name: new RegExp(`^${terreo}: .* 3 peças`) })).toBeVisible();
    for (const dbid of [10, 11, 20]) await expect(piece(page, dbid)).toHaveAttribute('data-color', '#00FF00');
    await expect(piece(page, 30)).not.toHaveAttribute('data-color', /.+/); // nenhuma regra: cor original
    for (const dbid of [12, 13, 21]) await expect(piece(page, dbid)).toHaveAttribute('data-color', '#FF0000');

    // o esquema salvo aparece no seletor da janela e reabre com as regras na ordem
    await (await colorPop(page)).getByRole('button', { name: 'Editar cores' }).click(); // fica no popover Colorir
    await expect(cores.getByRole('combobox', { name: 'Esquema de cores' }).locator('option:checked')).toHaveText(new RegExp(`Prioridade ${testInfo.project.name}`));
    await expect(cores.locator('tbody tr')).toHaveText([new RegExp(terreo), /Pendentes/]);
    await cores.getByRole('button', { name: 'Cancelar' }).click();
  });

  test('cor por gama numa data', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const pop = await colorByField(page, 'Data de expedição');
    await pop.getByRole('checkbox', { name: 'Cor por gama' }).check();
    await page.keyboard.press('Escape');
    await expect(legend(page).getByRole('heading')).toHaveText('Data de expedição (por gama)');
    const rows = legend(page).getByRole('button', { name: /: / });
    // V-01 (há um ano) na 1ª faixa, PP001 (hoje) na última; o resto sem valor
    const year = new Date(Date.now() - 365 * 86_400_000).toISOString().slice(0, 10);
    await expect(rows.first()).toHaveAccessibleName(new RegExp(`^${year} – .*: 1 marca · 2 peças`));
    await expect(rows.last()).toHaveAccessibleName(/^Sem valor: 1 marca · 3 peças/);
    await expect(piece(page, 20)).toHaveAttribute('data-color', '#FBE3B0');
    await expect(piece(page, 10)).toHaveAttribute('data-color', '#A86500');
    await expect(piece(page, 12)).toHaveAttribute('data-color', '#9AA0A6');
  });
});

test.describe('Parâmetros por peça (P4)', () => {
  test.skip(REAL, 'usa a obra de teste E2E-PEC (P-06 com 6 pilares)');
  const pec = () => process.env.E2E_PEC_OBRA_ID ?? '';
  const defId = () => process.env.E2E_PEC_PARAM_DEF_ID ?? '0';
  const PEC_PIECES = [10, 11, 12, 13, 14, 15, 20, 21];
  const piece = (page: Page, dbid: number) => page.getByTestId('fake-3d').getByRole('button', { name: `Peça ${String(dbid)}` });
  const panel = (page: Page) => page.getByRole('complementary', { name: 'Peça selecionada' });
  const cell = (page: Page, n: number) =>
    panel(page).getByRole('button', { name: new RegExp(`^Data de fabricação de P-06-${String(n)}:`) });
  const today = () => {
    const d = new Date();
    return `${String(d.getFullYear())}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  const br = (iso: string) => iso.split('-').reverse().join('/');

  interface Unit {
    id: number;
    number: number;
    element: { dbid: number } | null;
    values: { def_id: number; value: unknown }[];
  }

  /** Unidades da P-06 pela API (usuário da fábrica). */
  async function units(page: Page): Promise<{ headers: Record<string, string>; list: Unit[] }> {
    const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
    const headers = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
    const marks = (await (
      await page.request.get(`/api/versions/${process.env.E2E_PEC_VERSION_ID ?? ''}/marks`, { headers })
    ).json()) as { mark_id: number; code: string }[];
    const markId = marks.find((m) => m.code === 'P-06')?.mark_id ?? 0;
    const body = (await (await page.request.get(`/api/obras/${pec()}/marks/${String(markId)}/units`, { headers })).json()) as {
      units: Unit[];
    };
    return { headers, list: body.units.filter((u) => u.element !== null).sort((a, b) => a.number - b.number) };
  }

  /** Estado conhecido: as 6 peças vazias; `filled` (nºs das unidades) com a data de hoje. */
  async function setValues(page: Page, filled: number[] = []): Promise<Unit[]> {
    const { headers, list } = await units(page);
    const post = (ids: number[], value: string | null) =>
      page.request.post(`/api/obras/${pec()}/units/batch-apply`, {
        headers,
        data: { unit_ids: ids, changes: { [defId()]: value }, mode: 'overwrite' },
      });
    expect((await post(list.map((u) => u.id), null)).ok()).toBe(true);
    const ids = list.filter((u) => filled.includes(u.number)).map((u) => u.id);
    if (ids.length) expect((await post(ids, today())).ok()).toBe(true);
    return list;
  }

  const filledNumbers = async (page: Page) =>
    (await units(page)).list
      .filter((u) => u.values.some((v) => String(v.def_id) === defId() && v.value !== null))
      .map((u) => u.number);

  test('preencher a 3ª unidade de uma marca de 6 só muda essa peça', async ({ page }, testInfo) => {
    const list = await setValues(page);
    const third = list.find((u) => u.number === 3)?.element?.dbid ?? 0;
    const fifth = list.find((u) => u.number === 5)?.element?.dbid ?? 0;
    await fakeViewerOn(page, PEC_PIECES);
    await openRev(page, pec(), '(Fábrica)');
    testInfo.annotations.push({ type: 'obra', description: `E2E-PEC ${pec()}` });

    // Clique no 3D: seleciona a marca inteira e foca a linha da peça clicada.
    await piece(page, third).click();
    await expect(panel(page).getByRole('heading', { level: 3 })).toHaveText('P-06 · Structural Columns · 6 peças');
    const table = panel(page).getByRole('table', { name: 'Peças da marca' });
    await expect(table.getByRole('row')).toHaveCount(7);
    await expect(table.getByRole('row', { selected: true })).toContainText('P-06-3');
    // Um grupo só: PARÂMETROS DA FÁBRICA > Parâmetros por marca / Parâmetros por peça.
    const factory = panel(page).getByRole('region', { name: 'Parâmetros da fábrica' });
    await expect(factory.getByRole('region', { name: 'Parâmetros por marca' })).toBeVisible();
    await expect(factory.getByRole('region', { name: 'Parâmetros por peça' }).getByRole('table')).toBeVisible();
    for (const u of list) await expect(piece(page, u.element?.dbid ?? 0)).toHaveAttribute('aria-pressed', 'true');

    // Edição na célula: escolher a data só preenche o campo; Enter confirma e grava.
    await cell(page, 3).click();
    await panel(page).getByLabel('Data de fabricação de P-06-3').fill(today());
    await page.keyboard.press('Enter');
    await expect(cell(page, 3)).toHaveText(br(today()));
    for (const n of [1, 2, 4, 5, 6]) await expect(cell(page, n)).toHaveText('—');
    expect(await filledNumbers(page)).toEqual([3]);

    // Clicar numa linha destaca só aquela peça no 3D; clicar no 3D volta para a marca.
    await table.getByRole('button', { name: 'Mostrar P-06-5 no modelo' }).click();
    await expect(piece(page, fifth)).toHaveAttribute('aria-pressed', 'true');
    await expect(piece(page, third)).toHaveAttribute('aria-pressed', 'false');
    await expect(table.getByRole('row', { selected: true })).toContainText('P-06-5');
    await piece(page, third).click();
    await expect(piece(page, fifth)).toHaveAttribute('aria-pressed', 'true');
    await expect(table.getByRole('row', { selected: true })).toContainText('P-06-3');

    // Persiste após recarregar.
    await openRev(page, pec(), '(Fábrica)');
    await piece(page, third).click();
    await expect(cell(page, 3)).toHaveText(br(today()));
    await expect(cell(page, 1)).toHaveText('—');
  });

  test('catálogo: o botão Excluir é um link vermelho com texto legível', async ({ page }) => {
    await fakeViewerOn(page, PEC_PIECES);
    await openRev(page, pec(), '(Fábrica)');
    await page.getByRole('button', { name: /^Gerenciar/ }).click(); // gestão recolhida no "Gerenciar"
    await page.getByRole('button', { name: 'Catálogo', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Catálogo de parâmetros da fábrica' });
    const del = dialog.getByRole('button', { name: 'Excluir Data de fabricação' });
    await expect(del).toHaveText(/Excluir/);
    const look = await del.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { bg: cs.backgroundColor, color: cs.color };
    });
    expect(look.bg).toBe('rgba(0, 0, 0, 0)'); // sem o retângulo preenchido
    expect(look.color).not.toBe(look.bg);
    expect(look.color).not.toBe('rgb(255, 255, 255)');
  });

  test('preencher em lote 4 unidades com "Preencher selecionadas" e Desfazer', async ({ page }) => {
    const list = await setValues(page);
    await fakeViewerOn(page, PEC_PIECES);
    await openRev(page, pec(), '(Fábrica)');
    await piece(page, list[0]?.element?.dbid ?? 0).click();
    const table = panel(page).getByRole('table', { name: 'Peças da marca' });
    for (const n of [1, 2, 4, 5]) await table.getByRole('checkbox', { name: `Marcar P-06-${String(n)}` }).check();
    await panel(page).getByRole('button', { name: 'Preencher selecionadas (4)' }).click();

    const dialog = page.getByRole('dialog', { name: 'Preencher 4 peças' });
    await dialog.getByLabel('Data de fabricação').fill(today());
    await dialog.getByRole('button', { name: 'Aplicar' }).click();
    await expect(dialog).toContainText('4 peças serão alteradas.');
    await dialog.getByRole('button', { name: 'Confirmar' }).click();
    await expect(dialog).toBeHidden();

    await expect(page.getByText('Valores aplicados a 4 peças.')).toBeVisible();
    for (const n of [1, 2, 4, 5]) await expect(cell(page, n)).toHaveText(br(today()));
    for (const n of [3, 6]) await expect(cell(page, n)).toHaveText('—');
    expect(await filledNumbers(page)).toEqual([1, 2, 4, 5]);

    await page.getByRole('button', { name: 'Desfazer' }).click();
    for (const n of [1, 2, 4, 5]) await expect(cell(page, n)).toHaveText('—');
    expect(await filledNumbers(page)).toEqual([]);
  });

  test('filtrar pelo parâmetro por peça mostra só as peças preenchidas', async ({ page }, testInfo) => {
    const list = await setValues(page, [2, 5]);
    const dbid = (n: number) => list.find((u) => u.number === n)?.element?.dbid ?? 0;
    await fakeViewerOn(page, PEC_PIECES);
    await openRev(page, pec(), '(Fábrica)');
    testInfo.annotations.push({ type: 'obra', description: `E2E-PEC ${pec()}` });

    const pop = await openFilter(page);
    await pop.getByRole('button', { name: '+ Adicionar filtro' }).click();
    const picker = page.getByRole('dialog', { name: 'Selecionar parâmetro' });
    await picker.getByRole('searchbox', { name: 'Buscar parâmetro' }).fill('fabricacao');
    await picker.getByRole('region', { name: 'Fábrica' }).getByRole('button', { name: /Data de fabricação/ }).click();
    const step = page.getByRole('dialog', { name: 'Data de fabricação' });
    await expect(step.getByRole('combobox', { name: 'Operador' })).toHaveValue('this_month');
    await step.getByRole('button', { name: 'Adicionar' }).click();
    await expect(pop.getByRole('list', { name: 'Filtros ativos' })).toContainText('Data de fabricação: no mês atual');
    await expect(page.getByRole('list', { name: /^Marcas/ }).getByRole('button')).toHaveText([/P-06.*2 de 6 peças/]);
    await closePopovers(page);
    for (const n of [2, 5]) await expect(piece(page, dbid(n))).toHaveAttribute('data-state', 'normal');
    for (const n of [1, 3, 4, 6]) await expect(piece(page, dbid(n))).toBeHidden();
    for (const v of [20, 21]) await expect(piece(page, v)).toBeHidden();
  });
});

test.describe('Unidades órfãs (P5)', () => {
  test.skip(REAL, 'usa a obra de teste E2E-PECREV (v2 sem uma peça da P-06)');
  const piece = (page: Page, dbid: number) => page.getByTestId('fake-3d').getByRole('button', { name: `Peça ${String(dbid)}` });
  const panel = (page: Page) => page.getByRole('complementary', { name: 'Peça selecionada' });

  interface Unit {
    id: number;
    label: string;
    status: string;
    element: { dbid: number } | null;
    values: { value: unknown }[];
  }

  test('v2 com uma peça a menos deixa a unidade órfã com os valores; religar a outra peça recupera os valores', async ({ page }, testInfo) => {
    const { runSeed } = await import('./global-setup');
    const obra = String(runSeed().pecrev_obra_id); // estado inicial: v2 acabou de chegar
    testInfo.annotations.push({ type: 'obra', description: `E2E-PECREV ${obra}` });
    const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
    const headers = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
    const api = async <T,>(path: string): Promise<T> => (await (await page.request.get(`/api${path}`, { headers })).json()) as T;

    // A unidade da peça que saiu ficou órfã, com o valor.
    const [orphan] = await api<{ id: number; label: string; mark_id: number; values: { value: unknown }[] }[]>(
      `/obras/${obra}/unit-orphans`,
    );
    expect(orphan?.values.map((v) => v.value)).toHaveLength(1);
    const raw = orphan?.values[0]?.value;
    const date = typeof raw === 'string' ? raw : '';
    const br = date.split('-').reverse().join('/');
    const label = orphan?.label ?? '';

    await fakeViewerOn(page, [10, 11, 13, 14, 15, 20, 21]); // peças da pecas_v2 (sem a 12)
    await openRev(page, obra, '(Fábrica)');

    // Banner: a unidade que perdeu a peça (com valores) e o atalho para a fila.
    const banner = page.getByRole('region', { name: 'Versão nova' }).getByRole('group', { name: 'Peças' });
    await expect(banner).toContainText(`1 perdeu a peça nesta versão, com valores: ${label}`);
    await banner.getByRole('button', { name: '1 peça órfã' }).click();

    const dialog = page.getByRole('dialog', { name: 'Peças órfãs' });
    const list = dialog.getByRole('list', { name: 'Peças órfãs abertas' });
    await expect(list).toContainText(label);
    await expect(list).toContainText(`Data de fabricação: ${br}`);
    await expect(list).toContainText('Sem peça desde a versão 2');

    // Religar a uma peça vazia da mesma marca.
    await dialog.getByRole('button', { name: `Religar ${label}` }).click();
    const target = dialog.getByRole('list', { name: 'Peças de P-06' }).getByRole('button', { name: /vazia/ }).last();
    const targetLabel = ((await target.locator('b').textContent()) ?? '').trim();
    const before = await api<{ units: Unit[] }>(`/obras/${obra}/marks/${String(orphan?.mark_id)}/units`);
    const dbid = before.units.find((u) => u.label === targetLabel)?.element?.dbid ?? 0;
    await target.click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('status')).toContainText(`${label} religada à peça que era da ${targetLabel}: os valores voltaram.`);

    // A peça mostra a unidade religada com o valor recuperado.
    await piece(page, dbid).click();
    const table = panel(page).getByRole('table', { name: 'Peças da marca' });
    await expect(table.getByRole('row', { selected: true })).toContainText(label);
    await expect(panel(page).getByRole('button', { name: `Data de fabricação de ${label}: ${br}` })).toBeVisible();
    await expect(table).not.toContainText(targetLabel);

    // Fila vazia; tudo auditado no histórico da unidade.
    expect(await api<unknown[]>(`/obras/${obra}/unit-orphans`)).toEqual([]);
    const history = await api<{ action: string }[]>(`/obras/${obra}/units/${String(orphan?.id)}/history`);
    expect(history.map((h) => h.action)).toEqual(expect.arrayContaining(['orphan', 'relink']));
    await page.getByRole('button', { name: /^Gerenciar/ }).click(); // gestão recolhida no "Gerenciar"
    await page.getByRole('button', { name: 'Peças órfãs', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Peças órfãs' })).toContainText('Nenhuma peça órfã pendente.');
  });
});

test.describe('Coordenadas do eixo', () => {
  test.skip(REAL, 'usa a geometria do Viewer falso (valores conhecidos)');
  const piece = (page: Page, dbid: number) => page.getByTestId('fake-3d').getByRole('button', { name: `Peça ${String(dbid)}` });
  const coords = (page: Page) =>
    page.getByRole('complementary', { name: 'Peça selecionada' }).getByRole('table', { name: 'Coordenadas do eixo' });
  const cells = async (page: Page, row: number) =>
    (await coords(page).getByRole('row').nth(row).getByRole('cell').allTextContents()).slice(0, 3);

  test('pilar mostra X, Y, Z do eixo na base; viga mostra início e fim; marcador no 3D', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const panel = page.getByRole('complementary', { name: 'Peça selecionada' });

    // Pilar (PP001, 2 peças): coordenadas da peça CLICADA, em metros, ponto base do projeto
    await piece(page, 10).click();
    await expect(panel.getByRole('heading', { name: 'Coordenadas do eixo (ponto base do projeto)' })).toBeVisible();
    await expect(coords(page).getByRole('row')).toHaveCount(2);
    await expect.poll(() => cells(page, 1)).toEqual(['33,728', '67,256', '0,914']);
    await expect(panel.getByText(/Pilar · centro da seção na base · em metros/)).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Copiar Pilar: 33,728; 67,256; 0,914' })).toBeVisible();
    await expect(page.getByTestId('fake-3d')).toHaveAttribute('data-eixo', 'ponto');
    // a seleção destaca a marca inteira, mas a outra peça dela tem as suas coordenadas
    await expect(piece(page, 11)).toHaveAttribute('aria-pressed', 'true');
    await piece(page, 11).click();
    await expect.poll(() => cells(page, 1)).toEqual(['47,396', '61,112', '1,524']);

    // Viga: início e fim do eixo, na meia altura
    await piece(page, 20).click();
    const rows = coords(page).getByRole('row');
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(1).getByRole('rowheader')).toHaveText('Início');
    await expect(rows.nth(2).getByRole('rowheader')).toHaveText('Fim');
    await expect.poll(() => cells(page, 1)).toEqual(['33,528', '70,104', '4,524']);
    await expect.poll(() => cells(page, 2)).toEqual(['41,528', '70,104', '4,524']);
    await expect(page.getByTestId('fake-3d')).toHaveAttribute('data-eixo', 'linha');

    // Sem seleção: some o marcador e a seção
    await page.getByRole('button', { name: 'Limpar seleção' }).click();
    await expect(page.getByTestId('fake-3d')).not.toHaveAttribute('data-eixo', /.*/);
    await expect(coords(page)).toBeHidden();
  });
});

// Bug relatado em 2026-11-16 (docs/bugs/data-por-peca.md): o editor de DATA por peça grava
// a cada tecla (ano 0002) e não deixa corrigir. Estes testes FALHAM até a correção.
test.describe('Bug: editor de data por peça (docs/bugs/data-por-peca.md)', () => {
  test.skip(REAL, 'usa a obra de teste E2E-PEC');
  test.use({ locale: 'pt-BR' }); // campo de data no formato dd/mm/aaaa, como no tablet da fábrica
  const pec = () => process.env.E2E_PEC_OBRA_ID ?? '';
  const defId = () => process.env.E2E_PEC_PARAM_DEF_ID ?? '0';
  const panel = (page: Page) => page.getByRole('complementary', { name: 'Peça selecionada' });
  const cell = (page: Page, label: string) =>
    panel(page).getByRole('button', { name: new RegExp(`^Data de fabricação de ${label}:`) });

  interface Unit {
    id: number;
    number: number;
    label: string;
    element: { dbid: number } | null;
    values: { def_id: number; value: unknown }[];
  }

  /** Unidades da P-06 e o cabeçalho da fábrica (API). */
  async function units(page: Page): Promise<{ headers: Record<string, string>; list: Unit[] }> {
    const users = (await (await page.request.get('/api/dev/users')).json()) as { id: number; role: string }[];
    const headers = { 'X-Dev-User': String(users.find((u) => u.role === 'fabrica')?.id ?? '') };
    const marks = (await (
      await page.request.get(`/api/versions/${process.env.E2E_PEC_VERSION_ID ?? ''}/marks`, { headers })
    ).json()) as { mark_id: number; code: string }[];
    const markId = marks.find((m) => m.code === 'P-06')?.mark_id ?? 0;
    const body = (await (await page.request.get(`/api/obras/${pec()}/marks/${String(markId)}/units`, { headers })).json()) as {
      units: Unit[];
    };
    return { headers, list: body.units.filter((u) => u.element !== null).sort((a, b) => a.number - b.number) };
  }

  /** Zera a data da P-06-n (e, se `value`, grava esse valor) pela API. */
  async function setUnit(page: Page, n: number, value: string | null): Promise<Unit> {
    const { headers, list } = await units(page);
    const unit = list.find((u) => u.number === n);
    if (!unit) throw new Error(`P-06-${String(n)} não encontrada`);
    const post = (v: string | null) =>
      page.request.post(`/api/obras/${pec()}/units/batch-apply`, {
        headers,
        data: { unit_ids: [unit.id], changes: { [defId()]: v }, mode: 'overwrite' },
      });
    expect((await post(null)).ok()).toBe(true);
    if (value) expect((await post(value)).ok()).toBe(true);
    return unit;
  }

  async function valueOf(page: Page, n: number): Promise<unknown> {
    const { list } = await units(page);
    return list.find((u) => u.number === n)?.values.find((v) => String(v.def_id) === defId())?.value ?? null;
  }

  /** Abre o modelo da E2E-PEC e seleciona a peça da unidade. Devolve as gravações (PUT). */
  async function open(page: Page, unit: Unit): Promise<string[]> {
    const puts: string[] = [];
    page.on('request', (r) => {
      if (r.method() === 'PUT' && r.url().includes('/units/')) puts.push(r.postData() ?? '');
    });
    await fakeViewerOn(page, [10, 11, 12, 13, 14, 15, 20, 21]);
    await openRev(page, pec(), '(Fábrica)');
    await page.getByTestId('fake-3d').getByRole('button', { name: `Peça ${String(unit.element?.dbid ?? 0)}` }).click();
    return puts;
  }

  test('digitar 05052026 na célula grava 05/05/2026 (uma gravação só)', async ({ page }) => {
    const unit = await setUnit(page, 3, null);
    const puts = await open(page, unit);

    await cell(page, unit.label).click();
    const input = panel(page).getByLabel(`Data de fabricação de ${unit.label}`);
    await expect(input).toBeFocused();
    await page.keyboard.type('05052026', { delay: 80 });
    await page.keyboard.press('Enter');

    await expect(cell(page, unit.label)).toHaveText('05/05/2026');
    expect(await valueOf(page, 3)).toBe('2026-05-05');
    expect(puts).toHaveLength(1);
  });

  test('depois de salva, a célula reabre e a data pode ser corrigida', async ({ page }) => {
    const unit = await setUnit(page, 4, '2026-05-05');
    await open(page, unit);
    await expect(cell(page, unit.label)).toHaveText('05/05/2026');

    await cell(page, unit.label).click();
    const input = panel(page).getByLabel(`Data de fabricação de ${unit.label}`);
    await expect(input).toBeVisible();
    await expect(input).toHaveValue('2026-05-05');
    await page.keyboard.type('06062026', { delay: 80 });
    await page.keyboard.press('Enter');

    await expect(cell(page, unit.label)).toHaveText('06/06/2026');
    expect(await valueOf(page, 4)).toBe('2026-06-06');
  });

  test('data pela metade + Enter: avisa, não grava e não apaga a data antiga', async ({ page }) => {
    const unit = await setUnit(page, 5, '2026-05-05');
    const puts = await open(page, unit);
    await cell(page, unit.label).click();
    const input = panel(page).getByLabel(`Data de fabricação de ${unit.label}`);
    await expect(input).toBeFocused();
    await page.keyboard.type('0707', { delay: 80 }); // dia e mês; o ano fica pela metade
    await page.keyboard.press('Backspace');
    await page.keyboard.press('Enter');

    await expect(panel(page).getByText('Data inválida: use dd/mm/aaaa')).toBeVisible();
    await expect(input).toBeVisible(); // o editor continua aberto
    await page.keyboard.press('Escape');
    await expect(cell(page, unit.label)).toHaveText('05/05/2026');
    expect(puts).toHaveLength(0);
    expect(await valueOf(page, 5)).toBe('2026-05-05');
  });

  test('ano 0002: avisa abaixo do campo e não grava', async ({ page }) => {
    const unit = await setUnit(page, 6, null);
    const puts = await open(page, unit);
    await cell(page, unit.label).click();
    await expect(panel(page).getByLabel(`Data de fabricação de ${unit.label}`)).toBeFocused();
    await page.keyboard.type('05050002', { delay: 80 });
    await page.keyboard.press('Enter');

    await expect(panel(page).getByText('Data inválida: use dd/mm/aaaa')).toBeVisible();
    expect(puts).toHaveLength(0);
    expect(await valueOf(page, 6)).toBeNull();
  });
});

// ------------------------------------------------------------------ rolagem fantasma (docs/bugs/rolagem-fantasma.md)
test.describe('Tela da obra não rola como página', () => {
  test.skip(REAL, 'usa marcas simuladas');
  // 316 marcas COM status: o texto do status (só para leitor de tela) é o que vazava antes.
  const MARKS = Array.from({ length: 316 }, (_, i) => ({ mark_id: 9000 + i, code: `M${String(i + 1).padStart(3, '0')}`, category: 'Structural Columns', count: 2, dbids: [] }));
  const STATUS = {
    items: MARKS.map((m, i) => ({ mark_id: m.mark_id, status: (['pending', 'partial', 'complete', 'review'] as const)[i % 4] })),
    counts: [],
  };
  const pageHeights = (page: Page) =>
    page.evaluate(() => ({ doc: document.documentElement.scrollHeight, win: window.innerHeight, scrollY: window.scrollY }));

  for (const [w, h] of [[1440, 900], [1180, 820]] as const) {
    test(`${String(w)}x${String(h)}: documento do tamanho da janela com o painel aberto e fechado; a lista rola por dentro`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: w, height: h });
      await page.route(/\/api\/versions\/\d+\/marks$/, (route) => route.fulfill({ json: MARKS }));
      await page.route(/\/api\/versions\/\d+\/marks\/status$/, (route) => route.fulfill({ json: STATUS }));
      await openModel(page, testInfo);
      await expect(page.getByRole('heading', { name: 'Marcas (316)' })).toBeVisible();

      // painel esquerdo aberto
      expect(await pageHeights(page)).toEqual({ doc: h, win: h, scrollY: 0 });
      const left = page.locator('.model-left');
      const box = await left.evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
      expect(box.scroll).toBeGreaterThan(box.client); // a lista é maior que o painel…
      await left.evaluate((el) => { el.scrollTop = 600; });
      expect(await left.evaluate((el) => el.scrollTop)).toBeGreaterThan(0); // …e rola por dentro
      expect(await pageHeights(page)).toEqual({ doc: h, win: h, scrollY: 0 }); // sem mexer na página

      // fechar e abrir de novo: o documento continua do tamanho da janela e o Viewer é avisado
      const before = await page.evaluate(() => (window as unknown as { __E2E_RESIZES?: number }).__E2E_RESIZES ?? 0);
      await page.getByRole('button', { name: 'Esconder painel esquerdo' }).click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { __E2E_RESIZES?: number }).__E2E_RESIZES ?? 0)).toBeGreaterThan(before);
      expect(await pageHeights(page)).toEqual({ doc: h, win: h, scrollY: 0 });
      await page.getByRole('button', { name: 'Mostrar painel esquerdo' }).click();
      await expect(page.getByRole('heading', { name: 'Marcas (316)' })).toBeVisible();
      expect(await pageHeights(page)).toEqual({ doc: h, win: h, scrollY: 0 });
    });
  }
});

// ------------------------------------------------------------------ barra do visualizador móvel (FloatingPanel)
test.describe('Barra do visualizador móvel', () => {
  test.skip(REAL, 'usa o Viewer falso (barra nativa simulada)');
  const floating = (page: Page) => page.locator('.viewer-float');
  const grip = (page: Page) => page.getByRole('button', { name: 'Mover a barra do visualizador' });
  const rect = (page: Page, selector: string) =>
    page.locator(selector).first().evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
    });
  async function dragGrip(page: Page, dx: number, dy: number) {
    const box = await grip(page).boundingBox();
    if (!box) throw new Error('alça sem área visível');
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 4 });
    await page.mouse.move(x + dx, y + dy, { steps: 4 });
    await page.mouse.up();
  }

  test('padrão no topo, centralizada e longe da barra nativa (que fica clicável)', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const area = await rect(page, '.model-viewer');
    const bar = await rect(page, '.viewer-float');
    expect(bar.top - area.top).toBeLessThan(40);
    expect(Math.abs(bar.left + bar.width / 2 - (area.left + area.width / 2))).toBeLessThan(4);
    expect(bar.height).toBeLessThanOrEqual(testInfo.project.name === 'tablet' ? 48 : 36); // ~70%
    const native = await rect(page, '#guiviewer3d-toolbar');
    expect(bar.bottom).toBeLessThan(native.top); // não se sobrepõem
    // a barra nativa recebe o clique (o Playwright falha se algo estiver por cima)
    await page.getByRole('toolbar', { name: 'Barra nativa do Viewer' }).getByRole('button', { name: 'Órbita' }).click();
    expect(await page.evaluate(() => (window as unknown as { __E2E_NATIVE_CLICKS?: number }).__E2E_NATIVE_CLICKS)).toBe(1);
    // e o 3D fora do painel continua clicável (o painel não cobre a área toda)
    await page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 10' }).click();
    await expect(page.getByTestId('fake-3d').getByRole('button', { name: 'Peça 10' })).toHaveAttribute('aria-pressed', 'true');
  });

  test('arrastar muda a posição, que fica guardada ao recarregar; duplo clique volta ao padrão', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const before = await rect(page, '.viewer-float');
    const area = await rect(page, '.model-viewer');
    await dragGrip(page, -120, 160);
    await expect(floating(page)).toHaveAttribute('data-moved', 'true');
    const moved = await rect(page, '.viewer-float');
    // no tablet a barra ocupa quase a largura do 3D: o arraste para a esquerda para na borda
    expect(Math.round(moved.left - before.left)).toBe(Math.round(Math.max(-120, area.left - before.left)));
    expect(Math.round(moved.top - before.top)).toBe(160);

    // recarregar (o usuário simulado é escolhido de novo): a barra volta para onde foi deixada
    await page.reload();
    await openModel(page, testInfo);
    await expect(floating(page)).toHaveAttribute('data-moved', 'true');
    const again = await rect(page, '.viewer-float');
    expect(Math.round(again.left)).toBe(Math.round(moved.left));
    expect(Math.round(again.top)).toBe(Math.round(moved.top));

    // duplo clique na alça: posição padrão (topo, centralizada)
    await grip(page).dblclick();
    await expect(floating(page)).toHaveAttribute('data-moved', 'false');
    const back = await rect(page, '.viewer-float');
    expect(Math.round(back.top)).toBe(Math.round(before.top));
    expect(Math.round(back.left)).toBe(Math.round(before.left));
  });

  test('arrastar além da borda mantém a barra dentro do 3D; o popover abre para cima perto do fundo', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    await dragGrip(page, 3000, 3000);
    const area = await rect(page, '.model-viewer');
    const bar = await rect(page, '.viewer-float');
    expect(bar.right).toBeLessThanOrEqual(area.right + 0.5);
    expect(bar.bottom).toBeLessThanOrEqual(area.bottom + 0.5);
    await dragGrip(page, -3000, -3000);
    const bar2 = await rect(page, '.viewer-float');
    expect(bar2.left).toBeGreaterThanOrEqual(area.left - 0.5);
    expect(bar2.top).toBeGreaterThanOrEqual(area.top - 0.5);

    // no canto de baixo, o popover abre para cima e fica dentro do 3D
    await dragGrip(page, 3000, 3000);
    await page.getByRole('toolbar', { name: 'Barra do visualizador' }).getByRole('button', { name: 'Colorir' }).click();
    const pop = await rect(page, '.viewer-bar__pop');
    const barLow = await rect(page, '.viewer-float');
    expect(pop.bottom).toBeLessThanOrEqual(barLow.top);
    expect(pop.top).toBeGreaterThanOrEqual(area.top - 0.5);
    expect(pop.left).toBeGreaterThanOrEqual(area.left - 0.5);
    expect(pop.right).toBeLessThanOrEqual(area.right + 0.5);
  });

  test('teclado: com a alça em foco, setas movem 10 px e Shift+setas 50 px', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const before = await rect(page, '.viewer-float');
    await grip(page).focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Shift+ArrowDown');
    await page.keyboard.press('ArrowLeft');
    const after = await rect(page, '.viewer-float');
    expect(Math.round(after.top - before.top)).toBe(60);
    expect(Math.round(after.left - before.left)).toBe(-10);
  });
});

// ------------------------------------------------------------------ legenda móvel e retrátil (FloatingPanel)
test.describe('Legenda móvel e retrátil', () => {
  test.skip(REAL, 'usa o Viewer falso');
  const legendPanel = (page: Page) => page.locator('.legend-float');
  const legendGrip = (page: Page) => page.getByRole('button', { name: 'Mover a legenda' });
  const box = (page: Page, selector: string) =>
    page.locator(selector).first().evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width };
    });
  async function drag(page: Page, dx: number, dy: number) {
    const b = await legendGrip(page).boundingBox();
    if (!b) throw new Error('alça da legenda sem área visível');
    const x = b.x + b.width / 2;
    const y = b.y + b.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx, y + dy, { steps: 6 });
    await page.mouse.up();
  }

  test('padrão no canto superior direito; retrair vira pílula com resumo e expandir volta', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const area = await box(page, '.model-viewer');
    const panel = await box(page, '.legend-float');
    expect(area.right - panel.right).toBeLessThan(20);
    await page.getByRole('button', { name: 'Retrair legenda' }).click();
    await expect(page.getByRole('region', { name: 'Legenda' })).toBeHidden();
    // o resumo depende do estado dos dados (ex.: "Status · 2 completas · 4 pendentes")
    const pill = page.getByRole('button', { name: /^Expandir legenda: Status · .*\d+ (pendentes?|completas?|parciais|parcial|a revisar)$/ });
    await expect(pill).toBeVisible();
    expect((await box(page, '.legend-float')).width).toBeLessThan(panel.width + 200); // pílula compacta, numa linha
    await pill.click();
    await expect(page.getByRole('region', { name: 'Legenda' })).toBeVisible();
  });

  test('arrastar e retrair: ao recarregar, posição e estado voltam; duplo clique volta ao canto', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const start = await box(page, '.legend-float');
    await drag(page, -200, 120);
    await expect(legendPanel(page)).toHaveAttribute('data-moved', 'true');
    const moved = await box(page, '.legend-float');
    expect(Math.round(moved.top - start.top)).toBe(120);
    await page.getByRole('button', { name: 'Retrair legenda' }).click();

    await page.reload();
    await openModel(page, testInfo);
    await expect(page.getByRole('button', { name: /^Expandir legenda: / })).toBeVisible(); // continua retraída
    const again = await box(page, '.legend-float');
    expect(Math.round(again.left)).toBe(Math.round(moved.left));
    expect(Math.round(again.top)).toBe(Math.round(moved.top));

    await legendGrip(page).dblclick();
    await expect(legendPanel(page)).toHaveAttribute('data-moved', 'false');
    const back = await box(page, '.legend-float');
    expect(Math.round(back.top)).toBe(Math.round(start.top));
  });

  test('a legenda não sai da área do 3D', async ({ page }, testInfo) => {
    await openModel(page, testInfo);
    const area = await box(page, '.model-viewer');
    await drag(page, 3000, 3000);
    let p = await box(page, '.legend-float');
    expect(p.right).toBeLessThanOrEqual(area.right + 0.5);
    expect(p.bottom).toBeLessThanOrEqual(area.bottom + 0.5);
    await drag(page, -3000, -3000);
    p = await box(page, '.legend-float');
    expect(p.left).toBeGreaterThanOrEqual(area.left - 0.5);
    expect(p.top).toBeGreaterThanOrEqual(area.top - 0.5);
  });
});
