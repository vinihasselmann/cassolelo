import type { QueryClient } from '@tanstack/react-query';

/**
 * Consultas de uma versão que dependem dos valores ou do catálogo da fábrica. `fields` =
 * campos do Filtro e do Colorir (parâmetro novo aparece em "Fábrica" sem recarregar a
 * página; contagens de valores mudam ao gravar). Correção de 2026-11-18.
 */
const VALUE_DEPENDENT = new Set(['search', 'status', 'progress', 'param-values', 'diff', 'filter', 'colorize', 'color-scheme', 'color-scheme-preview', 'fields']);

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
