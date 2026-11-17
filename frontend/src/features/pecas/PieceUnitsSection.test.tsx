import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ParamDef } from '../../api/paramDefs';
import type { MarkUnits, PieceUnit, UnitBatchRequest, UnitChange } from '../../api/units';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { ParamDefDialog } from '../params/ParamDefDialog';
import { PieceUnitsSection } from './PieceUnitsSection';
import { rowOf, rowsOf, shortId, withoutPiece } from './unitTable';

const FAB = 9; // "Data de fabricação" (data, por peça)

const unit = (n: number, value: string | null = null): PieceUnit => ({
  id: 100 + n,
  number: n,
  label: `PP001-${String(n)}`,
  status: 'linked',
  external_id: `0f3c-aaaa-bbbb-${String(1000 + n)}`,
  since_version_id: 5,
  element: {
    element_id: 500 + n,
    dbid: 10 + n,
    external_id: `0f3c-aaaa-bbbb-${String(1000 + n)}`,
    level: n <= 3 ? 'TÉRREO' : '1º PAVIMENTO',
    name: `Pilar [${String(10 + n)}]`,
    method: 'key',
  },
  values: [
    {
      def_id: FAB,
      value,
      row_version: value === null ? null : 1,
      updated_at: null,
      updated_by_name: null,
    },
  ],
});

const markUnits = (units: PieceUnit[]): MarkUnits => ({
  mark: { id: 1, code: 'PP001', category: 'Structural Columns' },
  version_id: 5,
  params: [{ def_id: FAB, name: 'Data de fabricação', type: 'date', unit: null, required: true, options: null }],
  units,
});

/** Backend falso com 6 unidades (PP001-1…6) que guarda o que for gravado. */
function fakeBackend(start: PieceUnit[] = [1, 2, 3, 4, 5, 6].map((n) => unit(n))) {
  let units = start;
  const calls: FakeRequest[] = [];
  const fetchMock = installFakeApi({
    'GET /api/obras/7/marks/1/units': (req) => {
      calls.push(req);
      return markUnits(units);
    },
    'PUT /api/obras/7/units/103/values': (req) => {
      calls.push(req);
      const [change] = (req.body as { changes: UnitChange[] }).changes;
      units = units.map((u) => (u.id === 103 ? unit(3, change?.value as string) : u));
      return { mark: markUnits(units).mark, params: markUnits(units).params, unit: units.find((u) => u.id === 103) };
    },
    'POST /api/obras/7/units/batch-preview': (req) => {
      calls.push(req);
      const body = req.body as UnitBatchRequest;
      const n = body.unit_ids.length;
      return {
        units: n,
        marks: 1,
        categories: ['Structural Columns'],
        fields: [{ ...markUnits(units).params[0], applies_to: n, filled: 0, mixed: false, common_value: null }],
        units_to_change: Object.keys(body.changes).length ? n : 0,
        units_to_change_overwrite: Object.keys(body.changes).length ? n : 0,
        units_to_change_only_empty: Object.keys(body.changes).length ? n : 0,
        units_with_other_value: 0,
      };
    },
    'POST /api/obras/7/units/batch-apply': (req) => {
      calls.push(req);
      const body = req.body as UnitBatchRequest;
      const value = body.changes[FAB] as string;
      units = units.map((u) => (body.unit_ids.includes(u.id) ? unit(u.number, value) : u));
      return { batch_id: 'b-1', units_changed: body.unit_ids.length, fields_changed: body.unit_ids.length };
    },
  });
  return { calls, fetchMock };
}

function renderSection(over: Partial<Parameters<typeof PieceUnitsSection>[0]> = {}) {
  const props = {
    obraId: 7,
    markId: 1,
    versionId: 5,
    canEdit: true,
    focus: null,
    onPickPiece: vi.fn(),
    onBatchApplied: vi.fn(),
    ...over,
  };
  renderWithProviders(<PieceUnitsSection {...props} />);
  return props;
}

