import { useEffect, useMemo, useState } from 'react';

import type { Evaluation } from '../../api/filters';
import type { MarkStatus } from '../../api/status';
import type { MarkPieces, PieceType } from '../../api/versions';
import { errorMessage } from '../../lib/errors';
import { StatusDot } from '../modelo/StatusBadge';
import { STATUS_LABEL } from '../modelo/statusLabel';
import { markAlt, versionOrigin } from './markOrigin';
import { PieceTypeFilter } from './PieceTypeFilter';

const num = (n: number) => n.toLocaleString('pt-BR');
export const LIST_PAGE_SIZE = 50;

interface Row {
  key: string;
  markId: number | null;
  code: string;
  category: string;
  /** peças que bateram (sem filtro: todas) */
  matched: number;
  total: number;
  /** sem marca: as peças que bateram (para selecionar) */
  dbids: number[];
}

interface Props {
  marks: readonly MarkPieces[];
  evaluation: Evaluation | undefined;
  filtered: boolean;
  loading: boolean;
  error: unknown;
  selectedMarkIds: ReadonlySet<number>;
  onPickMark: (markId: number) => void;
  onPickPieces: (dbids: number[]) => void;
  onSelectAll: (markIds: number[]) => void;
  /** Status de produção de cada marca (agregado das peças); sem dado, a linha fica sem marcador. */
  statusById?: ReadonlyMap<number, MarkStatus>;
}

const NO_STATUS: ReadonlyMap<number, MarkStatus> = new Map();

const SECONDARY_KEY = 'marks.showSecondary';

/** Liga/desliga a 2ª linha (parâmetros secundários); fica no navegador. Padrão: ligada. */
function useShowSecondary(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(SECONDARY_KEY) !== '0';
    } catch {
      return true;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      localStorage.setItem(SECONDARY_KEY, v ? '1' : '0');
    } catch {
      // sem armazenamento (janela privada): vale só nesta tela
    }
  };
  return [on, set];
}

/**
 * Coluna esquerda: as marcas agrupadas pelo Nome da montagem. Com filtro, cada linha diz
 * quantas peças da marca bateram ("12 de 194 peças"); peças sem marca ficam no fim.
 */
