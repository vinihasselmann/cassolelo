import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { updateObra, type Obra } from '../../api/obras';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';

interface Props {
  obra: Obra;
  onClose: () => void;
}

/** Corrige o código e o nome da obra. Enter salva; Esc cancela (Modal). */
export function ObraEditDialog({ obra, onClose }: Props) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState(obra.code);
  const [name, setName] = useState(obra.name);
  const save = useMutation({
    mutationFn: () => updateObra(obra.id, { code: code.trim(), name: name.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['obras'] });
      onClose();
    },
  });
  const valid = code.trim() !== '' && name.trim() !== '';
  const changed = code.trim() !== obra.code || name.trim() !== obra.name;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || save.isPending) return;
    if (!changed) {
      onClose();
      return;
    }
    save.mutate();
  };

  return (
    <Modal title={`Editar obra ${obra.code}`} onClose={onClose}>
      <form onSubmit={submit} aria-label="Editar obra">
        <div className="form-row">
          <label>
            Código
            <input
              value={code}
              maxLength={50}
              required
              aria-invalid={code.trim() === ''}
              onChange={(e) => { setCode(e.target.value); }}
            />
          </label>
          <label className="grow">
            Nome
            <input
              value={name}
              maxLength={200}
              required
              aria-invalid={name.trim() === ''}
              onChange={(e) => { setName(e.target.value); }}
            />
          </label>
        </div>
        <p className="hint">O arquivo do Docs não muda. Os valores da fábrica continuam ligados à obra.</p>
        {save.isError && (
          <p role="alert" className="error">
            {errorMessage(save.error)}
          </p>
        )}
        <div className="actions">
          <button type="submit" disabled={!valid || save.isPending}>
            {save.isPending ? 'Salvando…' : 'Salvar'}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  );
}
