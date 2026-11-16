import { useQuery } from '@tanstack/react-query';

import { fetchFieldValues, type FilterField } from '../../api/filters';
import { useDebouncedValue } from '../../lib/useDebouncedValue';

/** Valores do campo para autocompletar (mais comuns primeiro), com o nº de peças. */
export function useFieldValues(versionId: number, field: FilterField | undefined, q: string, enabled = true) {
  const debounced = useDebouncedValue(q, 200);
  return useQuery({
    queryKey: ['versions', versionId, 'field-values', field?.source, field?.key, debounced],
    queryFn: () => (field ? fetchFieldValues(versionId, field, debounced) : Promise.resolve([])),
    enabled: enabled && field !== undefined && field.type !== 'bool',
    retry: false,
    staleTime: 60_000,
  });
}
