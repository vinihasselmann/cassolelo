/**
 * Eventos da obra em tempo real (Fase 8.1): GET /api/obras/{id}/events (Server-Sent Events).
 *
 * Usa fetch com leitura em fluxo (e não EventSource) porque o EventSource não envia
 * cabeçalhos, e o usuário simulado vai no X-Dev-User. Reconecta sozinho, mandando o
 * Last-Event-ID, para receber o que perdeu; se nada chegar por WATCHDOG_MS (nem o
 * heartbeat de 20 s), considera a conexão morta e reconecta.
 */

import { DEV_USER_HEADER, getDevUser } from './client';

export type ObraEventType =
  | 'version_ready'
  | 'version_failed'
  | 'values_changed'
  | 'batch_applied'
  | 'batch_undone'
  | 'orphan_changed'
  | 'param_def_changed'
  // parâmetros por peça (P2)
  | 'unit_values_changed'
  | 'unit_batch_applied'
  | 'unit_batch_undone'
  | 'unit_orphan_changed';

export interface EventActor {
  id: number;
  name: string;
}

/** Corpo (`data`) de um evento: campos comuns + os específicos do tipo. */
export interface ObraEventData {
  type: ObraEventType;
  obra_id: number;
  at: string;
  actor: EventActor | null;
  [key: string]: unknown;
}

export interface ObraEvent {
  id: string;
  type: ObraEventType;
  data: ObraEventData;
}

export interface SseMessage {
  id?: string;
  event?: string;
  data?: string;
  retry?: number;
}

/** Quebra o texto recebido em mensagens SSE completas; devolve também o resto incompleto. */
export function parseSse(buffer: string): { messages: SseMessage[]; rest: string } {
  const normalized = buffer.replace(/\r\n?/g, '\n');
  const blocks = normalized.split('\n\n');
  const rest = blocks.pop() ?? '';
  const messages: SseMessage[] = [];
  for (const block of blocks) {
    const msg: SseMessage = {};
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line === '' || line.startsWith(':')) continue; // comentário (heartbeat)
      const at = line.indexOf(':');
      const field = at < 0 ? line : line.slice(0, at);
      const value = at < 0 ? '' : line.slice(at + 1).replace(/^ /, '');
      if (field === 'id') msg.id = value;
      else if (field === 'event') msg.event = value;
      else if (field === 'data') data.push(value);
      else if (field === 'retry' && /^\d+$/.test(value)) msg.retry = Number(value);
    }
    if (data.length > 0) msg.data = data.join('\n');
    if (msg.id !== undefined || msg.event !== undefined || msg.data !== undefined || msg.retry !== undefined) {
      messages.push(msg);
    }
  }
  return { messages, rest };
}

export const WATCHDOG_MS = 60_000; // 3 heartbeats
const MAX_BACKOFF_MS = 30_000;

export interface ConnectOptions {
  onEvent: (event: ObraEvent) => void;
  /** Conectado (ou reconectado). */
  onOpen?: () => void;
  /** Para os testes: espera entre tentativas. */
  sleep?: (ms: number) => Promise<void>;
  watchdogMs?: number;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Assina os eventos da obra até `stop()`. Devolve a função que encerra. */
export function connectObraEvents(obraId: number, options: ConnectOptions): () => void {
  const controller = new AbortController();
  const sleep = options.sleep ?? defaultSleep;
  const watchdogMs = options.watchdogMs ?? WATCHDOG_MS;
  let lastId: string | null = null;
  let retryMs = 3000;
  let failures = 0;

  async function once(): Promise<boolean> {
    const headers = new Headers({ Accept: 'text/event-stream' });
    const user = getDevUser();
    if (user !== null) headers.set(DEV_USER_HEADER, user);
    if (lastId !== null) headers.set('Last-Event-ID', lastId);
    const attempt = new AbortController();
    const abort = () => { attempt.abort(); };
    controller.signal.addEventListener('abort', abort);
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(abort, watchdogMs);
    };
    try {
      const res = await fetch(`/api/obras/${String(obraId)}/events`, { headers, signal: attempt.signal });
      if (res.status === 404) return false; // obra não existe: não insistir
      if (!res.ok || !res.body) throw new Error(`HTTP ${String(res.status)}`);
      failures = 0;
      options.onOpen?.();
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      arm();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        arm();
        buffer += decoder.decode(value, { stream: true });
        const { messages, rest } = parseSse(buffer);
        buffer = rest;
        for (const m of messages) {
          if (m.retry !== undefined) retryMs = m.retry;
          if (m.id !== undefined) lastId = m.id;
          if (m.event && m.data) {
            try {
              const data = JSON.parse(m.data) as ObraEventData;
              options.onEvent({ id: m.id ?? '', type: m.event as ObraEventType, data });
            } catch {
              // evento malformado: ignora
            }
          }
        }
      }
    } catch {
      failures += 1;
    } finally {
      clearTimeout(watchdog);
      controller.signal.removeEventListener('abort', abort);
    }
    return true;
  }

  void (async () => {
    while (!controller.signal.aborted) {
      const again = await once();
      if (!again) return; // o while confere se foi encerrado
      await sleep(Math.min(retryMs * 2 ** Math.max(0, failures - 1), MAX_BACKOFF_MS));
    }
  })();

  return () => { controller.abort(); };
}