export function FilterResultList({
  marks,
  evaluation,
  filtered,
  loading,
  error,
  selectedMarkIds,
  onPickMark,
  onPickPieces,
  onSelectAll,
  statusById = NO_STATUS,
}: Props) {
  const [page, setPage] = useState(1);
  const [showSecondary, setShowSecondary] = useShowSecondary();
  const origin = useMemo(() => versionOrigin(marks), [marks]);
  const byId = useMemo(() => new Map(marks.map((m) => [m.mark_id, m])), [marks]);
  const hasSecondary = useMemo(() => marks.some((m) => (m.secondary ?? []).length > 0), [marks]);
  const [types, setTypes] = useState<ReadonlySet<PieceType>>(() => new Set());
  const typeOf = (markId: number | null): PieceType | undefined =>
    markId === null ? undefined : (byId.get(markId)?.piece_type ?? 'outros');
  const allRows = useMemo((): Row[] => {
    if (!filtered) {
      return [...marks]
        .sort((a, b) => a.code.localeCompare(b.code) || a.category.localeCompare(b.category))
        .map((m) => ({ key: `m${String(m.mark_id)}`, markId: m.mark_id, code: m.code, category: m.category, matched: m.count, total: m.count, dbids: [] }));
    }
    if (!evaluation) return [];
    return evaluation.groups.map((g) => ({
      key: g.mark_id === null ? `s:${g.category}` : `m${String(g.mark_id)}`,
      markId: g.mark_id,
      code: g.code ?? '(sem marca)',
      category: g.category,
      matched: g.matched,
      total: g.total,
      dbids: g.mark_id === null
        ? evaluation.pieces.filter((p) => p.mark_id === null).map((p) => p.dbid)
        : [],
    }));
  }, [marks, evaluation, filtered]);
  // Filtro "Tipo": só as marcas dos tipos marcados (as peças sem marca saem)
  const rows = useMemo(
    () => (types.size === 0 ? allRows : allRows.filter((r) => r.markId !== null && types.has(byId.get(r.markId)?.piece_type ?? 'outros'))),
    [allRows, types, byId],
  );
  const typeCounts = useMemo(() => {
    const out = new Map<PieceType, number>();
    for (const r of allRows) {
      if (r.markId === null || r.matched === 0) continue;
      const t = byId.get(r.markId)?.piece_type ?? 'outros';
      out.set(t, (out.get(t) ?? 0) + 1);
    }
    return out;
  }, [allRows, byId]);
  // Marcar/desmarcar um tipo seleciona no 3D todas as marcas dos tipos marcados
  const changeTypes = (next: Set<PieceType>) => {
    setTypes(next);
    onSelectAll(
      next.size === 0
        ? []
        : allRows.flatMap((r) => {
            const t = typeOf(r.markId);
            return r.markId !== null && r.matched > 0 && t && next.has(t) ? [r.markId] : [];
          }),
    );
  };
  useEffect(() => { setPage(1); }, [rows]);

  const pages = Math.max(1, Math.ceil(rows.length / LIST_PAGE_SIZE));
  const shown = rows.slice((page - 1) * LIST_PAGE_SIZE, page * LIST_PAGE_SIZE);

  return (
    <div className="model-sec">
      <div className="reshead">
        <h3 id="result-title" className="section-title">
          {/* o nome do parâmetro de onde vêm os nomes das peças (regra da obra) */}
          {origin.split.length === 1 && origin.main ? origin.main : 'Marcas'} (
          {num(types.size > 0 ? rows.length : filtered ? (evaluation?.matched_marks ?? 0) : marks.length)})
          {loading && <span className="muted small"> filtrando…</span>}
        </h3>
        <PieceTypeFilter counts={typeCounts} selected={types} onChange={changeTypes} />
      </div>
      {origin.split.length > 1 && (
        <p className="origin-line">
          Origem: {origin.split.map((s) => `${s.name} ${num(s.pieces)}`).join(' · ')} peças
        </p>
      )}
      {hasSecondary && (
        <label className="check origin-line">
          <input
            type="checkbox"
            checked={showSecondary}
            onChange={(e) => { setShowSecondary(e.target.checked); }}
          />
          Parâmetros secundários
        </label>
      )}
      {filtered && evaluation && (
        <p className="hint" role="status">
          {num(evaluation.matched_pieces)} de {num(evaluation.total_pieces)} peças no filtro
        </p>
      )}
      {error !== null && error !== undefined && (
        <p role="alert" className="error small">
          {errorMessage(error)}
        </p>
      )}
      {rows.length === 0 && !loading && (filtered ? evaluation !== undefined : true) && (
        <p className="muted small">{filtered ? 'Nenhuma peça no filtro.' : 'Nenhuma marca nesta versão.'}</p>
      )}
      {shown.length > 0 && (
        <ul className="mark-list" aria-labelledby="result-title">
          {shown.map((r) => {
            const orphan = r.markId !== null && r.total === 0;
            const qty = orphan
              ? 'órfã'
              : filtered
                ? `${num(r.matched)} de ${num(r.total)} ${r.total === 1 ? 'peça' : 'peças'}`
                : `${num(r.total)} ${r.total === 1 ? 'peça' : 'peças'}`;
            const status = r.markId !== null && !orphan ? statusById.get(r.markId) : undefined;
            const mark = r.markId !== null ? byId.get(r.markId) : undefined;
            const alt = mark ? markAlt(mark, origin.main) : null;
            const showAlt = alt !== null && (alt.via.length > 0 || (showSecondary && alt.secondary.length > 0));
            return (
              <li key={r.key}>
                <button
                  type="button"
                  className={`list-item mark-item${r.markId === null ? ' mark-item--loose' : ''}`}
                  aria-pressed={r.markId !== null && selectedMarkIds.has(r.markId)}
                  disabled={orphan}
                  title={orphan ? 'Marca órfã: não tem peças nesta versão' : undefined}
                  onClick={() => { if (r.markId === null) onPickPieces(r.dbids); else onPickMark(r.markId); }}
                >
                  <span className="mark-item__status" title={status ? STATUS_LABEL[status] : undefined}>
                    {status && <StatusDot status={status} />}
                  </span>
                  <span className="mark-item__code">{r.code}</span>
                  <span className="mark-item__cat">{r.category}</span>
                  <span className="mark-item__qty">
                    {qty}
                    {status && <span className="sr-only">, {STATUS_LABEL[status]}</span>}
                  </span>
                  {showAlt && (
                    <span className="mark-item__alt">
                      {alt.via.length > 0 && (
                        <span className="mark-item__via" title={`O nome destas peças veio de ${alt.via.join(', ')}`}>
                          via {alt.via.join(', ')}
                        </span>
                      )}
                      {showSecondary &&
                        alt.secondary.map((s) => (
                          <span
                            key={s.name}
                            className={s.divergent ? 'mark-item__warn' : undefined}
                            title={
                              s.divergent
                                ? `As peças desta marca têm valores diferentes em ${s.name}. Vale ${origin.main ?? 'o primeiro parâmetro da regra'}.`
                                : undefined
                            }
                          >
                            {s.divergent && <span aria-hidden="true">⚠ </span>}
                            {s.name}: {s.values.join(', ')}
                            {s.partial && ` (${num(s.pieces)} de ${num(mark?.count ?? 0)})`}
                            {s.divergent && <span className="sr-only"> (valores diferentes)</span>}
                          </span>
                        ))}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {pages > 1 && (
        <div className="pager">
          <button type="button" className="secondary" disabled={page <= 1} onClick={() => { setPage(page - 1); }}>
            Anterior
          </button>
          <span className="small">
            Página {page} de {pages}
          </span>
          <button type="button" className="secondary" disabled={page >= pages} onClick={() => { setPage(page + 1); }}>
            Próxima
          </button>
        </div>
      )}
    </div>
  );
}
