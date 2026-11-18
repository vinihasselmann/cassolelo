import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { setDevUser } from '../../api/client';
import type { ModelVersion, Obra } from '../../api/obras';
import type { User } from '../../api/users';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderApp } from '../../test/render';

const USERS: Record<string, User> = {
  '1': { id: 1, name: 'Paula Projetos', email: 'p@dev.local', role: 'projetos' },
  '2': { id: 2, name: 'Fábio Fábrica', email: 'f@dev.local', role: 'fabrica' },
  '4': { id: 4, name: 'Lia Leitura', email: 'l@dev.local', role: 'leitura' },
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

const version = (n: number, comment: string | null): ModelVersion => ({
  id: n,
  version_number: n,
  status: 'pending',
  published_by: 'Usuário Projetos',
  published_at: `2026-10-0${n}T12:00:00Z`,
  comment,
  error: null,
  has_urn: true,
  urn: 'dXJu',
});

const me = (req: FakeRequest) => USERS[req.headers.get('X-Dev-User') ?? ''] ?? Response.json({}, { status: 401 });

describe('Obras e versões', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('lista obras e mostra "Nova obra" só para projetos/admin', async () => {
    installFakeApi({ 'GET /api/me': me, 'GET /api/dev/users': Object.values(USERS), 'GET /api/obras': [OBRA] });
    setDevUser('4');
    const view = renderApp('/obras');
    expect(await screen.findByRole('link', { name: 'OB-001' })).toBeInTheDocument();
    expect(screen.getByText('OBRA-001.rvt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Nova obra' })).not.toBeInTheDocument();
    view.unmount();

    setDevUser('1');
    renderApp('/obras');
    expect(await screen.findByRole('button', { name: 'Nova obra' })).toBeInTheDocument();
  });

  it('pede para escolher usuário quando não há usuário simulado', async () => {
    installFakeApi({
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras': Response.json({ detail: 'x' }, { status: 401 }),
    });
    renderApp('/obras');
    expect(await screen.findByText('Selecione um usuário no cabeçalho.')).toBeInTheDocument();
  });

  it('aba Versões mostra o histórico e "Sincronizar agora" importa versões novas', async () => {
    let versions: ModelVersion[] = [version(1, null)];
    let syncCalls = 0;
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': () => versions,
      'POST /api/obras/7/sync': () => {
        syncCalls += 1;
        versions = [version(2, 'Revisão das vigas'), version(1, null)];
        return {
          total_in_docs: 2,
          created: 1,
          ready: 1,
          translating: 0,
          no_translation: 0,
          failed: 0,
          enqueued: 1,
          enqueue_failed: 0,
        };
      },
    });
    setDevUser('2');
    const user = userEvent.setup();
    renderApp('/obras/7');

    expect(await screen.findByRole('heading', { name: 'OB-001 — Galpão' })).toBeInTheDocument();
    const table = await screen.findByRole('table');
    expect(within(table).getByText('V1')).toBeInTheDocument();
    expect(within(table).getByText('Aguardando processamento')).toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: 'Sincronizar agora' }));
    expect(await screen.findByRole('status')).toHaveTextContent('1 versão nova importada.');
    expect(screen.getByRole('status')).toHaveTextContent('1 pronta para processamento');
    expect(await screen.findByText('Revisão das vigas')).toBeInTheDocument();
    expect(syncCalls).toBe(1);
  });

  it('avisa quando a fila está indisponível', async () => {
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [],
      'POST /api/obras/7/sync': {
        total_in_docs: 2,
        created: 2,
        ready: 2,
        translating: 0,
        no_translation: 0,
        failed: 0,
        enqueued: 0,
        enqueue_failed: 2,
      },
    });
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras/7/versoes');
    expect(await screen.findByText(/Nenhuma versão sincronizada ainda/)).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Sincronizar agora' }));
    expect(await screen.findByRole('status')).toHaveTextContent('fila indisponível');
  });

  it('leitura não vê o botão de sincronizar', async () => {
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(1, null)],
    });
    setDevUser('4');
    renderApp('/obras/7/versoes');
    expect(await screen.findByText('V1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sincronizar agora' })).not.toBeInTheDocument();
  });

  it('versão sem conversão mostra o aviso para publicar pelo Docs', async () => {
    const semConversao: ModelVersion = { ...version(2, null), status: 'no_translation', has_urn: false };
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [semConversao, version(1, null)],
    });
    setDevUser('4');
    renderApp('/obras/7/versoes');
    const note = await screen.findByRole('note');
    expect(note).toHaveTextContent(
      'Este arquivo não foi convertido pelo Docs. Abra-o no Autodesk Docs e inicie o processamento, ou publique pelo site do Docs ou pela publicação em nuvem do Revit.',
    );
    expect(screen.getByText('Sem conversão no Docs')).toBeInTheDocument();
    expect(screen.getAllByRole('note')).toHaveLength(1); // só na versão sem conversão
  });
});
