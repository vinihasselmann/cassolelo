import { apiFetch } from './client';
import type { UnitNumbering } from './obras';

/** Centros de gravidade guardados no servidor para a versão (2026-11-18). */
export interface CentroidStatus {
  pieces: number;
  stored: number;
  numbering: UnitNumbering;
}

export interface CentroidsResult extends CentroidStatus {
  /** unidades que mudaram de número (sequência de montagem) */
  renumbered: number;
  /** ligações pela ordem refeitas pela sequência */
  relinked: boolean;
}

export const centroidsKey = (versionId: number) => ['versions', versionId, 'centroids'] as const;

export function fetchCentroidStatus(versionId: number): Promise<CentroidStatus> {
  return apiFetch(`/versions/${String(versionId)}/centroids`);
}

/** Limite do servidor (Coord em app/api/schemas.py): ±1.000 km. */
export const MAX_COORD_M = 1e6;

/**
 * metros com 4 casas (0,1 mm): o Excel mostra 3; corpo menor. Coordenada que não é
 * número finito ou passa de ±1.000 km fica de fora (a peça sai sem coordenada, no fim do
 * Excel), para uma peça estranha não fazer o servidor recusar todas (2026-11-19).
 */
export function roundedCoordinates(
  coordinates: ReadonlyMap<number, readonly [number, number, number]>,
): Record<string, number[]> {
  return Object.fromEntries(
    [...coordinates]
      .filter(([, xyz]) => xyz.every((v) => Number.isFinite(v) && Math.abs(v) <= MAX_COORD_M))
      .map(([id, xyz]) => [id, xyz.map((v) => Math.round(v * 1e4) / 1e4)]),
  );
}

export function putCentroids(
  versionId: number,
  coordinates: ReadonlyMap<number, readonly [number, number, number]>,
): Promise<CentroidsResult> {
  return apiFetch(`/versions/${String(versionId)}/centroids`, {
    method: 'PUT',
    body: JSON.stringify({ coordinates: roundedCoordinates(coordinates) }),
  });
}
