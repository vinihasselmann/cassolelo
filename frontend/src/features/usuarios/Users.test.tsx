import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import type { AdminUser } from '../../api/adminUsers';
import { setDevUser } from '../../api/client';
import type { Obra } from '../../api/obras';
import type { User } from '../../api/users';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderApp } from '../../test/render';

const USERS: Record<string, User> = {
  '2': { id: 2, name: 'Fábio Fábrica', email: 'f@cassol.ind.br', role: 'fabrica' },
  '3': { id: 3, name: 'Ana Admin', email: 'a@cassol.ind.br', role: 'admin' },
};

const obra = (id: number, code: string): Obra => ({
  id,
  code,
  name: `Obra ${code}`,
  acc_hub_id: 'b.h',
  acc_project_id: 'b.p',
  acc_folder_id: 'urn:f',
  acc_item_id: `urn:i${String(id)}`,
  acc_item_name: `${code}.rvt`,
  active: true,
  acc_file_state: 'ok',
  acc_file_state_at: null,
  unit_numbering: 'sequence',
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
});
const OBRAS = [obra(7, 'OB-001'), obra(8, 'OB-002')];

const admin = (over: Partial<AdminUser>): AdminUser => ({
  id: 0,
  name: '',
  email: '',
  role: 'leitura',
  active: true,
  all_obras: true,
  obra_ids: [],
  role_source: 'table',
  created_at: '2026-11-19T12:00:00Z',
  updated_at: '2026-11-19T12:00:00Z',
  ...over,
});

const LIST: AdminUser[] = [
  admin({ id: 3, name: 'Ana Admin', email: 'a@cassol.ind.br', role: 'admin', role_source: 'bootstrap' }),
  admin({ id: 2, name: 'Fábio Fábrica', email: 'f@cassol.ind.br', role: 'fabrica', all_obras: false, obra_ids: [8] }),
  admin({ id: 4, name: 'Lia Leitura', email: 'l@cassol.ind.br', active: false }),
];

const me = (req: FakeRequest) => USERS[req.headers.get('X-Dev-User') ?? ''] ?? Response.json({}, { status: 401 });

function api() {
  const calls: FakeRequest[] = [];
  let users = [...LIST];
  installFakeApi({
    'GET /api/me': me,
    'GET /api/dev/users': Object.values(USERS),
    'GET /api/obras': OBRAS,
    'GET /api/users': () => users,
    'POST /api/users': (req: FakeRequest) => {
      calls.push(req);
      const body = req.body as Partial<AdminUser>;
      const created = admin({ id: 9, name: body.name ?? body.email ?? '', ...body });
      users = [...users, created];
      return Response.json(created, { status: 201 });
    },
    'PATCH /api/users/2': (req: FakeRequest) => {
      calls.push(req);
      const updated = { ...LIST[1], ...(req.body as Partial<AdminUser>) } as AdminUser;
      users = users.map((u) => (u.id === 2 ? updated : u));
      return updated;
    },
  });
  return calls;
}

describe('Tela Usuários', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('só o admin vê o link e a tela', async () => {
    api();
    setDevUser('2');
    renderApp('/usuarios');
    expect(await screen.findByText('Só o administrador acessa esta tela.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Usuários' })).not.toBeInTheDocument();
  });

  it('lista papel, situação e obras de cada um', async () => {
    api();
    setDevUser('3');
    renderApp('/usuarios');
    expect(await screen.findByRole('link', { name: 'Usuários' })).toBeInTheDocument();
    const ana = await screen.findByTestId('user-a@cassol.ind.br');
    expect(within(ana).getByText('(você)')).toBeInTheDocument();
    expect(within(ana).getByText('(fixo)')).toBeInTheDocument();
    expect(within(ana).getByText('Todas')).toBeInTheDocument();
    const fabio = screen.getByTestId('user-f@cassol.ind.br');
    expect(within(fabio).getByText('OB-002')).toBeInTheDocument();
    expect(within(screen.getByTestId('user-l@cassol.ind.br')).getByText('Desativado')).toBeInTheDocument();
  });

  it('restringe as obras de um usuário', async () => {
    const calls = api();
    setDevUser('3');
    const user = userEvent.setup();
    renderApp('/usuarios');
    await user.click(await screen.findByRole('button', { name: 'Editar Fábio Fábrica' }));
    const dialog = screen.getByRole('dialog', { name: 'Editar Fábio Fábrica' });
    expect(within(dialog).getByRole('radio', { name: 'Só as obras escolhidas' })).toBeChecked();
    await user.click(within(dialog).getByRole('checkbox', { name: /OB-001/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Salvar' }));
    await waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toEqual({ obra_ids: [7, 8] });
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); });
  });

  it('volta para todas as obras e troca o papel', async () => {
    const calls = api();
    setDevUser('3');
    const user = userEvent.setup();
    renderApp('/usuarios');
    await user.click(await screen.findByRole('button', { name: 'Editar Fábio Fábrica' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('radio', { name: /^Projetos/ }));
    await user.click(within(dialog).getByRole('radio', { name: /Todas as obras/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Salvar' }));
    await waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toEqual({ role: 'projetos', all_obras: true });
  });

  it('admin fixo e o próprio admin não trocam de papel', async () => {
    api();
    setDevUser('3');
    const user = userEvent.setup();
    renderApp('/usuarios');
    await user.click(await screen.findByRole('button', { name: 'Editar Ana Admin' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/BOOTSTRAP_ADMIN_EMAILS/)).toBeInTheDocument();
    expect(within(dialog).getByRole('radio', { name: /^Leitura/ })).toBeDisabled();
    expect(within(dialog).getByRole('checkbox', { name: /Ativo/ })).toBeDisabled();
    expect(within(dialog).getByText('Administrador vê sempre todas as obras.')).toBeInTheDocument();
  });

  it('cadastra pelo e-mail antes do primeiro acesso', async () => {
    const calls = api();
    setDevUser('3');
    const user = userEvent.setup();
    renderApp('/usuarios');
    await user.click(await screen.findByRole('button', { name: 'Cadastrar usuário' }));
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar usuário' });
    await user.type(within(dialog).getByLabelText('E-mail corporativo'), 'novo@cassol.ind.br');
    await user.click(within(dialog).getByRole('radio', { name: /^Fábrica/ }));
    await user.click(within(dialog).getByRole('radio', { name: 'Só as obras escolhidas' }));
    await user.click(within(dialog).getByRole('checkbox', { name: /OB-002/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Cadastrar' }));
    await waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toEqual({
      email: 'novo@cassol.ind.br',
      role: 'fabrica',
      all_obras: false,
      obra_ids: [8],
    });
    expect(await screen.findByTestId('user-novo@cassol.ind.br')).toBeInTheDocument();
  });

  it('mostra o erro do servidor', async () => {
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras': OBRAS,
      'GET /api/users': LIST,
      'PATCH /api/users/2': () =>
        Response.json({ detail: 'Este é o último administrador ativo: promova outro antes.' }, { status: 409 }),
    });
    setDevUser('3');
    const user = userEvent.setup();
    renderApp('/usuarios');
    await user.click(await screen.findByRole('button', { name: 'Editar Fábio Fábrica' }));
    await user.click(screen.getByRole('checkbox', { name: /Ativo/ }));
    await user.click(screen.getByRole('button', { name: 'Salvar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('último administrador ativo');
  });
});
