/** Busca por nome: sem acento e sem caixa ("viga" acha "VIGA", "pré" acha "PRE"). */
export const normalizeName = (s: string) =>
  s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
