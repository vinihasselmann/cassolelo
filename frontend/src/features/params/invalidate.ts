import type { QueryClient } from '@tanstack/react-query';

/** Consultas de uma versão que dependem dos valores ou do catálogo da fábrica. */
const VALUE_DEPENDENT = new Set(['search', 'status', 'progress', 'param-values', 'diff', 'filter', 'colorize', 'color-scheme', 'color-scheme-preview']);

/**
 * Depois de gravar valores (marca ou lote), desfazer um lote ou mudar o catálogo:
 * tudo que mostra valores, cores, status ou progresso precisa recarregar.
 */
export function invalidateValueQueries(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ['mark-batch'] }),
    queryClient.invalidateQueries({ queryKey: ['mark-values'] }),
    queryClient.invalidateQueries({ queryKey: ['mark-units'] }),
    queryClient.invalidateQueries({ queryKey: ['unit-batch'] }),
    queryClient.invalidateQueries({ queryKey: ['unit-orphans'] }),
    queryClient.invalidateQueries({ queryKey: ['param-defs'] }),
    queryClient.invalidateQueries({ queryKey: ['orphans'] }),
    queryClient.invalidateQueries({
      predicate: (q) => q.queryKey[0] === 'versions' && VALUE_DEPENDENT.has(String(q.queryKey[2])),
    }),
  ]);
}
