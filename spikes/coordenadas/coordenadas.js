// Spike "coordenadas": eixo da peça clicada no Viewer, relativo ao ponto base do projeto.
// Carrega o modelo com as MESMAS opções do app (GuiViewer3D, getDefaultGeometry,
// loadDocumentNode sem opções). ?applyRefPoint=1 só para experimentar (nunca no app).
// API para o run.mjs: window.__COORD = { ready, info(), measure(dbId), samples() }.

import { kindFromCategory, meshVolume, pieceAxis, refFromAec, toProjectBase } from '/axis.js';

const $ = (id) => document.getElementById(id);
const setStatus = (msg, err) => {
  $('status').textContent = msg;
  $('status').className = err ? 'erro' : '';
};
const params = new URLSearchParams(location.search);
const urn = params.get('urn');
const applyRefPoint = params.get('applyRefPoint') === '1';

// Membros que não são o concreto da peça (ignorar): armaduras, insertos, conexões.
const NOT_CONCRETE =
  /vergalh|armadur|rebar|reinforc|estribo|insert|chumbador|conex|connection|fastener|ferragem|alça|içamento|neoprene|elastômero|ifcopening|opening|abertura|ifcreinforcing|ifcmechanicalfastener|ifcdiscreteaccessory|ifcfastener/i;
const ASSEMBLY = /montage|assembl|ifcelementassembly/i;
const CONCRETE = /concreto|concrete|betão|beton/i;
// ?ignore=<regex>: troca a lista do que não é concreto (só para experimentos do spike)
const IGNORE = params.get('ignore') ? new RegExp(params.get('ignore'), 'i') : NOT_CONCRETE;

let viewer;
let model;
let doc;
let aec = null;

/** Cópia serializável (sem ciclos nem nós do bubble; profundidade limitada). */
function plain(value, depth = 6, seen = new WeakSet()) {
  if (value === null || typeof value !== 'object') return value;
  if (seen.has(value) || depth === 0) return '[…]';
  seen.add(value);
  if (Array.isArray(value)) return value.slice(0, 500).map((v) => plain(v, depth - 1, seen));
  if (ArrayBuffer.isView(value)) return Array.from(value);
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    if (k === 'parent' || k === 'children' || typeof v === 'function') continue;
    out[k] = plain(v, depth - 1, seen);
  }
  return out;
}

function getProps(dbId) {
  return new Promise((resolve, reject) => model.getProperties(dbId, resolve, reject));
}

/** Texto com nome, categoria, classe IFC e tipo (para decidir tipo e o que ignorar). */
async function describe(dbId) {
  const p = await getProps(dbId);
  const pick = (names) =>
    p.properties.filter((x) => names.includes(x.displayName) || names.includes(x.attributeName)).map((x) => String(x.displayValue));
  // Categoria do PRÓPRIO elemento: no NWD "Category" se repete em vários grupos (Fases,
  // Conexões estruturais…); vale a do grupo Element; senão a primeira.
  const cats = p.properties.filter((x) => ['Category', 'Categoria', '_RC'].includes(x.displayName));
  const own = cats.find((x) => x.displayCategory === 'Element') ?? cats[0];
  const category = own ? String(own.displayValue) : '';
  const ifc = pick(['IfcClass', 'Ifc Class', 'Entity', 'Type']).join(' ');
  const material = pick(['Material', 'Materials', 'Appearance', 'Material estrutural', 'Structural Material']).join(' ');
  return { dbId, name: p.name, externalId: p.externalId, category, ifc, material, text: `${p.name} ${category} ${ifc}` };
}

function fragIds(dbId, recursive = true) {
  const out = [];
  // o callback NÃO pode devolver valor verdadeiro: o Viewer para de enumerar
  model.getInstanceTree().enumNodeFragments(dbId, (f) => { out.push(f); }, recursive);
  return out;
}

