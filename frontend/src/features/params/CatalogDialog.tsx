import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  deleteParamDef,
  fetchParamLibrary,
  includeParamInObra,
  PARAM_TYPE_LABELS,
  removeParamFromObra,
  type ParamDef,
} from '../../api/paramDefs';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { formatDateTime, plural } from '../../lib/format';
import { invalidateValueQueries } from './invalidate';

function describe(p: ParamDef): string {
  const parts = [PARAM_TYPE_LABELS[p.type] + (p.unit ? ` (${p.unit})` : '')];
  if (p.type === 'list') parts.push(`${p.options?.length ?? 0} opções`);
  parts.push(p.categories?.length ? p.categories.join(', ') : 'todas as categorias');
  if (p.scope === 'obra') parts.push(`só a obra ${p.obra_code ?? ''}`.trim());
  else parts.push(`biblioteca · em ${plural(p.obras_count ?? 0, 'obra', 'obras')}`);
  if (p.level === 'piece') parts.push('por peça', `${plural(p.values_count, 'peça', 'peças')} com valor`);
  else parts.push(`${plural(p.values_count, 'marca', 'marcas')} com valor`);
  return parts.join(' · ');
}

type Action = 'include' | 'remove' | 'delete';
interface Pending {
  action: Action;
  param: ParamDef;
}

function question({ action, param }: Pending): string {
  if (action === 'remove') {
    return `Retirar “${param.name}” desta obra? Ele some das telas desta obra; os valores ficam guardados e voltam se ele for incluído de novo.`;
  }
  const n = param.values_count;
  const unit = param.level === 'piece' ? plural(n, 'peça', 'peças') : plural(n, 'marca', 'marcas');
  const values = n ? ` Os valores de ${unit} ficam só na auditoria.` : '';
  if (param.scope === 'global') {
    return `Excluir “${param.name}” da biblioteca? Ele sai de TODAS as obras (${param.obras_count ?? 0}).${values}`;
  }
  return `Excluir “${param.name}”?${values}`;
}

interface Props {
  obraId: number;
  canEdit: boolean;
  onClose: () => void;
  onNew: () => void;
  onEdit: (param: ParamDef) => void;
}

/**
 * Janela "Catálogo": os parâmetros que valem NESTA obra (os dela + os da biblioteca
 * incluídos) e o resto da biblioteca, para incluir. Parâmetro da biblioteca não vale
 * para nenhuma obra até ser incluído (decisão de 2026-11-13).
 */
export function CatalogDialog({ obraId, canEdit, onClose, onNew, onEdit }: Props) {
  const queryClient = useQueryClient();
  const defs = useQuery({
    queryKey: ['param-defs', obraId, 'library'],
    queryFn: () => fetchParamLibrary(obraId),
    retry: false,
  });
  const [pending, setPending] = useState<Pending | null>(null);
  const act = useMutation({
    mutationFn: ({ action, param }: Pending): Promise<unknown> => {
      if (action === 'include') return includeParamInObra(obraId, param.id);
      if (action === 'remove') return removeParamFromObra(obraId, param.id);
      return deleteParamDef(param.id);
    },
    onSuccess: async () => {
      setPending(null);
      await invalidateValueQueries(queryClient);
    },
  });

  const inObra = defs.data?.filter((p) => p.in_obra !== false) ?? [];
  const library = defs.data?.filter((p) => p.in_obra === false) ?? [];

  const row = (p: ParamDef) => (
    <li key={p.id} className="catalog__row">
      <div>
        <b>{p.name}</b>
        {p.required && <span className="req" title="Obrigatório"> *</span>}
        <div className="hint">{describe(p)}</div>
        <div className="hint">
          Criado por {p.created_by_name ?? 'sistema'} · {formatDateTime(p.created_at)}
        </div>
      </div>
      {canEdit && (
        <div className="catalog__actions">
          {p.in_obra === false && (
            <button
              type="button"
              className="link"
              aria-label={`Incluir ${p.name} nesta obra`}
              disabled={act.isPending}
              onClick={() => { act.mutate({ action: 'include', param: p }); }}
            >
              Incluir nesta obra
            </button>
          )}
          <button type="button" className="link" aria-label={`Editar ${p.name}`} onClick={() => { onEdit(p); }}>
            Editar
          </button>
          {p.scope === 'global' && p.in_obra !== false && (
            <button
              type="button"
              className="link"
              aria-label={`Retirar ${p.name} desta obra`}
              disabled={act.isPending}
              onClick={() => { setPending({ action: 'remove', param: p }); }}
            >
              Retirar desta obra
            </button>
          )}
          <button
            type="button"
            className="link danger"
            aria-label={`Excluir ${p.name}`}
            disabled={act.isPending}
            onClick={() => { setPending({ action: 'delete', param: p }); }}
          >
            {p.scope === 'global' ? 'Excluir da biblioteca' : 'Excluir'}
          </button>
        </div>
      )}
    </li>
  );

  return (
    <Modal title="Catálogo de parâmetros da fábrica" onClose={onClose} wide>
      <p className="muted small">
        Parâmetros que a fábrica preenche por marca. Os da biblioteca só valem nas obras em que forem incluídos;
        os &quot;só desta obra&quot; valem apenas aqui.
        {!canEdit && ' Somente a fábrica cria, inclui, retira e exclui parâmetros.'}
      </p>
      {defs.isPending && <p className="muted">Carregando…</p>}
      {defs.isError && <p role="alert" className="error">{errorMessage(defs.error)}</p>}
      {act.isError && <p role="alert" className="error">{errorMessage(act.error)}</p>}

      {pending && (
        <div className="confirm" role="alertdialog" aria-label="Confirmar">
          <p>{question(pending)}</p>
          <div className="actions">
            <button
              type="button"
              className={pending.action === 'delete' ? 'danger' : undefined}
              disabled={act.isPending}
              onClick={() => { act.mutate(pending); }}
            >
              {pending.action === 'remove' ? 'Retirar' : 'Excluir'}
            </button>
            <button type="button" className="secondary" onClick={() => { setPending(null); }}>
              Cancelar
            </button>
          </div>
        </div>
      )}

      {defs.data && (
        <>
          <h4>Nesta obra ({inObra.length})</h4>
          {inObra.length === 0 ? (
            <p className="muted">Nenhum parâmetro nesta obra. Crie um ou inclua da biblioteca abaixo.</p>
          ) : (
            <ul className="catalog" aria-label="Parâmetros desta obra">{inObra.map(row)}</ul>
          )}
          <h4>Biblioteca: não usados nesta obra ({library.length})</h4>
          {library.length === 0 ? (
            <p className="muted">Todos os parâmetros da biblioteca já estão nesta obra.</p>
          ) : (
            <ul className="catalog" aria-label="Biblioteca">{library.map(row)}</ul>
          )}
        </>
      )}
      <div className="actions">
        {canEdit && (
          <button type="button" onClick={onNew}>
            + Novo parâmetro
          </button>
        )}
        <button type="button" className="secondary" onClick={onClose}>
          Fechar
        </button>
      </div>
    </Modal>
  );
}
