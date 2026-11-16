/**
 * Estado do filtro da tela (F3) e as regras puras em volta dele: formato da URL,
 * texto das etiquetas, operadores por tipo e grupos do "Selecionar parâmetro".
 *
 * Combinação (decisão de 2026-11-16, estilo Dalux; quem calcula é o backend):
 * visíveis = regras Isolar (E/OU) menos QUALQUER regra Ocultar; o resultado são as
 * visíveis que batem nas regras Destacar e no texto; o resto visível fica esmaecido.
 */

import type {
  FieldRef,
  FieldType,
  FilterDefinition,
  FilterField,
  FilterLogic,
  FilterMode,
  FilterOp,
  FilterRule,
  SavedFilter,
} from '../../api/filters';

/** Regra na tela: sempre com modo. */
export interface ActiveRule extends FilterRule {
  mode: FilterMode;
}

export interface ActiveFilter {
  q: string;
  logic: FilterLogic;
  rules: ActiveRule[];
  /** Filtro salvo aplicado (marcado na lista; "Atualizar o filtro" grava nele). */
  savedId: number | null;
}

export const EMPTY_FILTER: ActiveFilter = { q: '', logic: 'and', rules: [], savedId: null };
export const DEFAULT_MODE: FilterMode = 'isolate';

export const MODE_LABELS: Record<FilterMode, string> = {
  isolate: 'Isolar',
  hide: 'Ocultar',
  highlight: 'Destacar',
};

export const OP_LABELS: Record<FilterOp, string> = {
  eq: 'é igual a',
  ne: 'é diferente de',
  contains: 'contém',
  not_contains: 'não contém',
  starts_with: 'começa com',
  empty: 'está vazio',
  not_empty: 'não está vazio',
  in: 'é um de',
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  between: 'entre',
  on: 'em',
  before: 'antes de',
  after: 'depois de',
  this_month: 'no mês atual',
  last_month: 'no mês anterior',
  last_n_days: 'nos últimos N dias',
};

/** Mesma lista do backend (filters.py), na ordem em que aparece no seletor. */
export const OPS_BY_TYPE: Record<FieldType, FilterOp[]> = {
  text: ['eq', 'ne', 'contains', 'not_contains', 'starts_with', 'in', 'empty', 'not_empty'],
  number: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', 'empty', 'not_empty'],
  date: ['this_month', 'last_month', 'last_n_days', 'on', 'before', 'after', 'between', 'empty', 'not_empty'],
  bool: ['eq', 'ne'],
};

export const TYPE_LABELS: Record<FieldType, string> = {
  text: 'texto',
  number: 'número',
  date: 'data',
  bool: 'sim/não',
};

const NO_VALUE: ReadonlySet<FilterOp> = new Set(['empty', 'not_empty', 'this_month', 'last_month']);

export function needsValue(op: FilterOp): boolean {
  return !NO_VALUE.has(op);
}

export function defaultOp(type: FieldType): FilterOp {
  return OPS_BY_TYPE[type][0] ?? 'eq';
}

export function defaultValue(type: FieldType, op: FilterOp): unknown {
  if (!needsValue(op)) return undefined;
  if (type === 'bool') return true;
  if (op === 'between') return ['', ''];
  if (op === 'in') return [];
  if (op === 'last_n_days') return 30;
  return '';
}

/** A regra está pronta para valer? (as linhas vazias do Avançado são ignoradas) */
export function isComplete(rule: FilterRule): boolean {
  if (!needsValue(rule.op)) return true;
  const v = rule.value;
  if (Array.isArray(v)) {
    if (rule.op === 'between') return v.length === 2 && v.every((x) => String(x ?? '').trim() !== '');
    return v.length > 0;
  }
  if (typeof v === 'boolean') return true;
  if (typeof v === 'number') return Number.isFinite(v);
  return typeof v === 'string' && v.trim() !== '';
}

export const sameField = (a: FieldRef, b: FieldRef) => a.source === b.source && a.key === b.key;

export function isActive(f: ActiveFilter): boolean {
  return f.q.trim() !== '' || f.rules.some(isComplete);
}

