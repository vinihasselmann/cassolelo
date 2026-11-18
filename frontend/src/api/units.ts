/** Parâmetros POR PEÇA (P2/P4): unidades de peça da marca, valores, lote e histórico. */

import { apiFetch } from './client';
import type { BatchMode } from './markBatch';
import type { ParamType } from './paramDefs';

export interface PieceParam {
  def_id: number;
  name: string;
  type: ParamType;
  unit: string | null;
  required: boolean;
  options: string[] | null;
}

export interface UnitValue {
  def_id: number;
  value: unknown;
  row_version: number | null; // devolver no PUT (null = ainda não havia valor)
  updated_at: string | null;
  updated_by_name: string | null;
}

export type UnitStatus = 'linked' | 'unlinked' | 'orphan';

export interface LinkedElement {
  element_id: number;
  dbid: number;
  external_id: string | null;
  level: string | null;
  name: string | null;
  method: 'key' | 'order' | 'new'; // "order" = ligada pela ordem: conferir
}

export interface PieceUnit {
  id: number;
  number: number;
  label: string; // PP001-3
  status: UnitStatus;
  external_id: string | null;
  since_version_id: number | null;
  /** Peça do modelo na versão aberta (null = a unidade não tem peça nesta versão). */
  element: LinkedElement | null;
  values: UnitValue[];
}

export interface MarkUnits {
  mark: { id: number; code: string; category: string };
  version_id: number | null;
  params: PieceParam[];
  units: PieceUnit[];
}

export interface UnitDetail {
  mark: MarkUnits['mark'];
  params: PieceParam[];
  unit: PieceUnit;
}

export interface UnitChange {
  def_id: number;
  value: unknown;
  row_version: number | null;
}

export interface UnitBatchRequest {
  unit_ids: number[];
  changes: Record<number, unknown>;
  mode: BatchMode;
}

export interface UnitBatchField extends PieceParam {
  applies_to: number;
  filled: number;
  mixed: boolean;
  common_value: unknown;
}

export interface UnitBatchPreview {
  units: number;
  marks: number;
  categories: string[];
  fields: UnitBatchField[];
  units_to_change: number;
  units_to_change_overwrite: number;
  units_to_change_only_empty: number;
  units_with_other_value: number;
}

export interface UnitBatchResult {
  batch_id: string | null; // null = nada mudou
  units_changed: number;
  fields_changed: number;
}

export const markUnitsKey = (obraId: number, markId: number, versionId: number) =>
  ['mark-units', obraId, markId, versionId] as const;

export const fetchMarkUnits = (obraId: number, markId: number, versionId: number): Promise<MarkUnits> =>
  apiFetch(`/obras/${obraId}/marks/${markId}/units?version_id=${versionId}`);
export const saveUnitValues = (
  obraId: number,
  unitId: number,
  changes: UnitChange[],
  versionId: number,
): Promise<UnitDetail> =>
  apiFetch(`/obras/${obraId}/units/${unitId}/values?version_id=${versionId}`, {
    method: 'PUT',
    body: JSON.stringify({ changes }),
  });
export const previewUnitBatch = (obraId: number, body: UnitBatchRequest): Promise<UnitBatchPreview> =>
  apiFetch(`/obras/${obraId}/units/batch-preview`, { method: 'POST', body: JSON.stringify(body) });
export const applyUnitBatch = (obraId: number, body: UnitBatchRequest): Promise<UnitBatchResult> =>
  apiFetch(`/obras/${obraId}/units/batch-apply`, { method: 'POST', body: JSON.stringify(body) });

/** Peça (unidade) de uma das marcas selecionadas, ligada na versão aberta. */
export interface MarkUnit {
  unit_id: number;
  label: string;
  mark_id: number;
}

/** Peças das marcas ligadas na versão (sem órfãs): lote por peça com várias marcas. */
export const fetchUnitsOfMarks = (obraId: number, versionId: number, markIds: number[]): Promise<MarkUnit[]> =>
  apiFetch(`/obras/${String(obraId)}/units/of-marks`, {
    method: 'POST',
    body: JSON.stringify({ version_id: versionId, mark_ids: markIds }),
  });

// ------------------------------------------------------------------ unidades órfãs (P5)

export interface UnitOrphan {
  id: number;
  number: number;
  label: string;
  status: 'orphan' | 'archived';
  mark_id: number;
  code: string;
  category: string;
  external_id: string | null;
  since_version_id: number | null;
  since_version_number: number | null;
  /** A marca tem peças na versão ativa (dá para religar). */
  mark_in_model: boolean;
  updated_at: string;
  values: { def_id: number; name: string; type: ParamType; value: unknown }[];
}

export interface UnitRelinkResult {
  unit_id: number;
  label: string;
  element_id: number;
  dbid: number;
  displaced_unit_id: number;
  displaced_label: string;
  displaced_status: 'unlinked' | 'orphan';
}

export const unitOrphansKey = (obraId: number) => ['unit-orphans', obraId] as const;

export const fetchUnitOrphans = (obraId: number): Promise<UnitOrphan[]> => apiFetch(`/obras/${obraId}/unit-orphans`);
export const relinkUnit = (
  obraId: number,
  unitId: number,
  targetUnitId: number,
  confirm = false,
): Promise<UnitRelinkResult> =>
  apiFetch(`/obras/${obraId}/units/${unitId}/relink`, {
    method: 'POST',
    body: JSON.stringify({ target_unit_id: targetUnitId, confirm }),
  });
export const archiveUnit = (obraId: number, unitId: number): Promise<unknown> =>
  apiFetch(`/obras/${obraId}/units/${unitId}/archive`, { method: 'POST' });
