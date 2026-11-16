import { apiFetch } from './client';
import type { VersionStatus } from './obras';

export interface PieceWithoutMark {
  dbid: number;
  external_id: string | null;
  category: string;
  name: string | null;
}

export interface DimensionValue {
  value: string;
  mm: number | null;
  count: number;
  dbids: number[];
}

export interface DimensionDifference {
  property: string;
  diff_mm: number | null; // null = valores não numéricos (comparados como texto)
  values: DimensionValue[];
}

export interface InconsistentMark {
  mark: string;
  category: string;
  pieces: number;
  differences: DimensionDifference[];
}

export interface CategoryTotals {
  category: string;
  pieces: number;
  marks: number;
  without_mark: number;
}

export interface ValidationReport {
  version_id: number;
  generated_at: string;
  config: { dimension_property_names: string[]; tolerance_mm: number };
  totals: {
    pieces: number;
    marks: number;
    without_mark: number;
    inconsistent_marks: number;
    /** relatórios antigos não têm (versões processadas antes de 2026-11-13) */
    divergent_pieces?: number;
    by_category: CategoryTotals[];
  };
  without_mark: PieceWithoutMark[];
  inconsistent: InconsistentMark[];
  divergent?: DivergentPiece[];
}

/** Peça cujos parâmetros de identificação discordam (vale o primeiro da regra). */
export interface DivergentPiece {
  dbid: number;
  external_id: string | null;
  category: string;
  name: string | null;
  mark: string | null;
  values: { property: string; value: string }[];
}

export interface VersionReportResponse {
  version_id: number;
  status: VersionStatus;
  updated_at: string;
  report: ValidationReport;
}

export const fetchVersionReport = (versionId: number): Promise<VersionReportResponse> =>
  apiFetch(`/versions/${versionId}/report`);

/** Marca de uma versão com as peças (dbIds do Viewer). */
export interface MarkPieces {
  mark_id: number;
  code: string;
  category: string;
  count: number;
  dbids: number[];
  /** membros das peças (consolos, geometria): um clique neles acha a marca */
  member_dbids?: number[];
}

export interface ModelProperty {
  name: string;
  value: unknown;
}

export interface PropertyGroup {
  name: string;
  properties: ModelProperty[];
}

export interface ElementDetail {
  dbid: number;
  external_id: string | null;
  name: string | null;
  category: string | null;
  mark_raw: string | null;
  mark: MarkPieces | null;
  groups: PropertyGroup[];
}

export const fetchMarks = (versionId: number): Promise<MarkPieces[]> =>
  apiFetch(`/versions/${versionId}/marks`);
export const fetchElement = (versionId: number, dbid: number): Promise<ElementDetail> =>
  apiFetch(`/versions/${versionId}/elements/${dbid}`);

export interface FacetValue {
  value: string;
  pieces: number;
}

export interface MarkFacets {
  categories: FacetValue[];
  levels: FacetValue[];
  pieces_without_level: number;
}

export const fetchFacets = (versionId: number): Promise<MarkFacets> =>
  apiFetch(`/versions/${versionId}/marks/facets`);
