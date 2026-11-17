import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { ApiError } from '../../api/client';
import {
  fetchMarkUnits,
  markUnitsKey,
  saveUnitValues,
  type MarkUnits,
  type PieceParam,
  type PieceUnit,
  type UnitBatchResult,
} from '../../api/units';
import { errorMessage } from '../../lib/errors';
import { formatParamValue } from '../../lib/format';
import { dateError } from '../params/dateDraft';
import { fieldLabel, fromDraft, toDraft } from '../params/fieldDraft';
import { FieldInput } from '../params/fieldInput';
import { invalidateValueQueries } from '../params/invalidate';
import type { DbId } from '../../viewer/ViewerAdapter';
import { UnitBatchDialog } from './UnitBatchDialog';
import { pecas, rowOf, rowsOf, shortId, valueOf, withoutPiece } from './unitTable';

/**
 * Tipos que gravam ao escolher (lista, sim/não). Texto, número e DATA gravam só ao confirmar:
 * Enter ou sair do campo (a data digitada passa por valores "válidos" a cada tecla, como
 * 05/05/0002, e não pode gravar no onChange: docs/bugs/data-por-peca.md). Esc cancela.
 */
const SAVE_ON_CHANGE = new Set(['list', 'bool']);

interface Editing {
  unitId: number;
  defId: number;
  text: string;
  /** Erro de validação mostrado abaixo do campo (o editor continua aberto). */
  error?: string | null;
}

interface CellProps {
  obraId: number;
  versionId: number;
  unit: PieceUnit;
  param: PieceParam;
  canEdit: boolean;
  editing: Editing | null;
  setEditing: (e: Editing | null) => void;
  onSaved: (unit: PieceUnit) => void;
  onError: (message: string, stale: boolean) => void;
}

function ValueCell({ obraId, versionId, unit, param, canEdit, editing, setEditing, onSaved, onError }: CellProps) {
  const { value, row_version } = valueOf(unit, param.def_id);
  const shown = formatParamValue(param.type, value);
  const label = `${fieldLabel(param)} de ${unit.label}`;
  const input = useRef<HTMLInputElement>(null);
  // Enter grava e desmonta o campo; o blur que pode vir junto não grava de novo.
  const closed = useRef(false);
  const save = useMutation({
    // row_version do momento da gravação (o cache já tem o que o servidor devolveu da anterior)
    mutationFn: ({ text, version }: { text: string; version: number | null }) =>
      saveUnitValues(obraId, unit.id, [{ def_id: param.def_id, value: fromDraft(param, text), row_version: version }], versionId),
    onSuccess: (detail) => { onSaved(detail.unit); },
    onError: (err) => {
      const stale = err instanceof ApiError && err.status === 409 && err.code === 'stale';
      onError(stale ? `Outro usuário alterou ${unit.label} agora há pouco. Os valores foram recarregados.` : errorMessage(err), stale);
    },
  });
  const open = editing?.unitId === unit.id && editing.defId === param.def_id;

  const commit = (text: string) => {
    if (closed.current) return;
    const problem = dateError(param, text, input.current);
    if (problem) {
      setEditing({ unitId: unit.id, defId: param.def_id, text, error: problem });
      return; // não salva; o campo continua aberto com o aviso
    }
    closed.current = true;
    setEditing(null);
    if (text === toDraft(param, value)) return; // nada mudou
    save.mutate({ text, version: row_version });
  };

  if (!canEdit) {
    return <td className={shown ? 'pv-value' : 'muted'}>{shown ?? '—'}</td>;
  }
  if (open) {
    return (
      <td className="unit-cell unit-cell--editing" onClick={(e) => { e.stopPropagation(); }}>
        <FieldInput
          f={param}
          id={`uc-${String(unit.id)}-${String(param.def_id)}`}
          ariaLabel={label}
          autoFocus
          inputRef={input}
          value={editing.text}
          error={editing.error}
          onChange={(v) => {
            if (SAVE_ON_CHANGE.has(param.type)) commit(v);
            else setEditing({ ...editing, text: v, error: null });
          }}
          onBlur={() => { if (!SAVE_ON_CHANGE.has(param.type)) commit(editing.text); else setEditing(null); }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              closed.current = true;
              setEditing(null);
            } else if (e.key === 'Enter') {
              e.preventDefault();
              commit(editing.text);
            }
          }}
        />
      </td>
    );
  }
  return (
    <td className="unit-cell">
      <button
        type="button"
        className={`unit-cell__btn${shown ? ' pv-value' : ' muted'}`}
        aria-label={`${label}: ${shown ?? 'vazio'}`}
        aria-busy={save.isPending}
        onClick={() => {
          closed.current = false;
          setEditing({ unitId: unit.id, defId: param.def_id, text: toDraft(param, value) });
        }}
      >
        {save.isPending ? '…' : (shown ?? '—')}
      </button>
    </td>
  );
}

interface Props {
  obraId: number;
  markId: number;
  versionId: number;
  canEdit: boolean;
  /** Peça em foco (a clicada no 3D ou na tabela): a linha dela fica destacada. */
  focus: DbId | null;
  /** Clique numa linha: destacar só aquela peça no 3D. */
  onPickPiece: (dbid: DbId) => void;
  onBatchApplied: (result: UnitBatchResult) => void;
}

/**
 * "Parâmetros por peça" (P4): uma linha por unidade da marca (nº, nível, identificador
 * curto) e uma coluna por parâmetro por peça. Edição na célula, "Preencher selecionadas".
 * Sem parâmetros por peça para a categoria, não aparece.
 */
