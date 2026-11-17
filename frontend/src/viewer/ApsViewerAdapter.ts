/**
 * ViewerAdapter com o Autodesk Viewer v7 (SVF2). ÚNICO arquivo do app que usa o Viewer.
 *
 * - Biblioteca carregada sob demanda do CDN oficial da Autodesk (só ao abrir o modelo).
 * - env AutodeskProduction2, api streamingV2 (streamingV2_EU para a região EMEA).
 * - Token: GET /api/viewer-token (2-legged, só viewables:read); o Viewer chama
 *   getAccessToken de novo quando o prazo informado acaba.
 */

import { apiFetch } from '../api/client';
import {
  parseHexColor,
  SELECTION_COLOR,
  type DbId,
  type HexColor,
  type ModelFrame,
  type ModelNode,
  type SelectionListener,
  type Triangle,
  type Vec3,
  type ViewerAdapter,
} from './ViewerAdapter';

export const VIEWER_VERSION = '7.*';
export const VIEWER_CDN = `https://developer.api.autodesk.com/modelderivative/v2/viewers/${VIEWER_VERSION}`;

// ------------------------------------------------------------------ tipos mínimos do Viewer v7

export interface AvInstanceTree {
  getRootId(): number;
  getNodeParentId(dbId: number): number;
  getNodeName?(dbId: number): string;
  /** o callback NÃO pode devolver valor verdadeiro: o Viewer para de enumerar */
  enumNodeChildren(dbId: number, cb: (child: number) => void, recursive?: boolean): void;
  enumNodeFragments(dbId: number, cb: (fragId: number) => void, recursive?: boolean): void;
}
export interface AvMatrix4 {
  elements: ArrayLike<number>;
}
export interface AvFragmentList {
  getWorldMatrix(fragId: number, out: AvMatrix4): void;
}
export interface AvGeometry {
  vb?: ArrayLike<number>;
  vbstride?: number;
  ib?: ArrayLike<number>;
  index?: { array: ArrayLike<number> } | null;
  attributes?: { position?: { offset?: number; itemOffset?: number; itemSize?: number; array?: ArrayLike<number> } };
  isLines?: boolean;
  isWideLines?: boolean;
  isPoints?: boolean;
}
export interface AvProperty {
  displayName: string;
  displayCategory?: string | null;
  displayValue: unknown;
}
export interface AvModel {
  getData?(): { globalOffset?: { x: number; y: number; z: number } | null };
  /** unidade do modelo -> metros */
  getUnitScale?(): number;
  getInstanceTree?(): AvInstanceTree | null;
  getFragmentList?(): AvFragmentList;
  getProperties?(
    dbId: number,
    onSuccess: (result: { name: string; properties: AvProperty[] }) => void,
    onError: (err: unknown) => void,
  ): void;
}
/** Partes internas do Viewer v7 usadas para a geometria e o marcador do eixo. */
export interface AvImpl {
  getRenderProxy(model: AvModel, fragId: number): { geometry?: AvGeometry | null } | null;
  createOverlayScene(name: string): void;
  addOverlay(name: string, object: unknown): void;
  removeOverlay(name: string, object: unknown): void;
  invalidate(needsClear: boolean, needsRender: boolean, overlayDirty: boolean): void;
}
interface AvBubbleNode {
  readonly __node?: never;
}
interface AvDocument {
  getRoot(): { getDefaultGeometry(): AvBubbleNode | null };
}
interface AvSelectionEvent {
  dbIdArray?: number[];
}
export interface AvViewer {
  start(): number;
  finish(): void;
  addEventListener(type: string, cb: (event: AvSelectionEvent) => void): void;
  loadDocumentNode(doc: AvDocument, node: AvBubbleNode): Promise<AvModel>;
  select(dbIds: number[]): void;
  clearSelection(): void;
  isolate(dbIds: number[]): void;
  hide(dbIds: number[]): void;
  setGhosting(enabled: boolean): void;
  showAll(): void;
  fitToView(dbIds?: number[]): void;
  resize(): void;
  setThemingColor(dbId: number, color: unknown, model?: AvModel, recursive?: boolean): void;
  clearThemingColors(model?: AvModel): void;
  /** Cor do destaque da seleção (Viewer v7). */
  setSelectionColor?(color: unknown, selectionType?: number): void;
  impl?: AvImpl;
}
export interface AvInitOptions {
  env: string;
  api: string;
  getAccessToken: (onSuccess: (token: string, expiresIn: number) => void) => void;
}
export interface AutodeskNamespace {
  Viewing: {
    Initializer(options: AvInitOptions, onReady: () => void): void;
    GuiViewer3D: new (container: HTMLElement) => AvViewer;
    Document: {
      load(
        urn: string,
        onSuccess: (doc: AvDocument) => void,
        onFailure: (code: number, message?: string) => void,
      ): void;
      /** AEC model data do Revit (níveis, grids, refPointTransformation) */
      getAecModelData?(node: AvBubbleNode): unknown;
    };
    SELECTION_CHANGED_EVENT: string;
    SelectionType?: { MIXED: number };
  };
}
interface ThreeObject {
  position: { set(x: number, y: number, z: number): void };
}
interface ThreeNamespace {
  Vector4: new (x: number, y: number, z: number, w: number) => unknown;
  Color?: new (r: number, g: number, b: number) => unknown;
  Matrix4?: new () => AvMatrix4;
  Vector3?: new (x: number, y: number, z: number) => unknown;
  Geometry?: new () => { vertices: unknown[] };
  SphereGeometry?: new (radius: number, widthSegments: number, heightSegments: number) => unknown;
  MeshBasicMaterial?: new (params: Record<string, unknown>) => unknown;
  LineBasicMaterial?: new (params: Record<string, unknown>) => unknown;
  Mesh?: new (geometry: unknown, material: unknown) => ThreeObject;
  Line?: new (geometry: unknown, material: unknown) => ThreeObject;
}
declare global {
  interface Window {
    Autodesk?: AutodeskNamespace;
    THREE?: ThreeNamespace;
  }
}

