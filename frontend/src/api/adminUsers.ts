import { apiFetch } from './client';
import type { Role } from './users';

/** De onde vem o papel: esta tela, admin fixo (BOOTSTRAP_ADMIN_EMAILS) ou grupos do Entra. */
export type RoleSource = 'table' | 'bootstrap' | 'groups';

export interface AdminUser {
  id: number;
  name: string;
  email: string;
  role: Role;
  active: boolean;
  /** vê todas as obras (admin vê sempre todas) */
  all_obras: boolean;
  /** as obras que vê quando `all_obras` é false */
  obra_ids: number[];
  role_source: RoleSource;
  created_at: string;
  updated_at: string;
}

export interface AdminUserCreate {
  email: string;
  name?: string;
  role: Role;
  all_obras: boolean;
  obra_ids: number[];
}

export type AdminUserUpdate = Partial<Pick<AdminUser, 'name' | 'role' | 'active' | 'all_obras' | 'obra_ids'>>;

export const fetchAdminUsers = (): Promise<AdminUser[]> => apiFetch<AdminUser[]>('/users');

export const createAdminUser = (body: AdminUserCreate): Promise<AdminUser> =>
  apiFetch<AdminUser>('/users', { method: 'POST', body: JSON.stringify(body) });

export const updateAdminUser = (id: number, body: AdminUserUpdate): Promise<AdminUser> =>
  apiFetch<AdminUser>(`/users/${String(id)}`, { method: 'PATCH', body: JSON.stringify(body) });

export const ROLE_SOURCE_HINT: Record<Exclude<RoleSource, 'table'>, string> = {
  bootstrap: 'Administrador fixo do servidor (BOOTSTRAP_ADMIN_EMAILS): o papel não muda por aqui.',
  groups: 'O papel vem dos grupos do Microsoft Entra: troque o grupo da pessoa no Entra.',
};
