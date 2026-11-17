import type { Coloring, LegendRow } from './coloringModel';
import { legendSummary, shortTitle } from './legendSummary';

const row = (label: string, pieces: number): LegendRow => ({ key: label, label, color: '#000000', pieces, marks: 0, dbids: [] });
const coloring = (title: string, legend: LegendRow[]): Coloring => ({ title, colors: new Map(), legend });

describe('resumo da legenda retraída', () => {
  it('status: do avanço ao pendente, plural concordando e milhar em pt-BR; zeros ficam de fora', () => {
    const c = coloring('Status de produção', [row('Pendente', 1522), row('Parcial', 0), row('Completa', 9), row('Revisar', 0), row('Sem marca', 3)]);
    expect(legendSummary(c)).toBe('Status · 9 completas · 1.522 pendentes');
    expect(legendSummary(coloring('Status de produção', [row('Pendente', 1), row('Revisar', 2)]))).toBe('Status · 2 a revisar · 1 pendente');
  });

  it('parâmetro: título e os maiores grupos, com "+N" para o resto', () => {
    const c = coloring('Tipo de forma', [row('F-11', 2), row('F-12', 1), row('Sem valor', 5), row('F-13', 1)]);
    expect(legendSummary(c)).toBe('Tipo de forma · Sem valor 5 · F-11 2 · +2');
  });

  it('sem peças coloridas', () => {
    expect(legendSummary(coloring('Tipo de forma', []))).toBe('Tipo de forma · nenhuma peça');
    expect(shortTitle('Status de produção')).toBe('Status');
  });
});
