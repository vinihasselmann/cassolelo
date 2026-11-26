import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ParamDef } from '../../api/paramDefs';
import { installFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { CatalogDialog } from './CatalogDialog';
import { ParamDefDialog } from './ParamDefDialog';

/** Parâmetros do Plannix no catálogo e na edição (2026-11-24). */

const def = (id: number, name: string, source: 'manual' | 'plannix'): ParamDef => ({
  id,
  name,
  type: 'date',
  unit: null,
  options: null,
  required: true,
  categories: null,
  scope: 'global',
  level: 'piece',
  source,
  obra_id: null,
  obra_code: null,
  active: true,
  values_count: 12,
  in_obra: true,
  obras_count: 1,
  options_in_use: [],
  created_at: '2026-11-24T12:00:00Z',
  updated_at: '2026-11-24T12:00:00Z',
  created_by_name: 'Fábio Fábrica',
});

describe('parâmetros do Plannix', () => {
  it('o catálogo mostra a etiqueta Plannix só nos do Plannix', async () => {
    installFakeApi({ 'GET /api/param-defs': [def(1, 'Concretagem', 'plannix'), def(2, 'Ciclo de cura', 'manual')] });
    renderWithProviders(<CatalogDialog obraId={22} canEdit onClose={vi.fn()} onNew={vi.fn()} onEdit={vi.fn()} />);
    const list = await screen.findByRole('list', { name: 'Parâmetros desta obra' });
    const [plannix, manual] = within(list).getAllByRole('listitem');
    expect(plannix).toHaveTextContent('Concretagem *Plannix');
    expect(plannix).toHaveTextContent('preenchido pela importação do Plannix');
    expect(manual).not.toHaveTextContent('Plannix');
  });

  it('na edição, nome, tipo, preenchimento e escopo ficam travados; obrigatório não', () => {
    renderWithProviders(
      <ParamDefDialog obraId={22} obraCode="9480" categories={[]} param={{ ...def(1, 'Forma', 'plannix'), values_count: 0 }} onClose={vi.fn()} />,
    );
    expect(screen.getByRole('note')).toHaveTextContent('Parâmetro do Plannix');
    expect(screen.getByLabelText(/^Nome/)).toBeDisabled();
    expect(screen.getByLabelText('Tipo')).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Por peça' })).toBeDisabled();
    expect(screen.getByLabelText('Escopo')).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /Obrigatório/ })).toBeEnabled();
  });
});
