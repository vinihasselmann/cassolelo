import { apiFetch } from './client';

/** Regra de identificação das peças da obra (o que vale agora). */
export interface MarkRule {
  mark_property_names: string[];
  category_property_names: string[];
  /** false = padrão do servidor */
  custom_marks: boolean;
  custom_categories: boolean;
  default_mark_property_names: string[];
  default_category_property_names: string[];
  /** montagens (.nwd/.rvt com vínculos): categorias do corpo; null = modo desligado */
  piece_category_names: string[] | null;
  default_piece_category_names: string[];
}

export interface MarkRuleUpdate extends MarkRule {
  changed: boolean;
  reprocess_version_id: number | null;
  reprocess_version_number: number | null;
  enqueued: boolean;
}

/** null = voltar ao padrão do servidor */
export interface MarkRuleInput {
  mark_property_names: string[] | null;
  category_property_names: string[] | null;
  piece_category_names: string[] | null;
}

export interface MarkCandidate {
  name: string;
  groups: string[];
  pieces_with_value: number;
  marks: number;
  inconsistent_marks: number;
  inconsistent_pieces: number;
  /** quase um valor por peça (≥ 90%): id, GUID... */
  unique_per_piece: boolean;
  constant: boolean;
  /** número + unidade (volume, comprimento...) */
  measure: boolean;
  current: boolean;
  /** [valor, nº de peças] */
  examples: [string, number][];
}

export interface MarkCandidates {
  version_id: number;
  pieces: number;
  mark_property_names: string[];
  /** false: o modelo não tem as propriedades de dimensão configuradas */
  dimensions_checked: boolean;
  candidates: MarkCandidate[];
}

export const fetchMarkRule = (obraId: number): Promise<MarkRule> =>
  apiFetch(`/obras/${obraId}/mark-rule`);
export const saveMarkRule = (obraId: number, body: MarkRuleInput): Promise<MarkRuleUpdate> =>
  apiFetch(`/obras/${obraId}/mark-rule`, { method: 'PUT', body: JSON.stringify(body) });
export const fetchMarkCandidates = (versionId: number): Promise<MarkCandidates> =>
  apiFetch(`/versions/${versionId}/mark-candidates`);
