import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';

import { ApiError } from '../../api/client';
import {
  fetchMarkHistory,
  fetchMarkValues,
  markValuesKey,
  saveMarkValues,
  type HistoryEntry,
  type StaleConflict,
  type ValueChange,
} from '../../api/markValues';
import { keepValues } from '../../api/reconcile';
import { errorMessage } from '../../lib/errors';
import { formatDateTime, formatParamValue, formatRelative } from '../../lib/format';
import { fieldLabel as label, fromDraft, toDraft, type Draft } from './fieldDraft';
import { dateErrors, withoutKey } from './dateDraft';
import { FieldInput } from './fieldInput';
import { invalidateValueQueries } from './invalidate';

function describeChange(e: HistoryEntry, type: string | undefined): string {
  const fmt = (v: unknown) => formatParamValue(type ?? 'text', v) ?? 'vazio';
  if (e.action === 'set') return `${e.param}: ${fmt(e.after)}`;
  if (e.action === 'clear') return `${e.param}: ${fmt(e.before)} → apagado`;
  return `${e.param}: ${fmt(e.before)} → ${fmt(e.after)}`;
}

interface Props {
  obraId: number;
  markId: number;
  canEdit: boolean;
}

/** "Parâmetros da fábrica" de UMA marca: ver, editar (Salvar/Cancelar, Esc) e histórico. */
export function MarkValuesSection({ obraId, markId, canEdit }: Props) {
  const queryClient = useQueryClient();
  const key = markValuesKey(obraId, markId);
  const values = useQuery({ queryKey: key, queryFn: () => fetchMarkValues(obraId, markId), retry: false });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>({});
  const [conflict, setConflict] = useState<StaleConflict | null>(null);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: [...key, 'history'],
    queryFn: () => fetchMarkHistory(obraId, markId),
    enabled: showHistory,
    retry: false,
  });

  const fields = values.data?.values ?? [];
  const initial = (): Draft => Object.fromEntries(fields.map((f) => [f.def_id, toDraft(f, f.value)]));
  // O que foi LIDO quando a edição começou (valores e row_version). Em tempo real (8.1)
  // os valores podem recarregar durante a edição; salvar precisa mandar a versão lida
  // no início, senão a edição de um colega seria sobrescrita sem o aviso de conflito.
  const [base, setBase] = useState<{ draft: Draft; versions: Record<number, number | null> }>({ draft: {}, versions: {} });

  const save = useMutation({
    mutationFn: (changes: ValueChange[]) => saveMarkValues(obraId, markId, changes),
    onSuccess: async (fresh) => {
      queryClient.setQueryData(key, fresh);
      setEditing(false);
      setConflict(null);
      // histórico, nº de marcas com valor no catálogo, busca, cores, status e progresso
      await invalidateValueQueries(queryClient);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409 && err.code === 'stale') {
        setConflict(err.body as unknown as StaleConflict);
      }
    },
  });

  const keep = useMutation({
    mutationFn: () => keepValues(markId),
    onSuccess: () => invalidateValueQueries(queryClient),
  });

  const startEdit = () => {
    const start = initial();
    setBase({ draft: start, versions: Object.fromEntries(fields.map((f) => [f.def_id, f.row_version])) });
    setDraft(start);
    setErrors({});
    setConflict(null);
    save.reset();
    setEditing(true);
  };
  const cancel = () => {
    setEditing(false);
    setConflict(null);
    save.reset();
  };

  // Esc cancela a edição.
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') cancel(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); };
  });

  // Troca de marca: sai da edição.
  useEffect(() => { setEditing(false); setConflict(null); setShowHistory(false); }, [markId]);

  async function reload() {
    await values.refetch();
    setConflict(null);
    save.reset();
    setEditing(false);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const bad = dateErrors(fields, draft, e.currentTarget as HTMLFormElement, (f) => `pv-${String(f.def_id)}`);
    setErrors(bad);
    if (Object.keys(bad).length > 0) return; // data inválida: não salva
    const changes: ValueChange[] = fields
      .filter((f) => (draft[f.def_id] ?? '') !== (base.draft[f.def_id] ?? ''))
      .map((f) => ({
        def_id: f.def_id,
        value: fromDraft(f, draft[f.def_id] ?? ''),
        row_version: f.def_id in base.versions ? (base.versions[f.def_id] ?? null) : f.row_version,
      }));
    if (changes.length === 0) {
      setEditing(false);
      return;
    }
    save.mutate(changes);
  }

  if (values.isPending) return <p className="muted small">Carregando…</p>;
  if (values.isError) return <p role="alert" className="error small">{errorMessage(values.error)}</p>;
  if (fields.length === 0) return <p className="muted small">Nenhum parâmetro se aplica a esta categoria.</p>;

  const types = new Map(fields.map((f) => [f.def_id, f.type]));
  const last = values.data.last_change_at;

  return (
    <div className="mark-values">
      {values.data.mark.review_status === 'review' && (
        <div className="alert alert--review" role="region" aria-label="Revisar">
          <b>Revisar:</b> esta marca mudou na versão nova e já tem valores da fábrica.
          <ul className="review-diff">
            {(values.data.mark.review_note ?? '').split('; ').filter(Boolean).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {canEdit && !editing && (
            <div className="btn-row">
              <button type="button" disabled={keep.isPending} onClick={() => { keep.mutate(); }}>
                Manter valores
              </button>
              <button type="button" className="secondary" onClick={startEdit}>
                Editar
              </button>
            </div>
          )}
          {keep.isError && <p className="error small">{errorMessage(keep.error)}</p>}
        </div>
      )}
      {conflict && (
        <div className="alert alert--warn" role="alert">
          <b>{conflict.changed_by_name ?? 'Outro usuário'}</b> alterou esta marca{' '}
          {conflict.changed_at ? formatRelative(conflict.changed_at) : 'agora há pouco'}. Seus valores não foram salvos.{' '}
          <button type="button" className="link" onClick={() => { void reload(); }}>
            Recarregar
          </button>
        </div>
      )}

      {editing ? (
        <form onSubmit={submit} aria-label="Editar parâmetros da fábrica">
          {fields.map((f) => (
            <div key={f.def_id} className="field">
              <label htmlFor={`pv-${f.def_id}`}>
                {label(f)}
                {f.required && <span className="req"> *</span>}
              </label>
              <FieldInput
                f={f}
                value={draft[f.def_id] ?? ''}
                error={errors[f.def_id]}
                onChange={(v) => {
                  setDraft((d) => ({ ...d, [f.def_id]: v }));
                  setErrors((errs) => withoutKey(errs, f.def_id));
                }}
              />
            </div>
          ))}
          {save.isError && !conflict && (
            <p role="alert" className="error small">
              {errorMessage(save.error)}
            </p>
          )}
          <div className="btn-row">
            <button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Salvando…' : 'Salvar'}
            </button>
            <button type="button" className="secondary" onClick={cancel}>
              Cancelar
            </button>
          </div>
        </form>
      ) : (
        <>
          <dl className="kv" aria-label="Valores da marca">
            {fields.map((f) => {
              const shown = formatParamValue(f.type, f.value);
              return (
                <div key={f.def_id} className="kv__row">
                  <dt>
                    {label(f)}
                    {f.required && <span className="req"> *</span>}
                  </dt>
                  <dd className={shown ? 'pv-value' : 'muted'}>{shown ?? '—'}</dd>
                </div>
              );
            })}
          </dl>
          {canEdit && (
            <button type="button" className="btn-sm" onClick={startEdit}>
              Editar
            </button>
          )}
        </>
      )}

      <p className="hint">
        {last ? `Última alteração: ${values.data.last_change_by ?? 'sistema'} · ${formatDateTime(last)}` : 'Nenhum valor preenchido ainda.'}
      </p>
      <button type="button" className="link small" aria-expanded={showHistory} onClick={() => { setShowHistory(!showHistory); }}>
        {showHistory ? 'Ocultar histórico' : 'Histórico'}
      </button>
      {showHistory && (
        <div className="history">
          {history.isPending && <p className="muted small">Carregando…</p>}
          {history.isError && <p className="error small">{errorMessage(history.error)}</p>}
          {history.data?.length === 0 && <p className="muted small">Sem alterações.</p>}
          {history.data && history.data.length > 0 && (
            <ul aria-label="Histórico da marca">
              {history.data.map((e, i) => (
                <li key={`${e.at}-${String(i)}`}>
                  <span className="muted">{formatDateTime(e.at)} · {e.user_name ?? 'sistema'}</span>
                  <br />
                  {describeChange(e, e.def_id !== null ? types.get(e.def_id) : undefined)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
