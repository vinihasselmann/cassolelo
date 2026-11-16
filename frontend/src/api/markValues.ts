import { apiFetch } from './client';
import type { ParamType } from './paramDefs';

export interface FieldValue {
  def_id: number;
  name: string;
  type: ParamType;
  unit: string | null;
  required: boolean;
  options: string[] | null;
  value: unknown;
  row_version: number | null; // devolver no PUT (null = ainda não havia valor)
  updated_at: string | null;
  updated_by_name: string | null;
}

export interface MarkValues {
  mark: { id: number; code: string; category: string; review_status?: 'ok' | 'review'; review_note?: string | null };
  values: FieldValue[];
  last_change_by: string | null;
  last_change_at: string | null;
}

export interface ValueChange {
  def_id: number;
  value: unknown;
  row_version: number | null;
}

export interface HistoryEntry {
  at: string;
  user_name: string | null;
  action: string; // set | update | clear
  param: string;
  def_id: number | null;
  before: unknown;
  after: unknown;
  batch_id: string | null;
}

/** Corpo do 409 quando outro usuário salvou antes. */
export interface StaleConflict {
  changed_by_name: string | null;
  changed_at: string | null;
  conflict_def_ids: number[];
}

const base = (obraId: number, markId: number) => `/obras/${obraId}/marks/${markId}`;

export const markValuesKey = (obraId: number, markId: number) => ['mark-values', obraId, markId] as const;

export const fetchMarkValues = (obraId: number, markId: number): Promise<MarkValues> =>
  apiFetch(`${base(obraId, markId)}/values`);
export const saveMarkValues = (obraId: number, markId: number, changes: ValueChange[]): Promise<MarkValues> =>
  apiFetch(`${base(obraId, markId)}/values`, { method: 'PUT', body: JSON.stringify({ changes }) });
export const fetchMarkHistory = (obraId: number, markId: number): Promise<HistoryEntry[]> =>
  apiFetch(`${base(obraId, markId)}/history`);
