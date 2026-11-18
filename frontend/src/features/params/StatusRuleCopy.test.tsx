import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ParamDef } from '../../api/paramDefs';
import { installFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { CatalogDialog } from './CatalogDialog';
import { ParamDefDialog } from './ParamDefDialog';

/**
 * Regra do status (CLAUDE.md) explicada na tela (2026-11-18): contam os obrigatórios;
 * sem nenhum obrigatório, contam todos. Caso da obra 9121: concretagem e forma opcionais.
 */

const def = (id: number, name: string, required: boolean): ParamDef => ({
  id,
  name,
  type: 'date',
  unit: null,
  options: null,
  required,
  categories: null,
  scope: 'obra',
  level: 'piece',
  obra_id: 17,
  obra_code: '9121',
  active: true,
  values_count: 0,
  in_obra: true,
  options_in_use: [],
  created_at: '2026-11-18T12:00:00Z',
  updated_at: '2026-11-18T12:00:00Z',
  created_by_name: 'Fábio Fábrica',
});

const catalog = (defs: ParamDef[]) => {
  installFakeApi({ 'GET /api/param-defs': defs });
  renderWithProviders(
    <CatalogDialog obraId={17} canEdit onClose={vi.fn()} onNew={vi.fn()} onEdit={vi.fn()} />,
  );
};

describe('regra do status explicada', () => {
  it('catálogo sem obrigatório avisa que todos contam', async () => {
    catalog([def(16, 'concretagem', false), def(17, 'forma', false)]);
    expect(await screen.findByRole('note')).toHaveTextContent(
      'Nenhum parâmetro obrigatório: todos contam para o status',
    );
  });

  it('catálogo com obrigatório diz que só eles contam', async () => {
    catalog([def(16, 'concretagem', true), def(17, 'forma', false)]);
    expect(await screen.findByRole('note')).toHaveTextContent('contam só os obrigatórios (*)');
  });

  it('a caixa "Obrigatório" explica a regra', () => {
    renderWithProviders(
      <ParamDefDialog obraId={17} obraCode="9121" categories={[]} onClose={vi.fn()} />,
    );
    const box = screen.getByRole('checkbox', { name: /Obrigatório: define o status da peça/ });
    expect(box).toHaveAccessibleDescription(/Se nenhum parâmetro da obra for obrigatório, todos contam/);
  });
});
