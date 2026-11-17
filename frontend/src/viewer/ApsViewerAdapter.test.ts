import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ApsViewerAdapter,
  LOAD_ERROR,
  VIEWER_CDN,
  loadViewerLibrary,
  streamingApi,
  type AutodeskNamespace,
  type AvInitOptions,
  type AvModel,
  type AvViewer,
  type ViewerToken,
} from './ApsViewerAdapter';
import { parseHexColor } from './ViewerAdapter';

const TOKEN: ViewerToken = { access_token: 'VIEWER-TOKEN', expires_in: 600, region: 'US' };

class Vector4 {
  constructor(
    public x: number,
    public y: number,
    public z: number,
    public w: number,
  ) {}
}

function fakeAutodesk(opts: { docFails?: boolean } = {}) {
  const inits: AvInitOptions[] = [];
  const loadedUrns: string[] = [];
  let selectionCb: ((e: { dbIdArray?: number[] }) => void) | null = null;
  const model: AvModel = {};
  const viewer = {
    start: vi.fn(() => 0),
    finish: vi.fn(),
    addEventListener: vi.fn((type: string, cb: (e: { dbIdArray?: number[] }) => void) => {
      if (type === 'selection') selectionCb = cb;
    }),
    loadDocumentNode: vi.fn(() => Promise.resolve(model)),
    select: vi.fn((ids: number[]) => selectionCb?.({ dbIdArray: ids })), // o Viewer real também emite
    clearSelection: vi.fn(() => selectionCb?.({ dbIdArray: [] })),
    isolate: vi.fn(),
    hide: vi.fn(),
    setGhosting: vi.fn(),
    showAll: vi.fn(),
    fitToView: vi.fn(),
    setThemingColor: vi.fn<(dbId: number, color: unknown, model?: AvModel, recursive?: boolean) => void>(),
    clearThemingColors: vi.fn(),
  } satisfies AvViewer;
  const av: AutodeskNamespace = {
    Viewing: {
      Initializer: vi.fn((options: AvInitOptions, onReady: () => void) => {
        inits.push(options);
        onReady();
      }),
      // `function` (não arrow): o adapter usa `new` e o Vitest 4+ exige um construtor.
      GuiViewer3D: vi.fn(function () {
        return viewer;
      }),
      Document: {
        load: (urn, ok, fail) => {
          loadedUrns.push(urn);
          if (opts.docFails) fail(7, 'sem acesso');
          else ok({ getRoot: () => ({ getDefaultGeometry: () => ({}) }) });
        },
      },
      SELECTION_CHANGED_EVENT: 'selection',
    },
  };
  return { av, viewer, model, inits, loadedUrns, userClicks: (ids: number[]) => selectionCb?.({ dbIdArray: ids }) };
}

function makeAdapter(fake: ReturnType<typeof fakeAutodesk>, fetchToken = vi.fn(() => Promise.resolve(TOKEN))) {
  const adapter = new ApsViewerAdapter(document.createElement('div'), {
    loadLibrary: () => Promise.resolve(fake.av),
    fetchToken,
  });
  return { adapter, fetchToken };
}

