import type { MarkStatus } from '../../api/status';

/** Rótulos do status de produção (os mesmos da legenda). */
export const STATUS_LABEL: Record<MarkStatus, string> = {
  pending: 'Pendente',
  partial: 'Parcial',
  complete: 'Completa',
  review: 'Revisar',
};
