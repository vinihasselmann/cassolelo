import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DEV_USER_HEADER, setDevUser } from '../../api/client';
import type { User } from '../../api/users';
import { AppRoutes } from '../../routes';

const USERS: User[] = [
  { id: 1, name: 'Paula Projetos', email: 'projetos@dev.local', role: 'projetos' },
  { id: 2, name: 'Fábio Fábrica', email: 'fabrica@dev.local', role: 'fabrica' },
  { id: 3, name: 'Ana Admin', email: 'admin@dev.local', role: 'admin' },
];

const urlOf = (input: RequestInfo | URL): string =>
  input instanceof Request ? input.url : input instanceof URL ? input.href : input;

/** Backend falso: /api/me responde conforme o header X-Dev-User. */
function fakeBackend() {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = urlOf(input);
    if (url === '/api/dev/users') return Promise.resolve(Response.json(USERS));
    if (url === '/api/me') {
      const id = new Headers(init?.headers).get(DEV_USER_HEADER);
      const user = USERS.find((u) => String(u.id) === id);
      return Promise.resolve(
        user ? Response.json(user) : Response.json({ detail: 'x' }, { status: 401 }),
      );
    }
    return Promise.resolve(new Response(null, { status: 404 }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('layout e usuário simulado', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('mostra o cabeçalho com o logotipo "Cassol Elo"', () => {
    fakeBackend();
    renderApp();
    const heading = screen.getByRole('heading', { level: 1 });
    expect(within(heading).getByRole('img', { name: 'Cassol Elo' })).toBeInTheDocument();
    expect(within(heading).getByRole('link', { name: 'Cassol Elo — início' })).toHaveAttribute('href', '/');
  });

  it('trocar o usuário muda o papel retornado por /api/me', async () => {
    const fetchMock = fakeBackend();
    const user = userEvent.setup();
    renderApp();

    // o seletor carrega sob demanda (lazy: fica fora do build de produção)
    const select = await screen.findByRole('combobox', { name: /usuário/i });
    await screen.findByRole('option', { name: /Fábio Fábrica/ });
    expect(screen.queryByTestId('current-role')).not.toBeInTheDocument();

    await user.selectOptions(select, '2');
    expect(await screen.findByTestId('current-role')).toHaveTextContent('Papel: Fábrica');

    await user.selectOptions(select, '3');
    expect(await screen.findByText('Papel: Administrador')).toBeInTheDocument();

    const meCalls = fetchMock.mock.calls.filter(([input]) => urlOf(input) === '/api/me');
    const sent = meCalls.map(([, init]) => new Headers(init?.headers).get(DEV_USER_HEADER));
    expect(sent).toEqual(['2', '3']);
  });

  it('avisa quando a lista de usuários não carrega', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 500 })));
    renderApp();
    expect(await screen.findByText('Não foi possível carregar os usuários.')).toHaveAttribute('role', 'alert');
  });
});
