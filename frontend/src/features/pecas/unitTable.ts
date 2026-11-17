/** Funções puras da tabela "Parâmetros por peça" (P4). */

import type { PieceUnit } from '../../api/units';
import type { DbId } from '../../viewer/ViewerAdapter';

export const pecas = (n: number) => `${n.toLocaleString('pt-BR')} ${n === 1 ? 'peça' : 'peças'}`;

/**
 * Identificador curto da peça: o fim do externalId (o começo costuma ser igual em
 * todas as peças do Revit). Sem externalId (NWD), o nome do elemento.
 */
export function shortId(unit: PieceUnit, size = 8): string {
  const ext = unit.element?.external_id ?? unit.external_id;
  if (ext) return ext.length > size ? `…${ext.slice(-size)}` : ext;
  return unit.element?.name ?? '—';
}

/** Unidades com peça na versão aberta (as linhas da tabela), na ordem do número. */
export function rowsOf(units: readonly PieceUnit[]): PieceUnit[] {
  return units.filter((u) => u.element !== null).sort((a, b) => a.number - b.number);
}

/** Unidades da marca sem peça nesta versão (órfãs ou não ligadas): só contadas (P5). */
export function withoutPiece(units: readonly PieceUnit[]): number {
  return units.filter((u) => u.element === null).length;
}

/** A linha da peça clicada no 3D (null = a peça clicada não é de nenhuma unidade, ex.: um membro). */
export function rowOf(units: readonly PieceUnit[], dbid: DbId | null): PieceUnit | null {
  if (dbid === null) return null;
  return units.find((u) => u.element?.dbid === dbid) ?? null;
}

export function valueOf(unit: PieceUnit, defId: number): { value: unknown; row_version: number | null } {
  const v = unit.values.find((x) => x.def_id === defId);
  return { value: v?.value ?? null, row_version: v?.row_version ?? null };
}
