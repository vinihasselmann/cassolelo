import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { archiveOrphan, fetchOrphans, orphansKey, type Orphan } from '../../api/reconcile';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { invalidateValueQueries } from '../params/invalidate';
import { describeValues } from './orphanText';
import { versionName } from '../../lib/format';

interface Props {
  obraId: number;
  canEdit: boolean;
  onClose: () => void;
  /** Religar: a tela entra no modo "escolha a marca de destino". */
  onRelink: (orphan: Orphan) => void;
}

/** Janela "Órfãs": marcas que sumiram do modelo com valores da fábrica. */
export function OrphansDialog({ obraId, canEdit, onClose, onRelink }: Props) {
  const queryClient = useQueryClient();
  const orphans = useQuery({ queryKey: orphansKey(obraId), queryFn: () => fetchOrphans(obraId), retry: false });
  const archive = useMutation({
    mutationFn: (o: Orphan) => archiveOrphan(o.id),
    onSuccess: () => invalidateValueQueries(queryClient),
  });

  function confirmArchive(o: Orphan) {
    if (window.confirm(`Arquivar a órfã ${o.code}?\n\nOs valores não são copiados, mas continuam guardados no histórico da marca.`)) {
      archive.mutate(o);
    }
  }

  return (
    <Modal title="Marcas órfãs" onClose={onClose} wide>
      <p className="muted small">
        Marcas que sumiram do modelo e tinham valores da fábrica. Religue a uma marca do modelo atual (os valores são
        copiados) ou arquive. Nada é apagado.
        {!canEdit && ' Somente a fábrica religa e arquiva.'}
      </p>
      {orphans.isPending && <p className="muted">Carregando…</p>}
      {orphans.isError && <p role="alert" className="error">{errorMessage(orphans.error)}</p>}
      {archive.isError && <p role="alert" className="error">{errorMessage(archive.error)}</p>}
      {orphans.data?.length === 0 && <p><b>Nenhuma órfã pendente.</b></p>}
      {orphans.data && orphans.data.length > 0 && (
        <ul className="orphan-list" aria-label="Órfãs abertas">
          {orphans.data.map((o) => (
            <li key={o.id}>
              <div>
                <b>{o.code}</b> · {o.category}
                <div className="hint">Sumiu na {versionName(o.since_version_number)}</div>
                <div className="small">{describeValues(o)}</div>
              </div>
              {canEdit && (
                <div className="btn-row">
                  <button type="button" aria-label={`Religar ${o.code}`} onClick={() => { onRelink(o); }}>
                    Religar
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    aria-label={`Arquivar ${o.code}`}
                    disabled={archive.isPending}
                    onClick={() => { confirmArchive(o); }}
                  >
                    Arquivar
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          Fechar
        </button>
      </div>
    </Modal>
  );
}
