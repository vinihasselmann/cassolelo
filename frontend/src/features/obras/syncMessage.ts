import type { SyncResult } from '../../api/obras';

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function syncMessage(r: SyncResult): string {
  if (r.created === 0) return 'Nenhuma versão nova no Docs.';
  const parts = [`${plural(r.created, 'versão nova importada', 'versões novas importadas')}.`];
  const details: string[] = [];
  if (r.ready > 0) details.push(`${r.ready} pronta(s) para processamento`);
  if (r.translating > 0) details.push(`${r.translating} ainda em conversão no Docs`);
  if (r.no_translation > 0) details.push(`${r.no_translation} sem conversão no Docs`);
  if (r.failed > 0) details.push(`${r.failed} com falha na conversão`);
  if (details.length > 0) parts.push(`(${details.join('; ')}.)`);
  if (r.enqueue_failed > 0) {
    parts.push(
      `Atenção: o processamento de ${r.enqueue_failed} versão(ões) não foi agendado (fila indisponível); elas ficam aguardando.`,
    );
  }
  return parts.join(' ');
}