/** Definição enviada ao backend (só as regras completas; números como número). */
export function toDefinition(f: ActiveFilter): FilterDefinition {
  const rules: FilterRule[] = f.rules.filter(isComplete).map((r) => {
    const out: FilterRule = { field: r.field, op: r.op, mode: r.mode };
    if (needsValue(r.op)) out.value = r.op === 'last_n_days' ? Number(r.value) : r.value;
    return out;
  });
  const def: FilterDefinition = { mode: DEFAULT_MODE, logic: f.logic, rules };
  if (f.q.trim()) def.q = f.q.trim();
  return def;
}

export function fromDefinition(def: FilterDefinition, savedId: number | null): ActiveFilter {
  return {
    q: def.q ?? '',
    logic: def.logic,
    rules: def.rules.map((r) => ({ ...r, mode: r.mode ?? def.mode })),
    savedId,
  };
}

export const fromSaved = (saved: SavedFilter): ActiveFilter => fromDefinition(saved.definition, saved.id);

/** O filtro ativo é diferente do filtro salvo de onde veio? */
export function differsFrom(f: ActiveFilter, saved: SavedFilter): boolean {
  return JSON.stringify(toDefinition(f)) !== JSON.stringify(toDefinition(fromSaved(saved)));
}

// ------------------------------------------------------------------ URL

/** Parâmetro da URL com o filtro (link compartilhável). */
export const URL_PARAM = 'f';

interface UrlShape {
  q?: string;
  l?: FilterLogic;
  r?: FilterRule[];
  s?: number;
}

export function encodeFilter(f: ActiveFilter): string | null {
  if (!isActive(f) && f.savedId === null && f.q === '') return null;
  const def = toDefinition(f);
  const out: UrlShape = {};
  if (f.q) out.q = f.q; // como foi digitado (aparar aqui comeria o espaço durante a digitação)
  if (def.logic !== 'and') out.l = def.logic;
  if (def.rules.length) out.r = def.rules;
  if (f.savedId !== null) out.s = f.savedId;
  return JSON.stringify(out);
}

const MODES = new Set<string>(['isolate', 'hide', 'highlight']);
const SOURCES = new Set<string>(['model', 'factory', 'system']);
const OPS = new Set<string>(Object.keys(OP_LABELS));

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function readRule(raw: unknown): ActiveRule | null {
  if (!isRecord(raw) || !isRecord(raw.field)) return null;
  const { source, key } = raw.field;
  if (typeof source !== 'string' || !SOURCES.has(source) || typeof key !== 'string' || !key) return null;
  if (typeof raw.op !== 'string' || !OPS.has(raw.op)) return null;
  const mode = typeof raw.mode === 'string' && MODES.has(raw.mode) ? (raw.mode as FilterMode) : DEFAULT_MODE;
  const rule: ActiveRule = { field: { source: source as FieldRef['source'], key }, op: raw.op as FilterOp, mode };
  if ('value' in raw) rule.value = raw.value;
  return rule;
}

/** Lê o filtro da URL; um link estragado vira "sem filtro" (nunca quebra a tela). */
export function decodeFilter(raw: string | null): ActiveFilter {
  if (!raw) return EMPTY_FILTER;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return EMPTY_FILTER;
    const rules = Array.isArray(parsed.r) ? parsed.r.map(readRule).filter((r): r is ActiveRule => r !== null) : [];
    return {
      q: typeof parsed.q === 'string' ? parsed.q : '',
      logic: parsed.l === 'or' ? 'or' : 'and',
      rules,
      savedId: typeof parsed.s === 'number' ? parsed.s : null,
    };
  } catch {
    return EMPTY_FILTER;
  }
}

// ------------------------------------------------------------------ texto das etiquetas

/** Valor simples como texto (objetos e vazios viram ""). */
export function str(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : '';
}

function formatDate(value: unknown): string {
  const s = str(value);
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? `${m[3] ?? ''}/${m[2] ?? ''}/${m[1] ?? ''}` : s;
}

