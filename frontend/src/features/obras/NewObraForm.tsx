import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { createObra } from '../../api/obras';
import { errorMessage } from '../../lib/errors';
import { AccPicker, type AccSelection } from '../acc/AccPicker';

interface Props {
  onCancel: () => void;
}

export function NewObraForm({ onCancel }: Props) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [selection, setSelection] = useState<AccSelection | null>(null);

  const mutation = useMutation({
    mutationFn: createObra,
    onSuccess: async (obra) => {
      await queryClient.invalidateQueries({ queryKey: ['obras'] });
      navigate(`/obras/${obra.id}`);
    },
  });

  const ready = code.trim() !== '' && name.trim() !== '' && selection !== null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!selection) return;
    mutation.mutate({
      code: code.trim(),
      name: name.trim(),
      acc: {
        hub_id: selection.hubId,
        project_id: selection.projectId,
        folder_id: selection.folderId,
        item_id: selection.itemId,
      },
    });
  }

  return (
    <form className="card" onSubmit={submit} aria-label="Nova obra">
      <h3>Nova obra</h3>
      <div className="form-row">
        <label>
          Código
          <input value={code} onChange={(e) => { setCode(e.target.value); }} maxLength={50} required />
        </label>
        <label className="grow">
          Nome
          <input value={name} onChange={(e) => { setName(e.target.value); }} maxLength={200} required />
        </label>
      </div>

      <fieldset>
        <legend>Arquivo do modelo no Autodesk Docs</legend>
        <AccPicker onSelect={setSelection} selectedItemId={selection?.itemId} />
        <p>
          {selection ? (
            <>Arquivo selecionado: <strong>{selection.itemName}</strong></>
          ) : (
            <span className="muted">Nenhum arquivo selecionado.</span>
          )}
        </p>
      </fieldset>

      {mutation.isError && (
        <p role="alert" className="error">
          {errorMessage(mutation.error)}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={!ready || mutation.isPending}>
          {mutation.isPending ? 'Salvando…' : 'Criar obra'}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
