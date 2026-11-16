/**
 * ViewerAdapter com o Autodesk Viewer v7 (SVF2). ÚNICO arquivo do app que usa o Viewer.
 *
 * - Biblioteca carregada sob demanda do CDN oficial da Autodesk (só ao abrir o modelo).
 * - env AutodeskProduction2, api streamingV2 (streamingV2_EU para a região EMEA).
 * - Token: GET /api/viewer-token (2-legged, só viewables:read); o Viewer chama
 *   getAccessToken de novo quando o prazo informado acaba.
 */

import { apiFetch } from '../api/client';
import { parseHexColor, SELECTION_COLOR, type DbId, type HexColor, type SelectionListener, type ViewerAdapter } from './ViewerAdapter';

export const VIEWER_VERSION = '7.*';
export const VIEWER_CDN = `https://developer.api.autodesk.com/modelderivative/v2/viewers/${VIEWER_VERSION}`;

// ------------------------------------------------------------------ tipos mínimos do Viewer v7

export interface AvModel {
  readonly __model?: never;
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
  setThemingColor(dbId: number, color: unknown, model?: AvModel, recursive?: boolean): void;
  clearThemingColors(model?: AvModel): void;
  /** Cor do destaque da seleção (Viewer v7). */
  setSelectionColor?(color: unknown, selectionType?: number): void;
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
    };
    SELECTION_CHANGED_EVENT: string;
    SelectionType?: { MIXED: number };
  };
}
interface ThreeNamespace {
  Vector4: new (x: number, y: number, z: number, w: number) => unknown;
  Color?: new (r: number, g: number, b: number) => unknown;
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
  /** Coloração em vigor e seleção atual: a seleção fica azul POR CIMA das cores. */
  private colors = new Map<DbId, HexColor>();
  private selected = new Set<DbId>();
  private paintedSelection = new Set<DbId>();
  private programmatic = false;
  private destroyed = false;

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
    const model = await viewer.loadDocumentNode(doc, node);
    if (seq === this.loadSeq) this.model = model;
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

  setColors(colors: ReadonlyMap<DbId, HexColor>): void {
    this.colors = new Map(colors);
    this.paintedSelection = new Set();
    this.withViewer((v) => {
      const model = this.model ?? undefined;
      v.clearThemingColors(model);
      colors.forEach((hex, dbId) => {
        this.theme(v, dbId, hex); // a cor de base também nas selecionadas; o azul vai por cima
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
   * ativa, a seleção é pintada de azul (SELECTION_COLOR) e, ao sair da seleção, a peça
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
  }

  private withViewer(fn: (viewer: AvViewer) => void): void {
    if (this.viewer && !this.destroyed) fn(this.viewer);
  }
}

export const createApsViewer = (container: HTMLElement): ViewerAdapter =>
  new ApsViewerAdapter(container);
