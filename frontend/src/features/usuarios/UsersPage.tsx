import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { fetchAdminUsers, type AdminUser } from '../../api/adminUsers';
import { fetchObras, type Obra } from '../../api/obras';
import { ROLE_LABELS } from '../../api/users';
import { errorMessage } from '../../lib/errors';
import { useCurrentUser } from '../dev-user/useCurrentUser';
import { UserDialog } from './UserDialog';

function obrasLabel(u: AdminUser, byId: Map<number, Obra>): string {
  if (u.role === 'admin' || u.all_obras) return 'Todas';
  if (u.obra_ids.length === 0) return 'Nenhuma';
  return u.obra_ids.map((id) => byId.get(id)?.code ?? `#${String(id)}`).join(', ');
}

/** Tela "Usuários" (só admin): papel, ativo e as obras que cada um vê. */
export function UsersPage() {
  const me = useCurrentUser();
  const isAdmin = me.data?.role === 'admin';
  const meId = me.data?.id;
  const users = useQuery({ queryKey: ['admin-users'], queryFn: fetchAdminUsers, enabled: isAdmin, retry: false });
  const obras = useQuery({ queryKey: ['obras'], queryFn: fetchObras, enabled: isAdmin, retry: false });
  const [editing, setEditing] = useState<AdminUser | null | 'new'>(null);
  const [query, setQuery] = useState('');

  const byId = useMemo(() => new Map((obras.data ?? []).map((o) => [o.id, o])), [obras.data]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = users.data ?? [];
    return q ? list.filter((u) => `${u.name} ${u.email}`.toLowerCase().includes(q)) : list;
  }, [users.data, query]);

  if (me.isPending) return <p className="muted">Carregando…</p>;
  if (!isAdmin) {
    return (
      <section>
        <h2>Usuários</h2>
        <p role="alert" className="error">Só o administrador acessa esta tela.</p>
      </section>
    );
  }

  return (
    <section>
      <div className="page-head">
        <h2>Usuários</h2>
        <button type="button" onClick={() => { setEditing('new'); }}>
          Cadastrar usuário
        </button>
      </div>
      <p className="hint">
        Quem entra pela primeira vez com a conta Microsoft fica como Leitura e vê todas as obras.
        Cadastre antes pelo e-mail para já definir o papel e as obras.
      </p>

      <label className="field">
        <span>Buscar</span>
        <input
          type="search"
          value={query}
          placeholder="Nome ou e-mail"
          onChange={(e) => { setQuery(e.target.value); }}
        />
      </label>

      {users.isPending && <p className="muted">Carregando…</p>}
      {users.isError && (
        <p role="alert" className="error">
          {errorMessage(users.error)}
        </p>
      )}
      {users.data && (
        <table className="table">
          <thead>
            <tr>
              <th>Nome</th>
              <th>E-mail</th>
              <th>Papel</th>
              <th>Situação</th>
              <th>Obras</th>
              <th>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((u) => (
              <tr key={u.id} className={u.active ? undefined : 'muted'} data-testid={`user-${u.email}`}>
                <td>
                  {u.name}
                  {u.id === meId && <span className="muted"> (você)</span>}
                </td>
                <td>{u.email}</td>
                <td>
                  {ROLE_LABELS[u.role]}
                  {u.role_source !== 'table' && (
                    <span className="muted" title={u.role_source === 'bootstrap' ? 'Administrador fixo do servidor' : 'Pelo grupo do Microsoft Entra'}>
                      {' '}
                      ({u.role_source === 'bootstrap' ? 'fixo' : 'Entra'})
                    </span>
                  )}
                </td>
                <td>{u.active ? 'Ativo' : 'Desativado'}</td>
                <td>{obrasLabel(u, byId)}</td>
                <td>
                  <button
                    type="button"
                    className="ghost btn-sm"
                    aria-label={`Editar ${u.name}`}
                    onClick={() => { setEditing(u); }}
                  >
                    Editar
                  </button>
                </td>
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Nenhum usuário encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {editing !== null && (
        <UserDialog
          user={editing === 'new' ? null : editing}
          obras={obras.data ?? []}
          meId={meId}
          onClose={() => { setEditing(null); }}
        />
      )}
    </section>
  );
}