describe('ApsViewerAdapter', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('inicializa com AutodeskProduction2 + streamingV2 e carrega o URN', async () => {
    const fake = fakeAutodesk();
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJuOnYx');

    expect(fake.inits).toHaveLength(1);
    expect(fake.inits[0]).toMatchObject({ env: 'AutodeskProduction2', api: 'streamingV2' });
    expect(fake.loadedUrns).toEqual(['urn:dXJuOnYx']);
    expect(fake.viewer.start).toHaveBeenCalledOnce();
    expect(fake.viewer.loadDocumentNode).toHaveBeenCalledOnce();
  });

  it('usa o endpoint de token e renova quando o Viewer pede', async () => {
    const fake = fakeAutodesk();
    const fetchToken = vi
      .fn<() => Promise<ViewerToken>>()
      .mockResolvedValueOnce(TOKEN)
      .mockResolvedValueOnce({ ...TOKEN, access_token: 'RENOVADO', expires_in: 300 });
    const { adapter } = makeAdapter(fake, fetchToken);
    await adapter.load('dXJu');

    const getAccessToken = fake.inits[0]?.getAccessToken;
    const received: [string, number][] = [];
    const take = (t: string, e: number) => received.push([t, e]);
    getAccessToken?.(take); // 1ª chamada: reaproveita o token buscado na inicialização
    getAccessToken?.(take); // depois: busca outro
    await vi.waitFor(() => { expect(received).toHaveLength(2); });
    expect(received).toEqual([
      ['VIEWER-TOKEN', 600],
      ['RENOVADO', 300],
    ]);
    expect(fetchToken).toHaveBeenCalledTimes(2);
  });

  it('região EMEA usa streamingV2_EU', () => {
    expect(streamingApi('EMEA')).toBe('streamingV2_EU');
    expect(streamingApi('US')).toBe('streamingV2');
    expect(streamingApi('AUS')).toBe('streamingV2');
  });

  it('repassa seleção, isolamento, enquadramento e cores ao Viewer', async () => {
    vi.stubGlobal('THREE', { Vector4 });
    const fake = fakeAutodesk();
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJu');

    adapter.selectDbIds([1, 2]);
    expect(fake.viewer.select).toHaveBeenCalledWith([1, 2]);
    adapter.selectDbIds([]);
    expect(fake.viewer.clearSelection).toHaveBeenCalled();
    adapter.isolate([3]);
    expect(fake.viewer.setGhosting).toHaveBeenLastCalledWith(false);
    expect(fake.viewer.isolate).toHaveBeenLastCalledWith([3]);
    adapter.highlight([6, 7]);
    expect(fake.viewer.setGhosting).toHaveBeenLastCalledWith(true);
    expect(fake.viewer.isolate).toHaveBeenLastCalledWith([6, 7]);
    adapter.hide([8, 9]);
    expect(fake.viewer.hide).toHaveBeenLastCalledWith([8, 9]);
    adapter.hide([]); // nada a esconder: não chama o Viewer
    expect(fake.viewer.hide).toHaveBeenCalledTimes(1);
    adapter.showAll();
    expect(fake.viewer.showAll).toHaveBeenCalled();
    adapter.fitTo([4]);
    expect(fake.viewer.fitToView).toHaveBeenLastCalledWith([4]);
    adapter.fitTo();
    expect(fake.viewer.fitToView).toHaveBeenLastCalledWith(undefined);

    adapter.setColors(new Map([[5, '#FF000080']]));
    expect(fake.viewer.clearThemingColors).toHaveBeenCalledWith(fake.model);
    const [dbId, color, model, recursive] = fake.viewer.setThemingColor.mock.calls[0] ?? [];
    expect(dbId).toBe(5);
    expect(model).toBe(fake.model);
    expect(recursive).toBe(true);
    expect(color).toEqual(new Vector4(1, 0, 0, 128 / 255));
    adapter.clearColors();
    expect(fake.viewer.clearThemingColors).toHaveBeenCalledTimes(2);
  });

  it('com coloração ativa, a seleção fica azul por cima e volta à cor ao sair', async () => {
    vi.stubGlobal('THREE', { Vector4 });
    const fake = fakeAutodesk();
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJu');
    const theme = () => new Map(fake.viewer.setThemingColor.mock.calls.map(([id, c]) => [id, c]));
    const blue = new Vector4(47 / 255, 111 / 255, 235 / 255, 1);

    adapter.selectDbIds([1]); // sem coloração: só o destaque normal do Viewer
    expect(fake.viewer.setThemingColor).not.toHaveBeenCalled();
    adapter.setColors(new Map([[1, '#FF0000'], [2, '#00FF00']]));
    expect(theme().get(1)).toEqual(blue); // selecionada: azul, não vermelha
    expect(theme().get(2)).toEqual(new Vector4(0, 1, 0, 1));

    fake.viewer.setThemingColor.mockClear();
    adapter.selectDbIds([2, 3]);
    expect(theme().get(1)).toEqual(new Vector4(1, 0, 0, 1)); // volta à cor da coloração
    expect(theme().get(2)).toEqual(blue);
    expect(theme().get(3)).toEqual(blue); // sem cor própria, mas selecionada

    fake.viewer.setThemingColor.mockClear();
    adapter.selectDbIds([]);
    expect(theme().get(3)).toEqual(new Vector4(0, 0, 0, 0)); // sem cor: alfa 0
    expect(theme().get(2)).toEqual(new Vector4(0, 1, 0, 1));
  });

  it('onSelect avisa só os cliques do usuário, não a seleção feita pelo app', async () => {
    const fake = fakeAutodesk();
    const { adapter } = makeAdapter(fake);
    const seen: number[][] = [];
    const off = adapter.onSelect((ids) => seen.push(ids));
    await adapter.load('dXJu');

    fake.userClicks([10, 11]);
    adapter.selectDbIds([12]); // programática: não volta pelo listener
    off();
    fake.userClicks([13]);
    expect(seen).toEqual([[10, 11]]);
  });

  it('chamadas antes de carregar são ignoradas e destroy encerra o Viewer', async () => {
    const fake = fakeAutodesk();
    const { adapter } = makeAdapter(fake);
    adapter.isolate([1]); // ainda sem Viewer: não quebra
    await adapter.load('dXJu');
    adapter.destroy();
    expect(fake.viewer.finish).toHaveBeenCalledOnce();
    adapter.showAll();
    expect(fake.viewer.showAll).not.toHaveBeenCalled();
  });

  it('erro ao abrir o documento vira mensagem em português', async () => {
    const fake = fakeAutodesk({ docFails: true });
    const { adapter } = makeAdapter(fake);
    await expect(adapter.load('dXJu')).rejects.toThrow(
      'Não foi possível abrir o modelo no visualizador (código 7: sem acesso).',
    );
  });

  it('falha do token na inicialização rejeita o load', async () => {
    const fake = fakeAutodesk();
    const { adapter } = makeAdapter(fake, vi.fn(() => Promise.reject(new Error('Credenciais do app APS inválidas'))));
    await expect(adapter.load('dXJu')).rejects.toThrow('Credenciais do app APS inválidas');
    expect(fake.inits).toHaveLength(0);
  });
});

