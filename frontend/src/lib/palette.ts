/**
 * Cores que o código JS precisa em hex (o Viewer pinta o 3D com elas).
 * São as mesmas de styles/tokens.css (--status-*, --selection); palette.test.ts
 * garante que os dois lugares batem. Mudou aqui, mude lá.
 */

/** Status de produção, sempre nesta ordem (mesmo com zero peças). */
export const STATUS_ORDER = ['Pendente', 'Parcial', 'Completa', 'Revisar'] as const;
export type ProductionStatus = (typeof STATUS_ORDER)[number];

export const STATUS_COLORS: Record<ProductionStatus, string> = {
  Pendente: '#B9BEC6',
  Parcial: '#E3B341',
  Completa: '#33A06F',
  Revisar: '#E8743B',
};

/** Nome do token CSS de cada status (para a legenda e testes). */
export const STATUS_TOKENS: Record<ProductionStatus, string> = {
  Pendente: '--status-pending',
  Parcial: '--status-partial',
  Completa: '--status-complete',
  Revisar: '--status-review',
};

/** Cor da seleção no 3D (token --selection): grafite do logo, distinta de todos os status. */
export const SELECTION_COLOR = '#3C3C3C';
