import type { MarkPieces, SecondaryValues, SourceCount } from '../../api/versions';

/** Parâmetro de onde vem o nome das peças na versão (o de mais peças) e a divisão. */
export interface VersionOrigin {
  /** parâmetro principal (título da coluna); null = versão sem origem gravada */
  main: string | null;
  /** peças por parâmetro, do maior para o menor; mais de um = origem mista */
  split: SourceCount[];
}

export function versionOrigin(marks: readonly MarkPieces[]): VersionOrigin {
  const by = new Map<string, number>();
  for (const m of marks) {
    for (const s of m.sources ?? []) by.set(s.name, (by.get(s.name) ?? 0) + s.pieces);
  }
  const split = [...by.entries()]
    .map(([name, pieces]) => ({ name, pieces }))
    .sort((a, b) => b.pieces - a.pieces || a.name.localeCompare(b.name));
  return { main: split[0]?.name ?? null, split };
}

export interface SecondaryInfo extends SecondaryValues {
  /** peças da marca com valores diferentes nesse parâmetro (vale o principal: só aviso) */
  divergent: boolean;
  /** nem todas as peças da marca têm esse parâmetro preenchido */
  partial: boolean;
}

/** O que vai na 2ª linha da marca: origens diferentes da principal e os secundários. */
export function markAlt(
  mark: MarkPieces,
  main: string | null,
): { via: string[]; secondary: SecondaryInfo[] } {
  const via = (mark.sources ?? []).map((s) => s.name).filter((n) => n !== main);
  const secondary = (mark.secondary ?? []).map((s) => ({
    ...s,
    divergent: s.values.length > 1,
    partial: s.pieces < mark.count,
  }));
  return { via, secondary };
}
