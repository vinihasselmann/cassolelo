import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { colorize, evaluateScheme } from '../../api/colors';
import type { DbId } from '../../viewer/ViewerAdapter';
import { fromColorize, fromScheme, type Coloring, type ColoringChoice } from './coloringModel';

/** Cores e legenda da escolha atual (null = sem coloração), calculadas no backend. */
export function useModelColoring(
  versionId: number | null,
  choice: ColoringChoice | null,
  markOf: (dbid: DbId) => number | undefined,
): { coloring: Coloring | null; error: unknown; loading: boolean } {
  const field = choice?.kind === 'field' ? choice : null;
  const scheme = choice?.kind === 'scheme' ? choice : null;
  const byField = useQuery({
    queryKey: ['versions', versionId, 'colorize', field?.field.source, field?.field.key, field?.mode],
    queryFn: () => (field ? colorize(versionId ?? 0, field.field, field.mode) : Promise.reject(new Error('sem campo'))),
    enabled: versionId !== null && field !== null,
    retry: false,
    staleTime: 30_000,
  });
  const byScheme = useQuery({
    queryKey: ['versions', versionId, 'color-scheme', scheme?.schemeId],
    queryFn: () => evaluateScheme(versionId ?? 0, { scheme_id: scheme?.schemeId ?? 0 }),
    enabled: versionId !== null && scheme !== null,
    retry: false,
    staleTime: 30_000,
  });

  const coloring = useMemo((): Coloring | null => {
    if (field && byField.data) return fromColorize(byField.data, field.field, markOf);
    if (scheme && byScheme.data) return fromScheme(byScheme.data, scheme.name, markOf);
    return null;
  }, [field, scheme, byField.data, byScheme.data, markOf]);

  const active = field ? byField : scheme ? byScheme : null;
  return { coloring, error: active?.error ?? null, loading: active?.isFetching ?? false };
}