/** Triângulos (mundo do Viewer) de um fragmento, lidos da malha carregada. */
function fragTriangles(fragId) {
  const proxy = viewer.impl.getRenderProxy(model, fragId);
  const g = proxy && proxy.geometry;
  if (!g || g.isLines || g.isWideLines || g.isPoints) return [];
  // A malha do SVF2 (OTG) vem normalizada; a transformação do fragmento (posição no
  // modelo, já com o globalOffset) é a da lista de fragmentos, não a do objeto.
  const world = new THREE.Matrix4();
  model.getFragmentList().getWorldMatrix(fragId, world);
  const m = world.elements;
  const pos = g.attributes && g.attributes.position;
  const vb = g.vb || (pos && pos.array);
  const stride = g.vb ? g.vbstride || 3 : (pos && pos.itemSize) || 3;
  const off = g.vb ? (pos ? (pos.offset ?? pos.itemOffset ?? 0) : 0) : 0;
  const ib = g.ib || (g.index && g.index.array);
  if (!vb) return [];
  const vert = (i) => {
    const x = vb[i * stride + off];
    const y = vb[i * stride + off + 1];
    const z = vb[i * stride + off + 2];
    return [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]];
  };
  const tris = [];
  if (ib) {
    for (let i = 0; i + 2 < ib.length; i += 3) tris.push([vert(ib[i]), vert(ib[i + 1]), vert(ib[i + 2])]);
  } else {
    const n = vb.length / stride;
    for (let i = 0; i + 2 < n; i += 3) tris.push([vert(i), vert(i + 1), vert(i + 2)]);
  }
  return tris;
}

function nodeTriangles(dbId) {
  return fragIds(dbId).flatMap(fragTriangles);
}

/** Nó de geometria (sólido do IFC "IfcExtrudedAreaSolid::material", nó intermediário):
 * sem categoria (Revit) e sem classe IFC/tipo; o elemento acima dele é a peça. */
const isGeometryItem = (d) => !d.category && !d.ifc;

/**
 * Peça clicada → membro de concreto.
 * 1. Sobe de um nó de geometria até o elemento; sobe do elemento até a montagem, se houver.
 * 2. Membros: numa montagem, cada elemento filho; senão, o próprio elemento.
 * 3. A geometria de um membro junta os sólidos dele que são concreto (o consolo entra:
 *    faz parte da peça); fora: armaduras, insertos, neoprene, aberturas.
 * 4. O membro principal é o de maior volume.
 */
async function mainMember(clicked) {
  const it = model.getInstanceTree();
  const root = it.getRootId();
  let element = clicked;
  for (let i = 0; i < 4; i++) {
    const d = await describe(element);
    const parent = it.getNodeParentId(element);
    if (!isGeometryItem(d) || !parent || parent === root) break;
    element = parent;
  }
  let top = element;
  for (let p = it.getNodeParentId(element), i = 0; p && p !== root && i < 4; p = it.getNodeParentId(p), i++) {
    const d = await describe(p);
    if (ASSEMBLY.test(d.text)) top = p;
  }
  const memberIds = [];
  if (top !== element || ASSEMBLY.test((await describe(top)).text)) {
    it.enumNodeChildren(top, (c) => { memberIds.push(c); });
  }
  if (memberIds.length === 0) memberIds.push(element);

  const candidates = [];
  for (const id of memberIds) {
    const d = await describe(id);
    const parts = [];
    const walk = (n) => {
      if (fragIds(n, false).length > 0) parts.push(n);
      it.enumNodeChildren(n, walk);
    };
    walk(id);
    let tris = [];
    const used = [];
    const skipped = [];
    for (const part of parts) {
      const pd = part === id ? d : await describe(part);
      if (IGNORE.test(`${pd.text} ${pd.material}`)) {
        skipped.push(pd.name);
        continue;
      }
      tris = tris.concat(fragIds(part, false).flatMap(fragTriangles));
      used.push(pd.name);
    }
    const ignored = IGNORE.test(`${d.text} ${d.material}`);
    candidates.push({ ...d, ignored, used, skipped, triangles: tris.length, volume: tris.length ? meshVolume(tris) : 0, tris });
  }
  // concreto primeiro (pelo material); depois qualquer um não ignorado; maior volume
  const usable = candidates.filter((c) => !c.ignored && c.triangles > 0);
  // o material pode estar no elemento ou só nos sólidos dele (nome "Ifc…Solid::material")
  const concrete = usable.filter((c) => CONCRETE.test(`${c.material} ${c.used.join(' ')}`));
  const pool = concrete.length ? concrete : usable.length ? usable : candidates;
  const best = [...pool].sort((a, b) => b.volume - a.volume)[0];
  return { assembly: top !== element ? top : null, member: best, members: candidates.map(({ tris, ...c }) => c) };
}

function unitToMm() {
  const s = model.getUnitScale ? model.getUnitScale() : 1; // unidade do modelo -> metros
  return s * 1000;
}

