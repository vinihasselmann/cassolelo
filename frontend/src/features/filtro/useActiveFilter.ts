import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { evaluateFilter, type FilterDefinition } from '../../api/filters';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import {
  decodeFilter,
  encodeFilter,
  isActive,
  toDefinition,
  URL_PARAM,
  type ActiveFilter,
} from './filterModel';

export const FILTER_DEBOUNCE_MS = 250;

/**
 * Estado ÚNICO do filtro da tela, guardado na URL (?f=...): o link abre a mesma vista
 * filtrada. A avaliação espera FILTER_DEBOUNCE_MS sem mudanças (digitação, cliques).
 */
export function useActiveFilter(versionId: number | undefined) {
  const [params, setParams] = useSearchParams();
  const raw = params.get(URL_PARAM);
  const filter = useMemo(() => decodeFilter(raw), [raw]);

  const set = useCallback(
    (next: ActiveFilter) => {
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          const encoded = encodeFilter(next);
          if (encoded === null) out.delete(URL_PARAM);
          else out.set(URL_PARAM, encoded);
          return out;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const definition = useMemo(() => toDefinition(filter), [filter]);
  const active = isActive(filter);
  const key = active ? JSON.stringify(definition) : '';
  const debounced = useDebouncedValue(key, FILTER_DEBOUNCE_MS);

  const evaluation = useQuery({
    queryKey: ['versions', versionId, 'filter', debounced],
    queryFn: () => evaluateFilter(versionId ?? 0, JSON.parse(debounced) as FilterDefinition),
    enabled: versionId !== undefined && debounced !== '',
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  });

  /** O filtro em vigor no 3D e na lista (já passou o debounce). */
  const applied = debounced !== '' && key !== '';
  return {
    filter,
    set,
    clear: () => { set({ q: '', logic: 'and', rules: [], savedId: null }); },
    definition,
    /** Há filtro na tela (mesmo antes do debounce). */
    active,
    applied,
    evaluation: applied ? evaluation : null,
    /** Esperando o debounce ou a resposta. */
    loading: active && (key !== debounced || evaluation.isFetching),
    error: applied && evaluation.isError ? evaluation.error : null,
  };
}

export type ActiveFilterState = ReturnType<typeof useActiveFilter>;
