import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { centroidsKey, fetchCentroidStatus, type CentroidStatus } from '../../api/centroids';
import type { DbId, ViewerAdapter } from '../../viewer/ViewerAdapter';
import { geometrySource, hasJob, syncCentroids, useCentroidState, type SyncState } from './centroidSync';

interface Options {
  obraId: number;
  versionId: number | null;
  viewer: ViewerAdapter | null;
  modelReady: boolean;
  pieceDbIds: readonly DbId[];
}

/**
 * Com o 3D carregado, manda ao servidor os centros de gravidade das peças que ele ainda
 * não tem (uma vez por versão, em segundo plano). Na obra com numeração provisória, é isso
 * que numera as peças pela sequência de montagem (Z → X → Y).
 */
export function useCentroidSync({ obraId, versionId, viewer, modelReady, pieceDbIds }: Options): {
  status: CentroidStatus | undefined;
  state: SyncState;
} {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: centroidsKey(versionId ?? 0),
    queryFn: () => fetchCentroidStatus(versionId ?? 0),
    enabled: versionId !== null,
    retry: false,
  });
  const state = useCentroidState(versionId);
  const missing = status.data !== undefined && status.data.pieces > 0 && status.data.stored < status.data.pieces;

  useEffect(() => {
    if (versionId === null || !modelReady || !missing || !viewer || pieceDbIds.length === 0) return;
    if (hasJob(versionId)) return; // já calculado (ou cancelado) nesta aba
    const source = geometrySource(viewer);
    if (!source) return;
    syncCentroids(versionId, viewer, source, pieceDbIds, queryClient, obraId).catch(() => {
      // cancelado ou falhou: o Excel pode tentar de novo; a tela segue normal
    });
  }, [versionId, modelReady, missing, viewer, pieceDbIds, queryClient, obraId]);

  return { status: status.data, state };
}
