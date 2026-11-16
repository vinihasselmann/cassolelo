import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import {
  createParamDef,
  PARAM_TYPE_LABELS,
  updateParamDef,
  type ParamDef,
  type ParamDefBody,
  type ParamScope,
  type ParamType,
} from '../../api/paramDefs';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { invalidateValueQueries } from './invalidate';

interface Props {
  obraId: number;
  obraCode: string | null;
  /** Categorias que aparecem como opção (as da versão + as já gravadas no parâmetro). */
  categories: readonly string[];
  /** Parâmetro a editar; ausente = novo. */
  param?: ParamDef;
  /** Categoria já marcada num parâmetro novo (ex.: a da marca selecionada). */
  presetCategory?: string | null;
  onClose: () => void;
  onSaved?: (param: ParamDef) => void;
}

/** "+ Novo parâmetro" / "Editar parâmetro". As regras completas são do backend. */
export function ParamDefDialog({ obraId, obraCode, categories, param, presetCategory, onClose, onSaved }: Props) {
  const queryClient = useQueryClient();
  const used = param?.values_count ?? 0;
  const [name, setName] = useState(param?.name ?? '');
  const [type, setType] = useState<ParamType>(param?.type ?? 'text');
  const [unit, setUnit] = useState(param?.unit ?? '');
  const [options, setOptions] = useState((param?.options ?? []).join('\n'));
  const [cats, setCats] = useState<string[]>(param ? (param.categories ?? []) : presetCategory ? [presetCategory] : []);
  const [scope, setScope] = useState<ParamScope>(param?.scope ?? 'global');
  const [required, setRequired] = useState(param?.required ?? false);
  const [localError, setLocalError] = useState<string | null>(null);

  const allCats = [...new Set([...categories, ...cats])];

  const save = useMutation({
    mutationFn: (body: ParamDefBody) => (param ? updateParamDef(param.id, body) : createParamDef(body)),
    onSuccess: async (saved) => {
      await invalidateValueQueries(queryClient); // catálogo, painel da marca, status e progresso
      onSaved?.(saved);
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setLocalError('Informe o nome do parâmetro.');
      return;
    }
    setLocalError(null);
    save.mutate({
      name,
      type,
      unit: type === 'number' ? unit : null,
      options: type === 'list' ? options.split('\n').map((o) => o.trim()).filter(Boolean) : null,
      required,
      categories: cats.length === allCats.length && allCats.length > 0 ? [] : cats,
      scope,
      obra_id: scope === 'obra' ? obraId : null,
      // criado da biblioteca aqui dentro: já entra nesta obra (as outras incluem se quiserem)
      ...(param ? {} : { include_in_obra_id: scope === 'global' ? obraId : null }),
    });
  }

  const toggleCat = (c: string) => {
    setCats((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  };
  const error = localError ?? (save.isError ? errorMessage(save.error) : null);

  return (
    <Modal title={param ? 'Editar parâmetro' : 'Novo parâmetro da fábrica'} onClose={onClose}>
      <p className="muted small">
        {param
          ? `Usado em ${used} marca(s).`
          : 'O parâmetro fica disponível nas marcas a que se aplica e aparece no painel, na busca e nas cores.'}
      </p>
      <form onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="pd-name">
            Nome <span className="req">*</span>
          </label>
          <input
            id="pd-name"
            value={name}
            placeholder="Ex.: Tipo de forma, Ciclo de cura, Peça com insert"
            onChange={(e) => { setName(e.target.value); }}
          />
        </div>

        <div className="field">
          <label htmlFor="pd-type">Tipo</label>
          <select id="pd-type" value={type} disabled={used > 0} onChange={(e) => { setType(e.target.value as ParamType); }}>
            {Object.entries(PARAM_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          {used > 0 && <p className="hint">O tipo não pode ser alterado porque já existem valores.</p>}
        </div>

        {type === 'number' && (
          <div className="field">
            <label htmlFor="pd-unit">Unidade</label>
            <input id="pd-unit" value={unit} placeholder="Ex.: h, kg, MPa, un" onChange={(e) => { setUnit(e.target.value); }} />
          </div>
        )}

        {type === 'list' && (
          <div className="field">
            <label htmlFor="pd-options">
              Opções (uma por linha) <span className="req">*</span>
            </label>
            <textarea id="pd-options" rows={4} value={options} placeholder={'F-01\nF-02\nF-03'} onChange={(e) => { setOptions(e.target.value); }} />
            {param && param.options_in_use.length > 0 && (
              <p className="hint">Em uso (não podem ser removidas): {param.options_in_use.join(', ')}</p>
            )}
          </div>
        )}

        <fieldset className="field">
          <legend>Aplica-se a</legend>
          {allCats.length === 0 && <p className="hint">Todas as categorias.</p>}
          {allCats.map((c) => (
            <label key={c} className="check">
              <input type="checkbox" checked={cats.includes(c)} onChange={() => { toggleCat(c); }} /> {c}
            </label>
          ))}
          {allCats.length > 0 && <p className="hint">Nenhuma marcada = todas as categorias.</p>}
        </fieldset>

        <div className="field">
          <label htmlFor="pd-scope">Escopo</label>
          <select id="pd-scope" value={scope} disabled={used > 0} onChange={(e) => { setScope(e.target.value as ParamScope); }}>
            <option value="global">Biblioteca (entra nesta obra; outras obras podem incluir)</option>
            <option value="obra">Somente esta obra{obraCode ? ` (${obraCode})` : ''}</option>
          </select>
        </div>

        <label className="check">
          <input type="checkbox" checked={required} onChange={(e) => { setRequired(e.target.checked); }} /> Obrigatório (define o
          status completo/pendente da marca)
        </label>

        {error && (
          <p role="alert" className="error small">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Salvando…' : param ? 'Salvar' : 'Criar parâmetro'}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  );
}