function refPoint() {
  return aec && aec.refPointTransformation ? refFromAec(aec.refPointTransformation) : null;
}

const fmt = (p) => p.map((x) => x.toFixed(1));

/** Pontos do eixo em mm: sem ponto base (arquivo), hipótese A e hipótese B. */
function convert(points) {
  const off = model.getData().globalOffset || { x: 0, y: 0, z: 0 };
  const g = [off.x, off.y, off.z];
  const ref = refPoint();
  const k = unitToMm();
  const out = {};
  for (const [name, p] of Object.entries(points)) {
    out[name] = {
      viewer: p,
      arquivo_mm: toProjectBase(p, g, null, k),
      pbp_A_mm: ref ? toProjectBase(p, g, ref, k) : null,
      pbp_B_mm: ref ? toProjectBase(p, g, ref, k, true) : null,
    };
  }
  return out;
}

async function measure(dbId) {
  const { assembly, member, members } = await mainMember(dbId);
  if (!member || member.triangles === 0) throw new Error(`sem geometria para ${dbId}`);
  const kind = kindFromCategory(`${member.category} ${member.ifc}`) || kindFromCategory((await describe(assembly ?? dbId)).text);
  const r = pieceAxis(member.tris, kind);
  const points = r.kind === 'viga' ? { inicio: r.start, fim: r.end } : r.kind === 'pilar' ? { base: r.point, topo: r.top } : { centro_inferior: r.point };
  return {
    clicked: dbId,
    assembly,
    member: { dbId: member.dbId, name: member.name, externalId: member.externalId, category: member.category, ifc: member.ifc, volume: member.volume, triangles: member.triangles, used: member.used, skipped: member.skipped },
    members,
    kind: r.kind,
    section_model_units: r.section,
    cuts: r.cuts,
    extents_model_units: r.extents,
    points: convert(points),
  };
}

async function info() {
  const data = model.getData();
  const md = data.metadata || {};
  return plain({
    urn,
    viewerVersion: Autodesk.Viewing.Private?.VIEWER_VERSION ?? null,
    loadOptions: data.loadOptions ?? null,
    globalOffset: data.globalOffset ?? null,
    placementWithOffset: data.placementWithOffset?.elements ?? null,
    placementTransform: model.getPlacementTransform?.()?.elements ?? null,
    unitString: model.getUnitString?.() ?? null,
    unitScale_to_m: model.getUnitScale?.() ?? null,
    displayUnit: model.getDisplayUnit?.() ?? null,
    metadata_distance_unit: md['distance unit'] ?? null,
    metadata_custom_values: md['custom values'] ?? null,
    metadata_georeference: md.georeference ?? null,
    metadata_world_bbox: md['world bounding box'] ?? null,
    bbox: model.getBoundingBox ? (({ min, max }) => ({ min, max }))(model.getBoundingBox()) : null,
    aec,
  });
}

/** Uma peça de cada tipo (pilar, viga, laje), pela categoria; para o run.mjs. */
async function samples(max = 2) {
  const it = model.getInstanceTree();
  const leaves = [];
  it.enumNodeChildren(it.getRootId(), (id) => { if (fragIds(id, false).length > 0) leaves.push(id); }, true);
  const props = await new Promise((resolve, reject) =>
    model.getBulkProperties(leaves, { propFilter: ['Category', 'IfcClass', 'name', 'Type'] }, resolve, reject),
  );
  const found = { pilar: [], viga: [], laje: [] };
  for (const p of props) {
    const text = [p.name, ...p.properties.map((x) => String(x.displayValue))].join(' ');
    const k = kindFromCategory(text);
    if (k && found[k].length < max && !NOT_CONCRETE.test(text)) found[k].push(p.dbId);
  }
  return found;
}

function renderPiece(r) {
  const rows = Object.entries(r.points)
    .map(([name, p]) => {
      const v = p.pbp_A_mm ?? p.arquivo_mm;
      return `<tr><td>${name}</td><td>${fmt(v).join('</td><td>')}</td></tr>`;
    })
    .join('');
  $('piece').innerHTML =
    `<p><b>${r.kind}</b> · ${r.member.name} (dbId ${r.member.dbId}${r.assembly ? `, montagem ${r.assembly}` : ''})</p>` +
    `<table><tr><th></th><th>X</th><th>Y</th><th>Z</th></tr>${rows}</table>` +
    `<pre>${JSON.stringify({ ...r, members: undefined }, null, 1)}</pre>`;
}

