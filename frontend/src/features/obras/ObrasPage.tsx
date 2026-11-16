import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { fetchObras } from '../../api/obras';
import { errorMessage } from '../../lib/errors';
import { EDITOR_ROLES, hasRole, useCurrentUser } from '../dev-user/useCurrentUser';
import { NewObraForm } from './NewObraForm';

export function ObrasPage() {
  const me = useCurrentUser();
  const obras = useQuery({ queryKey: ['obras'], queryFn: fetchObras, retry: false });
  const [creating, setCreating] = useState(false);
  const canEdit = hasRole(me.data, EDITOR_ROLES);

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
            </tr>
          </thead>
          <tbody>
            {obras.data.map((o) => (
              <tr key={o.id}>
                <td>
                  <Link to={`/obras/${o.id}`}>{o.code}</Link>
                </td>
                <td>{o.name}</td>
                <td>{o.acc_item_name ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
