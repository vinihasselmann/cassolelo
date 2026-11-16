import { afterEach, describe, expect, it, vi } from 'vitest';

import { setDevUser } from './client';
import { connectObraEvents, parseSse, type ObraEvent } from './events';

const sse = (id: string, type: string, data: object) => `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;

/** Resposta SSE que entrega `chunks` e termina (o cliente então reconecta). */
function streamResponse(chunks: string[]): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
}

describe('parseSse', () => {
  it('mensagens completas, comentários (heartbeat), várias linhas de data e o resto incompleto', () => {
    const { messages, rest } = parseSse('retry: 3000\n\n: heartbeat\n\nid: 1-0\nevent: x\ndata: {"a":\ndata: 1}\n\nid: 2-0\nevent: y');
    expect(messages).toEqual([{ retry: 3000 }, { id: '1-0', event: 'x', data: '{"a":\n1}' }]);
    expect(rest).toBe('id: 2-0\nevent: y');
  });

  it('aceita \\r\\n', () => {
    expect(parseSse('id: 1-0\r\nevent: x\r\ndata: 1\r\n\r\n').messages).toEqual([{ id: '1-0', event: 'x', data: '1' }]);
  });
});

describe('connectObraEvents', () => {
  afterEach(() => {
    setDevUser(null);
    vi.unstubAllGlobals();
  });

  it('entrega os eventos, manda o usuário e reconecta com o Last-Event-ID', async () => {
    setDevUser('2');
    const requests: Headers[] = [];
    const replies = [
      [': conectado\n\n', sse('1-0', 'values_changed', { mark: 'PP001' }).slice(0, 20), sse('1-0', 'values_changed', { mark: 'PP001' }).slice(20)],
      [sse('2-0', 'batch_applied', { marks: 3 })],
    ];
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => {
        requests.push(new Headers(init.headers));
        const next = replies.shift();
        return Promise.resolve(next ? streamResponse(next) : new Response(null, { status: 404 }));
      }),
    );
    const got: ObraEvent[] = [];
    const stop = connectObraEvents(7, { onEvent: (e) => got.push(e), sleep: () => Promise.resolve() });
    await vi.waitFor(() => { expect(got).toHaveLength(2); });
    stop();
    expect(got.map((e) => [e.id, e.type, e.data])).toEqual([
      ['1-0', 'values_changed', { mark: 'PP001' }],
      ['2-0', 'batch_applied', { marks: 3 }],
    ]);
    expect(requests[0]?.get('X-Dev-User')).toBe('2');
    expect(requests[0]?.get('Last-Event-ID')).toBeNull();
    expect(requests[1]?.get('Last-Event-ID')).toBe('1-0'); // reconexão sem perder nada
    expect(requests[2]?.get('Last-Event-ID')).toBe('2-0');
  });

  it('erro de rede: tenta de novo com espera crescente; parar encerra', async () => {
    const waits: number[] = [];
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        calls += 1;
        return calls < 3 ? Promise.reject(new TypeError('offline')) : Promise.resolve(new Response(null, { status: 404 }));
      }),
    );
    connectObraEvents(7, { onEvent: () => undefined, sleep: (ms) => { waits.push(ms); return Promise.resolve(); } });
    await vi.waitFor(() => { expect(calls).toBe(3); });
    expect(waits).toEqual([3000, 6000]);
  });
});
