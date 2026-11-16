import { useQuery } from '@tanstack/react-query';

import { getDevUser } from '../../api/client';
import { fetchMe, type Role, type User } from '../../api/users';

/** Usuário atual (via /api/me). Mesma chave usada pelo seletor do cabeçalho. */
export function useCurrentUser() {
  return useQuery<User>({
    queryKey: ['me'],
    queryFn: fetchMe,
    enabled: getDevUser() !== null,
    retry: false,
    // Só muda quando o usuário simulado é trocado, e aí o seletor invalida a query.
    staleTime: Infinity,
  });
}

export function hasRole(user: User | undefined, roles: readonly Role[]): boolean {
  return user !== undefined && roles.includes(user.role);
}

export const EDITOR_ROLES: readonly Role[] = ['projetos', 'admin'];
export const SYNC_ROLES: readonly Role[] = ['projetos', 'fabrica', 'admin'];
/** Quem cria, edita e exclui parâmetros da fábrica (e, na 6.2, preenche valores). */
export const PARAM_EDITOR_ROLES: readonly Role[] = ['fabrica', 'admin'];