// ------------------------------------------------------------------ carga e inicialização

export type ApsRegion = 'US' | 'EMEA' | 'AUS';

export interface ViewerToken {
  access_token: string;
  expires_in: number;
  region: ApsRegion;
}

export const fetchViewerToken = (): Promise<ViewerToken> => apiFetch('/viewer-token');

export const LOAD_ERROR =
  'Não foi possível carregar o visualizador da Autodesk. Verifique a conexão com a internet.';

let libraryPromise: Promise<AutodeskNamespace> | null = null;

/** Injeta o script e o CSS do CDN uma única vez por página. */
export function loadViewerLibrary(): Promise<AutodeskNamespace> {
  if (window.Autodesk?.Viewing) return Promise.resolve(window.Autodesk);
  libraryPromise ??= new Promise<AutodeskNamespace>((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = `${VIEWER_CDN}/style.min.css`;
    document.head.appendChild(css);

    const script = document.createElement('script');
    script.src = `${VIEWER_CDN}/viewer3D.min.js`;
    script.async = true;
    script.onload = () => {
      if (window.Autodesk?.Viewing) resolve(window.Autodesk);
      else reject(new Error(LOAD_ERROR));
    };
    script.onerror = () => {
      libraryPromise = null; // permite tentar de novo
      script.remove();
      reject(new Error(LOAD_ERROR));
    };
    document.head.appendChild(script);
  });
  return libraryPromise;
}

export function streamingApi(region: ApsRegion): string {
  return region === 'EMEA' ? 'streamingV2_EU' : 'streamingV2';
}

// O Initializer deve rodar uma vez por página (por namespace carregado).
const initialized = new WeakMap<AutodeskNamespace, Promise<void>>();

function initialize(av: AutodeskNamespace, fetchToken: () => Promise<ViewerToken>): Promise<void> {
  let ready = initialized.get(av);
  if (!ready) {
    ready = fetchToken().then(
      (first) =>
        new Promise<void>((resolve) => {
          let pending: ViewerToken | null = first; // o primeiro já foi buscado
          av.Viewing.Initializer(
            {
              env: 'AutodeskProduction2',
              api: streamingApi(first.region),
              getAccessToken: (onSuccess) => {
                const next = pending ? Promise.resolve(pending) : fetchToken();
                pending = null;
                next.then(
                  (t) => { onSuccess(t.access_token, t.expires_in); },
                  (err: unknown) => { console.error('Falha ao renovar o token do visualizador', err); },
                );
              },
            },
            resolve,
          );
        }),
    );
    ready.catch(() => initialized.delete(av)); // token falhou: tenta de novo no próximo load
    initialized.set(av, ready);
  }
  return ready;
}

// ------------------------------------------------------------------ adapter

