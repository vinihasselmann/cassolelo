import { describe, expect, it } from 'vitest';

import { DATE_INVALID, dateError, dateErrors, isValidDate, withoutKey } from './dateDraft';

describe('validação de data (1900–2100, completa)', () => {
  it.each([
    ['2026-05-05', true],
    ['1900-01-01', true],
    ['2100-12-31', true],
    ['2024-02-29', true],
    ['0002-05-05', false], // o bug: ano de um dígito
    ['0020-11-16', false],
    ['1899-12-31', false],
    ['2101-01-01', false],
    ['2026-02-30', false], // não existe
    ['2026-13-01', false],
    ['2023-02-29', false],
    ['05/05/2026', false],
    ['2026-5-5', false],
    ['', false],
  ])('%s → %s', (text, ok) => {
    expect(isValidDate(text)).toBe(ok);
  });

  it('a mensagem é a mesma do backend', () => {
    expect(DATE_INVALID).toBe('Data inválida: use dd/mm/aaaa');
  });

  it('vazio apaga (sem erro); campo incompleto (badInput) é erro, não apagar', () => {
    const date = { type: 'date' };
    expect(dateError(date, '')).toBeNull();
    expect(dateError(date, '2026-05-05')).toBeNull();
    expect(dateError(date, '0002-05-05')).toBe(DATE_INVALID);
    const partial = { validity: { badInput: true } } as HTMLInputElement;
    expect(dateError(date, '', partial)).toBe(DATE_INVALID);
  });

  it('outros tipos não são validados aqui', () => {
    expect(dateError({ type: 'text' }, '0002-05-05')).toBeNull();
    expect(dateError({ type: 'number' }, 'abc')).toBeNull();
  });

  it('formulário: erro só nos campos de data inválidos', () => {
    const form = document.createElement('form');
    form.innerHTML = '<input type="date" id="pv-1"><input id="pv-2">';
    const fields = [
      { def_id: 1, type: 'date' },
      { def_id: 2, type: 'text' },
    ];
    const id = (f: { def_id: number }) => `pv-${String(f.def_id)}`;
    expect(dateErrors(fields, { 1: '0002-01-01', 2: 'x' }, form, id)).toEqual({ 1: DATE_INVALID });
    expect(dateErrors(fields, { 1: '2026-01-01', 2: 'x' }, form, id)).toEqual({});
    expect(withoutKey({ 1: 'a', 2: 'b' }, 1)).toEqual({ 2: 'b' });
  });
});
