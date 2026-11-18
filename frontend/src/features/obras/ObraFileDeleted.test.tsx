import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { setDevUser } from '../../api/client';
import type { Obra } from '../../api/obras';
import type { User } from '../../api/users';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderApp } from '../../test/render';

/** Arquivo da obra excluído no Autodesk Docs: obra cinza, só Editar/Excluir (2026-11-18). */

const USERS: Record<string, User> = {
  '1': { id: 1, name: 'Paula Projetos', email: 'p@dev.local', role: 'projetos' },
};
const me = (req: FakeRequest) => USERS[req.headers.get('X-Dev-User') ?? ''] ?? Response.json({}, { status: 401 });

const base: Obra = {
  id: 7,
  code: 'OB-001',
  name: 'Galpão',
  acc_hub_id: 'b.h',
  acc_project_id: 'b.p',
  acc_folder_id: 'urn:f',
  acc_item_id: 'urn:i',
  acc_item_name: 'OBRA-001.ifc',
  active: true,
  acc_file_state: 'ok',
  acc_file_state_at: null,
  unit_numbering: 'sequence',
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
};
const DELETED: Obra = { ...base, id: 16, code: 'OB-EXC', acc_file_state: 'deleted', acc_file_state_at: '2026-11-18T11:16:08Z' };

describe('Obra com arquivo excluído no Docs', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('fica cinza na lista, sem link, mas com Editar e Excluir', async () => {
    installFakeApi({ 'GET /api/me': me, 'GET /api/dev/users': Object.values(USERS), 'GET /api/obras': [base, DELETED] });
    setDevUser('1');
    renderApp('/obras');

    expect(await screen.findByRole('link', { name: 'OB-001' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'OB-EXC' })).not.toBeInTheDocument();
    const row = screen.getByText('OB-EXC').closest('tr');
    expect(row).not.toBeNull();
    expect(row).toHaveClass('row-blocked');
    const cells = within(row as HTMLElement);
    expect(cells.getByText('Arquivo excluído no Docs')).toBeInTheDocument();
    expect(cells.getByRole('button', { name: 'Editar obra OB-EXC' })).toBeEnabled();
    expect(cells.getByRole('button', { name: 'Excluir obra OB-EXC' })).toBeEnabled();
    // a obra normal não ganha o selo
    const okRow = screen.getByRole('link', { name: 'OB-001' }).closest('tr');
    expect(okRow).not.toHaveClass('row-blocked');
  });

  it('pela URL, a página da obra mostra o aviso e esconde 3D e abas', async () => {
    installFakeApi({ 'GET /api/me': me, 'GET /api/dev/users': Object.values(USERS), 'GET /api/obras/16': DELETED });
    setDevUser('1');
    renderApp('/obras/16');

    expect(await screen.findByText(/foi excluído do Autodesk Docs/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Abrir modelo 3D' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Versões' })).not.toBeInTheDocument();
  });

  it('pela URL, o modelo 3D não abre', async () => {
    installFakeApi({ 'GET /api/me': me, 'GET /api/dev/users': Object.values(USERS), 'GET /api/obras/16': DELETED });
    setDevUser('1');
    renderApp('/obras/16/modelo');

    expect(await screen.findByText(/foi excluído do Autodesk Docs/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Voltar para a lista de obras' })).toBeInTheDocument();
  });
});

describe('mensagens do arquivo excluído', () => {
  it('sync e evento em tempo real', async () => {
    const { syncMessage } = await import('./syncMessage');
    const { describeEvent } = await import('../live/eventText');
    const r = {
      total_in_docs: 2, created: 0, ready: 0, translating: 0, no_translation: 0, failed: 0,
      enqueued: 0, enqueue_failed: 0, deleted: 1, file_state: 'deleted' as const,
    };
    expect(syncMessage(r)).toBe('O arquivo desta obra foi excluído do Autodesk Docs.');
    expect(syncMessage({ ...r, file_state: 'ok', deleted: 0 })).toBe('Nenhuma versão nova no Docs.');
    const ev = (state: string) => ({
      id: '1-0',
      type: 'obra_file_state' as const,
      data: { type: 'obra_file_state' as const, obra_id: 16, at: '', actor: null, state },
    });
    expect(describeEvent(ev('deleted'))).toBe('O arquivo da obra foi excluído do Docs');
    expect(describeEvent(ev('ok'))).toBe('O arquivo da obra foi restaurado no Docs');
  });
});
