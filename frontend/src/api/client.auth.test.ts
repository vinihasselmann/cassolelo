import { afterEach, describe, expect, it, vi } from 'vitest';

import { downloadObraExcel } from './export';
import {
  apiFetch,
  authFetch,
  DEV_USER_HEADER,
  isSignedIn,
  setDevUser,
  setTokenProvider,
  type TokenProvider,
} from './client';

function provider(): TokenProvider & ReturnType<typeof vi.fn> {
  let n = 0;
  return vi.fn(({ forceRefresh }: { forceRefresh: boolean }) => {
    n += 1;
    return Promise.resolve(forceRefresh ? `novo-${String(n)}` : `tok-${String(n)}`);
  });
}

const auth = (fn: ReturnType<typeof vi.fn<typeof fetch>>, call = 0): string | null =>
  new Headers(fn.mock.calls[call]?.[1]?.headers).get('Authorization');

describe('cliente HTTP com login Microsoft (Fase 11)', () => {
  afterEach(() => {
    setTokenProvider(null);
    setDevUser(null);
    vi.unstubAllGlobals();
  });

  it('manda Authorization: Bearer e não manda X-Dev-User', async () => {
    setDevUser('3');
    setTokenProvider(provider());
    const fn = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal('fetch', fn);
    await expect(apiFetch('/me')).resolves.toEqual({ ok: true });
    expect(auth(fn)).toBe('Bearer tok-1');
    expect(new Headers(fn.mock.calls[0]?.[1]?.headers).has(DEV_USER_HEADER)).toBe(false);
  });

  it('401: renova o token (forceRefresh) e repete uma vez', async () => {
    const p = provider();
    setTokenProvider(p);
    const fn = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ detail: 'Sessão expirada' }, { status: 401 }))
      .mockResolvedValueOnce(Response.json({ id: 1 }));
    vi.stubGlobal('fetch', fn);
    await expect(apiFetch('/me')).resolves.toEqual({ id: 1 });
    expect(fn).toHaveBeenCalledTimes(2);
    expect(auth(fn, 1)).toBe('Bearer novo-2');
    expect(p).toHaveBeenLastCalledWith({ forceRefresh: true });
  });

  it('401 de novo depois de renovar: erro, sem laço', async () => {
    setTokenProvider(provider());
    const fn = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(Response.json({ detail: 'Token inválido.' }, { status: 401 })));
    vi.stubGlobal('fetch', fn);
    await expect(apiFetch('/me')).rejects.toMatchObject({ status: 401, message: 'Token inválido.' });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('usuário simulado: 401 não repete (não há token para renovar)', async () => {
    setDevUser('1');
    const fn = vi.fn<typeof fetch>().mockResolvedValue(Response.json({}, { status: 401 }));
    vi.stubGlobal('fetch', fn);
    const res = await authFetch('/me');
    expect(res.status).toBe(401);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('isSignedIn: token ou usuário simulado', () => {
    expect(isSignedIn()).toBe(false);
    setDevUser('1');
    expect(isSignedIn()).toBe(true);
    setDevUser(null);
    setTokenProvider(provider());
    expect(isSignedIn()).toBe(true);
  });

  it('o Excel também vai com o Bearer', async () => {
    setTokenProvider(provider());
    const fn = vi.fn<typeof fetch>().mockResolvedValue(new Response(new Blob(['x'])));
    vi.stubGlobal('fetch', fn);
    vi.stubGlobal('URL', { ...URL, createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    await downloadObraExcel(1, 2, null).catch(() => undefined);
    expect(fn.mock.calls[0]?.[0]).toBe('/api/obras/1/export.xlsx');
    expect(auth(fn)).toBe('Bearer tok-1');
    click.mockRestore();
  });
});
