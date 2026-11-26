import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ImportPreview } from '../../api/excelImport';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { ImportExcelDialog } from './ImportExcel';

/** Planilha do Plannix (2026-11-24): o servidor reconhece; a tela mostra o que é dela. */

const PREVIEW: ImportPreview = {
  obra_code: '9480',
  file_version: null,
  marks_rows: 0,
  pieces_rows: 8,
  fills: 2,
  changes: 2,
  unchanged: 4,
  errors: [],
  warnings: [{ sheet: 'Plannix', row: null, column: 'Peça', message: 'Conferir VA3014: 2 no Plannix, 1 no modelo.' }],
  ignored_columns: [],
  params: [{ def_id: 0, name: 'Concretagem', level: 'piece', fills: 2, changes: 2 }],
  fill_items: [
    { sheet: 'Plannix', row: 2, target: 'PP301-1', category: 'Pilar', param: 'Concretagem', old: null, new: '2026-11-11' },
    { sheet: 'Plannix', row: 3, target: 'PP301-2', category: 'Pilar', param: 'Concretagem', old: null, new: '2026-11-05' },
  ],
  change_items: [
    { sheet: 'Plannix', row: 4, target: 'PP301-3', category: 'Pilar', param: 'Concretagem', old: '2026-11-01', new: '2026-11-02' },
    { sheet: 'Plannix', row: 5, target: 'LA3008-1', category: 'Laje', param: 'Concretagem', old: '2026-11-01', new: null },
  ],
  fingerprint: 'px1',
  clears: 1,
  plannix: {
    rows: 8,
    rejected: 1,
    linked: 6,
    new_links: 6,
    leftovers: 1,
    new_params: ['Corte e dobra', 'Concretagem'],
    check_marks: [{ code: 'VA3014', plannix: 2, model: 1 }],
    outside_model: [{ code: 'VA3099', rows: 1 }],
  },
};

const file = () =>
  new File([new Uint8Array([0x50, 0x4b, 3, 4])], 'tabela.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });

describe('Importar a planilha do Plannix', () => {
  it('mostra ligadas, recusadas, conferir e fora do modelo; aplica tudo sem "também alterar"', async () => {
    const calls: FakeRequest[] = [];
    installFakeApi({
      'POST /api/obras/7/import-xlsx/preview': () => PREVIEW,
      'POST /api/obras/7/import-xlsx/apply': (req) => {
        calls.push(req);
        return { batch_id: 'b-px', marks_changed: 0, units_changed: 4, fields_changed: 4, skipped_changes: 0, errors: 0 };
      },
    });
    const onApplied = vi.fn();
    renderWithProviders(<ImportExcelDialog obraId={7} onApplied={onApplied} onClose={vi.fn()} />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Arquivo (.xlsx)'), file());

    expect(await screen.findByTestId('plannix-summary')).toHaveTextContent(
      'Planilha do Plannix · 8 peças lidas · 6 ligadas a peças do modelo (6 novas) · 1 recusada ignorada · 1 sem peça no modelo',
    );
    expect(screen.getByTestId('import-summary')).toHaveTextContent('2 valores diferentes do app (1 a apagar)');
    expect(screen.getByText(/Parâmetros a criar na biblioteca/)).toHaveTextContent('Corte e dobra, Concretagem');
    expect(screen.getByText('1 marca com quantidade diferente (conferir)')).toBeInTheDocument();
    expect(screen.getByText(/2 no Plannix, 1 no modelo$/)).toBeInTheDocument();
    expect(screen.getByText('VA3099 (1)')).toBeInTheDocument();
    // o Plannix sempre sobrescreve: sem a caixa "também alterar"
    expect(screen.queryByRole('checkbox', { name: /Também alterar/ })).not.toBeInTheDocument();

    await user.click(screen.getByText('Ver os 2 valores diferentes do app'));
    const table = screen.getByRole('table', { name: 'Valores diferentes do app' });
    expect(within(table).getByRole('columnheader', { name: 'No Plannix' })).toBeInTheDocument();
    expect(within(table).getByText('apagar')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Aplicar 4 valores' }));
    await waitFor(() => { expect(onApplied).toHaveBeenCalled(); });
    expect(onApplied).toHaveBeenCalledWith('b-px', 'Importação do Plannix: 4 valores gravados (4 peças).');
  });

  it('só ligações novas: o botão guarda as ligações', async () => {
    installFakeApi({
      'POST /api/obras/7/import-xlsx/preview': () => ({
        ...PREVIEW,
        fills: 0,
        changes: 0,
        clears: 0,
        fill_items: [],
        change_items: [],
        params: [],
        plannix: { ...PREVIEW.plannix, new_links: 2 },
      }),
    });
    renderWithProviders(<ImportExcelDialog obraId={7} onApplied={vi.fn()} onClose={vi.fn()} />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Arquivo (.xlsx)'), file());
    expect(await screen.findByRole('button', { name: 'Guardar 2 ligações' })).toBeEnabled();
  });
});