const table = () => screen.findByRole('table', { name: 'Peças da marca' });
const cellOf = (n: number) => screen.getByRole('button', { name: new RegExp(`^Data de fabricação de PP001-${String(n)}:`) });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Parâmetros por peça (P4)', () => {
  it('lista as 6 peças da marca com nº, nível, identificador curto e a coluna do parâmetro', async () => {
    fakeBackend();
    renderSection();
    const rows = within(await table()).getAllByRole('row');
    expect(rows).toHaveLength(7); // cabeçalho + 6
    expect(rows[3]).toHaveTextContent('PP001-3');
    expect(rows[3]).toHaveTextContent('TÉRREO');
    expect(rows[3]).toHaveTextContent('…bbb-1003');
    expect(within(rows[0] as HTMLElement).getByRole('columnheader', { name: /Data de fabricação/ })).toBeInTheDocument();
  });

  it('preencher a 3ª unidade de uma marca de 6 só muda essa peça', async () => {
    const { calls } = fakeBackend();
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    const input = screen.getByLabelText('Data de fabricação de PP001-3');
    fireEvent.change(input, { target: { value: '2026-11-16' } }); // calendário: só guarda no campo
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0);
    await userEvent.keyboard('{Enter}'); // confirma

    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 16/11/2026' });
    const puts = calls.filter((c) => c.method === 'PUT');
    expect(puts).toHaveLength(1);
    expect(puts[0]?.path).toBe('/api/obras/7/units/103/values?version_id=5');
    expect(puts[0]?.body).toEqual({ changes: [{ def_id: FAB, value: '2026-11-16', row_version: null }] });
    for (const n of [1, 2, 4, 5, 6]) expect(cellOf(n)).toHaveAccessibleName(`Data de fabricação de PP001-${String(n)}: vazio`);
  });

  it('Esc cancela a edição da célula sem gravar', async () => {
    const { calls } = fakeBackend();
    renderSection();
    await table();
    await userEvent.click(cellOf(2));
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByLabelText('Data de fabricação de PP001-2')).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0);
  });

  it('preencher em lote 4 unidades: marca as linhas, "Preencher selecionadas" e confirma', async () => {
    const { calls } = fakeBackend();
    const props = renderSection();
    await table();
    expect(screen.getByRole('button', { name: 'Preencher selecionadas' })).toBeDisabled();
    for (const n of [1, 2, 4, 6]) await userEvent.click(screen.getByRole('checkbox', { name: `Marcar PP001-${String(n)}` }));
    await userEvent.click(screen.getByRole('button', { name: 'Preencher selecionadas (4)' }));

    const dialog = await screen.findByRole('dialog', { name: 'Preencher 4 peças' });
    expect(dialog).toHaveTextContent('PP001-1, PP001-2, PP001-4, PP001-6');
    fireEvent.change(await within(dialog).findByLabelText(/Data de fabricação/), { target: { value: '2026-11-10' } });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Aplicar' }));
    expect(await within(dialog).findByText(/serão alteradas/)).toHaveTextContent('4 peças serão alteradas.');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirmar' }));

    await vi.waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); });
    expect(calls.find((c) => c.path.endsWith('batch-apply'))?.body).toEqual({
      unit_ids: [101, 102, 104, 106],
      changes: { [FAB]: '2026-11-10' },
      mode: 'overwrite',
    });
    expect(props.onBatchApplied).toHaveBeenCalledWith({ batch_id: 'b-1', units_changed: 4, fields_changed: 4 });
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-6: 10/11/2026' });
    expect(cellOf(3)).toHaveAccessibleName('Data de fabricação de PP001-3: vazio');
    expect(cellOf(5)).toHaveAccessibleName('Data de fabricação de PP001-5: vazio');
    expect(screen.getByRole('checkbox', { name: 'Marcar PP001-1' })).not.toBeChecked(); // marcação limpa
  });

  it('clicar numa linha pede o destaque da peça; a peça em foco destaca a linha', async () => {
    fakeBackend();
    const props = renderSection({ focus: 14 }); // PP001-4 clicada no 3D
    const rows = within(await table()).getAllByRole('row');
    expect(rows[4]).toHaveAttribute('aria-selected', 'true');
    expect(rows[2]).toHaveAttribute('aria-selected', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'Mostrar PP001-2 no modelo' }));
    expect(props.onPickPiece).toHaveBeenCalledWith(12);
  });

  it('somente leitura: sem caixas de marcar, sem edição', async () => {
    fakeBackend([unit(1, '2026-11-01'), unit(2)]);
    renderSection({ canEdit: false });
    await table();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Preencher/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Data de fabricação de/ })).not.toBeInTheDocument();
    expect(await table()).toHaveTextContent('01/11/2026');
  });

  it('sem parâmetros por peça para a categoria, a seção não aparece', async () => {
    const fetchMock = installFakeApi({ 'GET /api/obras/7/marks/1/units': { ...markUnits([unit(1)]), params: [] } });
    renderSection();
    await vi.waitFor(() => { expect(fetchMock).toHaveBeenCalled(); });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('heading', { name: 'Parâmetros por peça' })).not.toBeInTheDocument();
  });
});

