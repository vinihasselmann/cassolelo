import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { ApiError } from '../../api/client';
import { fetchViewerConfig } from '../../api/viewerConfig';
import { errorMessage } from '../../lib/errors';
import { DEFAULT_AXIS_Z_RULE, pieceCoordinates, type AxisCoordinates, type AxisZRule, type GeometrySource } from '../../viewer/coordinates';
import type { DbId, ViewerAdapter } from '../../viewer/ViewerAdapter';

export type AxisState =
  | { status: 'unavailable' } // adapter sem geometria (ex.: testes)
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: AxisCoordinates }
  | { status: 'error'; message: string };

function geometrySource(viewer: ViewerAdapter | null): GeometrySource | null {
  if (!viewer?.getModelFrame || !viewer.getNodes || !viewer.getTriangles) return null;
  return {
    getModelFrame: () => viewer.getModelFrame?.() ?? null,
    getNodes: (ids) => viewer.getNodes?.(ids) ?? Promise.resolve([]),
    getTriangles: (id) => viewer.getTriangles?.(id) ?? [],
  };
}

/**
 * Coordenadas do eixo da INSTÂNCIA clicada (cada peça física tem a sua), mesmo que a
 * seleção destaque a marca inteira; e o marcador no 3D enquanto ela estiver selecionada.
 */
export function useAxisCoordinates(viewer: ViewerAdapter | null, dbId: DbId | null, modelReady: boolean): AxisState {
  const config = useQuery({ queryKey: ['viewer-config'], queryFn: fetchViewerConfig, staleTime: Infinity, retry: false });
  const rules: AxisZRule | null = config.data
    ? { ...DEFAULT_AXIS_Z_RULE, ...config.data.axis_z_rule }
    : config.isError
      ? DEFAULT_AXIS_Z_RULE
      : null;
  const ruleKey = rules ? `${rules.pilar}|${rules.viga}|${rules.laje}` : '';
  const source = geometrySource(viewer);
  const [state, setState] = useState<AxisState>({ status: 'idle' });

  useEffect(() => {
    if (!source) return;
    if (dbId === null || !modelReady || !rules) {
      setState({ status: 'idle' });
      viewer?.showAxisMarker?.(null);
      return;
    }
    let current = true;
    setState({ status: 'loading' });
    pieceCoordinates(source, dbId, rules).then(
      (data) => {
        if (!current) return;
        setState({ status: 'ready', data });
        viewer?.showAxisMarker?.(data.marker);
      },
      (err: unknown) => {
        if (!current) return;
        // erros do cálculo já vêm em português ("A peça não tem geometria…")
        setState({ status: 'error', message: err instanceof Error && !(err instanceof ApiError) ? err.message : errorMessage(err) });
        viewer?.showAxisMarker?.(null);
      },
    );
    return () => { current = false; };
    // as regras entram pela chave (o objeto muda a cada render)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, dbId, modelReady, ruleKey]);

  // Saiu da tela: apaga o marcador.
  useEffect(() => () => { viewer?.showAxisMarker?.(null); }, [viewer]);

  return source ? state : { status: 'unavailable' };
}
