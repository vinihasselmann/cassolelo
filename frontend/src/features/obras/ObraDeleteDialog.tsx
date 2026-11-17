import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { deleteObra, fetchDeletePreview, type Obra } from '../../api/obras';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { plural } from '../../lib/format';

interface Props {
  obra: Obra;
  isAdmin: boolean;
  onClose: () => void;
}

/** Exclusão para corrigir um cadastro errado. Mostra o que some junto e pede o código
 * da obra para confirmar. Com valores preenchidos pela fábrica, só o admin exclui
 * (decisão de 2026-11-17); a exclusão fica no histórico de alterações. */
export function ObraDeleteDialog({ obra, isAdmin, onClose }: Props) {
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState('');
  const preview = useQuery({
    queryKey: ['obras', obra.id, 'delete-preview'],
    queryFn: () => fetchDeletePreview(obra.id),
    retry: false,
    staleTime: 0,
  });
  const remove = useMutation({
    mutationFn: () => deleteObra(obra.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['obras', obra.id] });
      await queryClient.invalidateQueries({ queryKey: ['obras'] });
      onClose();
    },
  });

  const p = preview.data;
  const blocked = p !== undefined && p.admin_only && !isAdmin;
  const confirmed = typed.trim() === obra.code;
  const canDelete = p !== undefined && !blocked && confirmed && !remove.isPending;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (canDelete) remove.mutate();
  };

  return (
    <Modal title={`Excluir obra ${obra.code}`} onClose={onClose}>
      {preview.isPending && <p className="muted">Conferindo o que a obra tem…</p>}
      {preview.isError && (
        <p role="alert" className="error">
          {errorMessage(preview.error)}
        </p>
      )}
      {p && (
        <form onSubmit={submit} aria-label="Excluir obra">
          <p>
            Some junto com a obra <strong>{obra.name}</strong>:{' '}
            {plural(p.versions, 'versão', 'versões')}, {plural(p.marks, 'marca', 'marcas')},{' '}
            {plural(p.units, 'peça numerada', 'peças numeradas')} e{' '}
            {plural(p.filled_values, 'valor preenchido', 'valores preenchidos')} pela fábrica.
            O arquivo no Docs não é alterado.
          </p>
          {p.admin_only && (
            <p role="note" className="error">
              {blocked
                ? 'Esta obra tem valores preenchidos pela fábrica. Só um administrador pode excluí-la.'
                : 'Atenção: os valores preenchidos pela fábrica serão apagados. Não dá para desfazer.'}
            </p>
          )}
          {!blocked && (
            <div className="form-row">
              <label className="grow">
                Digite o código da obra ({obra.code}) para confirmar
                <input
                  value={typed}
                  autoComplete="off"
                  onChange={(e) => { setTyped(e.target.value); }}
                />
              </label>
            </div>
          )}
          {remove.isError && (
            <p role="alert" className="error">
              {errorMessage(remove.error)}
            </p>
          )}
          <div className="actions">
            {!blocked && (
              <button type="submit" className="danger" disabled={!canDelete}>
                {remove.isPending ? 'Excluindo…' : 'Excluir obra'}
              </button>
            )}
            <button type="button" className="secondary" onClick={onClose}>
              {blocked ? 'Fechar' : 'Cancelar'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
