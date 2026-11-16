const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' });

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : dateTime.format(d);
}

/** Valor de propriedade do modelo para exibição (listas separadas por vírgula; vazio = —). */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.map(formatValue).join(', ');
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return value.toString();
  }
  return JSON.stringify(value);
}

/** "há poucos segundos", "há 5 min", "há 2 h"; mais de um dia: data e hora. */
export function formatRelative(iso: string | null, now: number = Date.now()): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const seconds = Math.max(0, Math.round((now - t) / 1000));
  if (seconds < 60) return 'há poucos segundos';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  return `em ${formatDateTime(iso)}`;
}

const number = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 6 });

/** Valor de um parâmetro da fábrica para exibir (vazio = null). */
export function formatParamValue(type: string, value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (type === 'bool') return value === true ? 'Sim' : value === false ? 'Não' : formatValue(value);
  if (type === 'number' && typeof value === 'number') return number.format(value);
  if (type === 'date' && typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-');
    return `${d ?? ''}/${m ?? ''}/${y ?? ''}`;
  }
  return formatValue(value);
}
