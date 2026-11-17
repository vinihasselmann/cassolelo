import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { SELECTION_COLOR, STATUS_COLORS, STATUS_ORDER, STATUS_TOKENS } from './palette';

// os testes rodam a partir de frontend/ (npm test)
const tokensCss = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8');
const stylesCss = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8');

/** Valor declarado de um token em tokens.css (sem seguir var()). */
function tokenValue(name: string): string | undefined {
  const m = new RegExp(`${name}:\\s*([^;]+);`).exec(tokensCss);
  return m?.[1]?.trim();
}

describe('paleta', () => {
  it('cores de status no TS são as mesmas dos tokens CSS', () => {
    for (const s of STATUS_ORDER) {
      expect(tokenValue(STATUS_TOKENS[s])?.toLowerCase()).toBe(STATUS_COLORS[s].toLowerCase());
    }
  });

  it('cor da seleção no TS é a mesma do token --selection', () => {
    expect(tokenValue('--selection')?.toLowerCase()).toBe(SELECTION_COLOR.toLowerCase());
  });

  it('styles.css não tem cor em hex: tudo vem de tokens.css', () => {
    const semComentarios = stylesCss.replace(/\/\*[\s\S]*?\*\//g, '');
    expect(semComentarios.match(/#[0-9a-f]{3,8}\b/gi) ?? []).toEqual([]);
  });

  it('todo var(--x) usado em styles.css existe em tokens.css', () => {
    const usados = new Set([...stylesCss.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]));
    // variáveis locais de layout, declaradas no próprio styles.css
    const locais = new Set([...stylesCss.matchAll(/(--[a-z0-9-]+):/g)].map((m) => m[1]));
    const faltando = [...usados].filter((v) => v && !locais.has(v) && tokenValue(v) === undefined);
    expect(faltando).toEqual([]);
  });
});
