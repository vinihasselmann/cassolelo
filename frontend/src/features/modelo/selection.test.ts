import { describe, expect, it } from 'vitest';

import type { MarkPieces } from '../../api/versions';
import {
  buildMarkIndex,
  EMPTY_SELECTION,
  pieceCount,
  refreshSelection,
  resolveClick,
  selectionDbIds,
  type Selection,
} from './selection';

const PP001: MarkPieces = { mark_id: 1, code: 'PP001', category: 'Pilar', count: 3, dbids: [1, 2, 3] };
const V01: MarkPieces = { mark_id: 2, code: 'V-01', category: 'Viga', count: 2, dbids: [4, 5] };
const index = buildMarkIndex([PP001, V01]);

const click = (ids: number[], current: Selection = EMPTY_SELECTION, multi = false) =>
  resolveClick(ids, index, current, multi);

describe('resolveClick', () => {
  it('clique simples seleciona a marca inteira da peça', () => {
    const sel = click([2]);
    expect(sel.marks).toEqual([PP001]);
    expect(selectionDbIds(sel)).toEqual([1, 2, 3]);
    expect(sel.focus).toBe(2);
    expect(pieceCount(sel)).toBe(3);
  });

  it('clique simples numa outra marca substitui a seleção', () => {
    expect(click([4], click([2])).marks).toEqual([V01]);
  });

  it('peça sem Marca é selecionada sozinha', () => {
    const sel = click([99]);
    expect(sel).toEqual({ marks: [], unmarked: [99], focus: 99 });
  });

  it('clique no vazio limpa; no modo múltiplo mantém', () => {
    const sel = click([2]);
    expect(click([], sel)).toEqual(EMPTY_SELECTION);
    expect(click([], sel, true)).toBe(sel);
  });

  it('Ctrl+clique (seleção acumulada do Viewer) soma a marca nova', () => {
    const sel = click([1, 2, 3, 5], click([2]));
    expect(sel.marks).toEqual([PP001, V01]);
    expect(sel.focus).toBe(5);
  });

  it('Ctrl+clique tirando uma peça já selecionada tira a marca dela', () => {
    const both = click([1, 2, 3, 5], click([2]));
    const sel = click([1, 2, 3, 4], both); // o Viewer tirou o 5
    expect(sel.marks).toEqual([PP001]);
    expect(sel.focus).toBe(3); // o foco (5) saiu: passa para a última peça que sobrou
  });

  it('modo múltiplo: toque soma marcas e tocar de novo tira', () => {
    let sel = click([2], EMPTY_SELECTION, true);
    sel = click([4], sel, true);
    sel = click([99], sel, true);
    expect(selectionDbIds(sel)).toEqual([1, 2, 3, 4, 5, 99]);
    sel = click([3], sel, true); // PP001 já estava: sai
    expect(sel.marks).toEqual([V01]);
    expect(sel.unmarked).toEqual([99]);
    sel = click([99], sel, true);
    expect(sel.unmarked).toEqual([]);
  });
});

describe('buildMarkIndex com montagens', () => {
  it('um clique num membro (consolo, alça) acha a marca; o dbId da peça vence', () => {
    const PP312: MarkPieces = {
      mark_id: 3, code: 'PP312', category: 'Pilar', count: 1, dbids: [10], member_dbids: [11, 17, 4],
    };
    const idx = buildMarkIndex([V01, PP312]);
    expect(idx.get(17)).toBe(PP312);
    expect(idx.get(10)).toBe(PP312);
    expect(idx.get(4)).toBe(V01); // 4 é peça da V-01: não vira membro de outra marca
    const sel = resolveClick([17], idx, EMPTY_SELECTION, false);
    expect(selectionDbIds(sel)).toEqual([10]); // seleciona a peça (o nó do vínculo)
  });
});

describe('refreshSelection (clique antes de as marcas carregarem)', () => {
  it('a peça que entrou "sem Marca" passa para a marca quando o índice chega; o foco fica', () => {
    const early = resolveClick([2], buildMarkIndex([]), EMPTY_SELECTION, false);
    expect(early).toEqual({ marks: [], unmarked: [2], focus: 2 });
    const fixed = refreshSelection(early, index);
    expect(fixed.marks.map((m) => m.code)).toEqual(['PP001']);
    expect(fixed.unmarked).toEqual([]);
    expect(fixed.focus).toBe(2);
  });

  it('sem nada a corrigir devolve a mesma seleção (peça realmente sem Marca, ou já com marca)', () => {
    const none = click([99]);
    expect(refreshSelection(none, index)).toBe(none);
    const marked = click([1]);
    expect(refreshSelection(marked, index)).toBe(marked);
  });
});