describe('Editor de data por peça (docs/bugs/data-por-peca.md)', () => {
  const PUT = (calls: FakeRequest[]) => calls.filter((c) => c.method === 'PUT');
  const inputOf = (n: number) => screen.getByLabelText(`Data de fabricação de PP001-${String(n)}`);

  it('digitar não grava a cada tecla: os valores intermediários (0002, 0020, 0202) só ficam no campo', async () => {
    const { calls } = fakeBackend();
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    for (const v of ['0002-05-05', '0020-05-05', '0202-05-05', '2026-05-05']) {
      fireEvent.change(inputOf(3), { target: { value: v } });
    }
    expect(inputOf(3)).toHaveValue('2026-05-05'); // o editor continua aberto
    expect(PUT(calls)).toHaveLength(0);
    await userEvent.keyboard('{Enter}');
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 05/05/2026' });
    expect(PUT(calls)).toHaveLength(1);
    expect(PUT(calls)[0]?.body).toEqual({ changes: [{ def_id: FAB, value: '2026-05-05', row_version: null }] });
  });

  it('sair do campo confirma', async () => {
    const { calls } = fakeBackend();
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    fireEvent.change(inputOf(3), { target: { value: '2026-11-16' } });
    fireEvent.blur(inputOf(3));
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 16/11/2026' });
    expect(PUT(calls)).toHaveLength(1);
  });

  it('Esc depois de digitar cancela sem gravar e mantém o valor antigo', async () => {
    const { calls } = fakeBackend([1, 2, 3].map((n) => unit(n, n === 3 ? '2026-05-05' : null)));
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    fireEvent.change(inputOf(3), { target: { value: '2026-06-06' } });
    await userEvent.keyboard('{Escape}');
    expect(cellOf(3)).toHaveAccessibleName('Data de fabricação de PP001-3: 05/05/2026');
    expect(PUT(calls)).toHaveLength(0);
  });

  it('ano fora de 1900–2100: avisa abaixo do campo, não grava e o editor continua aberto', async () => {
    const { calls } = fakeBackend();
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    fireEvent.change(inputOf(3), { target: { value: '0002-05-05' } });
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('Data inválida: use dd/mm/aaaa');
    expect(inputOf(3)).toHaveAttribute('aria-invalid', 'true');
    fireEvent.blur(inputOf(3));
    expect(PUT(calls)).toHaveLength(0);
    // corrigir no mesmo campo grava
    fireEvent.change(inputOf(3), { target: { value: '2026-05-05' } });
    expect(screen.queryByText('Data inválida: use dd/mm/aaaa')).not.toBeInTheDocument();
    await userEvent.keyboard('{Enter}');
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 05/05/2026' });
    expect(PUT(calls)).toHaveLength(1);
  });

  it('depois de salvar, reabre e corrige com o row_version que o servidor devolveu', async () => {
    const { calls } = fakeBackend();
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    fireEvent.change(inputOf(3), { target: { value: '2026-05-05' } });
    await userEvent.keyboard('{Enter}');
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 05/05/2026' });

    await userEvent.click(cellOf(3));
    expect(inputOf(3)).toHaveValue('2026-05-05');
    fireEvent.change(inputOf(3), { target: { value: '2026-06-06' } });
    await userEvent.keyboard('{Enter}');
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 06/06/2026' });
    expect(PUT(calls).map((c) => (c.body as { changes: UnitChange[] }).changes[0]?.row_version)).toEqual([null, 1]);
  });

  it('409: mostra o aviso de conflito e a célula reabre', async () => {
    let gets = 0;
    installFakeApi({
      'GET /api/obras/7/marks/1/units': () => {
        gets += 1;
        return markUnits([1, 2, 3].map((n) => unit(n, gets > 1 && n === 3 ? '2026-01-01' : null)));
      },
      'PUT /api/obras/7/units/103/values': () => Response.json({ detail: 'alterado', code: 'stale' }, { status: 409 }),
    });
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    fireEvent.change(inputOf(3), { target: { value: '2026-05-05' } });
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('Outro usuário alterou PP001-3');
    // recarregou com o valor do colega, e a célula abre de novo
    await screen.findByRole('button', { name: 'Data de fabricação de PP001-3: 01/01/2026' });
    await userEvent.click(cellOf(3));
    expect(inputOf(3)).toHaveValue('2026-01-01');
  });

  it('422 do servidor: mostra a mensagem e a célula reabre', async () => {
    installFakeApi({
      'GET /api/obras/7/marks/1/units': markUnits([unit(3)]),
      'PUT /api/obras/7/units/103/values': () => Response.json({ detail: 'Data inválida: use dd/mm/aaaa' }, { status: 422 }),
    });
    renderSection();
    await table();
    await userEvent.click(cellOf(3));
    fireEvent.change(inputOf(3), { target: { value: '2026-05-05' } });
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('Data inválida: use dd/mm/aaaa');
    await userEvent.click(cellOf(3));
    expect(inputOf(3)).toBeInTheDocument();
  });
});