async function main() {
  if (!urn) {
    setStatus('Informe ?urn=<URN base64>', true);
    return;
  }
  const cfg = await (await fetch('/config')).json();
  await new Promise((resolve) =>
    Autodesk.Viewing.Initializer(
      {
        env: 'AutodeskProduction2',
        api: cfg.region === 'EMEA' ? 'streamingV2_EU' : 'streamingV2',
        getAccessToken: async (ok) => {
          const t = await (await fetch('/token')).json();
          ok(t.access_token, t.expires_in);
        },
      },
      resolve,
    ),
  );
  viewer = new Autodesk.Viewing.GuiViewer3D($('viewer'));
  viewer.start();
  doc = await new Promise((resolve, reject) => Autodesk.Viewing.Document.load(`urn:${urn}`, resolve, (c, m) => reject(new Error(`${c} ${m}`))));
  const node = doc.getRoot().getDefaultGeometry();
  // AEC model data (Revit): níveis, grids, refPointTransformation…
  try {
    if (Autodesk.Viewing.Document.getAecModelData) aec = plain(await Autodesk.Viewing.Document.getAecModelData(node));
    else if (doc.downloadAecModelData) {
      await doc.downloadAecModelData();
      aec = plain(doc.getRoot().getAecModelData?.() ?? null);
    }
  } catch (e) {
    aec = { error: String(e) };
  }
  model = applyRefPoint ? await viewer.loadDocumentNode(doc, node, { applyRefPoint: true }) : await viewer.loadDocumentNode(doc, node);
  await new Promise((resolve) => {
    if (model.isLoadDone && model.isLoadDone()) resolve();
    else viewer.addEventListener(Autodesk.Viewing.GEOMETRY_LOADED_EVENT, resolve, { once: true });
  });
  const i = await info();
  $('info').textContent = JSON.stringify({ ...i, aec: aec ? { ...aec, grids: undefined, levels: aec.levels?.length } : null }, null, 1);
  setStatus(`Modelo carregado${applyRefPoint ? ' (applyRefPoint: SÓ NO SPIKE)' : ''}. Clique numa peça.`);
  viewer.addEventListener(Autodesk.Viewing.SELECTION_CHANGED_EVENT, async (ev) => {
    const id = ev.dbIdArray?.[0];
    if (id === undefined) return;
    try {
      renderPiece(await measure(id));
    } catch (e) {
      $('piece').textContent = String(e);
    }
  });
}

const ready = main().catch((e) => {
  setStatus(String(e), true);
  throw e;
});
/**
 * Peças com este ElementId do Revit, EXATO: "Element ID/Value" (NWD), "Tag" (IFC) ou
 * "[id]" no nome (RVT).
 */
async function find(text) {
  const t = String(text);
  let ids = await new Promise((resolve, reject) => model.search(t, resolve, reject));
  if (ids.length === 0) {
    // RVT: o ElementId só aparece no nome ("Pilar [6657283]")
    const it = model.getInstanceTree();
    it.enumNodeChildren(it.getRootId(), (id) => { if (it.getNodeName(id)?.endsWith(`[${t}]`)) ids.push(id); }, true);
    return ids.filter((id) => fragIds(id).length > 0);
  }
  const props = await new Promise((resolve, reject) =>
    model.getBulkProperties(ids, { propFilter: ['Value', 'Tag', 'Id'] }, resolve, reject),
  );
  const exact = props
    .filter((p) =>
      p.properties.some(
        (x) =>
          ((x.displayCategory === 'Element ID' && x.displayName === 'Value') ||
            (x.displayCategory === 'IFC Attributes' && x.displayName === 'Tag')) &&
          String(x.displayValue) === t,
      ),
    )
    .map((p) => p.dbId);
  return exact.filter((id) => fragIds(id).length > 0);
}

window.__COORD = { ready, info, measure, samples, find, triangles: (id) => nodeTriangles(id), members: async (id) => { const r = await mainMember(id); return { assembly: r.assembly, members: r.members }; }, describe: async (id) => { const d = await describe(id); const p = await getProps(id); return { ...d, props: p.properties.map((x) => `${x.displayCategory}/${x.displayName}=${String(x.displayValue).slice(0, 60)}`).slice(0, 40) }; } };