export function PieceUnitsSection({ obraId, markId, versionId, canEdit, focus, onPickPiece, onBatchApplied }: Props) {
  const queryClient = useQueryClient();
  const key = markUnitsKey(obraId, markId, versionId);
  const data = useQuery({ queryKey: key, queryFn: () => fetchMarkUnits(obraId, markId, versionId), retry: false });
  const [editing, setEditing] = useState<Editing | null>(null);
  const [checked, setChecked] = useState<ReadonlySet<number>>(new Set());
  const [batch, setBatch] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const focusedRow = useRef<HTMLTableRowElement>(null);

  // Troca de marca: limpa a edição e as linhas marcadas.
  useEffect(() => {
    setEditing(null);
    setChecked(new Set());
    setError(null);
  }, [markId]);

  const rows = rowsOf(data.data?.units ?? []);
  const focused = rowOf(rows, focus);
  // Peça clicada no 3D: a linha dela aparece (rolagem dentro do painel).
  useEffect(() => {
    // (jsdom não tem scrollIntoView)
    (focusedRow.current as Partial<HTMLElement> | null)?.scrollIntoView?.({ block: 'nearest' });
  }, [focused?.id]);

  if (data.isPending) return null;
  if (data.isError) return <p role="alert" className="error small">{errorMessage(data.error)}</p>;
  const params = data.data.params;
  if (params.length === 0) return null; // nenhum parâmetro por peça vale para esta categoria

  const onSaved = (unit: PieceUnit) => {
    setError(null);
    queryClient.setQueryData<MarkUnits>(key, (old) =>
      old ? { ...old, units: old.units.map((u) => (u.id === unit.id ? unit : u)) } : old,
    );
    void invalidateValueQueries(queryClient); // filtro, cores, status e progresso
  };
  const onError = (message: string, stale: boolean) => {
    setError(message);
    if (stale) void data.refetch();
  };

  const toggle = (id: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const allChecked = rows.length > 0 && rows.every((u) => checked.has(u.id));
  const toggleAll = () => { setChecked(allChecked ? new Set() : new Set(rows.map((u) => u.id))); };
  const selected = rows.filter((u) => checked.has(u.id));
  const missing = withoutPiece(data.data.units);

  return (
    <section className="factory-sub unit-sec" aria-labelledby="piece-params">
      <div className="reshead">
        <h5 id="piece-params">Parâmetros por peça</h5>
        <span className="muted small">{pecas(rows.length)}</span>
      </div>
      {error && (
        <p role="alert" className="error small">
          {error}
        </p>
      )}
      {canEdit && (
        <div className="btn-row unit-actions">
          <button
            type="button"
            className="secondary"
            disabled={selected.length === 0}
            onClick={() => { setBatch(true); }}
          >
            Preencher selecionadas{selected.length > 0 ? ` (${String(selected.length)})` : ''}
          </button>
        </div>
      )}
      <div className="unit-table-wrap">
        <table className="unit-table" aria-label="Peças da marca">
          <thead>
            <tr>
              {canEdit && (
                <th className="unit-check">
                  <input type="checkbox" aria-label="Marcar todas as peças" checked={allChecked} onChange={toggleAll} />
                </th>
              )}
              <th>Peça</th>
              {/* Parâmetros logo depois da peça: é o que se preenche; Nível e Id ficam no fim. */}
              {params.map((p) => (
                <th key={p.def_id}>
                  {fieldLabel(p)}
                  {p.required && <span className="req"> *</span>}
                </th>
              ))}
              <th className="unit-meta">Nível</th>
              <th className="unit-meta">Id</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => {
              const isFocus = focused?.id === u.id;
              const dbid = u.element?.dbid;
              return (
                <tr
                  key={u.id}
                  ref={isFocus ? focusedRow : undefined}
                  className={isFocus ? 'unit-row unit-row--focus' : 'unit-row'}
                  aria-selected={isFocus}
                  onClick={() => { if (dbid !== undefined) onPickPiece(dbid); }}
                >
                  {canEdit && (
                    <td className="unit-check" onClick={(e) => { e.stopPropagation(); }}>
                      <input
                        type="checkbox"
                        aria-label={`Marcar ${u.label}`}
                        checked={checked.has(u.id)}
                        onChange={() => { toggle(u.id); }}
                      />
                    </td>
                  )}
                  <th scope="row">
                    <button type="button" className="link unit-label" aria-label={`Mostrar ${u.label} no modelo`}>
                      {u.label}
                    </button>
                  </th>
                  {params.map((p) => (
                    <ValueCell
                      key={p.def_id}
                      obraId={obraId}
                      versionId={versionId}
                      unit={u}
                      param={p}
                      canEdit={canEdit}
                      editing={editing}
                      setEditing={setEditing}
                      onSaved={onSaved}
                      onError={onError}
                    />
                  ))}
                  <td className="unit-meta">{u.element?.level ?? '—'}</td>
                  <td className="unit-meta mono" title={u.element?.external_id ?? u.external_id ?? undefined}>
                    {shortId(u)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {missing > 0 && (
        <p className="hint">
          {missing === 1 ? '1 peça numerada desta marca não está' : `${String(missing)} peças numeradas desta marca não estão`} nesta
          versão do modelo.
        </p>
      )}
      {batch && (
        <UnitBatchDialog
          obraId={obraId}
          unitIds={selected.map((u) => u.id)}
          labels={selected.map((u) => u.label)}
          onClose={() => { setBatch(false); }}
          onApplied={(r) => {
            setChecked(new Set());
            onBatchApplied(r);
          }}
        />
      )}
    </section>
  );
}
