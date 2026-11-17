import { apiFetch } from './client';

export type ParamType = 'text' | 'number' | 'list' | 'date' | 'bool';
export type ParamScope = 'global' | 'obra';
/** Por marca (vale para todas as peças da marca) ou por peça (cada unidade tem o seu). */
export type ParamLevel = 'mark' | 'piece';

export const PARAM_TYPE_LABELS: Record<ParamType, string> = {
  text: 'Texto',
  number: 'Número',
  list: 'Lista de opções',
  date: 'Data',
  bool: 'Sim/não',
};

export interface ParamDef {
  id: number;
  name: string;
  type: ParamType;
  unit: string | null;
  options: string[] | null;
  required: boolean;
  categories: string[] | null; // null = todas
  scope: ParamScope;
  level: ParamLevel;
  obra_id: number | null;
  obra_code: string | null;
  active: boolean;
  values_count: number;
  /** listado para uma obra: vale nela? (biblioteca só vale onde foi incluída) */
  in_obra?: boolean | null;
  /** obras em que o parâmetro da biblioteca está incluído */
  obras_count?: number;
  options_in_use: string[];
  created_at: string;
  updated_at: string;
  created_by_name: string | null;
}

export interface ParamDefBody {
  name: string;
  type: ParamType;
  unit: string | null;
  options: string[] | null;
  required: boolean;
  categories: string[]; // [] = todas
  scope: ParamScope;
  level?: ParamLevel; // padrão: mark
  obra_id: number | null;
  /** criar da biblioteca de dentro de uma obra: já inclui nela */
  include_in_obra_id?: number | null;
}

export const fetchParamDefs = (obraId: number): Promise<ParamDef[]> =>
  apiFetch(`/param-defs?obra_id=${obraId}`);
/** Os da obra + toda a biblioteca (in_obra diz se vale nesta obra). */
export const fetchParamLibrary = (obraId: number): Promise<ParamDef[]> =>
  apiFetch(`/param-defs?obra_id=${obraId}&library=true`);
export const includeParamInObra = (obraId: number, defId: number): Promise<unknown> =>
  apiFetch(`/obras/${obraId}/params/${defId}`, { method: 'POST' });
export const removeParamFromObra = (obraId: number, defId: number): Promise<unknown> =>
  apiFetch(`/obras/${obraId}/params/${defId}`, { method: 'DELETE' });
export const createParamDef = (body: ParamDefBody): Promise<ParamDef> =>
  apiFetch('/param-defs', { method: 'POST', body: JSON.stringify(body) });
export const updateParamDef = (id: number, body: Partial<ParamDefBody>): Promise<ParamDef> =>
  apiFetch(`/param-defs/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
export const deleteParamDef = (id: number): Promise<void> =>
  apiFetch(`/param-defs/${id}`, { method: 'DELETE' });

/** O parâmetro vale para a categoria? (categorias nulas/vazias = todas) */
export function appliesTo(def: ParamDef, category: string | null | undefined): boolean {
  if (!def.categories || def.categories.length === 0) return true;
  return category !== null && category !== undefined && def.categories.includes(category);
}
