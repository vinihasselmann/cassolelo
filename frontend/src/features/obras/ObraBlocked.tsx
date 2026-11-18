import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { BLOCKED_MESSAGE, fetchObra, isFileBlocked, type Obra } from '../../api/obras';
import { formatDateTime } from '../../lib/format';
import { useObraId } from './useObraId';

/** Aviso de obra bloqueada: o arquivo foi excluído (ou sumiu) do Autodesk Docs. */
export function ObraBlockedNotice({ obra }: { obra: Obra }) {
  if (obra.acc_file_state === 'ok') return null;
  return (
    <div className="blocked-panel" role="alert">
      <p>{BLOCKED_MESSAGE[obra.acc_file_state]}</p>
      {obra.acc_file_state_at && (
        <p className="small muted">Percebido em {formatDateTime(obra.acc_file_state_at)}.</p>
      )}
      <p className="small">
        <Link to="/obras">Voltar para a lista de obras</Link>
      </p>
    </div>
  );
}

/**
 * Só mostra `children` (o modelo 3D) se o arquivo da obra existe no Docs. Um evento
 * "obra_file_state" invalida ['obras'] e esta tela troca para o aviso sozinha.
 */
export function ObraFileGate({ children }: { children: ReactNode }) {
  const obraId = useObraId();
  const obra = useQuery({
    queryKey: ['obras', obraId],
    queryFn: () => fetchObra(obraId),
    enabled: Number.isFinite(obraId),
    retry: false,
  });
  if (obra.data && isFileBlocked(obra.data)) {
    return (
      <section>
        <h2>
          {obra.data.code} — {obra.data.name}
        </h2>
        <ObraBlockedNotice obra={obra.data} />
      </section>
    );
  }
  return <>{children}</>;
}