describe('unitTable', () => {
  it('identificador curto, linhas com peça, sem peça e linha da peça clicada', () => {
    const orphan: PieceUnit = { ...unit(7), status: 'orphan', element: null, external_id: 'zz' };
    const nwd: PieceUnit = { ...unit(8), external_id: null, element: { ...(unit(8).element ?? ({} as never)), external_id: null } };
    expect(shortId(unit(1))).toBe('…bbb-1001');
    expect(shortId(orphan)).toBe('zz');
    expect(shortId(nwd)).toBe('Pilar [18]');
    const units = [unit(2), orphan, unit(1)];
    expect(rowsOf(units).map((u) => u.number)).toEqual([1, 2]);
    expect(withoutPiece(units)).toBe(1);
    expect(rowOf(units, 12)?.label).toBe('PP001-2');
    expect(rowOf(units, 99)).toBeNull();
    expect(rowOf(units, null)).toBeNull();
  });
});

describe('Cadastro: Por marca / Por peça', () => {
  const base: ParamDef = {
    id: 9, name: 'Data de fabricação', type: 'date', unit: null, options: null, required: false, categories: null,
    scope: 'obra', level: 'piece', obra_id: 7, obra_code: 'OB-001', active: true, values_count: 0, options_in_use: [],
    created_at: '2026-11-16T12:00:00Z', updated_at: '2026-11-16T12:00:00Z', created_by_name: null,
  };

  it('novo parâmetro "Por peça" envia level=piece (padrão: por marca)', async () => {
    const calls: FakeRequest[] = [];
    installFakeApi({ 'POST /api/param-defs': (req) => { calls.push(req); return base; } });
    renderWithProviders(<ParamDefDialog obraId={7} obraCode="OB-001" categories={[]} onClose={vi.fn()} />);
    expect(screen.getByRole('radio', { name: 'Por marca' })).toBeChecked();
    expect(screen.getByText(/Cada peça da marca tem o seu valor/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Nome/), 'Data de fabricação');
    await userEvent.click(screen.getByRole('radio', { name: 'Por peça' }));
    await userEvent.click(screen.getByRole('button', { name: 'Criar parâmetro' }));
    await vi.waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toMatchObject({ name: 'Data de fabricação', level: 'piece' });
  });

  it('com valores, a escolha fica travada', () => {
    installFakeApi({});
    renderWithProviders(
      <ParamDefDialog obraId={7} obraCode="OB-001" categories={[]} param={{ ...base, values_count: 3 }} onClose={vi.fn()} />,
    );
    expect(screen.getByText('Preenchido em 3 peça(s).')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Por peça' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Por marca' })).toBeDisabled();
  });
});
