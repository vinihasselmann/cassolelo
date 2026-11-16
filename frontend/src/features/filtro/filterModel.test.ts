import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { FilterField, SavedFilter } from '../../api/filters';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import {
  decodeFilter,
  differsFrom,
  EMPTY_FILTER,
  encodeFilter,
  fieldGroup,
  fromSaved,
  isActive,
  isComplete,
  matchesField,
  ruleText,
  toDefinition,
  type ActiveFilter,
  type ActiveRule,
  typedRule,
} from './filterModel';

const field = (over: Partial<FilterField>): FilterField => ({
  source: 'model', key: 'G/N', name: 'N', group: 'G', type: 'text', distinct_values: 1, pieces: 1, ...over,
});
const EXP = field({ source: 'factory', key: '5', name: 'Data de expedição', group: 'Fábrica', type: 'date' });
const rule = (over: Partial<ActiveRule>): ActiveRule => ({ field: { source: 'factory', key: '5' }, op: 'this_month', mode: 'isolate', ...over });

describe('filterModel', () => {
  it('URL: ida e volta, texto como foi digitado, link estragado vira "sem filtro"', () => {
    const f: ActiveFilter = {
      q: 'pp ', logic: 'or', savedId: 3,
      rules: [rule({}), rule({ op: 'between', value: ['2026-11-01', ''] })], // a 2ª está incompleta
    };
    const raw = encodeFilter(f);
    expect(JSON.parse(raw ?? '')).toEqual({ q: 'pp ', l: 'or', s: 3, r: [{ field: { source: 'factory', key: '5' }, op: 'this_month', mode: 'isolate' }] });
    expect(decodeFilter(raw)).toEqual({ q: 'pp ', logic: 'or', savedId: 3, rules: [rule({})] });
    expect(encodeFilter(EMPTY_FILTER)).toBeNull();
    for (const bad of ['{', '[]', '"x"', JSON.stringify({ r: [{ field: { source: 'x', key: 'y' }, op: 'eq' }, { op: 'drop' }] })]) {
      expect(decodeFilter(bad)).toEqual(EMPTY_FILTER);
    }
    expect(decodeFilter(JSON.stringify({ r: [{ field: { source: 'system', key: 'level' }, op: 'eq', value: 'T', mode: '??' }] })).rules[0]?.mode).toBe('isolate');
  });

  it('definição enviada: só regras completas, texto aparado, dias como número', () => {
    const f: ActiveFilter = {
      q: '  pp1 ', logic: 'and', savedId: null,
      rules: [rule({ op: 'last_n_days', value: '30' }), rule({ op: 'on', value: '' }), rule({ op: 'empty', mode: 'hide' })],
    };
    expect(toDefinition(f)).toEqual({
      mode: 'isolate', logic: 'and', q: 'pp1',
      rules: [
        { field: { source: 'factory', key: '5' }, op: 'last_n_days', value: 30, mode: 'isolate' },
        { field: { source: 'factory', key: '5' }, op: 'empty', mode: 'hide' },
      ],
    });
    expect(isActive({ ...EMPTY_FILTER, rules: [rule({ op: 'on', value: '' })] })).toBe(false);
    expect(isActive({ ...EMPTY_FILTER, q: ' ' })).toBe(false);
  });

  it('regra completa por operador', () => {
    expect(isComplete(rule({ op: 'this_month' }))).toBe(true);
    expect(isComplete(rule({ op: 'on', value: '2026-11-16' }))).toBe(true);
    expect(isComplete(rule({ op: 'between', value: ['1', ''] }))).toBe(false);
    expect(isComplete(rule({ op: 'in', value: [] }))).toBe(false);
    expect(isComplete(rule({ op: 'eq', value: false }))).toBe(true);
    expect(isComplete(rule({ op: 'eq', value: '  ' }))).toBe(false);
  });

  it('texto das etiquetas', () => {
    expect(ruleText(rule({}), EXP)).toBe('Data de expedição: no mês atual');
    expect(ruleText(rule({ op: 'on', value: '2026-11-05' }), EXP)).toBe('Data de expedição: em 05/11/2026');
    expect(ruleText(rule({ op: 'last_n_days', value: 7 }), EXP)).toBe('Data de expedição: nos últimos 7 dias');
    expect(ruleText(rule({ op: 'between', value: ['2026-11-01', '2026-11-30'], mode: 'hide' }), EXP)).toBe(
      'Ocultar · Data de expedição: entre 01/11/2026 e 30/11/2026',
    );
    const cat = field({ source: 'system', key: 'category', name: 'Categoria' });
    expect(ruleText(rule({ field: cat, op: 'in', value: ['Pilar'] }), cat)).toBe('Categoria: Pilar');
    expect(ruleText(rule({ field: cat, op: 'in', value: ['Pilar', 'Viga'], mode: 'highlight' }), cat)).toBe('Destacar · Categoria: é um de Pilar, Viga');
    const sim = field({ type: 'bool', name: 'Nova na versão' });
    expect(ruleText(rule({ field: sim, op: 'eq', value: true }), sim)).toBe('Nova na versão: é igual a sim');
    expect(ruleText(rule({ field: { source: 'model', key: 'X/Y' }, op: 'eq', value: 'a' }), undefined)).toBe('X/Y: é igual a a');
  });

  it('grupos do "Selecionar parâmetro" e busca sem acento', () => {
    expect(fieldGroup(EXP)).toBe('Fábrica');
    expect(fieldGroup(field({ source: 'system', key: 'status' }))).toBe('Fábrica');
    expect(fieldGroup(field({ source: 'system', key: 'mark' }))).toBe('Montagem');
    expect(fieldGroup(field({ source: 'system', key: 'level' }))).toBe('Identificação');
    expect(fieldGroup(field({ group: 'Dimensões', name: 'Altura' }))).toBe('Dimensões');
    expect(fieldGroup(field({ group: 'Corpo · BaseQuantities', name: 'NetVolume' }))).toBe('Dimensões');
    expect(fieldGroup(field({ group: 'Dados de identidade', name: 'Comentários' }))).toBe('Identificação');
    expect(fieldGroup(field({ group: 'Outros', name: 'Nome da montagem' }))).toBe('Montagem');
    expect(fieldGroup(field({ group: 'Restrições', name: 'Nível base' }))).toBe('Outros');
    expect(matchesField(EXP, 'expedicao')).toBe(true);
    expect(matchesField(EXP, 'fabrica data')).toBe(true);
    expect(matchesField(EXP, 'forma')).toBe(false);
  });

  it('filtro salvo: modo das regras herdado e "alterado"', () => {
    const saved: SavedFilter = {
      id: 9, name: 'Expedidas', scope: 'personal', owner_id: 1, obra_id: 7, system_key: null, editable: true,
      definition: { mode: 'highlight', logic: 'and', rules: [{ field: { source: 'factory', key: '5' }, op: 'this_month' }] },
      created_at: '', updated_at: '', created_by: 1, updated_by: 1,
    };
    const f = fromSaved(saved);
    expect(f).toEqual({ q: '', logic: 'and', savedId: 9, rules: [rule({ mode: 'highlight' })] });
    expect(differsFrom(f, saved)).toBe(false);
    expect(differsFrom({ ...f, q: 'pp' }, saved)).toBe(true);
  });

  it('atalhos de digitação: "sem X" e "Nome=valor" viram regras quando o campo existe', () => {
    const fields = [field({ source: 'factory', key: '1', name: 'Tipo de forma' }), field({ key: 'Dimensões/Altura', name: 'Altura', type: 'number' }), EXP];
    expect(typedRule('sem tipo de forma', fields)).toEqual({ field: { source: 'factory', key: '1' }, op: 'empty', mode: 'isolate' });
    expect(typedRule('altura = 50', fields)).toEqual({ field: { source: 'model', key: 'Dimensões/Altura' }, op: 'eq', value: '50', mode: 'isolate' });
    expect(typedRule('Data de expedição=2026-11-05', fields)?.op).toBe('on');
    expect(typedRule('sem nada', fields)).toBeNull();
    expect(typedRule('pp001', fields)).toBeNull();
    expect(typedRule('Altura=', fields)).toBeNull();
  });

  it('useDebouncedValue só muda depois do intervalo sem alterações', () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 250), { initialProps: { v: 'a' } });
    rerender({ v: 'ab' });
    act(() => { vi.advanceTimersByTime(200); });
    rerender({ v: 'abc' });
    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current).toBe('a');
    act(() => { vi.advanceTimersByTime(60); });
    expect(result.current).toBe('abc');
    vi.useRealTimers();
  });
});
