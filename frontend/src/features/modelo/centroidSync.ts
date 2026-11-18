/**
 * Centros de gravidade das peças: calculados uma vez por versão, com o 3D carregado, e
 * mandados ao servidor (PUT /versions/{id}/centroids). Lá eles numeram as peças pela
 * sequência de montagem (obra com numeração provisória) e alimentam o Excel.
 *
 * Um cálculo por versão para a tela toda: o envio automático (useCentroidSync) e o
 * "Exportar Excel" usam o mesmo, e o progresso aparece nos dois.
 */
import type { QueryClient } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';

import { centroidsKey, putCentroids, type CentroidsResult } from '../../api/centroids';
import { invalidateValueQueries } from '../params/invalidate';
import { piecesCentroids, type GeometrySource } from '../../viewer/coordinates';
import type { DbId, TriangleVisitor, Vec3, ViewerAdapter } from '../../viewer/ViewerAdapter';

export interface SyncProgress {
  done: number;
  total: number;
  /** aguardando a geometria do 3D terminar de chegar */
  waiting?: boolean;
}

export interface SyncState {
  progress: SyncProgress | null;
  /** resposta do servidor (null enquanto calcula, ou se o envio falhou) */
  result: CentroidsResult | null;
  coords: Map<DbId, Vec3> | null;
  error: unknown;
}

interface Job {
  state: SyncState;
  promise: Promise<Map<DbId, Vec3>>;
  controller: AbortController;
}

const jobs = new Map<number, Job>();
const listeners = new Set<() => void>();
const EMPTY: SyncState = { progress: null, result: null, coords: null, error: null };

function set(versionId: number, patch: Partial<SyncState>) {
  const job = jobs.get(versionId);
  if (!job) return;
  job.state = { ...job.state, ...patch };
  listeners.forEach((fn) => { fn(); });
}

export function geometrySource(viewer: ViewerAdapter | null | undefined): GeometrySource | null {
  if (!viewer?.getModelFrame || !viewer.getNodes || !viewer.getTriangles) return null;
  return {
    getModelFrame: () => viewer.getModelFrame?.() ?? null,
    getNodes: (ids) => viewer.getNodes?.(ids) ?? Promise.resolve([]),
    getTriangles: (id) => viewer.getTriangles?.(id) ?? [],
    ...(viewer.getGeometryParts ? { getGeometryParts: (id: DbId) => viewer.getGeometryParts?.(id) ?? [] } : {}),
    ...(viewer.forEachTriangle ? { forEachTriangle: (id: DbId, fn: TriangleVisitor) => { viewer.forEachTriangle?.(id, fn); } } : {}),
  };
}

export function centroidState(versionId: number | null): SyncState {
  return (versionId !== null && jobs.get(versionId)?.state) || EMPTY;
}

/** Já houve (ou há) cálculo para a versão nesta aba? */
export const hasJob = (versionId: number) => jobs.has(versionId);

/**
 * Calcula (ou reaproveita) os centros da versão e manda ao servidor. Devolve as
 * coordenadas. O envio que falha não impede o Excel: as coordenadas vão junto nele.
 */
export function syncCentroids(
  versionId: number,
  viewer: ViewerAdapter,
  source: GeometrySource,
  dbIds: readonly DbId[],
  queryClient: QueryClient,
  obraId: number,
): Promise<Map<DbId, Vec3>> {
  const existing = jobs.get(versionId);
  if (existing && existing.state.error === null) return existing.promise;
  const controller = new AbortController();
  const job: Job = {
    state: { ...EMPTY, progress: { done: 0, total: dbIds.length, waiting: true } },
    controller,
    promise: Promise.resolve(new Map<DbId, Vec3>()),
  };
  jobs.set(versionId, job);
  listeners.forEach((fn) => { fn(); });
  job.promise = (async () => {
    try {
      await viewer.whenGeometryLoaded?.(); // SVF2: sem isso, peças ainda sem triângulos
      set(versionId, { progress: { done: 0, total: dbIds.length } });
      const coords = await piecesCentroids(source, dbIds, {
        signal: controller.signal,
        onProgress: (p) => { set(versionId, { progress: p }); },
      });
      set(versionId, { coords, progress: null });
      try {
        const result = await putCentroids(versionId, coords);
        set(versionId, { result });
        queryClient.setQueryData(centroidsKey(versionId), {
          pieces: result.pieces,
          stored: result.stored,
          numbering: result.numbering,
        });
        if (result.renumbered > 0 || result.relinked) {
          void queryClient.invalidateQueries({ queryKey: ['obras', obraId] });
          void invalidateValueQueries(queryClient);
        }
      } catch (err) {
        console.warn('Centros de gravidade não enviados ao servidor', err);
      }
      return coords;
    } catch (err) {
      set(versionId, { progress: null, error: err });
      throw err;
    }
  })();
  return job.promise;
}

export function cancelCentroids(versionId: number) {
  jobs.get(versionId)?.controller.abort();
}

/** Estado do cálculo da versão (progresso e resposta), para a tela. */
export function useCentroidState(versionId: number | null): SyncState {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => { listeners.delete(fn); };
    },
    () => centroidState(versionId),
  );
}

/** Testes: esquece os cálculos feitos. */
export function resetCentroidJobs() {
  jobs.clear();
  listeners.forEach((fn) => { fn(); });
}
