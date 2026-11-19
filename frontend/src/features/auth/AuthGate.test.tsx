import { InteractionRequiredAuthError, type AccountInfo, type IPublicClientApplication } from '@azure/msal-browser';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { setDevUser, setTokenProvider } from '../../api/client';
import { AppRoutes } from '../../routes';
import { AuthGate } from './AuthGate';
import { bootAuth, tokenProviderFor, type AuthBoot, type AuthConfig } from './microsoft';

const CONFIG: AuthConfig = {
  client_id: 'cid',
  tenant_id: 'tid',
  scope: 'api://cid/access_as_user',
  dev_login: false,
};
const ACCOUNT = { name: 'Vinícius Bastos', username: 'vhbastos@cassol.ind.br' } as AccountInfo;

type PcaMocks = Record<string, ReturnType<typeof vi.fn>>;

/** Funções simuladas do MSAL (mocks) e o objeto que o app recebe (asPca). */
function fakePca(overrides: PcaMocks = {}): PcaMocks {
  return {
    handleRedirectPromise: vi.fn().mockResolvedValue(null),
    getActiveAccount: vi.fn().mockReturnValue(null),
    getAllAccounts: vi.fn().mockReturnValue([]),
    setActiveAccount: vi.fn(),
    loginRedirect: vi.fn().mockResolvedValue(undefined),
    logoutRedirect: vi.fn().mockResolvedValue(undefined),
    acquireTokenSilent: vi.fn().mockResolvedValue({ accessToken: 'tok' }),
    acquireTokenRedirect: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const asPca = (m: PcaMocks) => m as unknown as IPublicClientApplication;

const urlOf = (input: RequestInfo | URL): string =>
  input instanceof Request ? input.url : input instanceof URL ? input.href : input;

/** Backend falso: /api/auth/config, /api/me (exige Bearer) e listas vazias. */
function backend(config: AuthConfig = CONFIG, me: Response | null = null) {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = urlOf(input);
    if (url === '/api/auth/config') return Promise.resolve(Response.json(config));
    if (url === '/api/me') {
      if (me) return Promise.resolve(me.clone());
      const bearer = new Headers(init?.headers).get('Authorization');
      return Promise.resolve(
        bearer === 'Bearer tok'
          ? Response.json({ id: 9, name: 'Vinícius Bastos', email: ACCOUNT.username, role: 'admin' })
          : Response.json({ detail: 'Entre com sua conta Microsoft.' }, { status: 401 }),
      );
    }
    return Promise.resolve(Response.json([]));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function renderGate(boot: Promise<AuthBoot>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AuthGate boot={boot}>
          <AppRoutes />
        </AuthGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  setTokenProvider(null);
  setDevUser(null);
  vi.unstubAllGlobals();
});

describe('bootAuth', () => {
  it('sem conta: pede login', async () => {
    backend();
    const pca = fakePca();
    const boot = await bootAuth(() => Promise.resolve(asPca(pca)));
    expect(boot.kind).toBe('login');
    expect(pca.handleRedirectPromise).toHaveBeenCalled();
  });

  it('volta do redirect: conta do resultado vira a ativa', async () => {
    backend();
    const pca = fakePca({ handleRedirectPromise: vi.fn().mockResolvedValue({ account: ACCOUNT }) });
    const boot = await bootAuth(() => Promise.resolve(asPca(pca)));
    expect(boot.kind).toBe('microsoft');
    expect(pca.setActiveAccount).toHaveBeenCalledWith(ACCOUNT);
  });

  it('sem Microsoft configurado: dev usa o simulado, fora de dev avisa', async () => {
    const factory = vi.fn();
    backend({ client_id: '', tenant_id: '', scope: '', dev_login: true });
    expect((await bootAuth(factory)).kind).toBe('dev');
    backend({ client_id: '', tenant_id: '', scope: '', dev_login: false });
    expect((await bootAuth(factory)).kind).toBe('unconfigured');
    expect(factory).not.toHaveBeenCalled();
  });
});

describe('tokenProviderFor', () => {
  it('pede o escopo do app em silêncio', async () => {
    const pca = fakePca();
    const get = tokenProviderFor(asPca(pca), ACCOUNT, CONFIG);
    await expect(get({ forceRefresh: true })).resolves.toBe('tok');
    expect(pca.acquireTokenSilent).toHaveBeenCalledWith({
      scopes: [CONFIG.scope],
      account: ACCOUNT,
      forceRefresh: true,
    });
  });

  it('sessão vencida na Microsoft: volta ao login por redirect', async () => {
    const pca = fakePca({
      acquireTokenSilent: vi.fn().mockRejectedValue(new InteractionRequiredAuthError('login_required', 'login necessário')),
    });
    const get = tokenProviderFor(asPca(pca), ACCOUNT, CONFIG);
    await expect(get({ forceRefresh: false })).rejects.toMatchObject({ status: 401 });
    expect(pca.acquireTokenRedirect).toHaveBeenCalledWith({ scopes: [CONFIG.scope], account: ACCOUNT });
  });
});

describe('AuthGate', () => {
  it('sem login: tela com "Entrar com Microsoft", que abre o redirect', async () => {
    backend();
    const pca = fakePca();
    renderGate(Promise.resolve({ kind: 'login', config: CONFIG, pca: asPca(pca) }));
    const button = await screen.findByRole('button', { name: 'Entrar com Microsoft' });
    expect(screen.queryByRole('button', { name: /simulado/ })).toBeNull(); // fora de dev
    await userEvent.click(button);
    expect(pca.loginRedirect).toHaveBeenCalledWith({ scopes: [CONFIG.scope], prompt: 'select_account' });
  });

  it('logado: confere /api/me com o Bearer, mostra nome e papel, e "Sair" desloga', async () => {
    const fn = backend();
    const pca = fakePca();
    renderGate(Promise.resolve({ kind: 'microsoft', config: CONFIG, pca: asPca(pca), account: ACCOUNT }));
    expect(await screen.findByTestId('current-role')).toHaveTextContent('Papel: Administrador');
    expect(screen.getByText('Vinícius Bastos')).toBeInTheDocument();
    expect(screen.queryByLabelText(/Usuário \(simulado\)/)).toBeNull();
    const meCall = fn.mock.calls.find(([input]) => urlOf(input) === '/api/me');
    expect(new Headers(meCall?.[1]?.headers).get('Authorization')).toBe('Bearer tok');
    await userEvent.click(screen.getByRole('button', { name: 'Sair' }));
    expect(pca.logoutRedirect).toHaveBeenCalledWith({ account: ACCOUNT });
  });

  it('e-mail fora do domínio (403): mostra o motivo e oferece outra conta', async () => {
    backend(CONFIG, Response.json({ detail: 'E-mail fora dos domínios permitidos (cassol.ind.br).' }, { status: 403 }));
    const pca = fakePca();
    renderGate(Promise.resolve({ kind: 'microsoft', config: CONFIG, pca: asPca(pca), account: ACCOUNT }));
    expect(await screen.findByRole('alert')).toHaveTextContent('cassol.ind.br');
    await userEvent.click(screen.getByRole('button', { name: 'Sair e usar outra conta' }));
    expect(pca.logoutRedirect).toHaveBeenCalled();
  });

  it('dev com Microsoft configurado: dá para seguir com o usuário simulado', async () => {
    backend();
    renderGate(Promise.resolve({ kind: 'login', config: { ...CONFIG, dev_login: true }, pca: asPca(fakePca()) }));
    await userEvent.click(await screen.findByRole('button', { name: 'Usar usuário simulado (dev)' }));
    expect(await screen.findByLabelText(/Usuário \(simulado\)/)).toBeInTheDocument();
  });

  it('dev sem Microsoft: direto no app com o seletor', async () => {
    backend({ client_id: '', tenant_id: '', scope: '', dev_login: true });
    renderGate(Promise.resolve({ kind: 'dev', config: { ...CONFIG, client_id: '', dev_login: true } }));
    expect(await screen.findByLabelText(/Usuário \(simulado\)/)).toBeInTheDocument();
  });

  it('servidor sem login configurado: avisa a TI', async () => {
    backend();
    renderGate(Promise.resolve({ kind: 'unconfigured', config: CONFIG }));
    expect(await screen.findByText(/faltam ENTRA_CLIENT_ID/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Entrar com Microsoft' })).toBeNull();
  });

  it('servidor fora do ar: mensagem e "Tentar de novo"', async () => {
    renderGate(Promise.reject(new Error('rede')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Não foi possível falar com o servidor');
    expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeInTheDocument();
  });
});