export interface ApsViewerDeps {
  loadLibrary?: () => Promise<AutodeskNamespace>;
  fetchToken?: () => Promise<ViewerToken>;
}

export class ApsViewerAdapter implements ViewerAdapter {
  private readonly container: HTMLElement;
  private readonly loadLibrary: () => Promise<AutodeskNamespace>;
  private readonly fetchToken: () => Promise<ViewerToken>;
  private started: Promise<{ av: AutodeskNamespace; viewer: AvViewer }> | null = null;
  private viewer: AvViewer | null = null;
  private model: AvModel | null = null;
  private readonly listeners = new Set<SelectionListener>();
  private loadSeq = 0;
  /** Coloração em vigor e seleção atual: a seleção fica grafite POR CIMA das cores. */
  private colors = new Map<DbId, HexColor>();
  private selected = new Set<DbId>();
  private paintedSelection = new Set<DbId>();
  private programmatic = false;
  private destroyed = false;
  /** AEC model data do modelo carregado: ponto de referência (refPointTransformation) */
  private refPoint: number[] | null = null;
  private markers: unknown[] = [];

  constructor(container: HTMLElement, deps: ApsViewerDeps = {}) {
    this.container = container;
    this.loadLibrary = deps.loadLibrary ?? loadViewerLibrary;
    this.fetchToken = deps.fetchToken ?? fetchViewerToken;
  }

  private start(): Promise<{ av: AutodeskNamespace; viewer: AvViewer }> {
    this.started ??= (async () => {
      const av = await this.loadLibrary();
      await initialize(av, this.fetchToken);
      const viewer = new av.Viewing.GuiViewer3D(this.container);
      viewer.start();
      const THREE = window.THREE;
      if (THREE?.Color && viewer.setSelectionColor) {
        const [r, g, b] = parseHexColor(SELECTION_COLOR);
        viewer.setSelectionColor(new THREE.Color(r, g, b), av.Viewing.SelectionType?.MIXED);
      }
      viewer.addEventListener(av.Viewing.SELECTION_CHANGED_EVENT, (event) => {
        if (this.programmatic) return; // só seleções feitas pelo usuário
        const ids = event.dbIdArray ?? [];
        this.listeners.forEach((listener) => { listener([...ids]); });
      });
      if (this.destroyed) viewer.finish();
      else this.viewer = viewer;
      return { av, viewer };
    })();
    this.started.catch(() => { this.started = null; });
    return this.started;
  }

  async load(urn: string): Promise<void> {
    const seq = ++this.loadSeq;
    const { av, viewer } = await this.start();
    const doc = await new Promise<AvDocument>((resolve, reject) => {
      av.Viewing.Document.load(`urn:${urn}`, resolve, (code, message) => {
        reject(
          new Error(
            `Não foi possível abrir o modelo no visualizador (código ${code}${message ? `: ${message}` : ''}).`,
          ),
        );
      });
    });
    if (seq !== this.loadSeq || this.destroyed) return; // outra versão foi pedida depois
    const node = doc.getRoot().getDefaultGeometry();
    if (!node) throw new Error('O modelo não tem vista 3D para exibir.');
    // Coordenadas do eixo: ponto de referência do AEC (Revit). Só leitura: as opções de
    // carga NÃO mudam (docs/coordenadas.md).
    const aec = await Promise.resolve(av.Viewing.Document.getAecModelData?.(node)).catch(() => null);
    const ref = (aec as { refPointTransformation?: unknown } | null)?.refPointTransformation;
    const model = await viewer.loadDocumentNode(doc, node);
    if (seq === this.loadSeq) {
      this.showAxisMarker(null);
      this.model = model;
      this.refPoint = Array.isArray(ref) && ref.length >= 12 ? ref.map(Number) : null;
    }
  }

  // ---------------------------------------------------------------- coordenadas do eixo

  getModelFrame(): ModelFrame | null {
    const model = this.model;
    if (!model?.getData) return null;
    const off = model.getData().globalOffset ?? { x: 0, y: 0, z: 0 };
    return {
      globalOffset: [off.x, off.y, off.z],
      unitScaleToM: model.getUnitScale?.() ?? 1,
      refPointTransformation: this.refPoint,
    };
  }

