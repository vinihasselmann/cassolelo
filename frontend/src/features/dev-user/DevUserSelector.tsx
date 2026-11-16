import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ChangeEvent } from 'react';

import { getDevUser, setDevUser } from '../../api/client';
import { fetchDevUsers, fetchMe, ROLE_LABELS } from '../../api/users';

/** Seletor do usuário simulado (só até a Fase 11). */
export function DevUserSelector() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string>(getDevUser() ?? '');

  const users = useQuery({ queryKey: ['dev-users'], queryFn: fetchDevUsers, staleTime: Infinity });
  // Chave fixa: ao trocar de usuário a query é invalidada e recarregada com o header novo.
  const me = useQuery({
    queryKey: ['me'],
    queryFn: fetchMe,
    enabled: selected !== '',
    retry: false,
    staleTime: Infinity,
  });

  function onChange(event: ChangeEvent<HTMLSelectElement>) {
    const id = event.target.value;
    setDevUser(id);
    setSelected(id);
    // Os dados dependem de quem está logado: recarrega tudo, menos a lista de usuários.
    void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'dev-users' });
  }

  return (
    <div className="dev-user">
      <label>
        Usuário (simulado){' '}
        <select value={selected} onChange={onChange} disabled={!users.data}>
          <option value="">Selecione…</option>
          {users.data?.map((u) => (
            <option key={u.id} value={String(u.id)}>
              {u.name} ({ROLE_LABELS[u.role]})
            </option>
          ))}
        </select>
      </label>
      {selected !== '' && me.data && (
        <span className="dev-user__role" data-testid="current-role">
          Papel: {ROLE_LABELS[me.data.role]}
        </span>
      )}
      {(users.isError || me.isError) && (
        <span role="alert" className="dev-user__error">
          {users.isError ? 'Não foi possível carregar os usuários.' : 'Usuário inválido.'}
        </span>
      )}
    </div>
  );
}
