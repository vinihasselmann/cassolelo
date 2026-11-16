import { apiFetch } from './client';
import type { FieldRef, FilterDefinition, FilterScope } from './filters';

/** Cores no 3D (F2/F4): coloração por campo e esquemas de cores (regras por filtro). */

export type ColorizeMode = 'distinct' | 'range';

export interface ColorLegendItem {
  label: string;
  color: string;
  pieces: number;
  /** distinct: o valor (null = sem valor) */
  value: string | null;
  /** range: limites da faixa (número ou data ISO) */
  min: number | string | null;
  max: number | string | null;
  /** peças do item (sem membros) */
  dbids: number[];
}

export interface ColorizeResult {
  mode: ColorizeMode;
  field_name: string;
  field_type: string;
  /** dbId (peças e membros) -> "#RRGGBB" */
  colors: Record<string, string>;
  legend: ColorLegendItem[];
  total_pieces: number;
}

export const colorize = (versionId: number, field: FieldRef, mode: ColorizeMode): Promise<ColorizeResult> =>
  apiFetch(`/versions/${versionId}/colorize`, { method: 'POST', body: JSON.stringify({ field, mode }) });

/** Regra de um esquema: filtro salvo (id) ou definição inline, a cor e um rótulo. */
export interface SchemeRule {
  filter: number | FilterDefinition;
  color: string;
  label?: string;
}

export interface RuleResult {
  index: number;
  label: string;
  color: string;
  filter_id: number | null;
  /** peças que batem no filtro da regra */
  matched: number;
  /** peças que ficaram com a cor da regra (as anteriores têm prioridade) */
  pieces: number;
  dbids: number[];
}

export interface SchemeResult {
  colors: Record<string, string>;
  rules: RuleResult[];
  total_pieces: number;
  colored_pieces: number;
  notes: string[];
}

export const evaluateScheme = (
  versionId: number,
  body: { scheme_id: number } | { rules: SchemeRule[] },
): Promise<SchemeResult> =>
  apiFetch(`/versions/${versionId}/color-scheme/evaluate`, { method: 'POST', body: JSON.stringify(body) });

export interface ColorScheme {
  id: number;
  name: string;
  scope: FilterScope;
  owner_id: number | null;
  obra_id: number | null;
  rules: SchemeRule[];
  editable: boolean;
  created_at: string;
  updated_at: string;
  created_by: number | null;
  updated_by: number | null;
}

export interface ColorSchemeBody {
  name: string;
  scope: FilterScope;
  obra_id: number | null;
  rules: SchemeRule[];
}

export const colorSchemesKey = (obraId: number) => ['color-schemes', obraId] as const;

export const fetchColorSchemes = (obraId: number): Promise<ColorScheme[]> =>
  apiFetch(`/color-schemes?obra_id=${obraId}`);

export const createColorScheme = (body: ColorSchemeBody): Promise<ColorScheme> =>
  apiFetch('/color-schemes', { method: 'POST', body: JSON.stringify(body) });

export const updateColorScheme = (id: number, body: Partial<ColorSchemeBody>): Promise<ColorScheme> =>
  apiFetch(`/color-schemes/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
