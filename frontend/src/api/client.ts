/**
 * Cliente HTTP central. TODA chamada ao backend passa por aqui.
 *
 * Até a Fase 11 o usuário é simulado: o id escolhido no seletor do cabeçalho
 * fica só em memória (nada de localStorage) e vai no header X-Dev-User.
 */

export const DEV_USER_HEADER = 'X-Dev-User';

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
  devUserId = id && id.trim() !== '' ? id : null;
}

export function getDevUser(): string | null {
  return devUserId;
}

export async function toApiError(res: Response): Promise<ApiError> {
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = await res.json();
    if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>;
  } catch {
    // corpo não é JSON
  }
  const detail = typeof body.detail === 'string' ? body.detail : res.statusText || `Erro HTTP ${res.status}`;
  return new ApiError(res.status, detail, body);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (devUserId !== null) headers.set(DEV_USER_HEADER, devUserId);

  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
