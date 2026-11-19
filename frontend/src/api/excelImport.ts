import { authFetch, toApiError } from './client';

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

export interface ImportIssue {
  sheet: string;
  /** linha do Excel (1 = cabeçalho) */
  row: number | null;
  column: string | null;
  message: string;
}

export interface ImportChange {
  sheet: string;
  row: number;
  /** marca (PP001) ou peça (PP001-3) */
  target: string;
  category: string;
  param: string;
  old: unknown;
  new: unknown;
}

export interface ImportParamSummary {
  def_id: number;
  name: string;
  level: 'mark' | 'piece';
  fills: number;
  changes: number;
}

export interface ImportPreview {
  obra_code: string;
  file_version: string | null;
  marks_rows: number;
  pieces_rows: number;
  /** campos vazios no app que o arquivo preenche */
  fills: number;
  /** campos já preenchidos que o arquivo traz com outro valor */
  changes: number;
  unchanged: number;
  errors: ImportIssue[];
  warnings: ImportIssue[];
  ignored_columns: string[];
  params: ImportParamSummary[];
  fill_items: ImportChange[];
  change_items: ImportChange[];
  fingerprint: string;
}

export interface ImportApplied {
  batch_id: string | null;
  marks_changed: number;
  units_changed: number;
  fields_changed: number;
  skipped_changes: number;
  errors: number;
}

async function post<T>(path: string, file: File): Promise<T> {
  const res = await authFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': XLSX, Accept: 'application/json' },
    body: file,
  });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

/** Prévia da importação: nada é gravado. */
export const previewImport = (obraId: number, file: File): Promise<ImportPreview> =>
  post(`/obras/${String(obraId)}/import-xlsx/preview`, file);

/** Grava os preenchimentos (e, com `overwrite`, as alterações) num lote só. */
export const applyImport = (
  obraId: number,
  file: File,
  fingerprint: string,
  overwrite: boolean,
): Promise<ImportApplied> => {
  const q = new URLSearchParams({ fingerprint, overwrite: String(overwrite) });
  return post(`/obras/${String(obraId)}/import-xlsx/apply?${q.toString()}`, file);
};
