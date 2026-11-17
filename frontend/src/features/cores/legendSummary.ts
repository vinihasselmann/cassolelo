import type { Coloring } from './coloringModel';

const num = (n: number) => n.toLocaleString('pt-BR');

/** Status no resumo: do que avançou para o que falta; plural concordando com "peças". */
const STATUS_WORDS: [label: string, one: string, many: string][] = [
  ['Completa', 'completa', 'completas'],
  ['Parcial', 'parcial', 'parciais'],
  ['Revisar', 'a revisar', 'a revisar'],
  ['Pendente', 'pendente', 'pendentes'],
];

const STATUS_TITLE = 'Status de produção';
const MAX_PARTS = 3;

/** Título curto da pílula ("Status de produção" → "Status"). */
export function shortTitle(title: string): string {
  return title === STATUS_TITLE ? 'Status' : title;
}

/**
 * Resumo da legenda retraída, ex.: "Status · 9 completas · 1.522 pendentes" ou
 * "Tipo de forma · F-11 2 · F-12 1 · +1". Itens sem peças ficam de fora.
 */
export function legendSummary(coloring: Coloring): string {
  const title = shortTitle(coloring.title);
  const parts: string[] = [];
  if (coloring.title === STATUS_TITLE) {
    for (const [label, one, many] of STATUS_WORDS) {
      const n = coloring.legend.find((i) => i.label === label)?.pieces ?? 0;
      if (n > 0) parts.push(`${num(n)} ${n === 1 ? one : many}`);
    }
  } else {
    const items = coloring.legend.filter((i) => i.pieces > 0).sort((a, b) => b.pieces - a.pieces);
    parts.push(...items.slice(0, MAX_PARTS - 1).map((i) => `${i.label} ${num(i.pieces)}`));
    if (items.length > MAX_PARTS - 1) parts.push(`+${String(items.length - (MAX_PARTS - 1))}`);
  }
  if (parts.length === 0) parts.push('nenhuma peça');
  return [title, ...parts.slice(0, MAX_PARTS)].join(' · ');
}
