import type { MarkStatus } from '../../api/status';
import { STATUS_LABEL } from './statusLabel';

/**
 * Marca do status: a cor da legenda e também uma forma (anel = pendente, losango = revisar),
 * para não depender só da cor sob luz forte.
 */
export function StatusDot({ status }: { status: MarkStatus }) {
  return <i className={`status-dot status-dot--${status}`} aria-hidden="true" />;
}

/** Selo com marca e texto: cabeçalho do painel da peça. */
export function StatusBadge({ status }: { status: MarkStatus }) {
  return (
    <span className="status-badge" title="Status de produção da marca">
      <StatusDot status={status} />
      {STATUS_LABEL[status]}
    </span>
  );
}
