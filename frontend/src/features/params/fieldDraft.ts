import type { ParamType } from '../../api/paramDefs';

/** O mínimo de um parâmetro para montar o campo de edição (marca única ou lote). */
export interface FieldShape {
  def_id: number;
  name: string;
  type: ParamType;
  unit: string | null;
  options: string[] | null;
}

export type Draft = Record<number, string>;

/** Valor gravado -> texto do campo de edição (número com vírgula; sim/não como 'true'/'false'). */
export function toDraft(f: { type: ParamType }, v: unknown): string {
  if (v === null || v === undefined) return '';
  if (f.type === 'number' && typeof v === 'number') return String(v).replace('.', ',');
  if (f.type === 'bool') return v === true ? 'true' : v === false ? 'false' : '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

/** Texto do campo -> valor enviado (o backend valida e normaliza; '' apaga). */
export function fromDraft(f: { type: ParamType }, text: string): unknown {
  if (text.trim() === '') return null;
  if (f.type === 'bool') return text === 'true';
  return text;
}

export function fieldLabel(f: FieldShape): string {
  return f.unit ? `${f.name} (${f.unit})` : f.name;
}

export const MIXED_KEEP = '(valores mistos: manter)';
