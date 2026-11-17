/**
 * Validação de DATA no frontend (docs/bugs/data-por-peca.md). Mesma regra do backend
 * (`mark_values.valid_date`): data completa, existente, com ano entre 1900 e 2100.
 */

export const DATE_MIN_YEAR = 1900;
export const DATE_MAX_YEAR = 2100;
export const DATE_INVALID = 'Data inválida: use dd/mm/aaaa';

/** 'AAAA-MM-DD' completa, existente e com ano em 1900–2100. */
export function isValidDate(text: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (y < DATE_MIN_YEAR || y > DATE_MAX_YEAR) return false;
  const dt = new Date(Date.UTC(y, mo - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d;
}

/**
 * Erro do campo de data, ou null se pode salvar. `el` é o <input type="date">: com algum
 * segmento faltando (ex.: só dia e mês), o navegador dá `value` vazio e `validity.badInput`;
 * isso NÃO é "apagar" (apagar é o campo totalmente vazio).
 */
export function dateError(f: { type: string }, text: string, el?: HTMLInputElement | null): string | null {
  if (f.type !== 'date') return null;
  if (el?.validity.badInput) return DATE_INVALID;
  if (text.trim() === '') return null;
  return isValidDate(text) ? null : DATE_INVALID;
}

/** O <input> de data de um campo dentro do formulário (pelo id do campo). */
export function dateInputOf(form: HTMLFormElement, id: string): HTMLInputElement | null {
  const el = form.elements.namedItem(id);
  return el instanceof HTMLInputElement ? el : null;
}

/** Erros de data de um formulário inteiro: def_id -> mensagem (vazio = pode salvar). */
export function dateErrors<F extends { def_id: number; type: string }>(
  fields: readonly F[],
  draft: Readonly<Record<number, string>>,
  form: HTMLFormElement,
  idOf: (f: F) => string,
): Record<number, string> {
  const out: Record<number, string> = {};
  for (const f of fields) {
    const problem = dateError(f, draft[f.def_id] ?? '', f.type === 'date' ? dateInputOf(form, idOf(f)) : null);
    if (problem) out[f.def_id] = problem;
  }
  return out;
}

/** Tira o erro de um campo (ao digitar nele de novo). */
export function withoutKey(errs: Record<number, string>, key: number): Record<number, string> {
  if (!(key in errs)) return errs;
  return Object.fromEntries(Object.entries(errs).filter(([k]) => Number(k) !== key));
}
