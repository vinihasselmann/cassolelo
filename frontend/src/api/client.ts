/**
 * Cliente HTTP central. TODA chamada ao backend passa por aqui (apiFetch/authFetch).
 *
 * Login Microsoft (Fase 11): o AuthGate registra um `TokenProvider` (MSAL) e cada
 * requisição leva `Authorization: Bearer <access token>`. Um 401 renova o token uma vez.
 * Só em dev (APP_ENV=dev), sem login: usuário simulado escolhido no seletor do
 * cabeçalho, só em memória (nada de localStorage), no header X-Dev-User. No build de
 * produção (`import.meta.env.DEV` = false) esse caminho some do pacote (11.2).
 */

export const DEV_USER_HEADER = import.meta.env.DEV ? 'X-Dev-User' : '';

export class ApiError extends Error {
  readonly status: number;
  /** Corpo JSON da resposta de erro (ex.: `code`, campos extras de um 409). */
  readonly body: Record<string, unknown>;

  constructor(status: number, message: string, body: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }

  get code(): string | undefined {
    return typeof this.body.code === 'string' ? this.body.code : undefined;
  }
}

let devUserId: string | null = null;

export function setDevUser(id: string | null): void {
  if (!import.meta.env.DEV) return;
  devUserId = id && id.trim() !== '' ? id : null;
}

export function getDevUser(): string | null {
  return devUserId;
}

/** Devolve um access token válido; `forceRefresh` ignora o cache (depois de um 401). */
export type TokenProvider = (options: { forceRefresh: boolean }) => Promise<string>;

let tokenProvider: TokenProvider | null = null;

export function setTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider;
}

/** Há alguém para mandar ao backend (login Microsoft ou usuário simulado)? */
export function isSignedIn(): boolean {
  return tokenProvider !== null || devUserId !== null;
}

/** Põe a identificação do usuário nos headers (Bearer, ou X-Dev-User em dev). */
export async function applyAuth(headers: Headers, forceRefresh = false): Promise<void> {
  if (tokenProvider !== null) {
    headers.set('Authorization', `Bearer ${await tokenProvider({ forceRefresh })}`);
    if (import.meta.env.DEV) headers.delete(DEV_USER_HEADER);
  } else if (import.meta.env.DEV && devUserId !== null) {
    headers.set(DEV_USER_HEADER, devUserId);
  }
}

/**
 * `fetch` em /api com a identificação do usuário. Com login Microsoft, um 401 renova o
 * token e repete uma vez (o access token pode ter vencido entre o cache e o servidor).
 */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  await applyAuth(headers);
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (res.status !== 401 || tokenProvider === null) return res;
  const retry = new Headers(init.headers);
  await applyAuth(retry, true);
  return fetch(`/api${path}`, { ...init, headers: retry });
}

export async function toApiError(res: Response): Promise<ApiError> {
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = await res.json();
    if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>;
  } catch {
    // corpo não é JSON
  }
  const detail = typeof body.detail === 'string' ? body.detail : fallbackMessage(res.status);
  return new ApiError(res.status, detail, body);
}

/**
 * Mensagem quando o servidor não manda uma em português (proxy fora do ar, validação em lista…).
 * Nunca o statusText HTTP, que vem em inglês.
 */
export function fallbackMessage(status: number): string {
  if (status >= 500) return `O servidor não respondeu (erro ${String(status)}). Tente de novo em instantes.`;
  if (status === 403) return 'Seu papel não permite esta ação.';
  if (status === 404) return 'Não encontrado. Pode ter sido removido: recarregue a página.';
  if (status === 409) return 'Outra pessoa alterou isto ao mesmo tempo. Recarregue e confira.';
  if (status === 422) return 'Dados inválidos. Confira os campos e tente de novo.';
  return `Não foi possível concluir (erro ${String(status)}). Tente de novo.`;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const res = await authFetch(path, { ...init, headers });
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
