import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import {
  createAdminUser,
  ROLE_SOURCE_HINT,
  updateAdminUser,
  type AdminUser,
  type AdminUserUpdate,
} from '../../api/adminUsers';
import type { Obra } from '../../api/obras';
import { ROLE_LABELS, type Role } from '../../api/users';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';

const ROLES: Role[] = ['leitura', 'fabrica', 'projetos', 'admin'];

const ROLE_HINTS: Record<Role, string> = {
  leitura: 'Só consulta.',
  fabrica: 'Preenche os parâmetros da fábrica.',
  projetos: 'Cadastra e edita obras.',
  admin: 'Tudo, inclusive esta tela. Vê sempre todas as obras.',
};

interface Props {
  /** null = cadastrar pessoa nova (antes do primeiro acesso) */
  user: AdminUser | null;
  obras: Obra[];
  /** o admin logado (não se desativa nem perde o papel de admin) */
  meId: number | undefined;
  onClose: () => void;
}

/** Cadastrar ou editar: nome, papel, ativo e as obras que a pessoa vê. */
export function UserDialog({ user, obras, meId, onClose }: Props) {
  const queryClient = useQueryClient();
  const isNew = user === null;
  const isSelf = user !== null && user.id === meId;
  const [email, setEmail] = useState('');
  const [name, setName] = useState(user?.name ?? '');
  const [role, setRole] = useState<Role>(user?.role ?? 'leitura');
  const [active, setActive] = useState(user?.active ?? true);
  const [allObras, setAllObras] = useState(user?.all_obras ?? true);
  const [obraIds, setObraIds] = useState<Set<number>>(new Set(user?.obra_ids ?? []));

  const roleLocked = user !== null && user.role_source !== 'table';
  const isAdminRole = role === 'admin';

  const save = useMutation({
    mutationFn: () => {
      const ids = [...obraIds].sort((a, b) => a - b);
      if (isNew) {
        const trimmed = name.trim();
        return createAdminUser({
          email: email.trim(),
          ...(trimmed ? { name: trimmed } : {}),
          role,
          all_obras: allObras,
          obra_ids: allObras ? [] : ids,
        });
      }
      const body: AdminUserUpdate = {};
      if (name.trim() !== user.name) body.name = name.trim();
      if (role !== user.role) body.role = role;
      if (active !== user.active) body.active = active;
      if (allObras !== user.all_obras) body.all_obras = allObras;
      if (!allObras) body.obra_ids = ids;
      return updateAdminUser(user.id, body);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      onClose();
    },
  });

  const valid = isNew ? email.trim().includes('@') : name.trim() !== '';

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || save.isPending) return;
    save.mutate();
  };

  const toggleObra = (id: number) => {
    setObraIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Modal title={isNew ? 'Cadastrar usuário' : `Editar ${user.name}`} onClose={onClose} wide>
      <form onSubmit={submit} aria-label={isNew ? 'Cadastrar usuário' : 'Editar usuário'}>
        <div className="form-row">
          {isNew ? (
            <label className="grow">
              E-mail corporativo
              <input
                type="email"
                value={email}
                required
                maxLength={320}
                placeholder="fulano@cassol.ind.br"
                onChange={(e) => { setEmail(e.target.value); }}
              />
            </label>
          ) : (
            <p className="grow">
              <span className="muted">E-mail</span>
              <br />
              {user.email}
            </p>
          )}
          <label className="grow">
            Nome
            <input
              value={name}
              maxLength={200}
              required={!isNew}
              placeholder={isNew ? 'Vazio: vem da conta Microsoft no 1º acesso' : undefined}
              onChange={(e) => { setName(e.target.value); }}
            />
          </label>
        </div>

        <fieldset className="field">
          <legend>Papel</legend>
          {roleLocked && <p className="hint">{ROLE_SOURCE_HINT[user.role_source as 'bootstrap' | 'groups']}</p>}
          {isSelf && !roleLocked && <p className="hint">Você não pode tirar o seu próprio papel de administrador.</p>}
          <div className="checks">
            {ROLES.map((r) => (
              <label key={r} className="check">
                <input
                  type="radio"
                  name="role"
                  value={r}
                  checked={role === r}
                  disabled={roleLocked || isSelf}
                  onChange={() => { setRole(r); }}
                />
                <span>
                  <strong>{ROLE_LABELS[r]}</strong> <span className="muted">· {ROLE_HINTS[r]}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {!isNew && (
          <label className="check">
            <input
              type="checkbox"
              checked={active}
              disabled={isSelf}
              onChange={(e) => { setActive(e.target.checked); }}
            />
            Ativo (desativado não entra no app, mesmo com conta Microsoft válida)
          </label>
        )}

        <fieldset className="field">
          <legend>Obras que vê</legend>
          {isAdminRole ? (
            <p className="hint">Administrador vê sempre todas as obras.</p>
          ) : (
            <>
              <div className="checks">
                <label className="check">
                  <input
                    type="radio"
                    name="scope"
                    checked={allObras}
                    onChange={() => { setAllObras(true); }}
                  />
                  Todas as obras (inclusive as cadastradas depois)
                </label>
                <label className="check">
                  <input
                    type="radio"
                    name="scope"
                    checked={!allObras}
                    onChange={() => { setAllObras(false); }}
                  />
                  Só as obras escolhidas
                </label>
              </div>
              {!allObras && (
                <fieldset className="checks user-obras" aria-label="Obras escolhidas">
                  {obras.length === 0 && <p className="muted">Nenhuma obra cadastrada.</p>}
                  {obras.map((o) => (
                    <label key={o.id} className="check">
                      <input
                        type="checkbox"
                        checked={obraIds.has(o.id)}
                        onChange={() => { toggleObra(o.id); }}
                      />
                      <span>
                        <strong>{o.code}</strong> {o.name}
                      </span>
                    </label>
                  ))}
                  <p className="hint">
                    {obraIds.size === 0
                      ? 'Nenhuma obra escolhida: a pessoa não verá obra nenhuma.'
                      : `${String(obraIds.size)} obra(s). Obras novas não entram sozinhas.`}
                  </p>
                </fieldset>
              )}
            </>
          )}
        </fieldset>

        {save.isError && (
          <p role="alert" className="error">
            {errorMessage(save.error)}
          </p>
        )}
        <div className="actions">
          <button type="submit" disabled={!valid || save.isPending}>
            {save.isPending ? 'Salvando…' : isNew ? 'Cadastrar' : 'Salvar'}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  );
}
