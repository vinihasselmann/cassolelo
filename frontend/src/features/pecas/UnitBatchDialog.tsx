import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import type { BatchMode } from '../../api/markBatch';
import {
  applyUnitBatch,
  isEditable,
  previewUnitBatch,
  type UnitBatchField,
  type UnitBatchPreview,
  type UnitBatchResult,
} from '../../api/units';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { fieldLabel, fromDraft, toDraft, type Draft } from '../params/fieldDraft';
import { dateErrors, withoutKey } from '../params/dateDraft';
import { FieldInput } from '../params/fieldInput';
import { invalidateValueQueries } from '../params/invalidate';
import { pecas } from './unitTable';

const num = (n: number) => n.toLocaleString('pt-BR');

function initialDraft(f: UnitBatchField): string {
  return f.mixed ? '' : toDraft(f, f.common_value);
}

interface Props {
  obraId: number;
  unitIds: number[];
  /** Rótulos das peças marcadas (PP001-2, PP001-3…), para o título. */
  labels: string[];
  /** Resumo no lugar da lista de rótulos (muitas peças, várias marcas). */
  summary?: string;
  onClose: () => void;
  onApplied: (result: UnitBatchResult) => void;
}

/** "Preencher selecionadas": um valor para várias peças da marca, com "Só nas vazias" e Desfazer. */
export function UnitBatchDialog({ obraId, unitIds, labels, summary: caption, onClose, onApplied }: Props) {
  const queryClient = useQueryClient();
  const summary = useQuery({
    queryKey: ['unit-batch', obraId, [...unitIds].sort((a, b) => a - b).join(',')],
    queryFn: () => previewUnitBatch(obraId, { unit_ids: unitIds, changes: {}, mode: 'overwrite' }),
    retry: false,
  });
  // as datas do Plannix só vêm pela importação: não entram no lote
  const all = summary.data?.fields ?? [];
  const fields = all.filter(isEditable);
  const fromPlannix = all.length - fields.length;
  const [draft, setDraft] = useState<Draft | null>(null);
  const current: Draft = draft ?? Object.fromEntries(fields.map((f) => [f.def_id, initialDraft(f)]));
  const [confirm, setConfirm] = useState<{ changes: Record<number, unknown>; preview: UnitBatchPreview } | null>(null);
  const [nothing, setNothing] = useState(false);
  const [errors, setErrors] = useState<Record<number, string>>({});

  const check = useMutation({
    mutationFn: (changes: Record<number, unknown>) =>
      previewUnitBatch(obraId, { unit_ids: unitIds, changes, mode: 'overwrite' }),
    onSuccess: (preview, changes) => { setConfirm({ changes, preview }); },
  });
  const apply = useMutation({
    mutationFn: ({ changes, mode }: { changes: Record<number, unknown>; mode: BatchMode }) =>
      applyUnitBatch(obraId, { unit_ids: unitIds, changes, mode }),
    onSuccess: async (result) => {
      onApplied(result);
      await invalidateValueQueries(queryClient);
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const bad = dateErrors(fields, current, e.currentTarget as HTMLFormElement, (f) => `ub-${String(f.def_id)}`);
    setErrors(bad);
    if (Object.keys(bad).length > 0) return; // data inválida: não aplica
    const changes: Record<number, unknown> = {};
    for (const f of fields) {
      const text = current[f.def_id] ?? '';
      if (text !== initialDraft(f)) changes[f.def_id] = fromDraft(f, text);
    }
    if (Object.keys(changes).length === 0) {
      setNothing(true);
      return;
    }
    setNothing(false);
    check.mutate(changes);
  }

  const title = `Preencher ${pecas(unitIds.length)}`;
  const p = confirm?.preview;

  return (
    <Modal title={title} onClose={onClose}>
      <p className="muted small">{caption ?? labels.join(', ')}</p>
      {summary.isPending && <p className="muted small">Carregando…</p>}
      {summary.isError && <p role="alert" className="error small">{errorMessage(summary.error)}</p>}

      {summary.data && !confirm && (
        <form onSubmit={submit} aria-label="Preencher peças selecionadas" className="unit-batch">
          {fields.map((f) => (
            <div key={f.def_id} className="field">
              <label htmlFor={`ub-${String(f.def_id)}`}>
                {fieldLabel(f)}
                {f.required && <span className="req"> *</span>}
              </label>
              <FieldInput
                f={f}
                id={`ub-${String(f.def_id)}`}
                mixed={f.mixed}
                value={current[f.def_id] ?? ''}
                error={errors[f.def_id]}
                onChange={(v) => {
                  setDraft({ ...current, [f.def_id]: v });
                  setErrors((errs) => withoutKey(errs, f.def_id));
                }}
              />
              {f.filled > 0 && f.mixed && <div className="hint">Valores diferentes entre as peças: vazio mantém o de cada uma.</div>}
            </div>
          ))}
          {fromPlannix > 0 && (
            <p className="hint">
              {fromPlannix === 1 ? '1 parâmetro vem' : `${String(fromPlannix)} parâmetros vêm`} do Plannix e não
              aparece{fromPlannix === 1 ? '' : 'm'} aqui (só leitura).
            </p>
          )}
          {nothing && <p role="alert" className="error small">Informe um valor para preencher.</p>}
          {check.isError && <p role="alert" className="error small">{errorMessage(check.error)}</p>}
          <div className="actions">
            <button type="submit" disabled={check.isPending}>
              {check.isPending ? 'Conferindo…' : 'Aplicar'}
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      {confirm && p && (
        <div role="group" aria-label="Confirmar preenchimento">
          {p.units_to_change_overwrite === 0 ? (
            <p>Nada muda: as peças selecionadas já têm esses valores.</p>
          ) : (
            <>
              <p>
                <b>{pecas(p.units_to_change_overwrite)}</b> {p.units_to_change_overwrite === 1 ? 'será alterada' : 'serão alteradas'}.
                {p.units_with_other_value > 0 && (
                  <>
                    {' '}
                    <b>{pecas(p.units_with_other_value)}</b> já {p.units_with_other_value === 1 ? 'tem' : 'têm'} outro valor.
                  </>
                )}
              </p>
              {p.units_with_other_value > 0 && (
                <p className="muted small">
                  “Sobrescrever todas” grava nas {num(p.units_to_change_overwrite)}; “Só nas vazias” grava só onde o campo está
                  vazio ({pecas(p.units_to_change_only_empty)}).
                </p>
              )}
            </>
          )}
          {apply.isError && <p role="alert" className="error small">{errorMessage(apply.error)}</p>}
          <div className="actions">
            {p.units_to_change_overwrite > 0 && (
              <button
                type="button"
                disabled={apply.isPending}
                onClick={() => { apply.mutate({ changes: confirm.changes, mode: 'overwrite' }); }}
              >
                {p.units_with_other_value > 0 ? 'Sobrescrever todas' : 'Confirmar'}
              </button>
            )}
            {p.units_with_other_value > 0 && (
              <button
                type="button"
                className="secondary"
                disabled={apply.isPending || p.units_to_change_only_empty === 0}
                onClick={() => { apply.mutate({ changes: confirm.changes, mode: 'only_empty' }); }}
              >
                Só nas vazias
              </button>
            )}
            <button type="button" className="secondary" onClick={() => { setConfirm(null); }}>
              Voltar
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
