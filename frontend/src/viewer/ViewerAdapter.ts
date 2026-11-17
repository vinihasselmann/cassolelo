/**
 * Única porta de entrada do app para o visualizador 3D (CLAUDE.md).
 *
 * Telas e componentes falam só com esta interface. A implementação com o
 * Autodesk Viewer v7 está em ApsViewerAdapter.ts, o ÚNICO arquivo que conhece o
 * Viewer (um teste garante isso). Nos testes usa-se um adapter falso.
 */

/** Id do elemento no modelo carregado (dbId do Viewer / objectid do Model Derivative). */
export type DbId = number;

/** Cor em hexadecimal: '#RRGGBB' ou '#RRGGBBAA' (alfa opcional; padrão opaco). */
export type HexColor = string;

/** Cor da seleção no 3D: definida em lib/palette.ts (token --selection). */
export { SELECTION_COLOR } from '../lib/palette';

export type SelectionListener = (dbIds: DbId[]) => void;

/** Ponto em coordenadas de MUNDO do Viewer (modelo − globalOffset), na unidade do modelo. */
export type Vec3 = [number, number, number];
export type Triangle = [Vec3, Vec3, Vec3];

/** O que é preciso para converter mundo do Viewer → arquivo → ponto base (docs/coordenadas.md). */
export interface ModelFrame {
  globalOffset: Vec3;
  /** unidade do modelo → metros (pé: 0,3048; cm: 0,01) */
  unitScaleToM: number;
  /** AEC model data: 12 números (colunas X, Y, Z e origem); null = sem ponto de referência */
  refPointTransformation: number[] | null;
}

/** Nó da árvore do modelo, com o mínimo para achar o membro de concreto de uma peça. */
export interface ModelNode {
  dbId: DbId;
  parent: DbId | null;
  children: DbId[];
  name: string;
  /** categoria do PRÓPRIO elemento (no NWD, a do grupo "Element") */
  category: string;
  /** classe IFC / tipo (IfcClass, Type) */
  ifcClass: string;
  /** Material, Materials, Appearance… */
  material: string;
  /** tem geometria própria (fragmentos do próprio nó) */
  hasGeometry: boolean;
}

export interface ViewerAdapter {
  /** Carrega o modelo (URN do derivativo em base64, sem o prefixo "urn:"). Substitui o anterior. */
  load(urn: string): Promise<void>;
  /** Seleciona exatamente estes elementos (lista vazia limpa a seleção). */
  selectDbIds(dbIds: DbId[]): void;
  /** Mostra só estes elementos; os demais ficam OCULTOS. */
  isolate(dbIds: DbId[]): void;
  /** Destaca estes elementos; os demais continuam visíveis, mas ESMAECIDOS. */
  highlight(dbIds: DbId[]): void;
  /** Esconde estes elementos sem mexer nos demais (vale depois de isolate/highlight). */
  hide(dbIds: DbId[]): void;
  /** Desfaz isolamento/destaque e mostra o modelo inteiro normalmente. */
  showAll(): void;
  /** Enquadra a câmera nestes elementos; sem ids (ou lista vazia), no modelo inteiro. */
  fitTo(dbIds?: DbId[]): void;
  /** Recalcula o tamanho do desenho depois que a área do 3D mudou (painel lateral aberto/fechado). */
  resize(): void;
  /** Pinta elementos (substitui as cores anteriores). */
  setColors(colors: ReadonlyMap<DbId, HexColor>): void;
  /** Remove todas as cores aplicadas por setColors. */
  clearColors(): void;
  /** Avisa quando a seleção muda no 3D (clique do usuário). Devolve a função que cancela. */
  onSelect(listener: SelectionListener): () => void;
  /** Libera o visualizador (ao sair da tela). */
  destroy(): void;

  // ---- Coordenadas do eixo da peça (opcionais: um adapter sem geometria não mostra) ----
  /** Dados de conversão do modelo carregado (null antes de carregar). */
  getModelFrame?(): ModelFrame | null;
  /** Nós da árvore (nome, categoria, material, pai, filhos). */
  getNodes?(dbIds: DbId[]): Promise<ModelNode[]>;
  /** Triângulos da geometria PRÓPRIA do nó, em coordenadas de mundo do Viewer. */
  getTriangles?(dbId: DbId): Triangle[];
  /** Marcador no 3D: 1 ponto = marcador; 2 pontos = linha (eixo da viga); null apaga. */
  showAxisMarker?(points: Vec3[] | null): void;
}

/** Cria o adapter dentro do elemento da página. */
export type ViewerFactory = (container: HTMLElement) => ViewerAdapter;

/** '#RRGGBB' | '#RRGGBBAA' -> [r, g, b, a] em 0..1. */
export function parseHexColor(color: HexColor): [number, number, number, number] {
  const m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(color.trim());
  if (!m) throw new Error(`Cor inválida: ${color} (use #RRGGBB ou #RRGGBBAA)`);
  const hex = m[1] ?? '';
  const channel = (i: number) => parseInt(hex.slice(i, i + 2), 16) / 255;
  const alpha = m[2] ? parseInt(m[2], 16) / 255 : 1;
  return [channel(0), channel(2), channel(4), alpha];
}
