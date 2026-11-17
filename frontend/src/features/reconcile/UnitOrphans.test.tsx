import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ObraEvent } from '../../api/events';
import type { VersionDiff } from '../../api/reconcile';
import type { MarkUnits, PieceUnit, UnitOrphan } from '../../api/units';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { describeEvent } from '../live/eventText';
import { UnitOrphansDialog } from './UnitOrphansDialog';
import { VersionBanner } from './VersionBanner';

const ORPHAN: UnitOrphan = {
  id: 103,
  number: 3,
  label: 'P-06-3',
  status: 'orphan',
  mark_id: 1,
  code: 'P-06',
  category: 'Structural Columns',
  external_id: 'pec-0012',
  since_version_id: 2,
  since_version_number: 2,
  mark_in_model: true,
  updated_at: '2026-11-16T12:00:00Z',
  values: [{ def_id: 9, name: 'Data de fabricação', type: 'date', value: '2026-11-03' }],
};

const unit = (n: number, value: string | null): PieceUnit => ({
  id: 100 + n,
  number: n,
  label: `P-06-${String(n)}`,
  status: 'linked',
  external_id: `pec-00${String(9 + n)}`,
  since_version_id: null,
  element: {
    element_id: 500 + n,
    dbid: 10 + n,
    external_id: `pec-00${String(9 + n)}`,
    level: 'TÉRREO',
    name: null,
    method: 'key',
  },
  values: [{ def_id: 9, value, row_version: value ? 1 : null, updated_at: null, updated_by_name: null }],
});

const UNITS: MarkUnits = {
  mark: { id: 1, code: 'P-06', category: 'Structural Columns' },
  version_id: 2,
  params: [{ def_id: 9, name: 'Data de fabricação', type: 'date', unit: null, required: false, options: null }],
  units: [unit(1, null), unit(5, '2026-11-05'), unit(6, null)],
};

