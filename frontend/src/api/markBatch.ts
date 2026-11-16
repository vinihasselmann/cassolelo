import { apiFetch } from './client';
import type { ParamType } from './paramDefs';

export type BatchMode = 'overwrite' | 'only_empty';

export interface BatchField {
  def_id: number;
  name: string;
  type: ParamType;
  unit: string | null;
  required: boolean;
  options: string[] | null;
  applies_to: number; // marcas da seleção em que o parâmetro vale
  filled: number;
  mixed: boolean;
  common_value: unknown; // quando não é misto (null = todas vazias)
}

export interface BatchChangePreview {
  def_id: number;
  applies_to: number;
  to_change: number;
  other_value: number;
}

export interface BatchPreview {
  marks: number;
  categories: string[];
  fields: BatchField[];
  changes: BatchChangePreview[];
  marks_to_change: number;
  marks_to_change_overwrite: number;
  marks_to_change_only_empty: number;
  marks_with_other_value: number;
}

export interface BatchRequest {
  mark_ids: number[];
  changes: Record<number, unknown>;
  mode: BatchMode;
}

export interface BatchApplyResult {
  batch_id: string | null; // null = nada mudou
  marks_changed: number;
  fields_changed: number;
}

export interface UndoResult {
  batch_id: string;
  restored: number;
}

export const markBatchKey = (obraId: number, markIds: readonly number[]) =>
  ['mark-batch', obraId, [...markIds].sort((a, b) => a - b).join(',')] as const;

export const previewBatch = (obraId: number, body: BatchRequest): Promise<BatchPreview> =>
  apiFetch(`/obras/${obraId}/marks/batch-preview`, { method: 'POST', body: JSON.stringify(body) });
export const applyBatch = (obraId: number, body: BatchRequest): Promise<BatchApplyResult> =>
  apiFetch(`/obras/${obraId}/marks/batch-apply`, { method: 'POST', body: JSON.stringify(body) });
export const undoBatch = (batchId: string): Promise<UndoResult> =>
  apiFetch(`/batches/${batchId}/undo`, { method: 'POST' });
