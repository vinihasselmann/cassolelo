import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ImportPreview } from '../../api/excelImport';
import { installFakeApi, jsonError, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { ImportExcelDialog } from './ImportExcel';

const PREVIEW: ImportPreview = {
  obra_code: 'OB-001',
  file_version: 'V2',
  marks_rows: 3,
  pieces_rows: 0,
  fills: 2,
  changes: 1,
  unchanged: 5,
  errors: [{ sheet: 'Marcas', row: 7, column: 'Concretagem', message: 'Concretagem: Data inválida: use dd/mm/aaaa' }],
  warnings: [],
  ignored_columns: [],
  params: [{ def_id: 1, name: 'Concretagem', level: 'mark', fills: 2, changes: 1 }],
  fill_items: [
    { sheet: 'Marcas', row: 4, target: 'P01', category: 'Pilar', param: 'Concretagem', old: null, new: '2026-11-20' },
    { sheet: 'Marcas', row: 5, target: 'P02', category: 'Pilar', param: 'Concretagem', old: null, new: '2026-11-21' },
  ],
  change_items: [
    { sheet: 'Marcas', row: 2, target: 'V01', category: 'Viga', param: 'Concretagem', old: '2026-11-10', new: '2026-12-01' },
  ],
  fingerprint: 'abc123',
};

const file = () =>
  new File([new Uint8Array([0x50, 0x4b, 3, 4])], 'obra.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });

function setup(applyReply: (req: FakeRequest) => Response | object = () => ({
  batch_id: 'b-1', marks_changed: 2, units_changed: 0, fields_changed: 2, skipped_changes: 1, errors: 1,
})) {
  const calls: FakeRequest[] = [];
  const fetchMock = installFakeApi({
    'POST /api/obras/7/import-xlsx/preview': (req) => { calls.push(req); return PREVIEW; },
    'POST /api/obras/7/import-xlsx/apply': (req) => { calls.push(req); return applyReply(req); },
  });
  const onApplied = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(<ImportExcelDialog obraId={7} onApplied={onApplied} onClose={onClose} />);
  return { calls, fetchMock, onApplied, onClose };
}

describe('Importar Excel', () => {
  it('mostra a prévia: a preencher, diferentes, erros; aplica só os vazios por padrão', async () => {
    const { calls, fetchMock, onApplied, onClose } = setup();
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Arquivo (.xlsx)'), file());

    const summary = await screen.findByTestId('import-summary');
    expect(summary).toHaveTextContent('Obra OB-001 · arquivo da V2 · 2 campos a preencher · 1 valor diferente do app · 5 iguais · 1 erro');
    expect(screen.getByText(/1 linha recusada/)).toBeInTheDocument();
    expect(screen.getByText('Concretagem: Data inválida: use dd/mm/aaaa')).toBeInTheDocument();
    expect(screen.getByText('Marcas · linha 7 · Concretagem')).toBeInTheDocument();

    // o arquivo vai no corpo, como Excel
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.body).toBeInstanceOf(File);
    expect(new Headers(init?.headers).get('Content-Type')).toContain('spreadsheetml');

    // detalhe com datas em dd/mm/aaaa
    await user.click(screen.getByText('Ver os 2 campos a preencher'));
    const table = screen.getByRole('table', { name: 'Campos a preencher' });
    expect(within(table).getByText('20/11/2026')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Aplicar 2 valores' }));
    await waitFor(() => { expect(onApplied).toHaveBeenCalled(); });
    expect(calls[1]?.path).toBe('/api/obras/7/import-xlsx/apply?fingerprint=abc123&overwrite=false');
    expect(onApplied).toHaveBeenCalledWith('b-1', 'Importação: 2 valores gravados (2 marcas).');
    expect(onClose).toHaveBeenCalled();
  });

  it('"também alterar" inclui os valores diferentes', async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Arquivo (.xlsx)'), file());
    await user.click(await screen.findByRole('checkbox', { name: 'Também alterar o valor já preenchido no app' }));
    await user.click(screen.getByRole('button', { name: 'Aplicar 3 valores' }));
    await waitFor(() => { expect(calls).toHaveLength(2); });
    expect(calls[1]?.path).toContain('overwrite=true');
  });

  it('erro do arquivo aparece e nada é aplicável', async () => {
    installFakeApi({
      'POST /api/obras/7/import-xlsx/preview': () => jsonError(422, 'Este arquivo é da obra OB-002, não da OB-001.'),
    });
    renderWithProviders(<ImportExcelDialog obraId={7} onApplied={vi.fn()} onClose={vi.fn()} />);
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Arquivo (.xlsx)'), file());
    expect(await screen.findByRole('alert')).toHaveTextContent('é da obra OB-002');
    expect(screen.getByRole('button', { name: 'Aplicar 0 valores' })).toBeDisabled();
  });

  it('mudou desde a prévia (409): oferece conferir de novo', async () => {
    const { calls } = setup(() => jsonError(409, 'Os valores da obra mudaram desde a prévia (alguém gravou agora). Confira de novo.'));
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText('Arquivo (.xlsx)'), file());
    await user.click(await screen.findByRole('button', { name: 'Aplicar 2 valores' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('mudaram desde a prévia');
    await user.click(screen.getByRole('button', { name: 'Conferir de novo' }));
    await waitFor(() => { expect(calls.filter((c) => c.path.endsWith('/preview'))).toHaveLength(2); });
  });
});
