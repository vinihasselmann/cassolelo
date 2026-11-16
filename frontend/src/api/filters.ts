import { apiFetch } from './client';

/** Motor de filtros do backend (F1–F3): campos, valores, avaliação e filtros salvos. */

export type FieldSource = 'model' | 'factory' | 'system';
export type FieldType = 'text' | 'number' | 'date' | 'bool';
export type FilterMode = 'isolate' | 'hide' | 'highlight';
export type FilterLogic = 'and' | 'or';
export type FilterOp =
  | 'eq' | 'ne' | 'contains' | 'not_contains' | 'starts_with' | 'empty' | 'not_empty' | 'in'
  | 'gt' | 'gte' | 'lt' | 'lte' | 'between'
  | 'on' | 'before' | 'after' | 'this_month' | 'last_month' | 'last_n_days';

export interface FieldRef {
  source: FieldSource;
  key: string;
}

export interface FilterField extends FieldRef {
  name: string;
  group: string | null;
  type: FieldType;
  distinct_values: number;
  pieces: number;
}

export interface FieldValueCount {
  value: string;
  pieces: number;
}

export interface FilterRule {
  field: FieldRef;
  op: FilterOp;
  value?: unknown;
  /** Isolar, Ocultar ou Destacar; sem modo, vale o do filtro. */
  mode?: FilterMode;
}

/** Formato gravado nos filtros salvos e aceito pela avaliação. */
export interface FilterDefinition {
  mode: FilterMode;
  logic: FilterLogic;
  rules: FilterRule[];
  /** "Pesquisar por objetos": cada palavra precisa aparecer. */
  q?: string;
}

export interface MarkGroup {
  mark_id: number | null;
  /** Nome da montagem; null = peças sem marca */
  code: string | null;
  category: string;
  matched: number;
  total: number;
}

export interface Evaluation {
  mode: FilterMode;
  logic: FilterLogic;
  total_pieces: number;
  matched_pieces: number;
  matched_marks: number;
  pieces: { dbid: number; mark_id: number | null }[];
  /** peças do resultado + membros delas (para o 3D) */
  dbids: number[];
  groups: MarkGroup[];
  notes: string[];
  /** "isolate": só o resultado à vista; "highlight": o resto esmaecido */
  view: 'isolate' | 'highlight';
  /** com "highlight": peças fora das visíveis, que ficam ocultas */
  hidden_dbids: number[];
}

export const fetchFields = (versionId: number): Promise<FilterField[]> =>
  apiFetch(`/versions/${versionId}/fields`);

export function fetchFieldValues(versionId: number, field: FieldRef, q = '', limit = 50): Promise<FieldValueCount[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (q) qs.set('q', q);
  const key = field.key.split('/').map(encodeURIComponent).join('/');
  return apiFetch(`/versions/${versionId}/fields/${field.source}/${key}/values?${qs.toString()}`);
}

export const evaluateFilter = (versionId: number, definition: FilterDefinition): Promise<Evaluation> =>
  apiFetch(`/versions/${versionId}/filter/evaluate`, { method: 'POST', body: JSON.stringify(definition) });

// ------------------------------------------------------------------ filtros salvos

export type FilterScope = 'personal' | 'shared';

export interface SavedFilter {
  id: number;
  name: string;
  scope: FilterScope;
  owner_id: number | null;
  obra_id: number | null;
  definition: FilterDefinition;
  system_key: string | null;
  editable: boolean;
  created_at: string;
  updated_at: string;
  created_by: number | null;
  updated_by: number | null;
}

export interface SavedFilterBody {
  name: string;
  scope: FilterScope;
  obra_id: number | null;
  definition: FilterDefinition;
}

export const savedFiltersKey = (obraId: number) => ['saved-filters', obraId] as const;

export const fetchSavedFilters = (obraId: number): Promise<SavedFilter[]> =>
  apiFetch(`/saved-filters?obra_id=${obraId}`);

export const createSavedFilter = (body: SavedFilterBody): Promise<SavedFilter> =>
  apiFetch('/saved-filters', { method: 'POST', body: JSON.stringify(body) });

export const updateSavedFilter = (id: number, body: Partial<SavedFilterBody>): Promise<SavedFilter> =>
  apiFetch(`/saved-filters/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
