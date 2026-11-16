import { apiFetch } from './client';

export type Role = 'projetos' | 'fabrica' | 'admin' | 'leitura';

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  /** O papel cria e edita filtros compartilhados (SHARED_FILTER_ROLES do servidor). */
  can_share_filters?: boolean;
}

export const ROLE_LABELS: Record<Role, string> = {
  projetos: 'Projetos',
  fabrica: 'Fábrica',
  admin: 'Administrador',
  leitura: 'Leitura',
};

export const fetchDevUsers = (): Promise<User[]> => apiFetch<User[]>('/dev/users');
export const fetchMe = (): Promise<User> => apiFetch<User>('/me');