  async getNodes(dbIds: DbId[]): Promise<ModelNode[]> {
    const model = this.model;
    const tree = model?.getInstanceTree?.();
    if (!model || !tree) return [];
    const root = tree.getRootId();
    const one = async (dbId: DbId): Promise<ModelNode> => {
      const children: DbId[] = [];
      tree.enumNodeChildren(dbId, (c) => { children.push(c); });
      let own = 0;
      tree.enumNodeFragments(dbId, () => { own += 1; }, false);
      const fallback = () => ({ name: tree.getNodeName?.(dbId) ?? '', properties: [] as AvProperty[] });
      const props = await new Promise<{ name: string; properties: AvProperty[] }>((resolve) => {
        if (!model.getProperties) resolve(fallback());
        else model.getProperties(dbId, resolve, () => { resolve(fallback()); });
      });
      const values = (names: string[]) =>
        props.properties.filter((x) => names.includes(x.displayName)).map((x) => String(x.displayValue));
      // categoria do PRÓPRIO elemento: no NWD "Category" se repete em vários grupos
      const cats = props.properties.filter((x) => ['Category', 'Categoria', '_RC'].includes(x.displayName));
      const category = cats.find((x) => x.displayCategory === 'Element') ?? cats[0];
      return {
        dbId,
        parent: dbId === root ? null : tree.getNodeParentId(dbId),
        children,
        name: props.name,
        category: category ? String(category.displayValue) : '',
        ifcClass: values(['IfcClass', 'Ifc Class', 'Entity', 'Type']).join(' '),
        material: values(['Material', 'Materials', 'Appearance', 'Material estrutural', 'Structural Material']).join(' '),
        hasGeometry: own > 0,
      };
    };
    return Promise.all(dbIds.map(one));
  }

  getTriangles(dbId: DbId): Triangle[] {
    const model = this.model;
    const tree = model?.getInstanceTree?.();
    const frags = model?.getFragmentList?.();
    const impl = this.viewer?.impl;
    const Matrix4 = window.THREE?.Matrix4;
    if (!model || !tree || !frags || !impl || !Matrix4) return [];
    const out: Triangle[] = [];
    tree.enumNodeFragments(
      dbId,
      (fragId) => {
        const g = impl.getRenderProxy(model, fragId)?.geometry;
        if (!g || g.isLines || g.isWideLines || g.isPoints) return;
        // A malha do SVF2 vem normalizada: a posição é a matriz da lista de fragmentos.
        const world = new Matrix4();
        frags.getWorldMatrix(fragId, world);
        const m = world.elements;
        const pos = g.attributes?.position;
        const vb = g.vb ?? pos?.array;
        if (!vb) return;
        const stride = g.vb ? (g.vbstride ?? 3) : (pos?.itemSize ?? 3);
        const off = g.vb ? (pos?.offset ?? pos?.itemOffset ?? 0) : 0;
        const e = (k: number) => m[k] ?? 0;
        const vert = (i: number): Vec3 => {
          const x = vb[i * stride + off] ?? 0;
          const y = vb[i * stride + off + 1] ?? 0;
          const z = vb[i * stride + off + 2] ?? 0;
          return [
            e(0) * x + e(4) * y + e(8) * z + e(12),
            e(1) * x + e(5) * y + e(9) * z + e(13),
            e(2) * x + e(6) * y + e(10) * z + e(14),
          ];
        };
        const ib = g.ib ?? g.index?.array;
        const count = ib ? ib.length : vb.length / stride;
        for (let i = 0; i + 2 < count; i += 3) {
          const a = ib ? (ib[i] ?? 0) : i;
          const b = ib ? (ib[i + 1] ?? 0) : i + 1;
          const c = ib ? (ib[i + 2] ?? 0) : i + 2;
          out.push([vert(a), vert(b), vert(c)]);
        }
      },
      false,
    );
    return out;
  }