function formatValue(type: FieldType | undefined, value: unknown): string {
  if (type === 'bool') return value === true ? 'sim' : 'não';
  if (type === 'date') return formatDate(value);
  return str(value);
}

/** "Data de expedição: no mês atual"; com modo diferente de Isolar, o modo vem antes. */
export function ruleText(rule: ActiveRule, field: FilterField | undefined): string {
  const name = field?.name ?? rule.field.key;
  const type = field?.type;
  let tail: string;
  if (rule.op === 'last_n_days') tail = `nos últimos ${str(rule.value)} dias`;
  else if (!needsValue(rule.op)) tail = OP_LABELS[rule.op];
  else if (rule.op === 'between' && Array.isArray(rule.value)) {
    tail = `entre ${formatValue(type, rule.value[0])} e ${formatValue(type, rule.value[1])}`;
  } else if (rule.op === 'in' && Array.isArray(rule.value)) {
    tail = rule.value.map((v) => formatValue(type, v)).join(', ');
    if (rule.value.length > 1) tail = `é um de ${tail}`;
  } else tail = `${OP_LABELS[rule.op]} ${formatValue(type, rule.value)}`;
  const prefix = rule.mode === DEFAULT_MODE ? '' : `${MODE_LABELS[rule.mode]} · `;
  return `${prefix}${name}: ${tail}`;
}

// ------------------------------------------------------------------ grupos do seletor

export const FIELD_GROUPS = ['Fábrica', 'Montagem', 'Identificação', 'Dimensões', 'Outros'] as const;
export type FieldGroup = (typeof FIELD_GROUPS)[number];

const fold = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();

const SYSTEM_GROUPS: Record<string, FieldGroup> = {
  status: 'Fábrica',
  mark: 'Montagem',
  first_version: 'Montagem',
  new: 'Montagem',
  orphan: 'Montagem',
  category: 'Identificação',
  level: 'Identificação',
  name: 'Identificação',
};

/** Grupo do campo no "Selecionar parâmetro" (por origem e pelo nome do grupo do modelo). */
export function fieldGroup(field: FilterField): FieldGroup {
  if (field.source === 'factory') return 'Fábrica';
  if (field.source === 'system') return SYSTEM_GROUPS[field.key] ?? 'Outros';
  const group = fold(field.group ?? '');
  const name = fold(field.name);
  if (group.includes('montagem') || group.includes('assembl') || name.includes('montagem')) return 'Montagem';
  if (/dimens|quantit|cotas|geometr/.test(group)) return 'Dimensões';
  if (/identi|ifc attributes|dados|^marca|mark/.test(group) || /^(marca|mark|tipo|type)/.test(name)) return 'Identificação';
  return 'Outros';
}

/** Busca do seletor: sem diferenciar maiúsculas nem acentos, por nome ou grupo. */
/**
 * Atalhos de digitação do campo de busca (Enter): "sem <parâmetro>" vira "<parâmetro> está
 * vazio" e "Nome=valor" vira "Nome é igual a valor", quando o campo existe na versão.
 */
export function typedRule(text: string, fields: readonly FilterField[]): ActiveRule | null {
  const missing = /^sem\s+(.+)$/i.exec(text.trim());
  if (missing?.[1]) {
    const name = fold(missing[1]).trim();
    const f = fields.find((x) => x.source === 'factory' && fold(x.name).trim() === name);
    return f ? { field: { source: f.source, key: f.key }, op: 'empty', mode: DEFAULT_MODE } : null;
  }
  const eq = text.indexOf('=');
  if (eq <= 0) return null;
  const name = fold(text.slice(0, eq)).trim();
  const value = text.slice(eq + 1).trim();
  const f = fields.find((x) => fold(x.name).trim() === name && x.type !== 'bool');
  if (!f || !value) return null;
  return { field: { source: f.source, key: f.key }, op: f.type === 'date' ? 'on' : 'eq', value, mode: DEFAULT_MODE };
}

export function matchesField(field: FilterField, q: string): boolean {
  const words = fold(q).split(/\s+/).filter(Boolean);
  const hay = fold(`${field.name} ${field.group ?? ''}`);
  return words.every((w) => hay.includes(w));
}
