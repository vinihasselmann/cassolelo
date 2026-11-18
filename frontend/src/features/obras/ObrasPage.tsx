import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { FILE_STATE_LABELS, fetchObras, isFileBlocked, type Obra } from '../../api/obras';
import { formatDateTime } from '../../lib/format';
import { errorMessage } from '../../lib/errors';
import { EDITOR_ROLES, hasRole, useCurrentUser } from '../dev-user/useCurrentUser';
import { NewObraForm } from './NewObraForm';
import { ObraDeleteDialog } from './ObraDeleteDialog';
import { ObraEditDialog } from './ObraEditDialog';

export function ObrasPage() {
  const me = useCurrentUser();
  const obras = useQuery({ queryKey: ['obras'], queryFn: fetchObras, retry: false });
  const [creating, setCreating] = useState(false);
  const canEdit = hasRole(me.data, EDITOR_ROLES);
  const [editing, setEditing] = useState<Obra | null>(null);
  const [deleting, setDeleting] = useState<Obra | null>(null);

  return (
    <section>
      <div className="page-head">
        <h2>Obras</h2>
        {canEdit && !creating && (
          <button type="button" onClick={() => { setCreating(true); }}>
            Nova obra
          </button>
        )}
      </div>

      {creating && <NewObraForm onCancel={() => { setCreating(false); }} />}

      {obras.isPending && <p className="muted">Carregando…</p>}
      {obras.isError && (
        <p role="alert" className="error">
          {errorMessage(obras.error)}
        </p>
      )}
      {obras.data?.length === 0 && (
        <p className="muted">
          Nenhuma obra cadastrada.{canEdit ? ' Use "Nova obra" para vincular um modelo do Docs.' : ''}
        </p>
      )}
      {obras.data && obras.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Código</th>
              <th>Nome</th>
              <th>Arquivo no Docs</th>
              {canEdit && (
                <th>
                  <span className="sr-only">Ações</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {obras.data.map((o) => (
              <tr
                key={o.id}
                className={isFileBlocked(o) ? 'row-blocked' : undefined}
                aria-disabled={isFileBlocked(o) || undefined}
              >
                <td>
                  {/* arquivo excluído no Docs: não abre; só Editar/Excluir */}
                  {isFileBlocked(o) ? o.code : <Link to={`/obras/${o.id}`}>{o.code}</Link>}
                </td>
                <td>{o.name}</td>
                <td>
                  {o.acc_item_name ?? '—'}
                  {o.acc_file_state !== 'ok' && (
                    <span className="blocked-badge" title={o.acc_file_state_at ? `Desde ${formatDateTime(o.acc_file_state_at)}` : undefined}>
                      {FILE_STATE_LABELS[o.acc_file_state]}
                    </span>
                  )}
                </td>
                {canEdit && (
                  <td className="row-actions">
                    <button
                      type="button"
                      className="link"
                      aria-label={`Editar obra ${o.code}`}
                      onClick={() => { setEditing(o); }}
                    >
                      Editar
                    </button>
                    <button
                      type="button"
                      className="link danger"
                      aria-label={`Excluir obra ${o.code}`}
                      onClick={() => { setDeleting(o); }}
                    >
                      Excluir
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editing && <ObraEditDialog obra={editing} onClose={() => { setEditing(null); }} />}
      {deleting && (
        <ObraDeleteDialog
          obra={deleting}
          isAdmin={me.data?.role === 'admin'}
          onClose={() => { setDeleting(null); }}
        />
      )}
    </section>
  );
}