describe('loadViewerLibrary', () => {
  afterEach(() => {
    document.head.innerHTML = '';
    vi.unstubAllGlobals();
  });

  it('injeta script e CSS do CDN oficial uma única vez', async () => {
    const first = loadViewerLibrary();
    const second = loadViewerLibrary();
    const scripts = document.head.querySelectorAll('script');
    expect(scripts).toHaveLength(1);
    expect(scripts[0]?.src).toBe(`${VIEWER_CDN}/viewer3D.min.js`);
    expect(VIEWER_CDN).toBe('https://developer.api.autodesk.com/modelderivative/v2/viewers/7.*');
    expect(document.head.querySelector('link')?.getAttribute('href')).toBe(`${VIEWER_CDN}/style.min.css`);

    const fake = fakeAutodesk();
    vi.stubGlobal('Autodesk', fake.av);
    scripts[0]?.dispatchEvent(new Event('load'));
    await expect(first).resolves.toBe(fake.av);
    await expect(second).resolves.toBe(fake.av);
    await expect(loadViewerLibrary()).resolves.toBe(fake.av); // já carregado: nada novo
    expect(document.head.querySelectorAll('script')).toHaveLength(1);
  });

  it('falha de rede rejeita com mensagem e permite tentar de novo', async () => {
    vi.resetModules(); // cache do módulo limpo (o teste anterior já carregou)
    const mod = await import('./ApsViewerAdapter');
    vi.stubGlobal('Autodesk', undefined);
    const attempt = mod.loadViewerLibrary();
    document.head.querySelector('script')?.dispatchEvent(new Event('error'));
    await expect(attempt).rejects.toThrow(LOAD_ERROR);
    void mod.loadViewerLibrary().catch(() => undefined);
    expect(document.head.querySelectorAll('script')).toHaveLength(1); // o antigo foi removido
  });
});

describe('parseHexColor', () => {
  it('converte #RRGGBB e #RRGGBBAA', () => {
    expect(parseHexColor('#33A06F')).toEqual([0x33 / 255, 0xa0 / 255, 0x6f / 255, 1]);
    expect(parseHexColor('#00000000')).toEqual([0, 0, 0, 0]);
    expect(() => parseHexColor('vermelho')).toThrow('Cor inválida');
  });
});

