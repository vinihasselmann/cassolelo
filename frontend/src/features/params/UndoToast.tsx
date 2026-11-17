import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { undoBatch } from '../../api/markBatch';
import { errorMessage } from '../../lib/errors';
import { invalidateValueQueries } from './invalidate';
import { Icon } from '../../components/Icon';

export const UNDO_SECONDS = 10;

interface Props {
  batchId: string;
  text: string;
  onClose: () => void;
}

/** Aviso depois de uma edição em lote, com "Desfazer" por 10 s. */
export function UndoToast({ batchId, text, onClose }: Props) {
  const queryClient = useQueryClient();
  const undo = useMutation({
    mutationFn: () => undoBatch(batchId),
    onSuccess: () => invalidateValueQueries(queryClient),
  });

  // Some sozinho: 10 s para desfazer; depois de desfeito (ou com erro), alguns segundos.
  const settled = undo.isSuccess || undo.isError;
  useEffect(() => {
    if (undo.isPending) return;
    const timer = window.setTimeout(onClose, (settled ? 4 : UNDO_SECONDS) * 1000);
    return () => { window.clearTimeout(timer); };
  }, [batchId, settled, undo.isPending, onClose]);

  return (
    <div className="toast" role="status">
      {undo.isSuccess ? (
        <span>Edição em lote desfeita.</span>
      ) : undo.isError ? (
        <span className="error">{errorMessage(undo.error)}</span>
      ) : (
        <>
          <span>{text}</span>
          <button type="button" className="link" disabled={undo.isPending} onClick={() => { undo.mutate(); }}>
            {undo.isPending ? 'Desfazendo…' : 'Desfazer'}
          </button>
        </>
      )}
      <button type="button" className="link toast__close" aria-label="Fechar aviso" onClick={onClose}>
        <Icon name="close" />
      </button>
    </div>
  );
}