  /** Marcador laranja no eixo (overlay do Viewer, por cima do modelo). */
  showAxisMarker(points: Vec3[] | null): void {
    const impl = this.viewer?.impl;
    const THREE = window.THREE;
    if (!impl) return;
    const scene = 'cassol-eixo';
    this.markers.forEach((obj) => { impl.removeOverlay(scene, obj); });
    this.markers = [];
    if (points && points.length > 0 && THREE?.Mesh && THREE.SphereGeometry && THREE.MeshBasicMaterial) {
      impl.createOverlayScene(scene);
      const scale = this.model?.getUnitScale?.() ?? 1;
      const radius = 0.12 / scale; // 12 cm, na unidade do modelo
      const material = new THREE.MeshBasicMaterial({ color: 0xf2a31b, depthTest: false, depthWrite: false });
      for (const [x, y, z] of points) {
        const dot = new THREE.Mesh(new THREE.SphereGeometry(radius, 16, 12), material);
        dot.position.set(x, y, z);
        this.markers.push(dot);
      }
      if (points.length === 2 && THREE.Geometry && THREE.Line && THREE.LineBasicMaterial && THREE.Vector3) {
        const line = new THREE.Geometry();
        for (const [x, y, z] of points) line.vertices.push(new THREE.Vector3(x, y, z));
        this.markers.push(new THREE.Line(line, new THREE.LineBasicMaterial({ color: 0xf2a31b, linewidth: 3, depthTest: false })));
      }
      this.markers.forEach((obj) => { impl.addOverlay(scene, obj); });
    }
    impl.invalidate(false, false, true);
  }

  selectDbIds(dbIds: DbId[]): void {
    this.selected = new Set(dbIds);
    this.withViewer((v) => {
      this.programmatic = true;
      try {
        if (dbIds.length === 0) v.clearSelection();
        else v.select([...dbIds]);
      } finally {
        this.programmatic = false;
      }
      this.paintSelection(v);
    });
  }

  isolate(dbIds: DbId[]): void {
    this.withViewer((v) => {
      v.setGhosting(false); // sem "fantasma": os demais somem
      v.isolate([...dbIds]);
    });
  }

  highlight(dbIds: DbId[]): void {
    this.withViewer((v) => {
      v.setGhosting(true); // os demais ficam esmaecidos (transparentes)
      v.isolate([...dbIds]);
    });
  }

  hide(dbIds: DbId[]): void {
    if (dbIds.length === 0) return;
    this.withViewer((v) => { v.hide([...dbIds]); });
  }

  showAll(): void {
    this.withViewer((v) => { v.showAll(); });
  }

  fitTo(dbIds?: DbId[]): void {
    this.withViewer((v) => { v.fitToView(dbIds && dbIds.length > 0 ? [...dbIds] : undefined); });
  }

  resize(): void {
    this.withViewer((v) => { v.resize(); });
  }

  setColors(colors: ReadonlyMap<DbId, HexColor>): void {
    this.colors = new Map(colors);
    this.paintedSelection = new Set();
    this.withViewer((v) => {
      const model = this.model ?? undefined;
      v.clearThemingColors(model);
      colors.forEach((hex, dbId) => {
        this.theme(v, dbId, hex); // a cor de base também nas selecionadas; o grafite vai por cima
      });
      this.paintSelection(v);
    });
  }

  clearColors(): void {
    this.colors = new Map();
    this.paintedSelection = new Set();
    this.withViewer((v) => { v.clearThemingColors(this.model ?? undefined); });
  }

  /** Uma cor de tema numa peça (null = sem cor: alfa 0). */
  private theme(v: AvViewer, dbId: DbId, hex: HexColor | null): void {
    const THREE = window.THREE;
    if (!THREE) return;
    const [r, g, b, a] = hex === null ? [0, 0, 0, 0] : parseHexColor(hex);
    v.setThemingColor(dbId, new THREE.Vector4(r, g, b, a), this.model ?? undefined, true);
  }

  /**
   * As cores de tema do Viewer ficam por cima do destaque de seleção: com coloração
   * ativa, a seleção é pintada de grafite (SELECTION_COLOR) e, ao sair da seleção, a peça
   * volta à cor da coloração. Sem coloração, vale o destaque normal do Viewer.
   */
  private paintSelection(v: AvViewer): void {
    const blue = this.colors.size > 0 ? this.selected : new Set<DbId>();
    this.paintedSelection.forEach((id) => {
      if (!blue.has(id)) this.theme(v, id, this.colors.get(id) ?? null);
    });
    blue.forEach((id) => {
      if (!this.paintedSelection.has(id)) this.theme(v, id, SELECTION_COLOR);
    });
    this.paintedSelection = new Set(blue);
  }

  onSelect(listener: SelectionListener): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  destroy(): void {
    this.destroyed = true;
    this.listeners.clear();
    this.viewer?.finish();
    this.viewer = null;
    this.model = null;
    this.markers = [];
  }

  private withViewer(fn: (viewer: AvViewer) => void): void {
    if (this.viewer && !this.destroyed) fn(this.viewer);
  }
}

export const createApsViewer = (container: HTMLElement): ViewerAdapter =>
  new ApsViewerAdapter(container);
