import { vi } from 'vitest';

export interface FakeRequest {
  method: string;
  path: string;
  headers: Headers;
  body: unknown;
}

type Reply = Response | object | null;
type HandlerFn = (req: FakeRequest) => Reply;
type Handler = Reply | HandlerFn;

/**
 * Substitui `fetch` por um backend falso. Chaves: "GET /api/obras".
 * Valor: JSON da resposta, um Response, ou função que recebe a requisição.
 * Uma chave sem query string atende qualquer query (ex.: buscas).
 * Rotas não mapeadas respondem 404.
 */
export function installFakeApi(routes: Record<string, Handler>) {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    const path = decodeURIComponent(url);
    const method = (init?.method ?? 'GET').toUpperCase();
    // Rota exata; senão, a mesma rota sem a query string (o handler lê req.path).
    const handler = routes[`${method} ${path}`] ?? routes[`${method} ${path.split('?')[0] ?? path}`];
    const req: FakeRequest = {
      method,
      path,
      headers: new Headers(init?.headers),
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null,
    };
    if (handler === undefined) {
      return Promise.resolve(Response.json({ detail: `sem rota ${method} ${path}` }, { status: 404 }));
    }
    const reply: Reply = typeof handler === 'function' ? (handler as HandlerFn)(req) : handler;
    return Promise.resolve(reply instanceof Response ? reply : Response.json(reply));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

export const jsonError = (status: number, detail: string): Response =>
  Response.json({ detail }, { status });
