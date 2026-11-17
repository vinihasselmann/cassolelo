import { apiFetch } from './client';

/** Configuração da tela do modelo (GET /api/viewer-config). */
export interface ViewerConfig {
  /** Coordenadas do eixo: ponto de cada tipo de peça (AXIS_Z_RULE). */
  axis_z_rule: { pilar: string; viga: string; laje: string };
}

export const fetchViewerConfig = (): Promise<ViewerConfig> => apiFetch('/viewer-config');
