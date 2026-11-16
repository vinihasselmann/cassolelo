import { describe, expect, it } from 'vitest';

import type { ColorizeResult, SchemeResult } from '../../api/colors';
import { CATEGORY_FIELD, fromColorize, fromScheme, STATUS_FIELD } from './coloringModel';

const markOf = (dbid: number) => ({ 10: 1, 11: 1, 12: 2, 20: 3 } as Record<number, number | undefined>)[dbid];
const item = (label: string, color: string, dbids: number[], value: string | null = label) => ({
  label, color, pieces: dbids.length, value, min: null, max: null, dbids,
});

describe('coloringModel', () => {
  it('status: ordem fixa, os quatro sempre presentes e "Sem valor" no fim; marcas contadas pelas peças', () => {
    const result: ColorizeResult = {
      mode: 'distinct', field_name: 'Status de produção', field_type: 'text', total_pieces: 5,
      colors: { '10': '#33A06F', '30': '#9AA0A6' },
      legend: [item('Completa', '#33A06F', [10, 11, 12]), item('Pendente', '#B9BEC6', [20]), item('Sem valor', '#9AA0A6', [30], null)],
    };
    const c = fromColorize(result, STATUS_FIELD, markOf);
    expect(c.legend.map((i) => [i.label, i.pieces, i.marks])).toEqual([
      ['Pendente', 1, 1], ['Parcial', 0, 0], ['Completa', 3, 2], ['Revisar', 0, 0], ['Sem valor', 1, 0],
    ]);
    expect(c.colors.get(10)).toBe('#33A06F');
    expect(c.title).toBe('Status de produção');
  });

  it('campo comum mantém a ordem do backend; gama vai no título', () => {
    const result: ColorizeResult = {
      mode: 'range', field_name: 'Altura', field_type: 'number', total_pieces: 2, colors: {},
      legend: [item('40 – 50', '#C6DBEF', [10], null), item('50 – 60', '#0B3C78', [20], null)],
    };
    const c = fromColorize(result, CATEGORY_FIELD, markOf);
    expect(c.title).toBe('Altura (por gama)');
    expect(c.legend.map((i) => i.label)).toEqual(['40 – 50', '50 – 60']);
  });

  it('esquema: uma linha por regra e aviso das peças sem regra', () => {
    const result: SchemeResult = {
      colors: { '20': '#FF0000' }, total_pieces: 6, colored_pieces: 2, notes: ['Regra 2: ignorada.'],
      rules: [
        { index: 0, label: 'Expedidas', color: '#FF0000', filter_id: 1, matched: 2, pieces: 2, dbids: [20, 21] },
        { index: 1, label: 'Antigo', color: '#00FF00', filter_id: 9, matched: 0, pieces: 0, dbids: [] },
      ],
    };
    const c = fromScheme(result, 'Meu esquema', markOf);
    expect(c.title).toBe('Meu esquema');
    expect(c.legend.map((i) => [i.label, i.pieces, i.marks])).toEqual([['Expedidas', 2, 1], ['Antigo', 0, 0]]);
    expect(c.note).toBe('Regra 2: ignorada. 4 peça(s) sem regra ficam com a cor original.');
  });
});
