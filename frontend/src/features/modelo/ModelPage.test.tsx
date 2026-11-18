import { act, fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { setDevUser } from '../../api/client';
import type { ModelVersion, Obra } from '../../api/obras';
import type { User } from '../../api/users';
import type { BatchPreview, BatchRequest } from '../../api/markBatch';
import type { ObraEvent } from '../../api/events';
import type { Orphan, VersionDiff } from '../../api/reconcile';
import type { MarkStatusResult, Progress } from '../../api/status';
import type { FieldValue, MarkValues } from '../../api/markValues';
import type { ParamDef, ParamDefBody } from '../../api/paramDefs';
import type { ElementDetail, MarkFacets, MarkPieces } from '../../api/versions';
import type { Evaluation, FilterDefinition, FilterField, FilterRule, SavedFilter } from '../../api/filters';
import type { ColorizeResult, ColorLegendItem, SchemeRule } from '../../api/colors';
import { AppRoutes } from '../../routes';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { DbId, SelectionListener, ViewerAdapter } from '../../viewer/ViewerAdapter';
import { ViewerFactoryProvider } from '../../viewer/ViewerProvider';
import { describeEvent } from '../live/eventText';
import { filenameFrom } from '../../api/export';

/** Muda um <input type="color"> (o user-event não abre o seletor do sistema). */
function fireColor(input: HTMLElement, value: string) {
  fireEvent.input(input, { target: { value } });
}

/** Painel da direita (a barra de progresso do rodapé também cita os parâmetros). */
const panel = () => within(screen.getByRole('complementary', { name: 'Peça selecionada' }));

const FABRICA: User = { id: 2, name: 'Fábio Fábrica', email: 'f@dev.local', role: 'fabrica' };
const PROJETOS: User = { id: 1, name: 'Paula Projetos', email: 'p@dev.local', role: 'projetos' };
const USERS_BY_ID: Record<string, User> = { '1': PROJETOS, '2': FABRICA };

const OBRA: Obra = {
  id: 7,
  code: 'OB-001',
  name: 'Galpão',
  acc_hub_id: 'b.h',
  acc_project_id: 'b.p',
  acc_folder_id: 'urn:f',
  acc_item_id: 'urn:i',
  acc_item_name: 'OBRA-001.rvt',
  active: true,
  acc_file_state: 'ok',
  acc_file_state_at: null,
  unit_numbering: 'sequence',
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
};

const version = (id: number, status: ModelVersion['status'] = 'ready'): ModelVersion => ({
  id,
  version_number: id,
  status,
  published_by: 'Projetos',
  published_at: '2026-11-01T12:00:00Z',
  comment: null,
  error: null,
  has_urn: true,
  urn: `urn-v${id}`,
});

const MARKS: MarkPieces[] = [
  { mark_id: 1, code: 'PP001', category: 'Structural Columns', count: 2, dbids: [10, 11] },
  { mark_id: 2, code: 'PP002', category: 'Structural Columns', count: 2, dbids: [12, 13] },
  { mark_id: 3, code: 'V-01', category: 'Structural Framing', count: 2, dbids: [20, 21] },
];

const element = (dbid: number): ElementDetail => {
  const mark = MARKS.find((m) => m.dbids.includes(dbid)) ?? null;
  return {
    dbid,
    external_id: `ext-${dbid}`,
    name: `Pilar [${dbid}]`,
    category: mark?.category ?? 'Structural Columns',
    mark_raw: mark?.code ?? null,
    mark,
    groups: [
      { name: 'Dados de identidade', properties: [{ name: 'Marca', value: mark?.code ?? '' }] },
      {
        name: 'Dimensões',
        properties: [
          { name: 'Altura', value: '50.0 cm' },
          { name: 'Largura', value: '40.0 cm' },
        ],
      },
      { name: 'Other', properties: [{ name: 'Category', value: 'Revit Structural Columns' }] },
    ],
  };
};

const FACETS: MarkFacets = {
  categories: [
    { value: 'Structural Columns', pieces: 4 },
    { value: 'Structural Framing', pieces: 2 },
  ],
  levels: [
    { value: '1º PAVIMENTO', pieces: 3 },
    { value: 'TÉRREO', pieces: 3 },
  ],
  pieces_without_level: 0,
};

/** Status calculado (falso): PP001 completa, PP002 parcial, V-01 pendente. */
const STATUS: MarkStatusResult = {
  items: [
    { mark_id: 1, status: 'complete' },
    { mark_id: 2, status: 'partial' },
    { mark_id: 3, status: 'pending' },
  ],
  counts: [
    { status: 'pending', marks: 1, pieces: 2 },
    { status: 'partial', marks: 1, pieces: 2 },
    { status: 'complete', marks: 1, pieces: 2 },
    { status: 'review', marks: 0, pieces: 0 },
  ],
};
const PROGRESS: Progress = {
  marks: 3,
  pieces: 6,
  required: [{ def_id: 1, name: 'Tipo de forma', marks_total: 2, marks_filled: 1, pieces_total: 4, pieces_filled: 2 }],
};
const statusOf = (markId: number) => STATUS.items.find((i) => i.mark_id === markId)?.status;

const STATUS_LABEL: Record<string, string> = { pending: 'Pendente', partial: 'Parcial', complete: 'Completa', review: 'Revisar' };

/** Campos do filtro (GET /fields). */
const FIELDS: FilterField[] = [
  { source: 'system', key: 'category', name: 'Categoria', group: 'Sistema', type: 'text', distinct_values: 2, pieces: 6 },
  { source: 'system', key: 'level', name: 'Nível', group: 'Sistema', type: 'text', distinct_values: 2, pieces: 6 },
  { source: 'system', key: 'mark', name: 'Nome da montagem', group: 'Sistema', type: 'text', distinct_values: 3, pieces: 6 },
  { source: 'system', key: 'status', name: 'Status de produção', group: 'Sistema', type: 'text', distinct_values: 3, pieces: 6 },
  { source: 'system', key: 'new', name: 'Nova na versão', group: 'Sistema', type: 'bool', distinct_values: 2, pieces: 6 },
  { source: 'factory', key: '5', name: 'Data de expedição', group: 'Fábrica', type: 'date', distinct_values: 1, pieces: 2 },
  { source: 'factory', key: '1', name: 'Tipo de forma', group: 'Fábrica', type: 'text', distinct_values: 2, pieces: 4 },
  { source: 'model', key: 'Dimensões/Altura', name: 'Altura', group: 'Dimensões', type: 'number', distinct_values: 2, pieces: 6 },
];

const systemFilter = (id: number, key: string, name: string, rule: FilterRule): SavedFilter => ({
  id, name, scope: 'shared', owner_id: null, obra_id: null, system_key: key, editable: false,
  definition: { mode: 'highlight', logic: 'and', rules: [rule] },
  created_at: '2026-11-13T12:00:00Z', updated_at: '2026-11-13T12:00:00Z', created_by: null, updated_by: null,
});
const statusRule = (label: string): FilterRule => ({ field: { source: 'system', key: 'status' }, op: 'eq', value: label });
const SAVED: SavedFilter[] = [
  systemFilter(1, 'pending', 'Pendentes', statusRule('Pendente')),
  systemFilter(2, 'partial', 'Parciais', statusRule('Parcial')),
  systemFilter(3, 'review', 'A revisar', statusRule('Revisar')),
  systemFilter(4, 'new', 'Novas na versão', { field: { source: 'system', key: 'new' }, op: 'eq', value: true }),
];

/** Motor de filtros falso (POST /filter/evaluate), com a combinação do Dalux: visíveis =
 * Isolar (E/OU) menos qualquer Ocultar; resultado = visíveis que batem em Destacar e no texto. */
const evalCalls: FilterDefinition[] = [];
function ruleMatches(m: MarkPieces, r: FilterRule): boolean {
  const key = `${r.field.source}:${r.field.key}`;
  if (key === 'system:category') return r.op === 'in' ? (r.value as string[]).includes(m.category) : m.category === r.value;
  if (key === 'system:status') return STATUS_LABEL[statusOf(m.mark_id) ?? ''] === r.value;
  if (key === 'system:new') return m.mark_id === 3;
  if (key === 'system:mark') return r.op === 'ne' ? m.code !== r.value : m.code === r.value;
  if (key === 'factory:5') return m.mark_id === 1; // "expedida no mês": só PP001
  return true;
}
function evaluateApi(req: FakeRequest): Evaluation {
  const def = req.body as FilterDefinition;
  evalCalls.push(def);
  const of = (mode: string) => def.rules.filter((r) => (r.mode ?? def.mode) === mode);
  const combine = (rules: FilterRule[], m: MarkPieces) =>
    rules.length === 0 || (def.logic === 'and' ? rules.every((r) => ruleMatches(m, r)) : rules.some((r) => ruleMatches(m, r)));
  const [iso, hide, hl] = [of('isolate'), of('hide'), of('highlight')];
  const q = (def.q ?? '').toLowerCase();
  const visible = MARKS.filter((m) => combine(iso, m) && !hide.some((r) => ruleMatches(m, r)));
  const result = visible.filter((m) => combine(hl, m) && m.code.toLowerCase().includes(q));
  const emphasis = hl.length > 0 || q !== '';
  const hidden = emphasis && (iso.length > 0 || hide.length > 0) ? MARKS.filter((m) => !visible.includes(m)).flatMap((m) => m.dbids) : [];
  return {
    mode: def.mode, logic: def.logic, total_pieces: 6,
    matched_pieces: result.reduce((n, m) => n + m.count, 0), matched_marks: result.length,
    pieces: result.flatMap((m) => m.dbids.map((dbid) => ({ dbid, mark_id: m.mark_id }))),
    dbids: result.flatMap((m) => m.dbids),
    groups: result.map((m) => ({ mark_id: m.mark_id, code: m.code, category: m.category, matched: m.count, total: m.count })),
    notes: [], view: emphasis ? 'highlight' : 'isolate', hidden_dbids: hidden,
  };
}

/** Coloração falsa (POST /colorize): status, categoria, Tipo de forma e Altura (gama). */
const colorizeCalls: { field: { source: string; key: string }; mode: string }[] = [];
const COLOR_OF: Record<string, string> = {
  Pendente: '#B9BEC6', Parcial: '#E3B341', Completa: '#33A06F',
  'Structural Columns': '#1F77B4', 'Structural Framing': '#FF7F0E', 'F-11': '#2CA02C',
};
function colorizeApi(req: FakeRequest): ColorizeResult {
  const body = req.body as { field: { source: string; key: string }; mode: 'distinct' | 'range' };
  colorizeCalls.push(body);
  const key = `${body.field.source}:${body.field.key}`;
  const valueOf = (m: MarkPieces): string | null =>
    key === 'system:status' ? (STATUS_LABEL[statusOf(m.mark_id) ?? ''] ?? null)
      : key === 'system:category' ? m.category
        : key === 'factory:1' ? (m.mark_id === 1 ? 'F-11' : null)
          : m.mark_id === 3 ? '2026-11-01' : '2026-11-20';
  const groups = new Map<string | null, number[]>();
  for (const m of MARKS) groups.set(valueOf(m), [...(groups.get(valueOf(m)) ?? []), ...m.dbids]);
  const colors: Record<string, string> = {};
  const legend: ColorLegendItem[] = [];
  for (const [value, dbids] of groups) {
    const color = value === null ? '#9AA0A6' : body.mode === 'range' ? (value < '2026-11-10' ? '#C6DBEF' : '#0B3C78') : (COLOR_OF[value] ?? '#AEC7E8');
    for (const d of dbids) colors[String(d)] = color;
    legend.push({ label: value ?? 'Sem valor', color, pieces: dbids.length, value, min: null, max: null, dbids });
  }
  legend.sort((a, b) => (a.value === null ? 1 : b.value === null ? -1 : b.pieces - a.pieces));
  const name = FIELDS.find((f) => `${f.source}:${f.key}` === key)?.name ?? key;
  return { mode: body.mode, field_name: name, field_type: 'text', colors, legend, total_pieces: 6 };
}

class FakeViewer implements ViewerAdapter {
  readonly listeners = new Set<SelectionListener>();
  load = vi.fn<(urn: string) => Promise<void>>(() => Promise.resolve());
  selectDbIds = vi.fn<(ids: DbId[]) => void>();
  isolate = vi.fn<(ids: DbId[]) => void>();
  highlight = vi.fn<(ids: DbId[]) => void>();
  hide = vi.fn<(ids: DbId[]) => void>();
  showAll = vi.fn();
  fitTo = vi.fn<(ids?: DbId[]) => void>();
  resize = vi.fn<() => void>();
  setColors = vi.fn();
  clearColors = vi.fn();
  destroy = vi.fn();
  onSelect(listener: SelectionListener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  click(ids: DbId[]) {
    act(() => { this.listeners.forEach((l) => { l(ids); }); });
  }
}

interface RenderOptions {
  userId?: string;
  routes?: Parameters<typeof installFakeApi>[0];
}

function renderModel(
  versions: ModelVersion[],
  route = '/obras/7/modelo',
  viewer = new FakeViewer(),
  { userId = '2', routes = {} }: RenderOptions = {},
) {
  installFakeApi({
    'GET /api/me': (req: FakeRequest) => {
      const u = USERS_BY_ID[req.headers.get('X-Dev-User') ?? ''];
      return u ? { ...u, can_share_filters: u.role === 'fabrica' } : Response.json({}, { status: 401 });
    },
    'GET /api/dev/users': [PROJETOS, FABRICA],
    'GET /api/param-defs': [],
    ...Object.fromEntries(
      MARKS.map((m) => [
        `GET /api/obras/7/marks/${m.mark_id}/values`,
        { mark: { id: m.mark_id, code: m.code, category: m.category }, values: [], last_change_by: null, last_change_at: null },
      ]),
    ),
    // P4: sem parâmetros por peça (a tabela por peça não aparece; tem testes próprios).
    ...Object.fromEntries(
      MARKS.map((m) => [
        `GET /api/obras/7/marks/${m.mark_id}/units`,
        { mark: { id: m.mark_id, code: m.code, category: m.category }, version_id: 1, params: [], units: [] },
      ]),
    ),
    'GET /api/obras/7': OBRA,
    'GET /api/obras/7/versions': versions,
    'GET /api/versions/1/marks': MARKS,
    'POST /api/versions/1/filter/evaluate': evaluateApi,
    'POST /api/versions/2/filter/evaluate': evaluateApi,
    'GET /api/versions/1/fields': FIELDS,
    'GET /api/versions/2/fields': FIELDS,
    'GET /api/versions/1/fields/system/category/values': [
      { value: 'Structural Columns', pieces: 4 },
      { value: 'Structural Framing', pieces: 2 },
    ],
    'GET /api/versions/1/fields/system/level/values': [{ value: 'TÉRREO', pieces: 3 }],
    'GET /api/saved-filters': SAVED,
    'POST /api/versions/1/colorize': colorizeApi,
    'POST /api/versions/2/colorize': colorizeApi,
    'GET /api/color-schemes': [],
    'GET /api/versions/1/marks/facets': FACETS,
    'GET /api/versions/1/marks/status': STATUS,
    'GET /api/versions/2/marks/status': STATUS,
    'GET /api/versions/1/progress': PROGRESS,
    'GET /api/versions/2/progress': PROGRESS,
    'GET /api/versions/2/marks/facets': FACETS,
    'GET /api/versions/2/marks': MARKS,
    'GET /api/versions/1/elements/11': element(11),
    'GET /api/versions/1/elements/10': element(10),
    'GET /api/versions/1/elements/20': element(20),
    'GET /api/versions/1/elements/21': element(21),
    'GET /api/versions/1/elements/30': element(30),
    ...routes,
  });
  setDevUser(userId);
  const containers: HTMLElement[] = [];
  const view = renderWithProviders(
    <ViewerFactoryProvider
      factory={(el) => {
        containers.push(el);
        return viewer;
      }}
    >
      <AppRoutes />
    </ViewerFactoryProvider>,
    route,
  );
  return { viewer, containers, view };
}

/** textContent sem os trechos .sr-only (só para leitor de tela). */
function visibleText(el: HTMLElement): string {
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('.sr-only').forEach((n) => { n.remove(); });
  return copy.textContent ?? '';
}

describe('Tela do modelo', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('mostra barra com obra e versão ativa, 3 colunas e carrega a versão pronta mais recente', async () => {
    const { viewer, containers } = renderModel([version(3, 'processing'), version(2), version(1)]);

    expect(await screen.findByText('OB-001 — Galpão')).toBeInTheDocument();
    const select = screen.getByRole('combobox', { name: 'Versão ativa' });
    await vi.waitFor(() => { expect(select).toHaveValue('2'); }); // v3 ainda processando
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      expect.stringMatching(/^V2 · .+ \(ativa\)$/),
      expect.stringMatching(/^V1 · [^(]+$/),
    ]);
    expect(screen.queryByRole('region', { name: 'Modo consulta' })).not.toBeInTheDocument();

    expect(screen.getByRole('complementary', { name: 'Marcas e filtros' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Modelo 3D' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Peça selecionada' })).toBeInTheDocument();

    expect(containers).toEqual([screen.getByTestId('viewer-container')]);
    await vi.waitFor(() => { expect(viewer.load).toHaveBeenCalledWith('urn-v2'); });
  });

  it('esconder e mostrar os painéis laterais; a escolha fica no navegador', async () => {
    const user = userEvent.setup();
    const { view, viewer } = renderModel([version(1)]);
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    const left = screen.getByRole('button', { name: 'Esconder painel esquerdo' });
    expect(left).toHaveAttribute('aria-expanded', 'true');
    const resizes = viewer.resize.mock.calls.length;
    await user.click(left);
    // a área do 3D mudou: o Viewer é avisado pelo ViewerAdapter (não por um "resize" falso na janela)
    await vi.waitFor(() => { expect(viewer.resize.mock.calls.length).toBeGreaterThan(resizes); });
    expect(screen.queryByRole('complementary', { name: 'Marcas e filtros' })).not.toBeInTheDocument(); // hidden
    expect(screen.getByRole('button', { name: 'Mostrar painel esquerdo' })).toHaveAttribute('aria-expanded', 'false');
    await user.click(screen.getByRole('button', { name: 'Esconder painel direito' }));
    expect(screen.queryByRole('complementary', { name: 'Peça selecionada' })).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('cassol-elo:paineis') ?? '{}')).toEqual({ left: false, right: false });

    // reabrir a tela mantém a escolha; mostrar de novo volta ao normal
    view.unmount();
    renderModel([version(1)]);
    await user.click(await screen.findByRole('button', { name: 'Mostrar painel esquerdo' }));
    expect(screen.getByRole('complementary', { name: 'Marcas e filtros' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Mostrar painel direito' }));
    expect(screen.getByRole('complementary', { name: 'Peça selecionada' })).toBeInTheDocument();
    localStorage.clear();
  });

  it('trocar a versão carrega o outro modelo; a anterior abre em modo consulta e dá para voltar', async () => {
    const { viewer } = renderModel([version(2), version(1)]);
    const user = userEvent.setup();
    await vi.waitFor(() => { expect(viewer.load).toHaveBeenCalledWith('urn-v2'); });
    await user.selectOptions(screen.getByRole('combobox', { name: 'Versão ativa' }), '1');
    await vi.waitFor(() => { expect(viewer.load).toHaveBeenLastCalledWith('urn-v1'); });
    const banner = await screen.findByRole('region', { name: 'Modo consulta' });
    expect(banner).toHaveTextContent('Visualizando V1 · somente leitura');
    await user.click(within(banner).getByRole('button', { name: 'Voltar para a versão ativa' }));
    await vi.waitFor(() => { expect(viewer.load).toHaveBeenLastCalledWith('urn-v2'); });
    expect(screen.getByRole('combobox', { name: 'Versão ativa' })).toHaveValue('2');
    expect(screen.queryByRole('region', { name: 'Modo consulta' })).not.toBeInTheDocument();
  });

  it('modo consulta: valores atuais da marca com aviso, sem edição', async () => {
    const field: FieldValue = {
      def_id: 1, name: 'Tipo de forma', type: 'list', unit: null, required: true, options: ['F-11'],
      value: 'F-11', row_version: 1, updated_at: null, updated_by_name: null,
    };
    const { viewer } = renderModel([version(2), version(1)], '/obras/7/modelo?versao=1', undefined, {
      routes: {
        'GET /api/versions/1/elements/10': element(10),
        'GET /api/obras/7/marks/1/values': {
          mark: { id: 1, code: 'PP001', category: 'Structural Columns', review_status: 'review', review_note: 'Seção: 40x60 → 40x80' },
          values: [field], last_change_by: null, last_change_at: null,
        },
      },
    });
    await screen.findByRole('region', { name: 'Modo consulta' });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    viewer.click([10]);
    expect(await panel().findByRole('note')).toHaveTextContent('Valores atuais da marca: valem para a versão ativa (V2).');
    expect(await panel().findByLabelText('Valores da marca')).toHaveTextContent('Tipo de forma *F-11');
    expect(panel().queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(panel().queryByRole('button', { name: 'Manter valores' })).not.toBeInTheDocument();
    expect(panel().queryByRole('button', { name: '+ Novo parâmetro' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '+ Novo parâmetro' })).not.toBeInTheDocument();
    viewer.click([10, 20]); // várias marcas: lote também só leitura
    expect(await panel().findByText('2 marcas selecionadas')).toBeInTheDocument();
    expect(panel().queryByRole('button', { name: 'Editar em lote' })).not.toBeInTheDocument();
  });

  it('layout: status de produção na lista de marcas e no cabeçalho; parâmetros antes das coordenadas', async () => {
    const { viewer } = renderModel([version(1)]);
    const list = await screen.findByRole('list', { name: 'Marcas (3)' });
    // status agregado da marca no nome acessível da linha (no fim: a linha continua começando pelo código)
    await vi.waitFor(() => { expect(within(list).getByRole('button', { name: /^PP001/ })).toHaveAccessibleName(/, Completa$/); });
    expect(within(list).getByRole('button', { name: /^PP002/ })).toHaveAccessibleName(/, Parcial$/);

    viewer.click([11]);
    const panel = await screen.findByRole('complementary', { name: 'Peça selecionada' });
    await within(panel).findByRole('heading', { name: 'PP001 · Structural Columns · 2 peças' });
    expect(within(panel).getByTitle('Status de produção da marca')).toHaveTextContent('Completa');
    const headings = within(panel).getAllByRole('heading', { level: 4 }).map((h) => h.textContent ?? '');
    const factory = headings.findIndex((t) => t.startsWith('Parâmetros da fábrica'));
    const props = headings.findIndex((t) => t.startsWith('Propriedades do modelo'));
    expect(factory).toBeGreaterThanOrEqual(0);
    expect(factory).toBeLessThan(props);
  });

  it('gestão sempre à mostra acima da lista (sem "Gerenciar"); a ação abre a janela', async () => {
    renderModel([version(1)]);
    const user = userEvent.setup();
    await screen.findByRole('button', { name: '+ Novo parâmetro' });
    expect(screen.queryByRole('button', { name: /^Gerenciar/ })).not.toBeInTheDocument();
    for (const name of ['+ Novo parâmetro', 'Catálogo', 'Marcas órfãs', 'Peças órfãs']) {
      expect(screen.getByRole('button', { name })).toBeVisible();
    }
    await user.click(screen.getByRole('button', { name: 'Catálogo' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('quem não edita parâmetros vê as 3 ações de consulta, sem "+ Novo parâmetro"', async () => {
    renderModel([version(1)], '/obras/7/modelo', new FakeViewer(), { userId: '1' });
    await screen.findByRole('button', { name: 'Catálogo' });
    expect(screen.getByRole('button', { name: 'Marcas órfãs' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Peças órfãs' })).toBeVisible();
    expect(screen.queryByRole('button', { name: '+ Novo parâmetro' })).not.toBeInTheDocument();
  });

  it('versão escolhida pela URL', async () => {
    const { viewer } = renderModel([version(2), version(1)], '/obras/7/modelo?versao=1');
    await vi.waitFor(() => { expect(viewer.load).toHaveBeenCalledWith('urn-v1'); });
    expect(viewer.load).not.toHaveBeenCalledWith('urn-v2');
  });

  it('clique numa peça seleciona a marca inteira e mostra marca, quantidade e propriedades', async () => {
    const { viewer } = renderModel([version(1)]);
    const user = userEvent.setup();
    const fit = await screen.findByRole('button', { name: 'Ampliar tudo' });
    await vi.waitFor(() => { expect(fit).toBeEnabled(); });
    expect(await screen.findByRole('heading', { name: 'Marcas (3)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Isolar' })).toBeDisabled(); // nada selecionado

    viewer.click([11]); // uma peça do PP001
    expect(await screen.findByRole('heading', { name: 'PP001 · Structural Columns · 2 peças' })).toBeInTheDocument();
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([10, 11]); // a marca inteira, pelos dbIds da API
    expect(await screen.findByText(/Peça clicada: Pilar \[11\]/)).toBeInTheDocument();
    expect(screen.getByText('Nenhum parâmetro se aplica a esta categoria.')).toBeInTheDocument();
    expect(screen.getByLabelText('Dimensões')).toHaveTextContent('Altura50.0 cm');

    await user.click(screen.getByRole('button', { name: 'Isolar' }));
    expect(viewer.isolate).toHaveBeenCalledWith([10, 11]);
    expect(screen.getByRole('button', { name: 'Isolar' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Isolar' }));
    expect(viewer.showAll).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Enquadrar seleção' }));
    expect(viewer.fitTo).toHaveBeenCalledWith([10, 11]);
    await user.click(fit);
    expect(viewer.fitTo).toHaveBeenLastCalledWith();
    await user.click(screen.getByRole('button', { name: 'Limpar seleção' }));
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([]);
    expect(screen.getByText('Toque numa peça no modelo, ou escolha uma marca na lista, para ver e preencher os parâmetros da fábrica.')).toBeInTheDocument();
  });

  it('Ctrl+clique e modo Seleção múltipla acumulam marcas', async () => {
    const { viewer } = renderModel([version(1)]);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    await vi.waitFor(() => { expect(screen.getByRole('button', { name: 'Seleção múltipla' })).toBeEnabled(); });

    viewer.click([10]);
    await screen.findByRole('heading', { name: 'PP001 · Structural Columns · 2 peças' });
    viewer.click([10, 11, 20]); // Ctrl+clique: o Viewer devolve a seleção acumulada
    expect(await screen.findByRole('heading', { name: '2 marcas · 4 peças' })).toBeInTheDocument();
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([10, 11, 20, 21]);

    await user.click(screen.getByRole('button', { name: 'Seleção múltipla' }));
    viewer.click([30]); // toque simples no modo múltiplo: soma a peça sem Marca
    expect(await screen.findByRole('heading', { name: '2 marcas · 5 peças' })).toBeInTheDocument();
    viewer.click([21]); // tocar de novo numa marca selecionada tira a marca
    expect(await screen.findByRole('heading', { name: '1 marca · 3 peças' })).toBeInTheDocument();
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([10, 11, 30]);
  });

  it('filtro e grupos recolhíveis nas propriedades do modelo', async () => {
    const { viewer } = renderModel([version(1)]);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    viewer.click([11]);
    const group = await screen.findByRole('button', { name: /Dimensões/ });
    expect(group).toHaveAttribute('aria-expanded', 'true');
    await user.click(group);
    expect(group).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Dimensões')).not.toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Filtrar propriedades' }), 'altura');
    const dims = screen.getByLabelText('Dimensões'); // com filtro, os grupos abrem
    expect(dims).toHaveTextContent('Altura50.0 cm');
    expect(dims).not.toHaveTextContent('Largura');
    expect(screen.queryByRole('button', { name: /Other/ })).not.toBeInTheDocument();

    await user.clear(screen.getByRole('searchbox', { name: 'Filtrar propriedades' }));
    await user.type(screen.getByRole('searchbox', { name: 'Filtrar propriedades' }), 'xyz');
    expect(screen.getByText('Nenhuma propriedade encontrada.')).toBeInTheDocument();
  });

  it('sem versão pronta avisa e não carrega nada', async () => {
    const { viewer } = renderModel([version(1, 'no_translation')]);
    expect(await screen.findByText('Nenhuma versão pronta para visualizar. Veja a aba Versões.')).toBeInTheDocument();
    expect(viewer.load).not.toHaveBeenCalled();
  });

  it('erro ao carregar aparece no lugar do modelo', async () => {
    const failing = new FakeViewer();
    failing.load.mockRejectedValueOnce(new Error('Não foi possível carregar o visualizador da Autodesk.'));
    renderModel([version(1)], undefined, failing);
    expect(await screen.findByText('Não foi possível carregar o visualizador da Autodesk.')).toBeInTheDocument();
  });

  it('sair da tela destrói o viewer', async () => {
    const { viewer, view } = renderModel([version(1)]);
    await vi.waitFor(() => { expect(viewer.load).toHaveBeenCalled(); });
    view.unmount();
    expect(viewer.destroy).toHaveBeenCalled();
  });

  it('a página da obra tem o link para abrir o modelo', async () => {
    renderModel([version(1)], '/obras/7/versoes');
    const link = await screen.findByRole('link', { name: 'Abrir modelo 3D' });
    expect(link).toHaveAttribute('href', '/obras/7/modelo');
  });
});

describe('Filtro (F3)', () => {
  afterEach(() => {
    setDevUser(null);
    evalCalls.length = 0;
  });

  async function ready(route?: string, opts: RenderOptions = {}) {
    const r = renderModel([version(1)], route, undefined, opts);
    await screen.findByRole('heading', { name: /^Marcas \(/ });
    await vi.waitFor(() => { expect(screen.getByRole('button', { name: 'Ampliar tudo' })).toBeEnabled(); });
    return { ...r, user: userEvent.setup() };
  }
  const bar = () => within(screen.getByRole('toolbar', { name: 'Barra do visualizador' }));
  const openFilter = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(bar().getByRole('button', { name: /^Filtro/ }));
    return within(await screen.findByRole('dialog', { name: 'Filtro' }));
  };
  const list = () => screen.getByRole('list', { name: /^Marcas/ });
  // texto visível da linha (sem o status, que vai só para o leitor de tela)
  const rows = () =>
    within(list())
      .getAllByRole('button')
      .map((b) => [...b.childNodes].map((n) => (n instanceof HTMLElement ? visibleText(n) : n.textContent)).join(''));

  it('barra inferior: Filtro, Ampliar tudo, Colorir; Remover só com algo ativo; sem Medida', async () => {
    const { viewer, user } = await ready();
    // barra única: Filtro · Colorir (✕ só com algo ativo) │ seleção │ Ampliar tudo; Editar cores fica no popover Colorir
    expect(bar().getAllByRole('button').map((b) => (b.getAttribute('aria-label') ?? b.textContent ?? '').trim())).toEqual([
      'Filtro', 'Colorir', 'Remover coloração', // status vem ligado
      'Enquadrar seleção', 'Isolar', 'Limpar seleção', 'Seleção múltipla', 'Ampliar tudo',
    ]);
    expect(screen.queryByRole('button', { name: 'Medida' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enquadrar tudo' })).not.toBeInTheDocument(); // foi para a barra
    await user.click(bar().getByRole('button', { name: 'Ampliar tudo' }));
    expect(viewer.fitTo).toHaveBeenLastCalledWith();
    // sem filtro: lista com todas as marcas e o 3D normal
    expect(rows()).toEqual(['PP001Structural Columns2 peças', 'PP002Structural Columns2 peças', 'V-01Structural Framing2 peças']);
    expect(evalCalls).toHaveLength(0);
  });

  it('pesquisar por objetos: debounce, "N de M peças", destaque no 3D e Remover filtros', async () => {
    const { viewer, user, view } = await ready();
    const pop = await openFilter(user);
    await user.type(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'PP001');
    await vi.waitFor(() => { expect(rows()).toEqual(['PP001Structural Columns2 de 2 peças']); });
    expect(evalCalls.map((d) => d.q)).toEqual(['PP001']); // debounce: uma chamada, com o texto final
    expect(screen.getByText('2 de 6 peças no filtro')).toBeInTheDocument();
    await vi.waitFor(() => { expect(viewer.highlight).toHaveBeenLastCalledWith([10, 11]); }); // texto destaca

    // Isolar (grupo Seleção da barra) sem seleção isola o resultado
    await user.click(screen.getByRole('button', { name: 'Isolar' }));
    expect(viewer.isolate).toHaveBeenLastCalledWith([10, 11]);
    await user.click(screen.getByRole('button', { name: 'Isolar' }));

    await user.click(bar().getByRole('button', { name: 'Remover filtros' }));
    await vi.waitFor(() => { expect(viewer.showAll).toHaveBeenCalled(); });
    expect(rows()).toHaveLength(3);
    expect(bar().queryByRole('button', { name: 'Remover filtros' })).not.toBeInTheDocument();
    view.unmount();
  });

  it('filtro salvo: clicar aplica, fica marcado e a etiqueta aparece', async () => {
    const { viewer, user } = await ready();
    const pop = await openFilter(user);
    expect(pop.getByRole('list', { name: 'Sistema' })).toHaveTextContent('PendentesParciaisA revisarNovas na versão');
    await user.click(pop.getByRole('button', { name: 'Pendentes' }));
    expect(pop.getByRole('button', { name: /Pendentes/ })).toHaveAttribute('aria-pressed', 'true');
    expect(pop.getByRole('list', { name: 'Filtros ativos' })).toHaveTextContent('Destacar · Status de produção: é igual a Pendente');
    await vi.waitFor(() => { expect(rows()).toEqual(['V-01Structural Framing2 de 2 peças']); });
    expect(evalCalls.at(-1)?.rules).toEqual([{ ...statusRule('Pendente'), mode: 'highlight' }]);
    await vi.waitFor(() => { expect(viewer.highlight).toHaveBeenLastCalledWith([20, 21]); });
    // remover a etiqueta desliga o filtro
    await user.click(pop.getByRole('button', { name: 'Remover filtro Destacar · Status de produção: é igual a Pendente' }));
    await vi.waitFor(() => { expect(rows()).toHaveLength(3); });
  });

  it('menu rápido Categoria: "é um de" em Isolar; o 3D isola o resultado', async () => {
    const { viewer, user } = await ready();
    const pop = await openFilter(user);
    await user.click(pop.getByRole('button', { name: /^Categoria/ }));
    await user.click(await pop.findByRole('checkbox', { name: /Structural Framing/ }));
    await vi.waitFor(() => { expect(rows()).toEqual(['V-01Structural Framing2 de 2 peças']); });
    expect(evalCalls.at(-1)?.rules).toEqual([
      { field: { source: 'system', key: 'category' }, op: 'in', value: ['Structural Framing'], mode: 'isolate' },
    ]);
    await vi.waitFor(() => { expect(viewer.isolate).toHaveBeenLastCalledWith([20, 21]); });
    expect(pop.getByRole('list', { name: 'Filtros ativos' })).toHaveTextContent('Categoria: Structural Framing');
  });

  it('+ Adicionar filtro: grupos, busca, tipo e valores; data "no mês atual"', async () => {
    const { user } = await ready();
    const pop = await openFilter(user);
    await user.click(pop.getByRole('button', { name: '+ Adicionar filtro' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Selecionar parâmetro' }));
    expect(dialog.getAllByRole('heading', { level: 4 }).map((h) => h.textContent)).toEqual([
      'Fábrica', 'Montagem', 'Identificação', 'Dimensões',
    ]);
    expect(within(dialog.getByRole('region', { name: 'Dimensões' })).getByRole('button')).toHaveTextContent('AlturaDimensõesnúmero · 2 valores');
    await user.type(dialog.getByRole('searchbox', { name: 'Buscar parâmetro' }), 'expedicao'); // sem acento
    expect(dialog.getAllByRole('button', { name: /Data de expedição/ })).toHaveLength(1);
    await user.click(dialog.getByRole('button', { name: /Data de expedição/ }));

    const step = within(await screen.findByRole('dialog', { name: 'Data de expedição' }));
    expect(step.getByRole('combobox', { name: 'Operador' })).toHaveValue('this_month'); // datas começam no mês atual
    await user.click(step.getByRole('button', { name: 'Adicionar' }));
    expect(pop.getByRole('list', { name: 'Filtros ativos' })).toHaveTextContent('Data de expedição: no mês atual');
    await vi.waitFor(() => { expect(evalCalls.at(-1)?.rules).toEqual([{ field: { source: 'factory', key: '5' }, op: 'this_month', mode: 'isolate' }]); });
    await vi.waitFor(() => { expect(rows()).toEqual(['PP001Structural Columns2 de 2 peças']); });
  });

  it('Avançado: modo por linha, OU, linha vazia no fim; Ocultar esconde no 3D', async () => {
    const { viewer, user } = await ready();
    const pop = await openFilter(user);
    await user.click(pop.getByRole('button', { name: 'Avançado' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Editar filtro' }));
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Parâmetro da nova regra' }), 'system:mark');
    await user.type(dialog.getByRole('combobox', { name: 'Valor da regra 1' }), 'PP002');
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Modo da regra 1' }), 'hide');
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Modo da nova regra' }), 'highlight');
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Parâmetro da nova regra' }), 'system:status');
    await user.type(dialog.getByRole('combobox', { name: 'Valor da regra 2' }), 'Parcial');
    await user.click(dialog.getByRole('radio', { name: 'Qualquer regra (OU)' }));
    // sempre há uma linha nova vazia no fim
    expect(dialog.getByRole('combobox', { name: 'Parâmetro da nova regra' })).toHaveValue('');
    await user.click(dialog.getByRole('button', { name: 'Aplicar' }));
    await vi.waitFor(() => {
      expect(evalCalls.at(-1)).toEqual({
        mode: 'isolate', logic: 'or',
        rules: [
          { field: { source: 'system', key: 'mark' }, op: 'eq', value: 'PP002', mode: 'hide' },
          { field: { source: 'system', key: 'status' }, op: 'eq', value: 'Parcial', mode: 'highlight' },
        ],
      });
    });
    // PP002 é a única parcial, mas está oculta: nada em destaque, PP002 escondida
    await vi.waitFor(() => { expect(viewer.hide).toHaveBeenLastCalledWith([12, 13]); });
    expect(screen.getByText('Nenhuma peça no filtro.')).toBeInTheDocument();
    expect(pop.getByRole('list', { name: 'Filtros ativos' })).toHaveTextContent('Ocultar · Nome da montagem: é igual a PP002');
  });

  it('Cancelar no Avançado não muda nada; "sem <parâmetro>" + Enter vira regra', async () => {
    const { user } = await ready();
    const pop = await openFilter(user);
    await user.click(pop.getByRole('button', { name: 'Avançado' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Editar filtro' }));
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Parâmetro da nova regra' }), 'system:mark');
    await user.click(dialog.getByRole('button', { name: 'Cancelar' }));
    expect(pop.queryByRole('list', { name: 'Filtros ativos' })).not.toBeInTheDocument();

    await user.type(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'sem tipo de forma{Enter}');
    expect(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' })).toHaveValue('');
    expect(pop.getByRole('list', { name: 'Filtros ativos' })).toHaveTextContent('Tipo de forma: está vazio');
  });

  it('Salvar como novo: pessoal por padrão; Compartilhar só para quem pode', async () => {
    const created: unknown[] = [];
    const routes = {
      'POST /api/saved-filters': (req: FakeRequest) => {
        created.push(req.body);
        return { ...SAVED[0], ...(req.body as object), id: 50, system_key: null, editable: true, owner_id: 1 } as SavedFilter;
      },
    };
    const { user } = await ready(undefined, { userId: '1', routes }); // projetos: não compartilha
    const pop = await openFilter(user);
    await user.type(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'PP');
    await user.click(pop.getByRole('button', { name: 'Salvar' }));
    await user.click(pop.getByRole('menuitem', { name: 'Salvar como novo…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Salvar filtro' }));
    expect(dialog.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(dialog.getByText('O filtro fica só para você.')).toBeInTheDocument();
    await user.type(dialog.getByRole('textbox', { name: 'Nome' }), 'Meus pilares');
    await user.click(dialog.getByRole('button', { name: 'Salvar' }));
    await vi.waitFor(() => {
      expect(created).toEqual([{ name: 'Meus pilares', scope: 'personal', obra_id: 7, definition: { mode: 'isolate', logic: 'and', rules: [], q: 'PP' } }]);
    });
    expect(await pop.findByText('Filtro "Meus pilares" salvo.')).toBeInTheDocument();
  });

  it('fábrica pode compartilhar ao salvar', async () => {
    const { user } = await ready();
    const pop = await openFilter(user);
    await user.type(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'PP');
    await user.click(pop.getByRole('button', { name: 'Salvar' }));
    expect(pop.getByRole('menuitem', { name: /Atualizar o filtro/ })).toBeDisabled(); // não veio de um salvo
    await user.click(pop.getByRole('menuitem', { name: 'Salvar como novo…' }));
    expect(await screen.findByRole('checkbox', { name: 'Compartilhar com todos (filtro da obra)' })).toBeInTheDocument();
  });

  it('o filtro vai para a URL; um link com filtro abre já filtrado', async () => {
    const f = JSON.stringify({ r: [{ field: { source: 'system', key: 'category' }, op: 'in', value: ['Structural Framing'], mode: 'isolate' }] });
    const { viewer } = await ready(`/obras/7/modelo?versao=1&f=${encodeURIComponent(f)}`);
    await vi.waitFor(() => { expect(rows()).toEqual(['V-01Structural Framing2 de 2 peças']); });
    await vi.waitFor(() => { expect(viewer.isolate).toHaveBeenLastCalledWith([20, 21]); });
    expect(bar().getByRole('button', { name: 'Remover filtros' })).toBeInTheDocument();
  });

  it('clicar numa marca da lista seleciona e enquadra; Tipo > Marcar tudo seleciona o resultado', async () => {
    const { viewer, user } = await ready();
    await user.click(screen.getByRole('button', { name: /^V-01/ }));
    expect(await screen.findByRole('heading', { name: 'V-01 · Structural Framing · 2 peças' })).toBeInTheDocument();
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([20, 21]);
    expect(viewer.fitTo).toHaveBeenLastCalledWith([20, 21]);
    expect(screen.getByRole('button', { name: /^V-01/ })).toHaveAttribute('aria-pressed', 'true');

    const pop = await openFilter(user);
    await user.type(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'PP');
    await vi.waitFor(() => { expect(rows()).toHaveLength(2); });
    await user.click(screen.getByRole('button', { name: /^Tipo/ }));
    await user.click(screen.getByRole('checkbox', { name: /Marcar tudo/ }));
    expect(await screen.findByRole('heading', { name: '2 marcas · 4 peças' })).toBeInTheDocument();
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([10, 11, 12, 13]);
  });

  it('erro do motor aparece na lista', async () => {
    const { user } = await ready(undefined, {
      routes: { 'POST /api/versions/1/filter/evaluate': Response.json({ detail: 'Regra 1 ("Altura"): "x" não é um número.' }, { status: 422 }) },
    });
    const pop = await openFilter(user);
    await user.type(pop.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'x');
    expect((await screen.findAllByRole('alert'))[0]).toHaveTextContent('não é um número');
  });
});


describe('Catálogo de parâmetros da fábrica (6.1)', () => {
  afterEach(() => {
    setDevUser(null);
  });

  const def = (over: Partial<ParamDef>): ParamDef => ({
    id: 1,
    name: 'Tipo de forma',
    type: 'list',
    unit: null,
    options: ['F-01', 'F-02', 'F-03'],
    required: true,
    categories: ['Structural Columns'],
    scope: 'global',
    level: 'mark',
    obra_id: null,
    obra_code: null,
    active: true,
    values_count: 0,
    options_in_use: [],
    created_at: '2026-11-11T12:00:00Z',
    updated_at: '2026-11-11T12:00:00Z',
    created_by_name: 'Fábio Fábrica',
    ...over,
  });

  /** Backend falso do catálogo, com estado (POST/PATCH/DELETE alteram a lista). */
  function catalogApi(initial: ParamDef[]) {
    let defs = [...initial];
    const calls: { method: string; path: string; body: unknown }[] = [];
    const record = (req: FakeRequest) => { calls.push({ method: req.method, path: req.path, body: req.body }); };
    const routes: Parameters<typeof installFakeApi>[0] = {
      'GET /api/param-defs': (req) => { record(req); return defs; },
      'POST /api/param-defs': (req) => {
        record(req);
        const body = req.body as ParamDefBody;
        if (defs.some((d) => d.name.toLowerCase() === body.name.trim().toLowerCase())) {
          return Response.json({ detail: `Já existe um parâmetro "${body.name}" no catálogo global.`, code: 'conflict' }, { status: 409 });
        }
        const created = def({ ...body, id: 99, categories: body.categories.length ? body.categories : null });
        defs = [...defs, created];
        return Response.json(created, { status: 201 });
      },
    };
    for (const d of initial) {
      routes[`PATCH /api/param-defs/${d.id}`] = (req) => {
        record(req);
        defs = defs.map((x) => (x.id === d.id ? { ...x, ...(req.body as Partial<ParamDef>) } : x));
        return defs.find((x) => x.id === d.id) ?? {};
      };
      routes[`DELETE /api/param-defs/${d.id}`] = (req) => {
        record(req);
        defs = defs.filter((x) => x.id !== d.id);
        return new Response(null, { status: 204 });
      };
    }
    return { routes, calls };
  }

  async function open(initial: ParamDef[], userId = '2') {
    const api = catalogApi(initial);
    const r = renderModel([version(1)], undefined, undefined, { userId, routes: api.routes });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    return { ...r, ...api, user: userEvent.setup() };
  }

  it('fábrica cria um parâmetro de lista pela barra lateral', async () => {
    const { calls, user } = await open([]);
    const fieldsCalls = () =>
      vi.mocked(fetch).mock.calls.filter(
        ([url, init]) => typeof url === 'string' && url.endsWith('/api/versions/1/fields') && (init?.method ?? 'GET') === 'GET',
      ).length;
    await vi.waitFor(() => { expect(fieldsCalls()).toBeGreaterThan(0); });
    const before = fieldsCalls();
    await user.click(await screen.findByRole('button', { name: '+ Novo parâmetro' }));
    const dialog = screen.getByRole('dialog', { name: 'Novo parâmetro da fábrica' });

    expect(within(dialog).queryByLabelText(/Opções/)).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Nome/), 'Tipo de forma');
    await user.selectOptions(within(dialog).getByLabelText('Tipo'), 'list');
    await user.type(within(dialog).getByLabelText(/Opções/), 'F-01{Enter}F-02{Enter}{Enter}F-03');
    await user.click(within(dialog).getByRole('checkbox', { name: /Structural Columns/ }));
    await user.click(within(dialog).getByRole('checkbox', { name: /Obrigatório/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Criar parâmetro' }));

    await vi.waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); });
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      name: 'Tipo de forma',
      type: 'list',
      unit: null,
      options: ['F-01', 'F-02', 'F-03'],
      required: true,
      categories: ['Structural Columns'],
      scope: 'global',
      level: 'mark',
      obra_id: null,
      include_in_obra_id: 7, // criado da biblioteca aqui: já entra nesta obra
    });
    expect(await screen.findByText('1 parâmetro no catálogo desta obra.')).toBeInTheDocument();
    // a lista de campos do Filtro/Colorir é pedida de novo: o parâmetro novo já aparece lá
    await vi.waitFor(() => { expect(fieldsCalls()).toBeGreaterThan(before); });
  });

  it('número mostra unidade; escopo da obra envia obra_id; erro do servidor aparece', async () => {
    const { calls, user } = await open([def({ id: 1, name: 'Forma' })]);
    await user.click(await screen.findByRole('button', { name: '+ Novo parâmetro' }));
    const dialog = screen.getByRole('dialog');
    await user.selectOptions(within(dialog).getByLabelText('Tipo'), 'number');
    await user.type(within(dialog).getByLabelText('Unidade'), 'h');
    await user.selectOptions(within(dialog).getByLabelText('Escopo'), 'obra');

    await user.click(within(dialog).getByRole('button', { name: 'Criar parâmetro' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Informe o nome do parâmetro.');
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);

    await user.type(within(dialog).getByLabelText(/Nome/), 'forma');
    await user.click(within(dialog).getByRole('button', { name: 'Criar parâmetro' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Já existe um parâmetro "forma" no catálogo global.');
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ type: 'number', unit: 'h', scope: 'obra', obra_id: 7 });
  });

  it('Catálogo lista, edita e exclui (com confirmação)', async () => {
    const used = def({ id: 1, values_count: 2, options_in_use: ['F-02'] });
    const free = def({ id: 2, name: 'Ciclo de cura', type: 'number', unit: 'h', options: null, required: false, categories: null });
    const { calls, user } = await open([used, free]);
    await user.click(await screen.findByRole('button', { name: 'Catálogo' }));
    const catalog = screen.getByRole('dialog', { name: 'Catálogo de parâmetros da fábrica' });
    const rows = within(catalog).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Lista de opções · 3 opções · Structural Columns · biblioteca · em 0 obras · 2 marcas com valor');
    expect(rows[1]).toHaveTextContent('Número (h) · todas as categorias · biblioteca · em 0 obras · 0 marcas com valor');

    // Editar um parâmetro com valores: tipo e escopo travados, opções em uso avisadas
    await user.click(within(catalog).getByRole('button', { name: 'Editar Tipo de forma' }));
    const edit = screen.getByRole('dialog', { name: 'Editar parâmetro' });
    expect(within(edit).getByLabelText('Tipo')).toBeDisabled();
    expect(within(edit).getByLabelText('Escopo')).toBeDisabled();
    expect(within(edit).getByText('O tipo não pode ser alterado porque já existem valores.')).toBeInTheDocument();
    expect(within(edit).getByText('Em uso (não podem ser removidas): F-02')).toBeInTheDocument();
    await user.clear(within(edit).getByLabelText(/Nome/));
    await user.type(within(edit).getByLabelText(/Nome/), 'Forma');
    await user.click(within(edit).getByRole('button', { name: 'Salvar' }));
    await vi.waitFor(() => { expect(calls.some((c) => c.method === 'PATCH' && c.path === '/api/param-defs/1')).toBe(true); });
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ name: 'Forma', type: 'list' });

    // Excluir: confirmação dentro do app (o window.confirm pode não aparecer no tablet)
    await user.click(screen.getByRole('button', { name: 'Catálogo' }));
    await user.click(screen.getByRole('button', { name: 'Excluir Ciclo de cura' }));
    const ask = screen.getByRole('alertdialog', { name: 'Confirmar' });
    expect(ask).toHaveTextContent('Excluir “Ciclo de cura” da biblioteca? Ele sai de TODAS as obras');
    await user.click(within(ask).getByRole('button', { name: 'Cancelar' }));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Excluir Ciclo de cura' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Excluir' }));
    await vi.waitFor(() => { expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/param-defs/2')).toBe(true); });
    await vi.waitFor(() => { expect(screen.queryByRole('button', { name: 'Excluir Ciclo de cura' })).not.toBeInTheDocument(); });
  });

  it('biblioteca: incluir nesta obra e retirar (os valores ficam guardados)', async () => {
    const inObra = def({ id: 1, name: 'Tipo de forma', in_obra: true, obras_count: 2, values_count: 3 });
    const lib = def({ id: 2, name: 'Liberação', type: 'bool', options: null, in_obra: false, obras_count: 1 });
    const own = def({ id: 3, name: 'Observação', type: 'text', options: null, scope: 'obra', obra_id: 7, obra_code: 'OB-001', in_obra: true });
    const api = catalogApi([inObra, lib, own]);
    api.routes['POST /api/obras/7/params/2'] = (req) => { api.calls.push({ method: req.method, path: req.path, body: null }); return { obra_id: 7, def_id: 2, in_obra: true, changed: true }; };
    api.routes['DELETE /api/obras/7/params/1'] = (req) => { api.calls.push({ method: req.method, path: req.path, body: null }); return { obra_id: 7, def_id: 1, in_obra: false, changed: true }; };
    renderModel([version(1)], undefined, undefined, { userId: '2', routes: api.routes });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Catálogo' }));
    const catalog = screen.getByRole('dialog', { name: 'Catálogo de parâmetros da fábrica' });

    const here = within(catalog).getByRole('list', { name: 'Parâmetros desta obra' });
    const library = within(catalog).getByRole('list', { name: 'Biblioteca' });
    expect(within(here).getAllByRole('listitem').map((li) => li.querySelector('b')?.textContent)).toEqual(['Tipo de forma', 'Observação']);
    expect(within(library).getAllByRole('listitem')).toHaveLength(1);
    expect(within(here).getAllByRole('listitem')[0]).toHaveTextContent('biblioteca · em 2 obras');
    // parâmetro só desta obra: sem "Retirar" (exclui-se)
    expect(within(here).queryByRole('button', { name: 'Retirar Observação desta obra' })).not.toBeInTheDocument();

    await user.click(within(library).getByRole('button', { name: 'Incluir Liberação nesta obra' }));
    await vi.waitFor(() => { expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/obras/7/params/2')).toBe(true); });

    await user.click(within(here).getByRole('button', { name: 'Retirar Tipo de forma desta obra' }));
    const ask = screen.getByRole('alertdialog');
    expect(ask).toHaveTextContent('os valores ficam guardados e voltam se ele for incluído de novo');
    await user.click(within(ask).getByRole('button', { name: 'Retirar' }));
    await vi.waitFor(() => { expect(api.calls.some((c) => c.method === 'DELETE' && c.path === '/api/obras/7/params/1')).toBe(true); });
    expect(api.calls.some((c) => c.method === 'DELETE' && c.path.startsWith('/api/param-defs'))).toBe(false);
  });

  it('projetos vê o catálogo só para leitura', async () => {
    const { user } = await open([def({})], '1');
    await screen.findByText('1 parâmetro no catálogo desta obra.');
    expect(screen.queryByRole('button', { name: '+ Novo parâmetro' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Catálogo' }));
    const catalog = screen.getByRole('dialog');
    expect(within(catalog).getByText(/Somente a fábrica cria, inclui, retira e exclui parâmetros/)).toBeInTheDocument();
    expect(within(catalog).queryByRole('button', { name: /Editar|Excluir|Novo|Incluir|Retirar/ })).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('painel da marca: "+ Novo parâmetro" já vem com a categoria da marca marcada', async () => {
    const { viewer, user } = await open([def({ id: 1 })]);
    viewer.click([11]); // PP001, Structural Columns
    await screen.findByRole('heading', { name: 'PP001 · Structural Columns · 2 peças' });
    const panel = screen.getByRole('complementary', { name: 'Peça selecionada' });
    await user.click(within(panel).getByRole('button', { name: '+ Novo parâmetro' }));
    const dialog = screen.getByRole('dialog', { name: 'Novo parâmetro da fábrica' });
    expect(within(dialog).getByRole('checkbox', { name: /Structural Columns/ })).toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: /Structural Framing/ })).not.toBeChecked();
  });
});


describe('Valores por marca (6.2)', () => {
  afterEach(() => {
    setDevUser(null);
  });

  const field = (over: Partial<FieldValue>): FieldValue => ({
    def_id: 1,
    name: 'Tipo de forma',
    type: 'list',
    unit: null,
    required: true,
    options: ['F-11', 'F-12', 'F-13'],
    value: null,
    row_version: null,
    updated_at: null,
    updated_by_name: null,
    ...over,
  });

  const minutesAgo = (n: number) => new Date(Date.now() - n * 60_000).toISOString();

  /** API de valores com estado (só a marca PP001, id 1). */
  function valuesApi(fields: FieldValue[], opts: { failWith?: Response } = {}) {
    let current: MarkValues = {
      mark: { id: 1, code: 'PP001', category: 'Structural Columns' },
      values: fields,
      last_change_by: 'Fábio Fábrica',
      last_change_at: '2026-11-11T12:00:00Z',
    };
    const puts: unknown[] = [];
    let fail = opts.failWith;
    const routes: Parameters<typeof installFakeApi>[0] = {
      'GET /api/obras/7/marks/1/values': () => current,
      'PUT /api/obras/7/marks/1/values': (req) => {
        puts.push(req.body);
        if (fail) {
          const r = fail;
          fail = undefined;
          return r;
        }
        const { changes } = req.body as { changes: { def_id: number; value: unknown }[] };
        current = {
          ...current,
          values: current.values.map((f) => {
            const c = changes.find((x) => x.def_id === f.def_id);
            if (!c) return f;
            const value = f.type === 'number' && typeof c.value === 'string' ? Number(c.value.replace(',', '.')) : c.value;
            return { ...f, value, row_version: (f.row_version ?? 0) + 1, updated_by_name: 'Fábio Fábrica' };
          }),
          last_change_at: new Date().toISOString(),
        };
        return current;
      },
      'GET /api/obras/7/marks/1/history': [
        { at: '2026-11-11T12:00:00Z', user_name: 'Fábio Fábrica', action: 'update', param: 'Tipo de forma', def_id: 1, before: 'F-11', after: 'F-12', batch_id: null },
        { at: '2026-11-10T12:00:00Z', user_name: 'Ana Admin', action: 'set', param: 'Ciclo de cura', def_id: 2, before: null, after: 8.5, batch_id: null },
      ],
    };
    return { routes, puts };
  }

  async function openMark(fields: FieldValue[], { userId = '2', failWith }: { userId?: string; failWith?: Response } = {}) {
    const api = valuesApi(fields, failWith ? { failWith } : {});
    const r = renderModel([version(1)], undefined, undefined, { userId, routes: api.routes });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    r.viewer.click([11]);
    await screen.findByRole('heading', { name: 'PP001 · Structural Columns · 2 peças' });
    return { ...r, ...api, user: userEvent.setup() };
  }

  const FIELDS = [
    field({ def_id: 2, name: 'Ciclo de cura', type: 'number', unit: 'h', required: false, options: null, value: 8.5, row_version: 3 }),
    field({ def_id: 3, name: 'Data de concretagem', type: 'date', required: false, options: null, value: '2026-11-20', row_version: 1 }),
    field({ def_id: 4, name: 'Peça com insert', type: 'bool', required: false, options: null, value: true, row_version: 1 }),
    field({ def_id: 1, value: 'F-11', row_version: 2 }),
  ];

  it('mostra só os parâmetros da marca com unidade, asterisco, valores formatados e última alteração', async () => {
    await openMark(FIELDS);
    const list = await screen.findByLabelText('Valores da marca');
    expect(list).toHaveTextContent('Ciclo de cura (h)8,5');
    expect(list).toHaveTextContent('Data de concretagem20/11/2026');
    expect(list).toHaveTextContent('Peça com insertSim');
    expect(list).toHaveTextContent('Tipo de forma *F-11');
    expect(screen.getByText(/Última alteração: Fábio Fábrica · /)).toBeInTheDocument();
  });

  it('Editar → Salvar envia só o que mudou, com a versão lida, e mostra o resultado', async () => {
    const { puts, user } = await openMark(FIELDS);
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    await user.selectOptions(panel().getByLabelText(/Tipo de forma/), 'F-12');
    await user.clear(screen.getByLabelText('Ciclo de cura (h)'));
    await user.type(screen.getByLabelText('Ciclo de cura (h)'), '12,5');
    await user.click(screen.getByRole('button', { name: 'Salvar' }));

    await vi.waitFor(() => { expect(screen.queryByRole('button', { name: 'Salvar' })).not.toBeInTheDocument(); });
    expect(puts).toEqual([
      {
        changes: [
          { def_id: 2, value: '12,5', row_version: 3 },
          { def_id: 1, value: 'F-12', row_version: 2 },
        ],
      },
    ]);
    const list = screen.getByLabelText('Valores da marca');
    expect(list).toHaveTextContent('Tipo de forma *F-12');
    expect(list).toHaveTextContent('Ciclo de cura (h)12,5');
  });

  it('Esc e Cancelar descartam a edição sem salvar', async () => {
    const { puts, user } = await openMark(FIELDS);
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    await user.selectOptions(panel().getByLabelText(/Tipo de forma/), 'F-13');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Salvar' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Valores da marca')).toHaveTextContent('Tipo de forma *F-11');

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    expect(panel().getByLabelText(/Tipo de forma/)).toHaveValue('F-11'); // começa do valor salvo
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(puts).toEqual([]);
  });

  it('409: avisa quem alterou e há quanto tempo; Recarregar busca os valores atuais', async () => {
    const stale = Response.json(
      { detail: 'Paula alterou esta marca.', code: 'stale', changed_by_name: 'Paula Projetos', changed_at: minutesAgo(5), conflict_def_ids: [1] },
      { status: 409 },
    );
    const { user } = await openMark(FIELDS, { failWith: stale });
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    await user.selectOptions(panel().getByLabelText(/Tipo de forma/), 'F-12');
    await user.click(screen.getByRole('button', { name: 'Salvar' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Paula Projetos alterou esta marca há 5 min');
    await user.click(within(alert).getByRole('button', { name: 'Recarregar' }));
    await vi.waitFor(() => { expect(screen.queryByRole('alert')).not.toBeInTheDocument(); });
    expect(screen.getByLabelText('Valores da marca')).toHaveTextContent('Tipo de forma *F-11');
  });

  it('data com ano fora de 1900–2100: avisa abaixo do campo e não salva; corrigida, salva', async () => {
    const { puts, user } = await openMark(FIELDS);
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    const input = screen.getByLabelText('Data de concretagem');
    fireEvent.change(input, { target: { value: '0002-05-05' } }); // não grava ao mudar
    expect(puts).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Salvar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Data inválida: use dd/mm/aaaa');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(puts).toEqual([]);

    fireEvent.change(input, { target: { value: '2026-05-05' } });
    await user.click(screen.getByRole('button', { name: 'Salvar' }));
    await vi.waitFor(() => { expect(puts).toEqual([{ changes: [{ def_id: 3, value: '2026-05-05', row_version: 1 }] }]); });
  });

  it('422: a mensagem do servidor aparece no formulário', async () => {
    const invalid = Response.json({ detail: 'Ciclo de cura: "abc" não é um número (use vírgula para decimais).', code: 'validation' }, { status: 422 });
    const { user } = await openMark(FIELDS, { failWith: invalid });
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    await user.clear(screen.getByLabelText('Ciclo de cura (h)'));
    await user.type(screen.getByLabelText('Ciclo de cura (h)'), 'abc');
    await user.click(screen.getByRole('button', { name: 'Salvar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('"abc" não é um número');
    expect(screen.getByRole('button', { name: 'Salvar' })).toBeInTheDocument(); // continua editando
  });

  it('histórico da marca', async () => {
    const { user } = await openMark(FIELDS);
    await user.click(await screen.findByRole('button', { name: 'Histórico' }));
    const items = within(await screen.findByRole('list', { name: 'Histórico da marca' })).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Fábio Fábrica');
    expect(items[0]).toHaveTextContent('Tipo de forma: F-11 → F-12');
    expect(items[1]).toHaveTextContent('Ciclo de cura: 8,5');
  });

  it('projetos vê os valores sem Editar', async () => {
    await openMark(FIELDS, { userId: '1' });
    expect(await screen.findByLabelText('Valores da marca')).toHaveTextContent('Tipo de forma *F-11');
    expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
  });

  it('peça sem Marca: sem edição de valores', async () => {
    const { viewer } = await openMark(FIELDS);
    viewer.click([30]);
    expect(await screen.findByText('Peça sem Marca: os parâmetros da fábrica são preenchidos por marca.')).toBeInTheDocument();
  });
});

describe('Edição em lote (6.3)', () => {
  afterEach(() => {
    setDevUser(null);
  });

  const CATEGORY: Record<number, string> = { 1: 'Structural Columns', 2: 'Structural Columns', 3: 'Structural Framing' };
  const DEFS = [
    { def_id: 2, name: 'Ciclo de cura', type: 'number' as const, unit: 'h', required: false, options: null, categories: null },
    { def_id: 1, name: 'Tipo de forma', type: 'list' as const, unit: null, required: true, options: ['F-11', 'F-12', 'F-13'], categories: ['Structural Columns'] },
  ];
  type Def = (typeof DEFS)[number];
  type Values = Record<number, Record<number, unknown>>;

  const appliesTo = (d: Def, ids: number[]) => ids.filter((m) => !d.categories || d.categories.includes(CATEGORY[m] ?? ''));
  const parse = (d: Def, raw: unknown) => (d.type === 'number' && typeof raw === 'string' ? Number(raw.replace(',', '.')) : raw);

  /** Backend falso do lote, com estado: valores[marca][parâmetro]. */
  function batchApi(initial: Values) {
    let values: Values = structuredClone(initial);
    const snapshots = new Map<string, Values>();
    const calls: { path: string; body: unknown }[] = [];
    const preview = (req: FakeRequest): BatchPreview => {
      const { mark_ids, changes, mode } = req.body as BatchRequest;
      const fields = DEFS.filter((d) => appliesTo(d, mark_ids).length > 0).map((d) => {
        const current = appliesTo(d, mark_ids).map((m) => values[m]?.[d.def_id] ?? null);
        const distinct = new Set(current.map((v) => JSON.stringify(v)));
        return {
          ...d,
          applies_to: current.length,
          filled: current.filter((v) => v !== null).length,
          mixed: distinct.size > 1,
          common_value: distinct.size === 1 ? current[0] : null,
        };
      });
      const touched = { overwrite: new Set<number>(), only_empty: new Set<number>() };
      const other = new Set<number>();
      for (const [key, raw] of Object.entries(changes)) {
        const d = DEFS.find((x) => x.def_id === Number(key));
        if (!d) continue;
        const next = parse(d, raw);
        for (const m of appliesTo(d, mark_ids)) {
          const old = values[m]?.[d.def_id] ?? null;
          if (old === next) continue;
          touched.overwrite.add(m);
          if (old === null) touched.only_empty.add(m);
          else other.add(m);
        }
      }
      return {
        marks: mark_ids.length,
        categories: [...new Set(mark_ids.map((m) => CATEGORY[m] ?? ''))].sort(),
        fields,
        changes: [],
        marks_to_change: touched[mode].size,
        marks_to_change_overwrite: touched.overwrite.size,
        marks_to_change_only_empty: touched.only_empty.size,
        marks_with_other_value: other.size,
      };
    };
    const routes: Parameters<typeof installFakeApi>[0] = {
      'POST /api/obras/7/marks/batch-preview': (req) => {
        calls.push({ path: req.path, body: req.body });
        return preview(req);
      },
      'POST /api/obras/7/marks/batch-apply': (req) => {
        calls.push({ path: req.path, body: req.body });
        const { mark_ids, changes, mode } = req.body as BatchRequest;
        const id = `batch-${String(snapshots.size + 1)}`;
        snapshots.set(id, structuredClone(values));
        const changed = new Set<number>();
        for (const [key, raw] of Object.entries(changes)) {
          const d = DEFS.find((x) => x.def_id === Number(key));
          if (!d) continue;
          const next = parse(d, raw);
          for (const m of appliesTo(d, mark_ids)) {
            const old = values[m]?.[d.def_id] ?? null;
            if (old === next || (mode === 'only_empty' && old !== null)) continue;
            values[m] = { ...values[m], [d.def_id]: next };
            changed.add(m);
          }
        }
        return { batch_id: id, marks_changed: changed.size, fields_changed: changed.size };
      },
      'POST /api/batches/batch-1/undo': (req) => {
        calls.push({ path: req.path, body: null });
        values = snapshots.get('batch-1') ?? values;
        return { batch_id: 'undo-1', restored: 1 };
      },
    };
    return { routes, calls, values: () => values };
  }

  async function openMarks(initial: Values, clicks: DbId[][], userId = '2') {
    const api = batchApi(initial);
    const r = renderModel([version(1)], undefined, undefined, { userId, routes: api.routes });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    for (const ids of clicks) r.viewer.click(ids);
    return { ...r, ...api, user: userEvent.setup() };
  }

  it('2+ marcas: "N marcas selecionadas", valor comum e "(valores mistos)"', async () => {
    await openMarks({ 1: { 1: 'F-11', 2: 12 }, 2: { 1: 'F-12', 2: 12 } }, [[11], [11, 12]]);
    expect(await screen.findByText('2 marcas selecionadas')).toBeInTheDocument();
    const list = await screen.findByLabelText('Valores das marcas selecionadas');
    expect(list).toHaveTextContent('Ciclo de cura (h)12');
    expect(list).toHaveTextContent('Tipo de forma *(valores mistos)');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('aviso quando a seleção mistura categorias', async () => {
    await openMarks({}, [[11], [11, 20]]);
    expect(await screen.findByRole('note')).toHaveTextContent(
      'A seleção mistura categorias (Structural Columns, Structural Framing). Cada parâmetro só é gravado nas marcas em que se aplica.',
    );
    expect(await screen.findByLabelText('Valores das marcas selecionadas')).toHaveTextContent('Tipo de forma *— · 1 de 2');
  });

  it('Editar em lote: campo misto começa em "manter", confirmação, Só nas vazias e Desfazer', async () => {
    const { user, calls, values } = await openMarks({ 1: { 1: 'F-11' }, 2: {} }, [[11], [11, 12]]);
    await user.click(await screen.findByRole('button', { name: 'Editar em lote' }));
    const forma = panel().getByLabelText(/Tipo de forma/);
    expect(forma).toHaveValue('');
    expect(within(forma).getByRole('option', { name: '(valores mistos: manter)' })).toBeInTheDocument();

    await user.selectOptions(forma, 'F-12');
    await user.click(screen.getByRole('button', { name: 'Aplicar' }));
    const dialog = await screen.findByRole('dialog', { name: 'Aplicar às marcas selecionadas' });
    expect(dialog).toHaveTextContent('2 marcas serão alteradas. 1 marca já tem outro valor.');
    expect(within(dialog).getByRole('button', { name: 'Sobrescrever todas' })).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Só nas vazias' }));

    const toast = await screen.findByRole('status');
    expect(toast).toHaveTextContent('Valores aplicados a 1 marca.');
    expect(calls.find((c) => c.path.endsWith('batch-apply'))?.body).toEqual({
      mark_ids: [1, 2],
      changes: { 1: 'F-12' },
      mode: 'only_empty',
    });
    expect(values()).toEqual({ 1: { 1: 'F-11' }, 2: { 1: 'F-12' } }); // PP001 (preenchida) intacta

    await user.click(within(toast).getByRole('button', { name: 'Desfazer' }));
    expect(await screen.findByText('Edição em lote desfeita.')).toBeInTheDocument();
    expect(values()).toEqual({ 1: { 1: 'F-11' }, 2: {} });
    expect(calls.some((c) => c.path === '/api/batches/batch-1/undo')).toBe(true);
  });

  it('Sobrescrever todas grava em todas e só o campo alterado vai no lote', async () => {
    const { user, calls, values } = await openMarks({ 1: { 1: 'F-11', 2: 8 }, 2: { 2: 10 } }, [[11], [11, 12]]);
    await user.click(await screen.findByRole('button', { name: 'Editar em lote' }));
    expect(screen.getByLabelText('Ciclo de cura (h)')).toHaveAttribute('placeholder', '(valores mistos: manter)');
    await user.selectOptions(panel().getByLabelText(/Tipo de forma/), 'F-13');
    await user.click(screen.getByRole('button', { name: 'Aplicar' }));
    await user.click(await screen.findByRole('button', { name: 'Sobrescrever todas' }));
    await screen.findByText('Valores aplicados a 2 marcas.');
    expect(calls.filter((c) => c.path.endsWith('batch-apply')).map((c) => c.body)).toEqual([
      { mark_ids: [1, 2], changes: { 1: 'F-13' }, mode: 'overwrite' },
    ]);
    expect(values()).toEqual({ 1: { 1: 'F-13', 2: 8 }, 2: { 1: 'F-13', 2: 10 } });
    await vi.waitFor(() => {
      expect(screen.getByLabelText('Valores das marcas selecionadas')).toHaveTextContent('Tipo de forma *F-13');
    });
  });

  it('projetos vê o resumo do lote sem "Editar em lote"', async () => {
    await openMarks({}, [[11], [11, 12]], '1');
    expect(await screen.findByLabelText('Valores das marcas selecionadas')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar em lote' })).not.toBeInTheDocument();
  });
});

describe('Coloração, legenda e progresso (6.4 / F4)', () => {
  afterEach(() => {
    setDevUser(null);
    colorizeCalls.length = 0;
  });

  const FORMA = {
    id: 1, name: 'Tipo de forma', type: 'list', unit: null, options: ['F-11', 'F-12'], required: true,
    categories: ['Structural Columns'], scope: 'global', obra_id: null, obra_code: null, active: true,
    values_count: 1, options_in_use: ['F-11'], created_at: '2026-11-11T12:00:00Z', updated_at: '2026-11-11T12:00:00Z',
    created_by_name: 'Fábio Fábrica',
  };

  async function open(routes: Parameters<typeof installFakeApi>[0] = {}) {
    const r = renderModel([version(1)], undefined, undefined, { routes: { 'GET /api/param-defs': [FORMA], ...routes } });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    await vi.waitFor(() => { expect(screen.getByRole('button', { name: 'Colorir' })).toBeEnabled(); });
    return { ...r, user: userEvent.setup() };
  }
  const legend = () => screen.findByRole('region', { name: 'Legenda' });
  const lastColors = (viewer: FakeViewer) => viewer.setColors.mock.lastCall?.[0] as ReadonlyMap<DbId, string> | undefined;
  const colorPop = async (user: ReturnType<typeof userEvent.setup>) => {
    if (!screen.queryByRole('dialog', { name: 'Colorir' })) await user.click(screen.getByRole('button', { name: 'Colorir' }));
    return within(screen.getByRole('dialog', { name: 'Colorir' }));
  };

  it('por padrão colore por status (backend) pelo ViewerAdapter.setColors; legenda com os 4 status', async () => {
    const { viewer } = await open();
    const box = await legend();
    expect(box).toHaveTextContent('Status de produção');
    expect(colorizeCalls[0]).toEqual({ field: { source: 'system', key: 'status' }, mode: 'distinct' });
    expect(within(box).getAllByRole('button', { name: /: / }).map((b) => b.getAttribute('aria-label'))).toEqual([
      'Pendente: 1 marca · 2 peças', 'Parcial: 1 marca · 2 peças', 'Completa: 1 marca · 2 peças', 'Revisar: 0 marcas · 0 peças',
    ]);
    expect(within(box).getByRole('button', { name: /^Revisar/ })).toBeDisabled();
    await vi.waitFor(() => { expect(lastColors(viewer)?.get(10)).toBe('#33A06F'); });
    expect([lastColors(viewer)?.get(12), lastColors(viewer)?.get(20)]).toEqual(['#E3B341', '#B9BEC6']);
  });

  it('clicar num item da legenda seleciona as peças dele; a legenda pode ser retraída numa pílula com resumo', async () => {
    const { viewer, user } = await open();
    await user.click(within(await legend()).getByRole('button', { name: /^Parcial/ }));
    expect(await screen.findByRole('heading', { name: 'PP002 · Structural Columns · 2 peças' })).toBeInTheDocument();
    expect(viewer.selectDbIds).toHaveBeenLastCalledWith([12, 13]);
    await user.click(screen.getByRole('button', { name: 'Retrair legenda' }));
    expect(screen.queryByRole('region', { name: 'Legenda' })).not.toBeInTheDocument();
    const pill = screen.getByRole('button', { name: /^Expandir legenda: Status · / });
    expect(pill).toHaveAttribute('aria-expanded', 'false');
    await user.click(pill);
    expect(await legend()).toBeInTheDocument();
    localStorage.clear();
  });

  it('popover Colorir: Status e Categoria no topo, busca em todos os campos, cor por gama', async () => {
    const { viewer, user } = await open();
    let pop = await colorPop(user);
    await user.click(pop.getByRole('button', { name: 'Categoria' }));
    await vi.waitFor(async () => { expect(await legend()).toHaveTextContent('Categoria'); });
    expect(within(await legend()).getByRole('button', { name: 'Structural Columns: 2 marcas · 4 peças' })).toBeInTheDocument();
    await vi.waitFor(() => { expect(lastColors(viewer)?.get(20)).toBe('#FF7F0E'); });

    // Cor por gama só vale para números e datas
    pop = await colorPop(user);
    expect(pop.getByRole('checkbox', { name: 'Cor por gama' })).toBeDisabled();
    // campos sim/não e calculados não aparecem; Status/Categoria só no topo
    expect(pop.queryByRole('button', { name: /Nova na versão/ })).not.toBeInTheDocument();
    await user.type(pop.getByRole('searchbox', { name: 'Buscar parâmetro' }), 'forma');
    await user.click(pop.getByRole('button', { name: /Tipo de forma/ }));
    await vi.waitFor(async () => { expect(await legend()).toHaveTextContent('Tipo de forma'); });
    expect(within(await legend()).getByRole('button', { name: 'F-11: 1 marca · 2 peças' })).toBeInTheDocument();
    expect(within(await legend()).getByRole('button', { name: 'Sem valor: 2 marcas · 4 peças' })).toBeInTheDocument();

    pop = await colorPop(user);
    await user.clear(pop.getByRole('searchbox', { name: 'Buscar parâmetro' }));
    await user.click(pop.getByRole('button', { name: /Data de expedição/ }));
    await user.click(pop.getByRole('checkbox', { name: 'Cor por gama' }));
    await vi.waitFor(() => { expect(colorizeCalls.at(-1)).toEqual({ field: { source: 'factory', key: '5' }, mode: 'range' }); });
    expect(await legend()).toHaveTextContent('Data de expedição (por gama)');
    await vi.waitFor(() => { expect(lastColors(viewer)?.get(20)).toBe('#C6DBEF'); });
  });

  it('Remover coloração volta às cores originais; escolher um modo liga de novo', async () => {
    const { viewer, user } = await open();
    await legend();
    await user.click(screen.getByRole('button', { name: 'Remover coloração' }));
    await vi.waitFor(() => { expect(viewer.clearColors).toHaveBeenCalled(); });
    expect(screen.queryByRole('region', { name: 'Legenda' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remover coloração' })).not.toBeInTheDocument();
    const pop = await colorPop(user);
    expect(pop.getByRole('button', { name: 'Status' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(pop.getByRole('button', { name: 'Status' }));
    expect(await legend()).toHaveTextContent('Status de produção');
  });

  it('coloração e filtro juntos: o filtro decide o que aparece, a coloração a cor', async () => {
    const { viewer, user } = await open();
    await legend();
    await user.click(screen.getByRole('button', { name: /^Filtro/ }));
    await user.type(screen.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'V-01');
    await vi.waitFor(() => { expect(viewer.highlight).toHaveBeenLastCalledWith([20, 21]); });
    expect(viewer.clearColors).not.toHaveBeenCalled();
    expect(lastColors(viewer)?.get(10)).toBe('#33A06F');
  });

  it('Editar cores: esquema com 2 regras (prévia, prioridade, mover) salvo e aplicado', async () => {
    const created: unknown[] = [];
    const previews: SchemeRule[][] = [];
    const evaluate = (req: FakeRequest) => {
      const body = req.body as { rules?: SchemeRule[]; scheme_id?: number };
      const rules = body.rules ?? (created[0] as { rules: SchemeRule[] }).rules;
      if (body.rules) previews.push(body.rules);
      // filtro 1 (Pendentes) = V-01; filtro 2 (Parciais) = PP002; filtro 3 (Novas) = V-01
      const hits: Record<number, number[]> = { 1: [20, 21], 2: [12, 13], 4: [20, 21] };
      const taken = new Set<number>();
      const results = rules.map((r, index) => {
        const all = hits[r.filter as number] ?? [];
        const mine = all.filter((d) => !taken.has(d));
        mine.forEach((d) => taken.add(d));
        return { index, label: SAVED.find((f) => f.id === r.filter)?.name ?? '', color: r.color, filter_id: r.filter as number, matched: all.length, pieces: mine.length, dbids: mine };
      });
      const colors: Record<string, string> = {};
      results.forEach((x) => { x.dbids.forEach((d) => { colors[String(d)] = x.color; }); });
      return { colors, rules: results, total_pieces: 6, colored_pieces: taken.size, notes: [] };
    };
    const { viewer, user } = await open({
      'POST /api/versions/1/color-scheme/evaluate': evaluate,
      'POST /api/color-schemes': (req: FakeRequest) => {
        created.push(req.body);
        return { ...(req.body as object), id: 70, owner_id: 2, editable: true, created_at: '', updated_at: '', created_by: 2, updated_by: 2 };
      },
    });
    await user.click(screen.getByRole('button', { name: 'Colorir' })); // "Editar cores" fica no popover Colorir
    await user.click(screen.getByRole('button', { name: 'Editar cores' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Cores' }));
    expect(dialog.getByRole('combobox', { name: 'Esquema de cores' })).toHaveValue('');

    const addRule = async (filterName: string, color: string) => {
      await user.click(dialog.getByRole('button', { name: 'Adicionar' }));
      const rule = within(await screen.findByRole('dialog', { name: 'Adicionar regra' }));
      await user.selectOptions(rule.getByRole('combobox', { name: 'Filtro salvo' }), rule.getByRole('option', { name: new RegExp(filterName) }));
      fireColor(rule.getByLabelText('Cor'), color);
      await user.click(rule.getByRole('button', { name: 'OK' }));
    };
    await addRule('Pendentes', '#ff0000');
    await addRule('Novas na versão', '#00ff00');
    // a 2ª regra pega as mesmas peças: com a 1ª na frente, fica com 0
    await vi.waitFor(() => { expect(dialog.getAllByRole('cell').map((c) => c.textContent)).toEqual(['', 'Pendentes', '2', '', 'Novas na versão', '0']); });
    await user.click(dialog.getByRole('button', { name: 'Mover para cima' })); // a selecionada é a 2ª
    await vi.waitFor(() => { expect(dialog.getAllByRole('cell').map((c) => c.textContent)).toEqual(['', 'Novas na versão', '2', '', 'Pendentes', '0']); });
    await user.click(dialog.getByRole('radio', { name: 'Regra 2: Pendentes' }));
    await user.click(dialog.getByRole('button', { name: 'Remover' }));
    await addRule('Parciais', '#0000ff');
    expect(dialog.getByRole('option', { name: 'Todos (compartilhado)' })).toBeInTheDocument(); // fábrica compartilha
    await user.type(dialog.getByRole('textbox', { name: 'Nome do esquema' }), 'Expedição');
    await user.click(dialog.getByRole('button', { name: 'Salvar' }));
    await vi.waitFor(() => {
      expect(created).toEqual([{
        name: 'Expedição', scope: 'personal', obra_id: 7,
        rules: [{ filter: 4, color: '#00FF00' }, { filter: 2, color: '#0000FF' }],
      }]);
    });
    expect(previews.length).toBeGreaterThan(0);
    // aplicado no modelo: legenda do esquema, na ordem das regras
    const box = await legend();
    await vi.waitFor(() => { expect(box).toHaveTextContent('Expedição'); });
    expect(within(box).getAllByRole('button', { name: /: / }).map((b) => b.getAttribute('aria-label'))).toEqual([
      'Novas na versão: 1 marca · 2 peças', 'Parciais: 1 marca · 2 peças',
    ]);
    expect(box).toHaveTextContent('2 peças sem regra ficam com a cor original.');
    await vi.waitFor(() => { expect(lastColors(viewer)?.get(20)).toBe('#00FF00'); });
  });

  it('rodapé com a barra de progresso de cada obrigatório', async () => {
    await open();
    const bar = await screen.findByRole('progressbar', { name: 'Progresso de Tipo de forma' });
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    const foot = screen.getByRole('region', { name: 'Progresso' });
    expect(foot).toHaveTextContent('1/2 marcas · 2/4 peças (50%)');
    expect(foot).toHaveTextContent('OB-001 · V1 · 3 marcas · 6 peças');
  });

  it('sem obrigatórios o rodapé explica', async () => {
    await open({ 'GET /api/versions/1/progress': { marks: 3, pieces: 6, required: [] } });
    expect(await screen.findByText(/Nenhum parâmetro obrigatório: o status das peças conta todos os parâmetros/)).toBeInTheDocument();
  });

  it('salvar valores atualiza status, cores e progresso', async () => {
    let colorCalls = 0;
    let progressCalls = 0;
    const field: FieldValue = {
      def_id: 1, name: 'Tipo de forma', type: 'list', unit: null, required: true, options: ['F-11', 'F-12'],
      value: null, row_version: null, updated_at: null, updated_by_name: null,
    };
    const values: MarkValues = { mark: { id: 3, code: 'V-01', category: 'Structural Framing' }, values: [field], last_change_by: null, last_change_at: null };
    const { viewer, user } = await open({
      'POST /api/versions/1/colorize': (req: FakeRequest) => { colorCalls += 1; return colorizeApi(req); },
      'GET /api/versions/1/progress': () => { progressCalls += 1; return PROGRESS; },
      'GET /api/obras/7/marks/3/values': values,
      'PUT /api/obras/7/marks/3/values': { ...values, values: [{ ...field, value: 'F-12', row_version: 1 }] },
    });
    await legend();
    const before = [colorCalls, progressCalls];
    viewer.click([20]);
    await user.click(await panel().findByRole('button', { name: 'Editar' }));
    await user.selectOptions(panel().getByLabelText(/Tipo de forma/), 'F-12');
    await user.click(panel().getByRole('button', { name: 'Salvar' }));
    await vi.waitFor(() => {
      expect(colorCalls).toBeGreaterThan(before[0] ?? 0);
      expect(progressCalls).toBeGreaterThan(before[1] ?? 0);
    });
  });
});

describe('Reconciliação: banner, revisar e órfãs (7.2)', () => {
  afterEach(() => {
    setDevUser(null);
    vi.restoreAllMocks();
  });

  const DIFF: VersionDiff = {
    version_id: 1, version_number: 2, prev_version_id: 9, prev_version_number: 1,
    totals: { unchanged: 1, count_changed: 0, changed: 1, new: 2, removed: 1 },
    review: 1, orphans: 1, returned: 0, review_open: 1, orphans_open: 1, review_properties: ['Seção'], marks: [],
  };
  const ORPHAN: Orphan = {
    id: 5, status: 'open', mark_id: 9, code: 'PP009', category: 'Structural Columns', since_version_id: 1,
    since_version_number: 2, relinked_to: null, relinked_to_code: null, created_at: '2026-11-11T12:00:00Z',
    updated_at: '2026-11-11T12:00:00Z', values: [{ def_id: 1, name: 'Tipo de forma', type: 'list', value: 'F-12' }],
  };
  const reviewField: FieldValue = {
    def_id: 1, name: 'Tipo de forma', type: 'list', unit: null, required: true, options: ['F-11', 'F-12'],
    value: 'F-11', row_version: 1, updated_at: null, updated_by_name: null,
  };

  function api(opts: { relinkConflict?: boolean } = {}) {
    let review = true;
    let orphans = [ORPHAN];
    const calls: { path: string; body: unknown }[] = [];
    let conflictLeft = opts.relinkConflict ?? false;
    const routes: Parameters<typeof installFakeApi>[0] = {
      'GET /api/versions/1/diff': () => ({ ...DIFF, review_open: review ? 1 : 0, orphans_open: orphans.length }),
      'GET /api/obras/7/marks/1/values': () => ({
        mark: {
          id: 1, code: 'PP001', category: 'Structural Columns',
          review_status: review ? 'review' : 'ok', review_note: review ? 'Altura: 60.0 cm → 80.0 cm; Seção: 40x60 → 40x80' : null,
        },
        values: [reviewField], last_change_by: null, last_change_at: null,
      }),
      'POST /api/marks/1/review/keep': (req) => {
        calls.push({ path: req.path, body: null });
        review = false;
        return { id: 1, code: 'PP001', category: 'Structural Columns', review_status: 'ok', review_note: null };
      },
      'GET /api/obras/7/orphans': () => orphans,
      'POST /api/orphans/5/archive': (req) => {
        calls.push({ path: req.path, body: null });
        orphans = [];
        return { id: 5, status: 'archived' };
      },
      'POST /api/orphans/5/relink': (req) => {
        calls.push({ path: req.path, body: req.body });
        if (conflictLeft) {
          conflictLeft = false;
          return Response.json(
            { detail: 'conflito', code: 'relink_conflict', conflicts: [{ def_id: 1, name: 'Tipo de forma', orphan_value: 'F-12', target_value: 'F-11' }] },
            { status: 409 },
          );
        }
        orphans = [];
        return { orphan_id: 5, target_mark_id: 3, copied: ['Tipo de forma'], skipped: [], batch_id: 'b' };
      },
    };
    return { routes, calls };
  }

  async function open(opts: { relinkConflict?: boolean; userId?: string } = {}) {
    const fake = api(opts);
    const r = renderModel([version(1)], undefined, undefined, { routes: fake.routes, userId: opts.userId ?? '2' });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    return { ...r, ...fake, user: userEvent.setup() };
  }

  it('banner da versão nova: "N novas · N a revisar · N órfãs" com atalhos', async () => {
    const { user } = await open();
    const banner = await screen.findByRole('region', { name: 'Versão nova' });
    expect(banner).toHaveTextContent('V2 comparada com a V1:');
    expect(banner).toHaveTextContent(/2 novas\s*·\s*1 a revisar\s*·\s*1 órfã/);
    await user.click(within(banner).getByRole('button', { name: '1 a revisar' }));
    await vi.waitFor(() => { expect(evalCalls.at(-1)?.rules).toEqual([{ ...statusRule('Revisar'), mode: 'highlight' }]); });
    await user.click(within(banner).getByRole('button', { name: '2 novas' }));
    await vi.waitFor(() => { expect(evalCalls.at(-1)?.rules[0]?.field.key).toBe('new'); });
    await user.click(within(banner).getByRole('button', { name: '1 órfã' }));
    expect(await screen.findByRole('dialog', { name: 'Marcas órfãs' })).toHaveTextContent('PP009');
    await user.click(screen.getByRole('button', { name: 'Fechar' }));
    await user.click(screen.getByRole('button', { name: 'Fechar aviso da versão' }));
    expect(screen.queryByRole('region', { name: 'Versão nova' })).not.toBeInTheDocument();
  });

  it('marca em revisão: alerta laranja com o diff; Manter valores limpa', async () => {
    const { viewer, user, calls } = await open();
    viewer.click([10]);
    const alert = await panel().findByRole('region', { name: 'Revisar' });
    expect(alert).toHaveTextContent('Seção: 40x60 → 40x80');
    expect(alert).toHaveTextContent('Altura: 60.0 cm → 80.0 cm');
    await user.click(within(alert).getByRole('button', { name: 'Manter valores' }));
    await vi.waitFor(() => { expect(panel().queryByRole('region', { name: 'Revisar' })).not.toBeInTheDocument(); });
    expect(calls.map((c) => c.path)).toContain('/api/marks/1/review/keep');
  });

  it('Editar no alerta abre o formulário da marca', async () => {
    const { viewer, user } = await open();
    viewer.click([10]);
    const alert = await panel().findByRole('region', { name: 'Revisar' });
    await user.click(within(alert).getByRole('button', { name: 'Editar' }));
    expect(panel().getByRole('form', { name: 'Editar parâmetros da fábrica' })).toBeInTheDocument();
  });

  it('projetos vê o alerta sem os botões', async () => {
    const { viewer } = await open({ userId: '1' });
    viewer.click([10]);
    const alert = await panel().findByRole('region', { name: 'Revisar' });
    expect(within(alert).queryByRole('button')).not.toBeInTheDocument();
  });

  it('Órfãs: arquivar com confirmação', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { user, calls } = await open();
    await user.click(screen.getByRole('button', { name: 'Marcas órfãs' }));
    const dialog = await screen.findByRole('dialog', { name: 'Marcas órfãs' });
    expect(dialog).toHaveTextContent('Sumiu na V2');
    expect(dialog).toHaveTextContent('Tipo de forma: F-12');
    await user.click(within(dialog).getByRole('button', { name: 'Arquivar PP009' }));
    expect(await within(dialog).findByText('Nenhuma órfã pendente.')).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toEqual(['/api/orphans/5/archive']);
  });

  it('Religar: clicar na marca de destino no 3D, confirmar e copiar', async () => {
    const { viewer, user, calls } = await open();
    await user.click(screen.getByRole('button', { name: 'Marcas órfãs' }));
    await user.click(await screen.findByRole('button', { name: 'Religar PP009' }));
    expect(screen.getByRole('status', { name: 'Religar órfã' })).toHaveTextContent('Religar PP009: clique na marca de destino');
    viewer.click([20]);
    const confirm = await screen.findByRole('dialog', { name: 'Religar órfã' });
    expect(confirm).toHaveTextContent('Religar PP009 (Structural Columns) → V-01 (Structural Framing)?');
    expect(confirm).toHaveTextContent('Categorias diferentes');
    await user.click(within(confirm).getByRole('button', { name: 'Religar' }));
    expect(await screen.findByText('PP009 religada a V-01: 1 valor copiado.')).toBeInTheDocument();
    expect(calls).toEqual([{ path: '/api/orphans/5/relink', body: { target_mark_id: 3, overwrite: false } }]);
    expect(screen.queryByRole('status', { name: 'Religar órfã' })).not.toBeInTheDocument();
  });

  it('Religar pela lista; conflito pede para sobrescrever', async () => {
    const { user, calls } = await open({ relinkConflict: true });
    await user.click(screen.getByRole('button', { name: 'Marcas órfãs' }));
    await user.click(await screen.findByRole('button', { name: 'Religar PP009' }));
    await user.click(screen.getByRole('button', { name: /^PP002/ }));
    const confirm = await screen.findByRole('dialog', { name: 'Religar órfã' });
    await user.click(within(confirm).getByRole('button', { name: 'Religar' }));
    expect(await within(confirm).findByRole('alert')).toHaveTextContent('Tipo de forma: F-11 (órfã: F-12)');
    await user.click(within(confirm).getByRole('button', { name: 'Sobrescrever e religar' }));
    expect(await screen.findByText('PP009 religada a PP002: 1 valor copiado.')).toBeInTheDocument();
    expect(calls.map((c) => c.body)).toEqual([
      { target_mark_id: 2, overwrite: false },
      { target_mark_id: 2, overwrite: true },
    ]);
  });
});

describe('Tempo real (8.1)', () => {
  afterEach(() => {
    setDevUser(null);
  });

  /** Canal SSE falso: cada conexão vira um stream em que o teste empurra eventos. */
  function liveChannel() {
    const enc = new TextEncoder();
    let push: ((text: string) => void) | null = null;
    let seq = 0;
    const route = () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            push = (text) => { controller.enqueue(enc.encode(text)); };
            controller.enqueue(enc.encode(': conectado\n\n'));
          },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
      );
    const send = (type: string, data: Record<string, unknown>, actor: { id: number; name: string } | null) => {
      seq += 1;
      const body = { type, obra_id: 7, at: '2026-11-11T12:00:00Z', actor, ...data };
      act(() => { push?.(`id: ${String(seq)}-0\nevent: ${type}\ndata: ${JSON.stringify(body)}\n\n`); });
    };
    return { route, send, connected: () => push !== null };
  }

  it('edição de outro usuário: aviso discreto e os valores da marca recarregam', async () => {
    const ch = liveChannel();
    let valueReads = 0;
    const r = renderModel([version(1)], undefined, undefined, {
      routes: {
        'GET /api/obras/7/events': ch.route,
        'GET /api/obras/7/marks/1/values': () => {
          valueReads += 1;
          return { mark: { id: 1, code: 'PP001', category: 'Structural Columns' }, values: [], last_change_by: null, last_change_at: null };
        },
      },
    });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    r.viewer.click([10]);
    expect(await panel().findByText('Nenhum parâmetro se aplica a esta categoria.')).toBeInTheDocument();
    expect(valueReads).toBe(1);
    await vi.waitFor(() => { expect(ch.connected()).toBe(true); });

    ch.send('values_changed', { mark_id: 1, mark: 'PP001', fields: ['Tipo de forma'] }, { id: 1, name: 'Paula Projetos' });
    const log = screen.getByRole('log', { name: 'Atualizações da obra' });
    expect(await within(log).findByText('Paula Projetos alterou PP001')).toBeInTheDocument();
    await vi.waitFor(() => { expect(valueReads).toBe(2); });

    // a própria edição não gera aviso (mas atualiza)
    ch.send('values_changed', { mark_id: 1, mark: 'PP001', fields: [] }, { id: 2, name: 'Fábio Fábrica' });
    await vi.waitFor(() => { expect(valueReads).toBe(3); });
    expect(within(log).queryByText('Fábio Fábrica alterou PP001')).not.toBeInTheDocument();

    ch.send('batch_applied', { marks: 10 }, { id: 1, name: 'Paula Projetos' });
    expect(await within(log).findByText('Paula Projetos alterou 10 marcas em lote')).toBeInTheDocument();
    await userEvent.setup().click(within(log).getAllByRole('button', { name: 'Fechar aviso' })[0] as HTMLElement);
    expect(within(log).queryByText('Paula Projetos alterou PP001')).not.toBeInTheDocument();
  });

  it('colega salva durante a edição: o evento recarrega, mas salvar usa a versão lida e avisa o conflito', async () => {
    const ch = liveChannel();
    const field: FieldValue = {
      def_id: 1, name: 'Tipo de forma', type: 'list', unit: null, required: true, options: ['F-11', 'F-12', 'F-13'],
      value: 'F-11', row_version: 1, updated_at: null, updated_by_name: null,
    };
    let server = { ...field };
    const puts: unknown[] = [];
    const r = renderModel([version(1)], undefined, undefined, {
      routes: {
        'GET /api/obras/7/events': ch.route,
        'GET /api/obras/7/marks/1/values': () => ({
          mark: { id: 1, code: 'PP001', category: 'Structural Columns' }, values: [server], last_change_by: null, last_change_at: null,
        }),
        'PUT /api/obras/7/marks/1/values': (req) => {
          puts.push(req.body);
          const [c] = (req.body as { changes: { row_version: number | null }[] }).changes;
          if (c?.row_version !== server.row_version) {
            return Response.json(
              { detail: 'conflito', code: 'stale', changed_by_name: 'Paula Projetos', changed_at: new Date().toISOString(), conflict_def_ids: [1] },
              { status: 409 },
            );
          }
          return { mark: { id: 1, code: 'PP001', category: 'Structural Columns' }, values: [server], last_change_by: null, last_change_at: null };
        },
      },
    });
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    r.viewer.click([10]);
    await user.click(await panel().findByRole('button', { name: 'Editar' }));
    await user.selectOptions(panel().getByLabelText(/Tipo de forma/), 'F-12');
    await vi.waitFor(() => { expect(ch.connected()).toBe(true); });

    // Paula salva F-13 enquanto o formulário está aberto; o evento recarrega os valores
    server = { ...field, value: 'F-13', row_version: 2 };
    ch.send('values_changed', { mark_id: 1, mark: 'PP001', fields: ['Tipo de forma'] }, { id: 1, name: 'Paula Projetos' });
    expect(await screen.findByText('Paula Projetos alterou PP001')).toBeInTheDocument();
    expect(panel().getByLabelText(/Tipo de forma/)).toHaveValue('F-12'); // a edição não é perdida

    await user.click(panel().getByRole('button', { name: 'Salvar' }));
    expect(await panel().findByRole('alert')).toHaveTextContent('Paula Projetos alterou esta marca');
    expect(puts).toEqual([{ changes: [{ def_id: 1, value: 'F-12', row_version: 1 }] }]); // versão lida no início
  });

  it('versão nova pronta: banner "Nova versão disponível" e Carregar troca o modelo', async () => {
    const ch = liveChannel();
    let list = [version(1)];
    const r = renderModel([version(1)], undefined, undefined, {
      routes: { 'GET /api/obras/7/events': ch.route, 'GET /api/obras/7/versions': () => list },
    });
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    await vi.waitFor(() => { expect(r.viewer.load).toHaveBeenCalledWith('urn-v1'); });
    await vi.waitFor(() => { expect(ch.connected()).toBe(true); });

    list = [version(2), version(1)];
    ch.send('version_ready', { version_id: 2, version_number: 2, status: 'ready' }, null);
    const banner = await screen.findByRole('region', { name: 'Nova versão disponível' });
    expect(banner).toHaveTextContent('Nova versão disponível: V2 acabou de ficar pronta.');
    expect(r.viewer.load).not.toHaveBeenCalledWith('urn-v2'); // não troca sozinho

    await userEvent.setup().click(within(banner).getByRole('button', { name: 'Carregar' }));
    await vi.waitFor(() => { expect(r.viewer.load).toHaveBeenLastCalledWith('urn-v2'); });
    expect(screen.queryByRole('region', { name: 'Nova versão disponível' })).not.toBeInTheDocument();
  });

  it('textos dos avisos', () => {
    const ev = (type: ObraEvent['type'], data: Record<string, unknown>): ObraEvent => ({
      id: '1-0',
      type,
      data: { type, obra_id: 7, at: '', actor: { id: 1, name: 'J. Silva' }, ...data },
    });
    expect(describeEvent(ev('values_changed', { mark: 'PP003' }))).toBe('J. Silva alterou PP003');
    expect(describeEvent(ev('values_changed', { mark: 'PP003', review: 'kept' }))).toBe('J. Silva manteve os valores de PP003 (revisão)');
    expect(describeEvent(ev('batch_applied', { marks: 1 }))).toBe('J. Silva alterou 1 marca em lote');
    expect(describeEvent(ev('batch_undone', {}))).toBe('J. Silva desfez uma edição em lote');
    expect(describeEvent(ev('orphan_changed', { mark: 'PP004', status: 'relinked', target: 'PP004A' }))).toBe(
      'J. Silva religou a órfã PP004 a PP004A',
    );
    expect(describeEvent(ev('orphan_changed', { mark: 'PP005', status: 'archived' }))).toBe('J. Silva arquivou a órfã PP005');
    expect(describeEvent(ev('param_def_changed', { name: 'Ciclo', action: 'created' }))).toBe('J. Silva criou o parâmetro “Ciclo”');
    expect(describeEvent(ev('version_failed', { version_number: 3 }))).toBe('A versão 3 não pôde ser processada');
    expect(describeEvent(ev('version_ready', {}))).toBeNull();
    // parâmetros por peça (P2)
    expect(describeEvent(ev('unit_values_changed', { unit: 'PP001-3' }))).toBe('J. Silva alterou a peça PP001-3');
    expect(describeEvent(ev('unit_batch_applied', { units: 4 }))).toBe('J. Silva alterou 4 peças em lote');
    expect(describeEvent(ev('unit_batch_undone', {}))).toBe('J. Silva desfez uma edição em lote de peças');
    // tipo desconhecido (servidor mais novo que a tela): sem aviso, sem quebrar
    expect(describeEvent(ev('outro' as ObraEvent['type'], {}))).toBeNull();
  });
});

describe('Exportar Excel (9.1)', () => {
  afterEach(() => {
    setDevUser(null);
    vi.unstubAllGlobals();
  });

  it('nome do arquivo do Content-Disposition', () => {
    expect(filenameFrom(`attachment; filename="OB_Rev.02.xlsx"; filename*=UTF-8''OB%C3%A7_Rev.02.xlsx`, 'x')).toBe('OBç_Rev.02.xlsx');
    expect(filenameFrom('attachment; filename="OB_Rev.02.xlsx"', 'x')).toBe('OB_Rev.02.xlsx');
    expect(filenameFrom(null, 'x.xlsx')).toBe('x.xlsx');
  });

  it('exporta a versão aberta com os filtros ativos e baixa o arquivo', async () => {
    const calls: FakeRequest[] = [];
    const created: Blob[] = [];
    vi.stubGlobal('URL', Object.assign(URL, {
      createObjectURL: (b: Blob) => { created.push(b); return 'blob:x'; },
      revokeObjectURL: () => undefined,
    }));
    const clicks: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    });
    renderModel([version(2), version(1)], '/obras/7/modelo?versao=1', undefined, {
      routes: {
        'POST /api/obras/7/export.xlsx': (req) => {
          calls.push(req);
          return new Response(new Blob(['xlsx']), {
            headers: { 'Content-Disposition': `attachment; filename="OB-001_Rev.01_2026-11-11.xlsx"` },
          });
        },
      },
    });
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    await vi.waitFor(() => { expect(screen.getByRole('button', { name: /^Filtro/ })).toBeEnabled(); });
    await user.click(screen.getByRole('button', { name: /^Filtro/ }));
    await user.type(screen.getByRole('searchbox', { name: 'Pesquisar por objetos' }), 'PP');
    await vi.waitFor(() => { expect(screen.getByText('com o filtro ativo')).toBeInTheDocument(); });

    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await vi.waitFor(() => { expect(clicks).toEqual(['OB-001_Rev.01_2026-11-11.xlsx']); });
    expect(calls[0]?.body).toEqual({ version_id: 1, filter: { mode: 'isolate', logic: 'and', rules: [], q: 'PP' } }); // a versão aberta
    expect(calls[0]?.headers.get('X-Dev-User')).toBe('2');
    expect(created).toHaveLength(1);
    click.mockRestore();
  });

  it('erro na exportação aparece ao lado do botão', async () => {
    renderModel([version(1)], undefined, undefined, {
      routes: { 'POST /api/obras/7/export.xlsx': Response.json({ detail: 'Falhou.' }, { status: 500 }) },
    });
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: 'Marcas (3)' });
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    expect(await screen.findByText('Falhou.')).toBeInTheDocument();
  });
});