describe('ApsViewerAdapter · coordenadas do eixo', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Viewer falso com árvore (raiz 1 → pilar 10 → sólido 11), malha normalizada e overlay. */
  function geometryFake(aec: unknown = { refPointTransformation: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0] }) {
    const fake = fakeAutodesk();
    const children: Record<number, number[]> = { 1: [10], 10: [11], 11: [] };
    const parent: Record<number, number> = { 10: 1, 11: 10 };
    const fragsOf: Record<number, number[]> = { 11: [7] };
    const props: Record<number, { name: string; properties: { displayName: string; displayCategory?: string; displayValue: unknown }[] }> = {
      10: {
        name: 'Pilar [6657283]',
        properties: [
          { displayName: 'Category', displayCategory: 'Fases', displayValue: 'Fases' },
          { displayName: 'Category', displayCategory: 'Element', displayValue: 'Pilares estruturais' },
          { displayName: 'Material', displayValue: 'Concreto' },
        ],
      },
      11: { name: 'IfcExtrudedAreaSolid::Concreto', properties: [] },
    };
    const model = {
      getData: () => ({ globalOffset: { x: 100, y: 200, z: 0 } }),
      getUnitScale: () => 0.3048,
      getInstanceTree: () => ({
        getRootId: () => 1,
        getNodeParentId: (id: number) => parent[id] ?? 0,
        enumNodeChildren: (id: number, cb: (c: number) => void) => { (children[id] ?? []).forEach(cb); },
        enumNodeFragments: (id: number, cb: (f: number) => void) => { (fragsOf[id] ?? []).forEach(cb); },
      }),
      // fragmento 7: escala 2 e translação (5, 6, 7) aplicadas à malha unitária
      getFragmentList: () => ({
        getWorldMatrix: (_f: number, out: { elements: number[] }) => {
          out.elements = [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 5, 6, 7, 1];
        },
      }),
      getProperties: (id: number, ok: (r: (typeof props)[number]) => void, fail: (e: unknown) => void) => {
        const p = props[id];
        if (p) ok(p);
        else fail(new Error('sem propriedades'));
      },
    };
    fake.viewer.loadDocumentNode.mockResolvedValue(model);
    const overlay = { added: [] as unknown[], removed: [] as unknown[], scenes: [] as string[], invalidated: 0 };
    Object.assign(fake.viewer, {
      impl: {
        // vb intercalado (stride 6: posição + normal), posição no deslocamento 0
        getRenderProxy: () => ({
          geometry: { vb: [0, 0, 0, 9, 9, 9, 1, 0, 0, 9, 9, 9, 0, 1, 0, 9, 9, 9], vbstride: 6, attributes: { position: { offset: 0 } }, ib: [0, 1, 2] },
        }),
        createOverlayScene: (name: string) => overlay.scenes.push(name),
        addOverlay: (_n: string, obj: unknown) => overlay.added.push(obj),
        removeOverlay: (_n: string, obj: unknown) => overlay.removed.push(obj),
        invalidate: () => { overlay.invalidated += 1; },
      },
    });
    Object.assign(fake.av.Viewing.Document, { getAecModelData: () => Promise.resolve(aec) });
    class Obj {
      position = { set: vi.fn() };
    }
    class Stub {
      readonly stub = true;
    }
    vi.stubGlobal('THREE', {
      Vector4,
      Matrix4: class {
        elements: number[] = [];
      },
      Vector3: Stub,
      Geometry: class {
        vertices: unknown[] = [];
      },
      SphereGeometry: Stub,
      MeshBasicMaterial: Stub,
      LineBasicMaterial: Stub,
      Mesh: Obj,
      Line: Obj,
    });
    return { fake, overlay };
  }

  it('dados de conversão: globalOffset, unidade e ponto de referência do AEC (sem mudar a carga)', async () => {
    const { fake } = geometryFake();
    const { adapter } = makeAdapter(fake);
    expect(adapter.getModelFrame()).toBeNull(); // antes de carregar
    await adapter.load('dXJu');
    expect(adapter.getModelFrame()).toEqual({
      globalOffset: [100, 200, 0],
      unitScaleToM: 0.3048,
      refPointTransformation: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
    });
    expect(fake.viewer.loadDocumentNode.mock.calls[0]).toHaveLength(2); // sem opções de carga
  });

  it('sem AEC (IFC/NWD): sem ponto de referência', async () => {
    const { fake } = geometryFake(null);
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJu');
    expect(adapter.getModelFrame()?.refPointTransformation).toBeNull();
  });

  it('nós: categoria do grupo Element, material, pai e filhos, geometria própria', async () => {
    const { fake } = geometryFake();
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJu');
    const [pilar, solido] = await adapter.getNodes([10, 11]);
    expect(pilar).toMatchObject({ dbId: 10, parent: 1, children: [11], category: 'Pilares estruturais', material: 'Concreto', hasGeometry: false });
    expect(solido).toMatchObject({ dbId: 11, parent: 10, children: [], name: 'IfcExtrudedAreaSolid::Concreto', hasGeometry: true });
  });

  it('triângulos em coordenadas de mundo: matriz da lista de fragmentos sobre a malha normalizada', async () => {
    const { fake } = geometryFake();
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJu');
    expect(adapter.getTriangles(11)).toEqual([
      [
        [5, 6, 7],
        [7, 6, 7],
        [5, 8, 7],
      ],
    ]);
    expect(adapter.getTriangles(10)).toEqual([]); // só a geometria PRÓPRIA do nó
  });

  it('marcador: esfera no ponto, esferas + linha na viga; null apaga', async () => {
    const { fake, overlay } = geometryFake();
    const { adapter } = makeAdapter(fake);
    await adapter.load('dXJu');
    adapter.showAxisMarker([[1, 2, 3]]);
    expect(overlay.scenes).toContain('cassol-eixo');
    expect(overlay.added).toHaveLength(1);
    adapter.showAxisMarker([
      [0, 0, 0],
      [8, 0, 0],
    ]);
    expect(overlay.removed).toHaveLength(1);
    expect(overlay.added).toHaveLength(4); // 1 + (2 esferas + 1 linha)
    adapter.showAxisMarker(null);
    expect(overlay.removed).toHaveLength(4);
  });
});
