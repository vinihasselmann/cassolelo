/**
 * Coloração do modelo (F4): o que está escolhido e como a legenda é montada.
 * As cores vêm do backend (/colorize e /color-scheme/evaluate); aqui só se organiza.
 */

import type { ColorizeMode, ColorizeResult, SchemeResult } from '../../api/colors';
import type { FieldRef } from '../../api/filters';
import { plural } from '../../lib/format';
import { STATUS_COLORS, STATUS_ORDER } from '../../lib/palette';
import type { DbId, HexColor } from '../../viewer/ViewerAdapter';

export type ColoringChoice =
  | { kind: 'field'; field: FieldRef; mode: ColorizeMode }
  | { kind: 'scheme'; schemeId: number; name: string };

export const STATUS_FIELD: FieldRef = { source: 'system', key: 'status' };
export const CATEGORY_FIELD: FieldRef = { source: 'system', key: 'category' };
/** Padrão ao abrir a tela: status de produção. */
export const DEFAULT_COLORING: ColoringChoice = { kind: 'field', field: STATUS_FIELD, mode: 'distinct' };

/** Status sempre nesta ordem (mesmo com zero peças); cores em lib/palette.ts. */
export { STATUS_ORDER };

/** Campos que não dá para colorir: sim/não e os calculados na hora. */
export const NOT_COLORABLE = new Set(['system:new', 'system:orphan']);

export interface LegendRow {
  key: string;
  label: string;
  color: HexColor;
  pieces: number;
  /** marcas com peças neste item */
  marks: number;
  /** peças do item (para selecionar) */
  dbids: DbId[];
}

export interface Coloring {
  title: string;
  colors: Map<DbId, HexColor>;
  legend: LegendRow[];
  note?: string;
}

export const sameRef = (a: FieldRef, b: FieldRef) => a.source === b.source && a.key === b.key;

function toMap(colors: Record<string, string>): Map<DbId, HexColor> {
  return new Map(Object.entries(colors).map(([k, v]) => [Number(k), v]));
}

type MarkOf = (dbid: DbId) => number | undefined;

function marksIn(dbids: readonly DbId[], markOf: MarkOf): number {
  const set = new Set<number>();
  for (const d of dbids) {
    const m = markOf(d);
    if (m !== undefined) set.add(m);
  }
  return set.size;
}

/** Legenda da coloração por campo. Status: ordem fixa e os quatro sempre presentes. */
export function fromColorize(result: ColorizeResult, field: FieldRef, markOf: MarkOf): Coloring {
  let items = result.legend.map((i) => ({ key: i.value ?? i.label, label: i.label, color: i.color, pieces: i.pieces, dbids: i.dbids }));
  if (sameRef(field, STATUS_FIELD)) {
    const byLabel = new Map(items.map((i) => [i.label, i]));
    const fixed = STATUS_ORDER.map(
      (s) => byLabel.get(s) ?? { key: s, label: s, color: STATUS_COLORS[s], pieces: 0, dbids: [] },
    );
    items = [...fixed, ...items.filter((i) => !(STATUS_ORDER as readonly string[]).includes(i.label))];
  }
  const legend = items.map((i) => ({ ...i, marks: marksIn(i.dbids, markOf) }));
  const title = result.mode === 'range' ? `${result.field_name} (por gama)` : result.field_name;
  return { title, colors: toMap(result.colors), legend };
}

/** Legenda do esquema: uma linha por regra, na ordem (a ordem é a prioridade). */
export function fromScheme(result: SchemeResult, name: string, markOf: MarkOf): Coloring {
  const legend = result.rules.map((r) => ({
    key: `r${String(r.index)}`,
    label: r.label,
    color: r.color,
    pieces: r.pieces,
    dbids: r.dbids,
    marks: marksIn(r.dbids, markOf),
  }));
  const rest = result.total_pieces - result.colored_pieces;
  const notes = [...result.notes];
  if (rest > 0) notes.push(`${plural(rest, 'peça sem regra fica', 'peças sem regra ficam')} com a cor original.`);
  const coloring: Coloring = { title: name, colors: toMap(result.colors), legend };
  if (notes.length) coloring.note = notes.join(' ');
  return coloring;
}

/** Cores para novas regras do esquema (contrastantes, sem cinza). */
export const RULE_PALETTE: HexColor[] = ['#E8743B', '#2CA02C', '#1F77B4', '#D62728', '#9467BD', '#E3B341', '#17BECF', '#E377C2'];
