import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch, DEV_USER_HEADER, getDevUser, setDevUser } from './client';

function stubFetch(response: Response) {
  const fn = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal('fetch', fn);
  return fn;
}

function sentHeaders(fn: ReturnType<typeof stubFetch>): Headers {
  const init = fn.mock.calls[0]?.[1];
  return new Headers(init?.headers);
}

describe('apiFetch', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('prefixa /api e envia X-Dev-User do usuário simulado', async () => {
    setDevUser('3');
    const fn = stubFetch(Response.json({ ok: true }));
    await expect(apiFetch('/me')).resolves.toEqual({ ok: true });
    expect(fn.mock.calls[0]?.[0]).toBe('/api/me');
    expect(sentHeaders(fn).get(DEV_USER_HEADER)).toBe('3');
  });

  it('não envia o header sem usuário selecionado', async () => {
    const fn = stubFetch(Response.json({}));
    await apiFetch('/health');
    expect(sentHeaders(fn).has(DEV_USER_HEADER)).toBe(false);
  });

  it('trocar o usuário muda o header das próximas requisições', async () => {
    setDevUser('1');
    const first = stubFetch(Response.json({}));
    await apiFetch('/me');
    setDevUser('2');
    const second = stubFetch(Response.json({}));
    await apiFetch('/me');
    expect(sentHeaders(first).get(DEV_USER_HEADER)).toBe('1');
    expect(sentHeaders(second).get(DEV_USER_HEADER)).toBe('2');
  });

  it('usuário vazio equivale a nenhum', () => {
    setDevUser('');
    expect(getDevUser()).toBeNull();
  });

  it('lança ApiError com o detail do backend', async () => {
    stubFetch(Response.json({ detail: 'Seu papel não permite esta ação.' }, { status: 403 }));
    const error = await apiFetch('/x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, message: 'Seu papel não permite esta ação.' });
  });
});
