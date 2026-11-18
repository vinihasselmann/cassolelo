import { useMutation, useQueryClient } from '@tanstack/react-query';

import { downloadObraExcel } from '../../api/export';
import type { FilterDefinition } from '../../api/filters';
import { errorMessage } from '../../lib/errors';
import type { DbId, ViewerAdapter } from '../../viewer/ViewerAdapter';
import { cancelCentroids, centroidState, geometrySource, syncCentroids, useCentroidState } from './centroidSync';

interface Props {
  obraId: number;
  versionId: number;
  /** Filtro da tela (null = sem filtro): o Excel traz só o resultado, como a lista. */
  filter: FilterDefinition | null;
  /** Visualizador com o modelo carregado: calcula o centro de gravidade das peças. */
  viewer?: ViewerAdapter | null;
  modelReady?: boolean;
  /** dbIds das peças da versão (todas as marcas). */
  pieceDbIds?: readonly DbId[];
  /** O servidor já tem o centro de todas as peças da versão: não recalcula. */
  centroidsStored?: boolean;
}

const num = (n: number) => n.toLocaleString('pt-BR');

/**
 * "Exportar Excel": as marcas da lista (versão aberta + filtro ativo) e as peças. Com o
 * modelo carregado, calcula antes o centro de gravidade de cada peça (colunas X/Y/Z e
 * sequência de montagem X → Y → Z), se o servidor ainda não o tem. O cálculo é o mesmo da
 * numeração das peças (centroidSync): feito uma vez por versão.
 */
export function ExportButton({
  obraId,
  versionId,
  filter,
  viewer = null,
  modelReady = false,
  pieceDbIds = [],
  centroidsStored = false,
}: Props) {
  const queryClient = useQueryClient();
  const sync = useCentroidState(versionId);

  const exporter = useMutation({
    mutationFn: async () => {
      let coords = centroidState(versionId).coords;
      const source = modelReady ? geometrySource(viewer) : null;
      if (!coords && !centroidsStored && source && viewer && pieceDbIds.length > 0) {
        coords = await syncCentroids(versionId, viewer, source, pieceDbIds, queryClient, obraId);
      }
      // sem coordenadas aqui, o servidor usa os centros que já tem
      return downloadObraExcel(obraId, versionId, filter, coords);
    },
  });
  const progress = exporter.isPending ? sync.progress : null;
  const filtered = filter !== null;
  const cancelled = exporter.error instanceof DOMException && exporter.error.name === 'AbortError';
  return (
    <span className="export">
      <button
        type="button"
        className="secondary"
        disabled={exporter.isPending}
        title={filtered ? 'Exporta só as marcas da lista (filtro ativo)' : 'Exporta todas as marcas da versão aberta'}
        onClick={() => { exporter.mutate(); }}
      >
        {exporter.isPending ? 'Gerando…' : 'Exportar Excel'}
      </button>
      {progress && (
        <>
          <span className="hint" role="status">
            {progress.waiting
              ? 'Aguardando o modelo terminar de carregar…'
              : `Calculando coordenadas ${num(progress.done)}/${num(progress.total)}…`}
          </span>
          <button type="button" className="link" onClick={() => { cancelCentroids(versionId); }}>
            Cancelar
          </button>
        </>
      )}
      {filtered && !progress && <span className="hint">com o filtro ativo</span>}
      {exporter.isError && !cancelled && (
        <span role="alert" className="error small">
          {errorMessage(exporter.error)}
        </span>
      )}
    </span>
  );
}
