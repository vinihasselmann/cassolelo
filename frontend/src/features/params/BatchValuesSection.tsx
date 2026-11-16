import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';

import {
  applyBatch,
  markBatchKey,
  previewBatch,
  type BatchApplyResult,
  type BatchField,
  type BatchMode,
  type BatchPreview,
} from '../../api/markBatch';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { formatParamValue } from '../../lib/format';
import { fieldLabel, fromDraft, toDraft, type Draft } from './fieldDraft';
import { FieldInput } from './fieldInput';
import { invalidateValueQueries } from './invalidate';

const num = (n: number) => n.toLocaleString('pt-BR');
const marcas = (n: number) => `${num(n)} ${n === 1 ? 'marca' : 'marcas'}`;

function initialDraft(f: BatchField): string {
  return f.mixed ? '' : toDraft(f, f.common_value);
}

interface Confirm {
  changes: Record<number, unknown>;
  preview: BatchPreview;
}

interface Props {
  obraId: number;
  markIds: number[];
  canEdit: boolean;
  /** Peças sem Marca também selecionadas (ficam de fora do lote). */
  unmarked: number;
  onApplied: (result: BatchApplyResult) => void;
}

/** "Parâmetros da fábrica" com 2+ marcas: valores comuns/mistos e edição em lote. */
export function BatchValuesSection({ obraId, markIds, canEdit, unmarked, onApplied }: Props) {
  const queryClient = useQueryClient();
  const summary = useQuery({
    queryKey: markBatchKey(obraId, markIds),
    queryFn: () => previewBatch(obraId, { mark_ids: markIds, changes: {}, mode: 'overwrite' }),
    retry: false,
  });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>({});
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  const check = useMutation({
    mutationFn: (changes: Record<number, unknown>) =>
      previewBatch(obraId, { mark_ids: markIds, changes, mode: 'overwrite' }),
    onSuccess: (preview, changes) => { setConfirm({ changes, preview }); },
  });
  const apply = useMutation({
    mutationFn: ({ changes, mode }: { changes: Record<number, unknown>; mode: BatchMode }) =>
      applyBatch(obraId, { mark_ids: markIds, changes, mode }),
    onSuccess: async (result) => {
      setConfirm(null);
      setEditing(false);
      onApplied(result);
      await invalidateValueQueries(queryClient);
    },
  });

  const fields = summary.data?.fields ?? [];
  const cancel = () => {
    setEditing(false);
    setConfirm(null);
    check.reset();
    apply.reset();
  };

  // Esc cancela a edição (com a confirmação aberta, o Esc só fecha a confirmação).
  useEffect(() => {
    if (!editing || confirm) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cancel(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); };
  });

  // Seleção mudou: sai da edição.
  const selectionKey = markBatchKey(obraId, markIds)[2];
  useEffect(() => { setEditing(false); setConfirm(null); }, [selectionKey]);

  function startEdit() {
    setDraft(Object.fromEntries(fields.map((f) => [f.def_id, initialDraft(f)])));
    check.reset();
    apply.reset();
    setEditing(true);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const changes: Record<number, unknown> = {};
    for (const f of fields) {
      const text = draft[f.def_id] ?? '';
      if (text !== initialDraft(f)) changes[f.def_id] = fromDraft(f, text);
    }
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    check.mutate(changes);
  }

  const total = markIds.length;
  const categories = summary.data?.categories ?? [];

  return (
    <div className="mark-values">
      <p>
        <b>{marcas(total)} selecionadas</b>
        {unmarked > 0 && <span className="muted small"> · peças sem Marca ficam de fora</span>}
      </p>
      {categories.length > 1 && (
        <div className="alert alert--warn" role="note">
          A seleção mistura categorias ({categories.join(', ')}). Cada parâmetro só é gravado nas marcas em que se aplica.
        </div>
      )}
      {summary.isPending && <p className="muted small">Carregando…</p>}
      {summary.isError && <p role="alert" className="error small">{errorMessage(summary.error)}</p>}
      {summary.data && fields.length === 0 && (
        <p className="muted small">Nenhum parâmetro se aplica às categorias selecionadas.</p>
      )}

      {summary.data && fields.length > 0 && editing && (
        <form onSubmit={submit} aria-label="Editar em lote">
          {fields.map((f) => (
            <div key={f.def_id} className="field">
              <label htmlFor={`pv-${String(f.def_id)}`}>
                {fieldLabel(f)}
                {f.required && <span className="req"> *</span>}
              </label>
              <FieldInput
                f={f}
                mixed={f.mixed}
                value={draft[f.def_id] ?? ''}
                onChange={(v) => { setDraft((d) => ({ ...d, [f.def_id]: v })); }}
              />
              {f.applies_to < total && <div className="hint">Vale para {marcas(f.applies_to)} de {num(total)}.</div>}
            </div>
          ))}
          {(check.isError || apply.isError) && (
            <p role="alert" className="error small">
              {errorMessage(check.error ?? apply.error)}
            </p>
          )}
          <div className="btn-row">
            <button type="submit" disabled={check.isPending}>
              {check.isPending ? 'Conferindo…' : 'Aplicar'}
            </button>
            <button type="button" className="secondary" onClick={cancel}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      {summary.data && fields.length > 0 && !editing && (
        <>
          <dl className="kv" aria-label="Valores das marcas selecionadas">
            {fields.map((f) => {
              const shown = f.mixed ? null : formatParamValue(f.type, f.common_value);
              return (
                <div key={f.def_id} className="kv__row">
                  <dt>
                    {fieldLabel(f)}
                    {f.required && <span className="req"> *</span>}
                  </dt>
                  <dd className={shown ? 'pv-value' : 'muted'}>
                    {f.mixed ? '(valores mistos)' : (shown ?? '—')}
                    {f.applies_to < total && <span className="muted small"> · {num(f.applies_to)} de {num(total)}</span>}
                  </dd>
                </div>
              );
            })}
          </dl>
          {canEdit && (
            <button type="button" className="secondary small-btn" onClick={startEdit}>
              Editar em lote
            </button>
          )}
        </>
      )}

      {confirm && (
        <Modal title="Aplicar às marcas selecionadas" onClose={() => { setConfirm(null); }}>
          <ConfirmBody confirm={confirm} />
          {apply.isError && <p role="alert" className="error small">{errorMessage(apply.error)}</p>}
          <div className="actions">
            {confirm.preview.marks_to_change_overwrite > 0 && (
              <button
                type="button"
                disabled={apply.isPending}
                onClick={() => { apply.mutate({ changes: confirm.changes, mode: 'overwrite' }); }}
              >
                Sobrescrever todas
              </button>
            )}
            {confirm.preview.marks_to_change_overwrite > 0 && (
              <button
                type="button"
                className="secondary"
                disabled={apply.isPending || confirm.preview.marks_to_change_only_empty === 0}
                onClick={() => { apply.mutate({ changes: confirm.changes, mode: 'only_empty' }); }}
              >
                Só nas vazias
              </button>
            )}
            <button type="button" className="secondary" onClick={() => { setConfirm(null); }}>
              Cancelar
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ConfirmBody({ confirm }: { confirm: Confirm }) {
  const p = confirm.preview;
  if (p.marks_to_change_overwrite === 0) {
    return <p>Nada muda: as marcas selecionadas já têm esses valores.</p>;
  }
  return (
    <>
      <p>
        <b>{marcas(p.marks_to_change_overwrite)}</b> serão alteradas.
        {p.marks_with_other_value > 0 && (
          <>
            {' '}
            <b>{marcas(p.marks_with_other_value)}</b> já {p.marks_with_other_value === 1 ? 'tem' : 'têm'} outro valor.
          </>
        )}
      </p>
      {p.marks_to_change_overwrite > 0 && (
        <p className="muted small">
          “Sobrescrever todas” grava nas {num(p.marks_to_change_overwrite)}; “Só nas vazias” grava só onde o campo está vazio
          ({marcas(p.marks_to_change_only_empty)}).
        </p>
      )}
      {p.categories.length > 1 && (
        <p className="muted small">Cada parâmetro só é gravado nas marcas em que se aplica.</p>
      )}
    </>
  );
}
