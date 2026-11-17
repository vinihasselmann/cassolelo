import { apiFetch } from './client';
import type { ParamType } from './paramDefs';

export type ChangeKind = 'unchanged' | 'count_changed' | 'changed' | 'new' | 'removed';

export interface DiffMark {
  mark_id: number | null;
  code: string;
  category: string;
  change: ChangeKind;
  prev_count: number;
  curr_count: number;
  diffs: { property: string; before: string | null; after: string | null }[];
  note: string | null;
  has_values: boolean;
  action: 'review' | 'orphan' | 'returned' | null;
}

export interface VersionDiff {
  version_id: number;
  version_number: number;
  prev_version_id: number | null;
  prev_version_number: number | null;
  totals: Record<ChangeKind, number>;
  review: number;
  orphans: number;
  returned: number;
  review_open: number;
  orphans_open: number;
  review_properties: string[];
  marks: DiffMark[];
  /** Parâmetros por peça (P5): unidades que perderam a peça (com valores), novas, que voltaram. */
  units?: UnitDiff;
}

export interface UnitDiff {
  lost: number;
  new: number;
  returned: number;
  by_order: number;
  lost_units: { unit_id: number; label: string }[];
  new_units: { unit_id: number; label: string }[];
  orphans_open: number;
}

export type OrphanStatus = 'open' | 'relinked' | 'archived' | 'returned';

export interface Orphan {
  id: number;
  status: OrphanStatus;
  mark_id: number;
  code: string;
  category: string;
  since_version_id: number;
  since_version_number: number;
  relinked_to: number | null;
  relinked_to_code: string | null;
  created_at: string;
  updated_at: string;
  values: { def_id: number; name: string; type: ParamType; value: unknown }[];
}

export interface RelinkResult {
  orphan_id: number;
  target_mark_id: number;
  copied: string[];
  skipped: string[];
  batch_id: string;
}

/** Corpo do 409 `relink_conflict`. */
export interface RelinkConflict {
  conflicts: { def_id: number; name: string; orphan_value: unknown; target_value: unknown }[];
}

export const diffKey = (versionId: number) => ['versions', versionId, 'diff'] as const;
export const orphansKey = (obraId: number) => ['orphans', obraId] as const;

export const fetchDiff = (versionId: number): Promise<VersionDiff> => apiFetch(`/versions/${versionId}/diff`);
export const keepValues = (markId: number): Promise<unknown> =>
  apiFetch(`/marks/${markId}/review/keep`, { method: 'POST' });
export const fetchOrphans = (obraId: number): Promise<Orphan[]> => apiFetch(`/obras/${obraId}/orphans`);
export const relinkOrphan = (orphanId: number, targetMarkId: number, overwrite = false): Promise<RelinkResult> =>
  apiFetch(`/orphans/${orphanId}/relink`, {
    method: 'POST',
    body: JSON.stringify({ target_mark_id: targetMarkId, overwrite }),
  });
export const archiveOrphan = (orphanId: number): Promise<unknown> =>
  apiFetch(`/orphans/${orphanId}/archive`, { method: 'POST' });
