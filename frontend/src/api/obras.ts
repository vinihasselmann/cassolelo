import { apiFetch } from './client';

export interface Obra {
  id: number;
  code: string;
  name: string;
  acc_hub_id: string | null;
  acc_project_id: string | null;
  acc_folder_id: string | null;
  acc_item_id: string | null;
  acc_item_name: string | null;
  active: boolean;
  /** "deleted"/"missing": arquivo excluído no Docs; a obra fica bloqueada (só editar/excluir). */
  acc_file_state: AccFileState;
  acc_file_state_at: string | null;
  created_at: string;
  updated_at: string;
}

export type AccFileState = 'ok' | 'deleted' | 'missing';

export const isFileBlocked = (o: Pick<Obra, 'acc_file_state'>): boolean => o.acc_file_state !== 'ok';

export const FILE_STATE_LABELS: Record<Exclude<AccFileState, 'ok'>, string> = {
  deleted: 'Arquivo excluído no Docs',
  missing: 'Arquivo não encontrado no Docs',
};

export const BLOCKED_MESSAGE: Record<Exclude<AccFileState, 'ok'>, string> = {
  deleted:
    'O arquivo desta obra foi excluído do Autodesk Docs. A obra fica bloqueada: só é possível editá-la ou excluí-la na lista de obras. Se o arquivo for restaurado no Docs, ela é liberada.',
  missing:
    'O arquivo desta obra não foi encontrado no Autodesk Docs. A obra fica bloqueada: só é possível editá-la ou excluí-la na lista de obras.',
};

export interface AccLink {
  hub_id: string;
  project_id: string;
  folder_id: string;
  item_id: string;
}

export interface ObraCreate {
  code: string;
  name: string;
  acc: AccLink;
}

export type VersionStatus =
  | 'pending'
  | 'translating'
  | 'processing'
  | 'ready'
  | 'failed'
  | 'no_translation'
  | 'deleted';

export const VERSION_STATUS_LABELS: Record<VersionStatus, string> = {
  pending: 'Aguardando processamento',
  translating: 'Convertendo no Docs',
  processing: 'Processando',
  ready: 'Pronta',
  failed: 'Falhou',
  no_translation: 'Sem conversão no Docs',
  deleted: 'Excluída no Docs',
};

export const NO_TRANSLATION_MESSAGE =
  'Este arquivo não foi convertido pelo Docs. Abra-o no Autodesk Docs e inicie o processamento, ou publique pelo site do Docs ou pela publicação em nuvem do Revit.';

export interface ModelVersion {
  id: number;
  version_number: number;
  status: VersionStatus;
  published_by: string | null;
  published_at: string | null;
  comment: string | null;
  error: string | null;
  has_urn: boolean;
  urn: string | null;
}

export interface SyncResult {
  total_in_docs: number;
  created: number;
  ready: number;
  translating: number;
  no_translation: number;
  failed: number;
  enqueued: number;
  enqueue_failed: number;
  deleted: number;
  file_state: AccFileState;
}

export const fetchObras = (): Promise<Obra[]> => apiFetch('/obras');
export const fetchObra = (id: number): Promise<Obra> => apiFetch(`/obras/${id}`);
export const createObra = (body: ObraCreate): Promise<Obra> =>
  apiFetch('/obras', { method: 'POST', body: JSON.stringify(body) });
export const fetchVersions = (obraId: number): Promise<ModelVersion[]> =>
  apiFetch(`/obras/${obraId}/versions`);
export const syncVersions = (obraId: number): Promise<SyncResult> =>
  apiFetch(`/obras/${obraId}/sync`, { method: 'POST' });

export interface ObraUpdate {
  code?: string;
  name?: string;
}

/** O que some junto com a obra. Com valores preenchidos, só o admin exclui. */
export interface DeletePreview {
  versions: number;
  marks: number;
  units: number;
  filled_values: number;
  admin_only: boolean;
}

export const updateObra = (id: number, body: ObraUpdate): Promise<Obra> =>
  apiFetch(`/obras/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
export const fetchDeletePreview = (id: number): Promise<DeletePreview> =>
  apiFetch(`/obras/${id}/delete-preview`);
export const deleteObra = (id: number): Promise<DeletePreview> =>
  apiFetch(`/obras/${id}`, { method: 'DELETE' });
