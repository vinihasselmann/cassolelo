import { apiFetch } from './client';
import type { ParamType } from './paramDefs';

export type MarkStatus = 'pending' | 'partial' | 'complete' | 'review';

export interface MarkStatusResult {
  items: { mark_id: number; status: MarkStatus }[];
  counts: { status: MarkStatus; marks: number; pieces: number }[];
}

export interface ParamProgress {
  def_id: number;
  name: string;
  marks_total: number;
  marks_filled: number;
  pieces_total: number;
  pieces_filled: number;
}

export interface Progress {
  marks: number;
  pieces: number;
  required: ParamProgress[];
}

export interface ParamValuesByMark {
  def_id: number;
  name: string;
  type: ParamType;
  options: string[] | null;
  items: { mark_id: number; value: unknown }[]; // só as marcas em que o parâmetro se aplica
}

export const markStatusKey = (versionId: number) => ['versions', versionId, 'status'] as const;
export const progressKey = (versionId: number) => ['versions', versionId, 'progress'] as const;
export const paramValuesKey = (versionId: number, defId: number) => ['versions', versionId, 'param-values', defId] as const;

export const fetchMarkStatus = (versionId: number): Promise<MarkStatusResult> =>
  apiFetch(`/versions/${versionId}/marks/status`);
export const fetchProgress = (versionId: number): Promise<Progress> => apiFetch(`/versions/${versionId}/progress`);
export const fetchParamValues = (versionId: number, defId: number): Promise<ParamValuesByMark> =>
  apiFetch(`/versions/${versionId}/params/${defId}/values`);
