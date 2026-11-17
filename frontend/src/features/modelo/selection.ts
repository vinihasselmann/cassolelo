/**
 * Seleção por MARCA: clicar numa peça seleciona todas as peças da mesma marca,
 * usando os dbIds de GET /api/versions/{id}/marks (nunca getProperties do Viewer).
 */

import type { MarkPieces } from '../../api/versions';
import type { DbId } from '../../viewer/ViewerAdapter';

export interface Selection {
  marks: MarkPieces[];
  /** Peças sem Marca selecionadas (cada uma vale por si). */
  unmarked: DbId[];
  /** Peça cujas propriedades aparecem no painel (a última clicada). */
  focus: DbId | null;
}

export const EMPTY_SELECTION: Selection = { marks: [], unmarked: [], focus: null };

export type MarkIndex = ReadonlyMap<DbId, MarkPieces>;

export function buildMarkIndex(marks: readonly MarkPieces[]): MarkIndex {
  const index = new Map<DbId, MarkPieces>();
  for (const mark of marks) {
    // membros primeiro: o dbId da própria peça sempre vence
    for (const dbid of mark.member_dbids ?? []) if (!index.has(dbid)) index.set(dbid, mark);
    for (const dbid of mark.dbids) index.set(dbid, mark);
  }
  return index;
}

export function selectionDbIds(sel: Selection): DbId[] {
  return [...sel.marks.flatMap((m) => m.dbids), ...sel.unmarked];
}

export function pieceCount(sel: Selection): number {
  return sel.marks.reduce((n, m) => n + m.count, 0) + sel.unmarked.length;
}

function add(current: Selection, ids: DbId[], index: MarkIndex, focus: DbId | null): Selection {
  const marks = [...current.marks];
  const unmarked = [...current.unmarked];
  for (const id of ids) {
    const mark = index.get(id);
    if (mark) {
      if (!marks.some((m) => m.mark_id === mark.mark_id)) marks.push(mark);
    } else if (!unmarked.includes(id)) {
      unmarked.push(id);
    }
  }
  return { marks, unmarked, focus };
}

function remove(current: Selection, ids: DbId[], index: MarkIndex): Selection {
  const removedMarks = new Set(ids.map((id) => index.get(id)?.mark_id).filter((x) => x !== undefined));
  const next: Selection = {
    marks: current.marks.filter((m) => !removedMarks.has(m.mark_id)),
    unmarked: current.unmarked.filter((id) => !ids.includes(id)),
    focus: null,
  };
  const remaining = selectionDbIds(next);
  next.focus = current.focus !== null && remaining.includes(current.focus) ? current.focus : (remaining.at(-1) ?? null);
  return next;
}

/**
 * Nova seleção a partir dos dbIds que o Viewer informou após um clique do usuário.
 *
 * - Clique simples: a marca da peça clicada (substitui a seleção).
 * - Ctrl+clique (o Viewer devolve a seleção acumulada) ou modo "Seleção múltipla":
 *   peça nova acrescenta a marca dela; peça já selecionada retira a marca dela.
 * - Clique no vazio: limpa (no modo múltiplo, mantém a seleção).
 */
export function resolveClick(
  ids: readonly DbId[],
  index: MarkIndex,
  current: Selection,
  multi: boolean,
): Selection {
  if (ids.length === 0) return multi ? current : EMPTY_SELECTION;
  const selected = new Set(selectionDbIds(current));
  const additive = multi || ids.length > 1;
  if (!additive) {
    const [only] = ids;
    return only === undefined ? EMPTY_SELECTION : add(EMPTY_SELECTION, [only], index, only);
  }
  const fresh = ids.filter((id) => !selected.has(id));
  if (fresh.length > 0) return add(current, fresh, index, fresh.at(-1) ?? null);
  // Nada novo: o usuário clicou numa peça já selecionada (modo múltiplo) ou
  // tirou uma com Ctrl+clique (o Viewer devolve o que sobrou).
  const removed = ids.length === 1 ? [...ids] : [...selected].filter((id) => !ids.includes(id));
  return remove(current, removed, index);
}

/** Seleção a partir de peças (ex.: um item da legenda): as marcas delas e as peças sem marca. */
export function selectPieces(ids: readonly DbId[], index: MarkIndex): Selection {
  return ids.length === 0 ? EMPTY_SELECTION : add(EMPTY_SELECTION, [...ids], index, ids[0] ?? null);
}

/**
 * O índice de marcas chegou (ou mudou) depois do clique: peças que estavam "sem Marca" só
 * porque o índice ainda não tinha carregado passam para a marca delas. A peça em foco não muda.
 * Sem nada a corrigir, devolve a mesma seleção (sem re-render).
 */
export function refreshSelection(current: Selection, index: MarkIndex): Selection {
  if (!current.unmarked.some((id) => index.has(id))) return current;
  return { ...selectPieces(selectionDbIds(current), index), focus: current.focus };
}
