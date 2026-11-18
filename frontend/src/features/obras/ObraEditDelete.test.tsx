import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { setDevUser } from '../../api/client';
import type { DeletePreview, Obra } from '../../api/obras';
import type { User } from '../../api/users';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderApp } from '../../test/render';

const USERS: Record<string, User> = {
  '1': { id: 1, name: 'Paula Projetos', email: 'p@dev.local', role: 'projetos' },
  '2': { id: 2, name: 'Fábio Fábrica', email: 'f@dev.local', role: 'fabrica' },
  '3': { id: 3, name: 'Ana Admin', email: 'a@dev.local', role: 'admin' },
};

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
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
};

const EMPTY: DeletePreview = { versions: 1, marks: 12, units: 30, filled_values: 0, admin_only: false };
const FILLED: DeletePreview = { ...EMPTY, filled_values: 5, admin_only: true };

const me = (req: FakeRequest) => USERS[req.headers.get('X-Dev-User') ?? ''] ?? Response.json({}, { status: 401 });

function api(extra: Record<string, unknown> = {}) {
  let obras: Obra[] = [OBRA];
  const calls: FakeRequest[] = [];
  installFakeApi({
    'GET /api/me': me,
    'GET /api/dev/users': Object.values(USERS),
    'GET /api/obras': () => obras,
    'PATCH /api/obras/7': (req: FakeRequest) => {
      calls.push(req);
      const updated = { ...OBRA, ...(req.body as Partial<Obra>) };
      obras = [updated];
      return updated;
    },
    'DELETE /api/obras/7': (req: FakeRequest) => {
      calls.push(req);
      obras = [];
      return EMPTY;
    },
    'GET /api/obras/7/delete-preview': EMPTY,
    ...extra,
  });
  return calls;
}

describe('Editar e excluir obra', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('fábrica não vê Editar nem Excluir', async () => {
    api();
    setDevUser('2');
    renderApp('/obras');
    expect(await screen.findByRole('link', { name: 'OB-001' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar obra OB-001' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Excluir obra OB-001' })).not.toBeInTheDocument();
  });

  it('edita código e nome; Enter salva', async () => {
    const calls = api();
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras');
    await user.click(await screen.findByRole('button', { name: 'Editar obra OB-001' }));
    const dialog = screen.getByRole('dialog', { name: 'Editar obra OB-001' });
    const code = within(dialog).getByLabelText('Código');
    await user.clear(code);
    await user.type(code, 'OB-002');
    const name = within(dialog).getByLabelText('Nome');
    await user.clear(name);
    await user.type(name, 'Galpão novo{Enter}');

    expect(await screen.findByRole('link', { name: 'OB-002' })).toBeInTheDocument();
    expect(screen.getByText('Galpão novo')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(calls[0]?.body).toEqual({ code: 'OB-002', name: 'Galpão novo' });
  });

  it('Esc cancela a edição sem gravar', async () => {
    const calls = api();
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras');
    await user.click(await screen.findByRole('button', { name: 'Editar obra OB-001' }));
    await user.type(screen.getByLabelText('Código'), 'X');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(screen.getByRole('link', { name: 'OB-001' })).toBeInTheDocument();
  });

  it('mostra o erro de código repetido', async () => {
    api({
      'PATCH /api/obras/7': Response.json(
        { detail: "Já existe uma obra com o código 'OB-009'.", code: 'conflict' },
        { status: 409 },
      ),
    });
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras');
    await user.click(await screen.findByRole('button', { name: 'Editar obra OB-001' }));
    const code = screen.getByLabelText('Código');
    await user.clear(code);
    await user.type(code, 'OB-009');
    await user.click(screen.getByRole('button', { name: 'Salvar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("Já existe uma obra com o código 'OB-009'.");
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('exclui depois de digitar o código da obra', async () => {
    const calls = api();
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras');
    await user.click(await screen.findByRole('button', { name: 'Excluir obra OB-001' }));
    const dialog = screen.getByRole('dialog', { name: 'Excluir obra OB-001' });
    expect(await within(dialog).findByText(/1 versão, 12 marcas, 30 peças numeradas/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole('button', { name: 'Excluir obra' });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByLabelText(/Digite o código da obra/), 'OB-00');
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Digite o código da obra/), '1');
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(await screen.findByText('Nenhuma obra cadastrada.', { exact: false })).toBeInTheDocument();
    expect(calls.map((c) => c.method)).toEqual(['DELETE']);
  });

  it('obra com valores: projetos é bloqueado', async () => {
    const calls = api({ 'GET /api/obras/7/delete-preview': FILLED });
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras');
    await user.click(await screen.findByRole('button', { name: 'Excluir obra OB-001' }));
    expect(await screen.findByRole('note')).toHaveTextContent('Só um administrador pode excluí-la.');
    expect(screen.queryByRole('button', { name: 'Excluir obra' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Digite o código da obra/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Fechar' }));
    expect(calls).toHaveLength(0);
  });

  it('obra com valores: admin exclui com aviso', async () => {
    const calls = api({ 'GET /api/obras/7/delete-preview': FILLED });
    setDevUser('3');
    const user = userEvent.setup();
    renderApp('/obras');
    await user.click(await screen.findByRole('button', { name: 'Excluir obra OB-001' }));
    expect(await screen.findByRole('note')).toHaveTextContent('serão apagados');
    expect(screen.getByText(/5 valores preenchidos/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Digite o código da obra/), 'OB-001{Enter}');
    await waitFor(() => { expect(calls.map((c) => c.method)).toEqual(['DELETE']); });
  });
});
