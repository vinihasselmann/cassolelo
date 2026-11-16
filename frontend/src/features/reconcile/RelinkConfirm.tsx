import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '../../api/client';
import { relinkOrphan, type Orphan, type RelinkConflict, type RelinkResult } from '../../api/reconcile';
import type { MarkPieces } from '../../api/versions';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { formatValue } from '../../lib/format';
import { invalidateValueQueries } from '../params/invalidate';
import { describeValues } from './orphanText';

interface Props {
  orphan: Orphan;
  target: MarkPieces;
  onCancel: () => void;
  onDone: (result: RelinkResult) => void;
}

/** Confirmação do religar: origem → destino, valores copiados; conflito pede sobrescrever. */
export function RelinkConfirm({ orphan, target, onCancel, onDone }: Props) {
  const queryClient = useQueryClient();
  const relink = useMutation({
    mutationFn: (overwrite: boolean) => relinkOrphan(orphan.id, target.mark_id, overwrite),
    onSuccess: async (result) => {
      await invalidateValueQueries(queryClient);
      onDone(result);
    },
  });
  const conflict =
    relink.error instanceof ApiError && relink.error.status === 409 && relink.error.code === 'relink_conflict'
      ? (relink.error.body as unknown as RelinkConflict)
      : null;

  return (
    <Modal title="Religar órfã" onClose={onCancel}>
      <p>
        Religar <b>{orphan.code}</b> ({orphan.category}) → <b>{target.code}</b> ({target.category})?
      </p>
      <p className="small">Valores copiados: {describeValues(orphan)}</p>
      {target.category !== orphan.category && (
        <p className="hint">Categorias diferentes: parâmetros que não valem para {target.category} ficam só na marca antiga.</p>
      )}
      {conflict ? (
        <div className="alert alert--warn" role="alert">
          <b>{target.code}</b> já tem outro valor em:
          <ul>
            {conflict.conflicts.map((c) => (
              <li key={c.def_id}>
                {c.name}: {formatValue(c.target_value)} (órfã: {formatValue(c.orphan_value)})
              </li>
            ))}
          </ul>
        </div>
      ) : (
        relink.isError && <p role="alert" className="error">{errorMessage(relink.error)}</p>
      )}
      <div className="actions">
        <button type="button" disabled={relink.isPending} onClick={() => { relink.mutate(conflict !== null); }}>
          {conflict ? 'Sobrescrever e religar' : 'Religar'}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </Modal>
  );
}
