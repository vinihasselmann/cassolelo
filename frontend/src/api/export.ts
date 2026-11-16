import { DEV_USER_HEADER, getDevUser, toApiError } from './client';
import type { FilterDefinition } from './filters';

/** Nome do arquivo do Content-Disposition (filename*=UTF-8'' tem prioridade). */
export function filenameFrom(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star?.[1]) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain?.[1] ?? fallback;
}

/**
 * Baixa o Excel da obra (POST /api/obras/{id}/export.xlsx) com o filtro da tela: as
 * marcas do resultado, como a lista à esquerda. Sem filtro, todas as marcas da versão.
 */
export async function downloadObraExcel(
  obraId: number,
  versionId: number,
  filter: FilterDefinition | null,
): Promise<string> {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const user = getDevUser();
  if (user !== null) headers.set(DEV_USER_HEADER, user);
  const res = await fetch(`/api/obras/${String(obraId)}/export.xlsx`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ version_id: versionId, filter }),
  });
  if (!res.ok) throw await toApiError(res);
  const filename = filenameFrom(res.headers.get('Content-Disposition'), `obra-${String(obraId)}.xlsx`);
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => { URL.revokeObjectURL(url); }, 1000);
  return filename;
}
