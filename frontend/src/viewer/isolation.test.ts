import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * CLAUDE.md: o frontend só acessa o visualizador pela interface ViewerAdapter.
 * Só ApsViewerAdapter.ts (e o próprio teste dele) pode usar o Viewer da Autodesk.
 */
const SRC = resolve(process.cwd(), 'src'); // o Vitest roda a partir de frontend/
const ALLOWED = new Set(['viewer/ApsViewerAdapter.ts', 'viewer/ApsViewerAdapter.test.ts']);
const VIEWER_USAGE = [
  /\bAutodesk\s*\??\.\s*Viewing\b/, // Autodesk.Viewing / Autodesk?.Viewing
  /window\s*\.\s*Autodesk\b/,
  /modelderivative\/v2\/viewers/, // CDN do Viewer
  /from\s+['"](forge-viewer|@types\/forge-viewer|autodesk-viewer)/,
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

describe('isolamento do Viewer', () => {
  it('nenhum arquivo fora de ApsViewerAdapter.ts usa o Autodesk Viewer', () => {
    const offenders = sourceFiles(SRC)
      .map((path) => relative(SRC, path).split(sep).join('/'))
      .filter((rel) => !ALLOWED.has(rel) && rel !== 'viewer/isolation.test.ts')
      .filter((rel) => {
        const text = readFileSync(join(SRC, rel), 'utf-8');
        return VIEWER_USAGE.some((re) => re.test(text));
      });
    expect(offenders).toEqual([]);
  });

  it('o próprio adapter usa o Viewer (o teste acima não está vazio)', () => {
    const text = readFileSync(join(SRC, 'viewer/ApsViewerAdapter.ts'), 'utf-8');
    expect(VIEWER_USAGE.some((re) => re.test(text))).toBe(true);
  });
});