function renderDialog(over: { canEdit?: boolean; orphans?: UnitOrphan[] } = {}) {
  const calls: FakeRequest[] = [];
  let open = over.orphans ?? [ORPHAN];
  installFakeApi({
    'GET /api/obras/7/unit-orphans': () => open,
    'GET /api/obras/7/marks/1/units': UNITS,
    'POST /api/obras/7/units/103/relink': (req) => {
      calls.push(req);
      const body = req.body as { target_unit_id: number; confirm: boolean };
      if (body.target_unit_id === 105 && !body.confirm) {
        return Response.json({ detail: 'P-06-5 já tem valores.', code: 'unit_relink_conflict' }, { status: 409 });
      }
      open = [];
      const target = UNITS.units.find((u) => u.id === body.target_unit_id);
      return {
        unit_id: 103,
        label: 'P-06-3',
        element_id: 500,
        dbid: target?.element?.dbid ?? 0,
        displaced_unit_id: body.target_unit_id,
        displaced_label: target?.label ?? '',
        displaced_status: body.confirm ? 'orphan' : 'unlinked',
      };
    },
    'POST /api/obras/7/units/103/archive': (req) => {
      calls.push(req);
      open = [];
      return { id: 103, label: 'P-06-3', status: 'archived' };
    },
  });
  const props = { obraId: 7, versionId: 2, canEdit: over.canEdit ?? true, onClose: vi.fn(), onRelinked: vi.fn() };
  renderWithProviders(<UnitOrphansDialog {...props} />);
  return { calls, props };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Peças órfãs (P5)', () => {
  it('lista a unidade órfã com os valores preservados', async () => {
    renderDialog();
    const list = await screen.findByRole('list', { name: 'Peças órfãs abertas' });
    expect(list).toHaveTextContent('P-06-3');
    expect(list).toHaveTextContent('Sem peça desde a versão 2');
    expect(list).toHaveTextContent('Data de fabricação: 03/11/2026');
  });

  it('religar a uma peça vazia da mesma marca', async () => {
    const { calls, props } = renderDialog();
    await userEvent.click(await screen.findByRole('button', { name: 'Religar P-06-3' }));
    const chooser = screen.getByRole('group', { name: 'Religar P-06-3' });
    const targets = within(await within(chooser).findByRole('list', { name: 'Peças de P-06' })).getAllByRole('button');
    expect(targets.map((b) => b.textContent)).toEqual([
      expect.stringContaining('P-06-1'),
      expect.stringContaining('P-06-5'),
      expect.stringContaining('P-06-6'),
    ]);
    expect(targets[1]).toHaveTextContent('com valores');
    await userEvent.click(targets[2] as HTMLElement);
    await vi.waitFor(() => { expect(props.onRelinked).toHaveBeenCalled(); });
    expect(calls[0]?.body).toEqual({ target_unit_id: 106, confirm: false });
    expect(props.onRelinked).toHaveBeenCalledWith(expect.objectContaining({ label: 'P-06-3', displaced_status: 'unlinked' }));
  });

  it('peça com valores pede confirmação antes de religar', async () => {
    const { calls, props } = renderDialog();
    await userEvent.click(await screen.findByRole('button', { name: 'Religar P-06-3' }));
    await userEvent.click(await screen.findByRole('button', { name: /P-06-5/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('P-06-5 já tem valores');
    expect(props.onRelinked).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Religar mesmo assim' }));
    await vi.waitFor(() => { expect(props.onRelinked).toHaveBeenCalled(); });
    expect(calls.map((c) => c.body)).toEqual([
      { target_unit_id: 105, confirm: false },
      { target_unit_id: 105, confirm: true },
    ]);
  });

  it('arquivar pede confirmação e esvazia a fila', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { calls } = renderDialog();
    await userEvent.click(await screen.findByRole('button', { name: 'Arquivar P-06-3' }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Os valores continuam guardados'));
    expect(await screen.findByText('Nenhuma peça órfã pendente.')).toBeInTheDocument();
    expect(calls[0]?.path).toBe('/api/obras/7/units/103/archive');
  });

  it('somente leitura e marca fora do modelo', async () => {
    renderDialog({ canEdit: false, orphans: [{ ...ORPHAN, mark_in_model: false }] });
    expect(await screen.findByText('A marca P-06 não está no modelo atual: só é possível arquivar.')).toBeInTheDocument();
    expect(screen.getByText(/Somente a fábrica religa e arquiva/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Religar/ })).not.toBeInTheDocument();
  });

  it('o banner da versão informa as peças que perderam a peça e as novas', async () => {
    const diff: VersionDiff = {
      version_id: 2,
      version_number: 2,
      prev_version_id: 1,
      prev_version_number: 1,
      totals: { unchanged: 2, count_changed: 0, changed: 0, new: 0, removed: 0 },
      review: 0,
      orphans: 0,
      returned: 0,
      review_open: 0,
      orphans_open: 0,
      review_properties: [],
      marks: [],
      units: {
        lost: 1,
        new: 2,
        returned: 0,
        by_order: 0,
        lost_units: [{ unit_id: 103, label: 'P-06-3' }],
        new_units: [
          { unit_id: 107, label: 'P-06-7' },
          { unit_id: 108, label: 'V-02-3' },
        ],
        orphans_open: 1,
      },
    };
    installFakeApi({ 'GET /api/versions/2/diff': diff });
    const onShowUnitOrphans = vi.fn();
    renderWithProviders(
      <VersionBanner
        versionId={2}
        onShowNew={vi.fn()}
        onShowReview={vi.fn()}
        onShowOrphans={vi.fn()}
        onShowUnitOrphans={onShowUnitOrphans}
      />,
    );
    const peças = await screen.findByRole('group', { name: 'Peças' });
    expect(peças).toHaveTextContent('1 perdeu a peça nesta versão, com valores: P-06-3');
    expect(peças).toHaveTextContent('2 peças novas: P-06-7, V-02-3');
    await userEvent.click(within(peças).getByRole('button', { name: '1 peça órfã' }));
    expect(onShowUnitOrphans).toHaveBeenCalled();
  });

  it('aviso em tempo real de outra pessoa', () => {
    const ev = (status: string): ObraEvent => ({
      id: '1-0',
      type: 'unit_orphan_changed',
      data: {
        type: 'unit_orphan_changed',
        obra_id: 7,
        at: '',
        actor: { id: 1, name: 'Ana' },
        unit: 'P-06-3',
        target_unit: 'P-06-6',
        status,
      },
    });
    expect(describeEvent(ev('relinked'))).toBe('Ana religou a peça órfã P-06-3 (no lugar de P-06-6)');
    expect(describeEvent(ev('archived'))).toBe('Ana arquivou a peça órfã P-06-3');
  });
});
