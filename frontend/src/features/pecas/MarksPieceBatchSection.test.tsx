import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { MarksPieceBatchSection } from './MarksPieceBatchSection';

/** Várias marcas selecionadas: parâmetro por peça em todas as peças delas (2026-11-18). */

const UNITS = [
  { unit_id: 11, label: 'PP001-1', mark_id: 1 },
  { unit_id: 12, label: 'PP001-2', mark_id: 1 },
  { unit_id: 21, label: 'PP002-1', mark_id: 2 },
  { unit_id: 22, label: 'PP002-2', mark_id: 2 },
];
const FIELD = {
  def_id: 7, name: 'Concretagem', type: 'text', unit: null, required: false, options: null,
  applies_to: 4, filled: 0, mixed: false, common_value: null,
};
const preview = (fields: unknown[]) => ({
  units: 4, marks: 2, categories: ['Pilares estruturais'], fields,
  units_to_change: 0, units_to_change_overwrite: 0, units_to_change_only_empty: 0, units_with_other_value: 0,
});

function setup(fields: unknown[] = [FIELD]) {
  const asked: FakeRequest[] = [];
  installFakeApi({
    'POST /api/obras/5/units/of-marks': (req) => {
      asked.push(req);
      return UNITS;
    },
    'POST /api/obras/5/units/batch-preview': preview(fields),
  });
  return asked;
}

describe('Parâmetros por peça com várias marcas', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('pede as peças das marcas da versão e abre o lote com todas, com resumo', async () => {
    const asked = setup();
    renderWithProviders(
      <MarksPieceBatchSection obraId={5} versionId={3} markIds={[2, 1]} unmarked={0} canEdit onApplied={vi.fn()} />,
    );
    expect(await screen.findByText('4 peças de 2 marcas')).toBeInTheDocument();
    expect(asked[0]?.body).toEqual({ version_id: 3, mark_ids: [1, 2] });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Preencher todas as peças' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Preencher 4 peças');
    expect(dialog).toHaveTextContent('4 peças de 2 marcas (PP001-1, PP001-2, PP002-1… e mais 1)');
    expect(await screen.findByLabelText(/Concretagem/)).toBeInTheDocument();
  });

  it('sem parâmetro por peça: avisa e não oferece o lote', async () => {
    setup([]);
    renderWithProviders(
      <MarksPieceBatchSection obraId={5} versionId={3} markIds={[1, 2]} unmarked={0} canEdit onApplied={vi.fn()} />,
    );
    expect(await screen.findByText('Nenhum parâmetro por peça para estas categorias.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Preencher todas as peças' })).not.toBeInTheDocument();
  });

  it('papel sem edição não vê o botão; peças sem marca são avisadas', async () => {
    setup();
    renderWithProviders(
      <MarksPieceBatchSection obraId={5} versionId={3} markIds={[1, 2]} unmarked={3} canEdit={false} onApplied={vi.fn()} />,
    );
    expect(await screen.findByText('4 peças de 2 marcas')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Preencher todas as peças' })).not.toBeInTheDocument();
    expect(screen.getByText(/3 peças sem marca ignoradas/)).toBeInTheDocument();
  });
});
