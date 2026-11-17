/**
 * Coordenadas do EIXO da peça clicada, relativas ao ponto base do projeto
 * (método e resultados em docs/coordenadas.md).
 *
 * Só matemática e regras: não conhece o Autodesk Viewer (CLAUDE.md). A geometria e a
 * árvore do modelo chegam pelo ViewerAdapter (`GeometrySource`).
 *
 * 1. Clique → elemento (sobe dos nós de geometria) → montagem, se houver.
 * 2. Membro principal: entre os membros de CONCRETO (material), o de maior volume; fora
 *    armaduras, alças, esperas, insertos, conexões, neoprene e aberturas. A geometria do
 *    membro junta os sólidos de concreto dele (engastamento e consolo entram).
 * 3. Eixo: PCA com os momentos exatos da superfície, refinada pelos centros dos cortes
 *    de menor seção (o corpo prismático); pontas sem os trechos finos (< 20% da seção).
 * 4. Ponto pela regra de Z por tipo (AXIS_Z_RULE): pilar base|topo; viga meia altura|
 *    face inferior|face superior (início e fim); laje face inferior|face superior.
 * 5. Conversão: modelo = mundo + globalOffset; ponto base = Rᵀ·(modelo − t)
 *    (refPointTransformation); × unidade → metros.
 */

import type { DbId, ModelFrame, ModelNode, Triangle, Vec3 } from './ViewerAdapter';

// ------------------------------------------------------------------ vetores

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const mul = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
export const norm = (a: Vec3): number => Math.hypot(a[0], a[1], a[2]);
export const unit = (a: Vec3): Vec3 => mul(a, 1 / (norm(a) || 1));
const UP: Vec3 = [0, 0, 1];

type Mat3 = [Vec3, Vec3, Vec3];
const zero3 = (): Mat3 => [
  [0, 0, 0],
  [0, 0, 0],
  [0, 0, 0],
];
const at = (m: Mat3, i: number, j: number): number => m[i]?.[j] ?? 0;
/** a·bᵀ */
const outer = ([a0, a1, a2]: Vec3, [b0, b1, b2]: Vec3): Mat3 => [
  [a0 * b0, a0 * b1, a0 * b2],
  [a1 * b0, a1 * b1, a1 * b2],
  [a2 * b0, a2 * b1, a2 * b2],
];
const addMat = (x: Mat3, y: Mat3): Mat3 => [add(x[0], y[0]), add(x[1], y[1]), add(x[2], y[2])];
const scaleMat = (x: Mat3, k: number): Mat3 => [mul(x[0], k), mul(x[1], k), mul(x[2], k)];
type Eigen = { value: number; vector: Vec3 };
function set(m: Mat3, i: number, j: number, v: number): void {
  const row = m[i];
  if (row) row[j] = v;
}

/** Autovetores de uma matriz 3x3 simétrica (Jacobi), do maior autovalor para o menor. */
export function eigenSym3(input: Mat3): [Eigen, Eigen, Eigen] {
  const a: Mat3 = [[...input[0]], [...input[1]], [...input[2]]];
  const v: Mat3 = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ];
  const pairs: [number, number][] = [
    [0, 1],
    [0, 2],
    [1, 2],
  ];
  for (let sweep = 0; sweep < 50; sweep++) {
    if (Math.abs(at(a, 0, 1)) + Math.abs(at(a, 0, 2)) + Math.abs(at(a, 1, 2)) < 1e-18) break;
    for (const [p, q] of pairs) {
      const apq = at(a, p, q);
      if (Math.abs(apq) < 1e-30) continue;
      const theta = (at(a, q, q) - at(a, p, p)) / (2 * apq);
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
      const c = 1 / Math.sqrt(t * t + 1);
      const s = t * c;
      for (let k = 0; k < 3; k++) {
        const akp = at(a, k, p);
        const akq = at(a, k, q);
        set(a, k, p, c * akp - s * akq);
        set(a, k, q, s * akp + c * akq);
      }
      for (let k = 0; k < 3; k++) {
        const apk = at(a, p, k);
        const aqk = at(a, q, k);
        set(a, p, k, c * apk - s * aqk);
        set(a, q, k, s * apk + c * aqk);
      }
      for (let k = 0; k < 3; k++) {
        const vkp = at(v, k, p);
        const vkq = at(v, k, q);
        set(v, k, p, c * vkp - s * vkq);
        set(v, k, q, s * vkp + c * vkq);
      }
    }
  }
  const pair = (i: number): Eigen => ({ value: at(a, i, i), vector: [at(v, 0, i), at(v, 1, i), at(v, 2, i)] });
  return [pair(0), pair(1), pair(2)].sort((x, y) => y.value - x.value) as [Eigen, Eigen, Eigen];
}

// ------------------------------------------------------------------ geometria

/**
 * PCA da superfície com os momentos EXATOS de cada triângulo (área A, s = a + b + c):
 * ∫x dA = A·s/3, ∫x·xᵀ dA = A/12·(aaᵀ + bbᵀ + ccᵀ + ssᵀ). Só os centroides desviariam a
 * direção (a diagonal que divide cada face não é simétrica).
 */
export function surfacePca(triangles: Triangle[]): { center: Vec3; axes: [Vec3, Vec3, Vec3] } {
  let total = 0;
  let first: Vec3 = [0, 0, 0];
  let second = zero3();
  for (const [a, b, c] of triangles) {
    const area = norm(cross(sub(b, a), sub(c, a))) / 2;
    if (!(area > 0)) continue;
    const s = add(add(a, b), c);
    total += area;
    first = add(first, mul(s, area / 3));
    const sum = addMat(addMat(outer(a, a), outer(b, b)), addMat(outer(c, c), outer(s, s)));
    second = addMat(second, scaleMat(sum, area / 12));
  }
  if (total <= 0) throw new Error('A peça não tem geometria.');
  const center = mul(first, 1 / total);
  const cov = addMat(scaleMat(second, 1 / total), scaleMat(outer(center, center), -1));
  const [major, middle] = eigenSym3(cov);
  const e1 = unit(major.vector);
  let e2 = unit(sub(middle.vector, mul(e1, dot(middle.vector, e1))));
  const e3 = unit(cross(e1, e2));
  e2 = unit(cross(e3, e1));
  return { center, axes: [e1, e2, e3] };
}

/** [min, max] das projeções dos vértices numa direção. */
export function range(triangles: Triangle[], dir: Vec3): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const tri of triangles) {
    for (const p of tri) {
      const t = dot(p, dir);
      if (t < lo) lo = t;
      if (t > hi) hi = t;
    }
  }
  return [lo, hi];
}

function rangePts(points: Vec3[], dir: Vec3): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of points) {
    const t = dot(p, dir);
    if (t < lo) lo = t;
    if (t > hi) hi = t;
  }
  return [lo, hi];
}

/** Pontos onde o plano {x : x·n = t} corta as arestas dos triângulos. */
export function slice(triangles: Triangle[], n: Vec3, t: number): Vec3[] {
  const out: Vec3[] = [];
  for (const [p0, p1, p2] of triangles) {
    const d0 = dot(p0, n) - t;
    const d1 = dot(p1, n) - t;
    const d2 = dot(p2, n) - t;
    const edges: [Vec3, number, Vec3, number][] = [
      [p0, d0, p1, d1],
      [p1, d1, p2, d2],
      [p2, d2, p0, d0],
    ];
    for (const [pi, di, pj, dj] of edges) {
      if ((di < 0 && dj > 0) || (di > 0 && dj < 0)) out.push(add(pi, mul(sub(pj, pi), di / (di - dj))));
      else if (di === 0) out.push(pi);
    }
  }
  return out;
}

interface Section {
  u: number;
  v: number;
  du: number;
  dv: number;
}
function center2(points: Vec3[], u: Vec3, v: Vec3): Section {
  const [ulo, uhi] = rangePts(points, u);
  const [vlo, vhi] = rangePts(points, v);
  return { u: (ulo + uhi) / 2, v: (vlo + vhi) / 2, du: uhi - ulo, dv: vhi - vlo };
}

/** Volume da malha fechada (escolhe o membro de concreto). */
export function meshVolume(triangles: Triangle[]): number {
  let v = 0;
  for (const [a, b, c] of triangles) v += dot(a, cross(b, c)) / 6;
  return Math.abs(v);
}

/** Base da seção: v o mais "para cima" possível (meia altura = centro em v). */
function sectionBasis(dir: Vec3, hint: Vec3): { u: Vec3; v: Vec3 } {
  let v = sub(UP, mul(dir, dot(UP, dir)));
  if (norm(v) < 0.2) v = sub(hint, mul(dir, dot(hint, dir))); // peça vertical: faces da PCA
  if (norm(v) < 1e-6) v = Math.abs(dir[0]) < 0.9 ? cross(dir, [1, 0, 0]) : cross(dir, [0, 1, 0]);
  v = unit(v);
  return { u: unit(cross(v, dir)), v };
}

interface AxisLine {
  point: Vec3;
  dir: Vec3;
  u: Vec3;
  v: Vec3;
  /** largura (u) e altura (v) da seção do corpo */
  section: [number, number];
}

/**
 * Reta do eixo: 9 cortes de 5% a 95% do comprimento; ficam os de MENOR seção (o corpo:
 * consolo e dente aumentam a seção); a reta passa pelos centros deles. 3 iterações.
 */
export function axisLine(triangles: Triangle[], first: Vec3, hint: Vec3): AxisLine {
  let dir = unit(first);
  let result: AxisLine | null = null;
  for (let iter = 0; iter < 3; iter++) {
    const { u, v } = sectionBasis(dir, hint);
    const [tlo, thi] = range(triangles, dir);
    const len = thi - tlo;
    const found: { t: number; c: Section; area: number }[] = [];
    for (let i = 0; i <= 8; i++) {
      const t = tlo + len * (0.05 + (0.9 * i) / 8);
      const pts = slice(triangles, dir, t);
      if (pts.length < 3) continue;
      const c = center2(pts, u, v);
      found.push({ t, c, area: c.du * c.dv });
    }
    if (found.length === 0) throw new Error('Não foi possível cortar a peça para achar o eixo.');
    const minArea = Math.min(...found.map((f) => f.area));
    const kept = found.filter((f) => f.area <= minArea * 1.02 + 1e-12);
    const centers = kept.map((f) => add(add(mul(dir, f.t), mul(u, f.c.u)), mul(v, f.c.v)));
    const point = mul(
      centers.reduce<Vec3>((acc, p) => add(acc, p), [0, 0, 0]),
      1 / centers.length,
    );
    const body = kept[0];
    if (!body) throw new Error('Não foi possível achar a seção da peça.');
    result = { point, dir, u, v, section: [body.c.du, body.c.dv] };
    if (centers.length < 2) break;
    const cov = centers.reduce((acc, p) => {
      const d = sub(p, point);
      return addMat(acc, outer(d, d));
    }, zero3());
    let next = unit(eigenSym3(cov)[0].vector);
    if (dot(next, dir) < 0) next = mul(next, -1);
    const change = norm(sub(next, dir));
    dir = next;
    if (change < 1e-12) break;
  }
  if (!result) throw new Error('Eixo não encontrado.');
  const { u, v } = sectionBasis(dir, hint);
  return { ...result, dir, u, v };
}

/**
 * Faixa do eixo onde a peça tem CORPO: de cada extremo para dentro (até 15% do
 * comprimento), descarta o trecho com seção < `frac` da seção do corpo (ex.: o neoprene
 * que o SVF2 do RVT junta ao concreto). Dentes e consolos (seção grande) ficam.
 */
export function trimmedRange(triangles: Triangle[], line: AxisLine, frac = 0.2): [number, number] {
  const [tlo, thi] = range(triangles, line.dir);
  const len = thi - tlo;
  const body = line.section[0] * line.section[1];
  const solid = (t: number): boolean => {
    const pts = slice(triangles, line.dir, t);
    if (pts.length < 3) return false;
    const c = center2(pts, line.u, line.v);
    return c.du * c.dv >= frac * body;
  };
  const edge = (from: number, sign: 1 | -1): number => {
    const step = len / 3000;
    let prev = from;
    for (let t = from + sign * step * 0.5; sign * (t - from) <= 0.15 * len; t += sign * step) {
      if (solid(t)) {
        let a = prev;
        let b = t;
        for (let i = 0; i < 30; i++) {
          const m = (a + b) / 2;
          if (solid(m)) b = m;
          else a = m;
        }
        return (a + b) / 2;
      }
      prev = t;
    }
    return from;
  };
  return [edge(tlo, 1), edge(thi, -1)];
}

// ------------------------------------------------------------------ tipos e regra de Z

export type PieceKind = 'pilar' | 'viga' | 'laje';
export type AxisZRule = Record<PieceKind, string>;
export const DEFAULT_AXIS_Z_RULE: AxisZRule = { pilar: 'base', viga: 'meia altura', laje: 'face inferior' };

/** Tipo pela categoria (Revit pt/en, classe IFC); null = decidir pela forma. */
export function kindFromCategory(text: string): PieceKind | null {
  const s = text.toLowerCase();
  if (/pilar|column/.test(s)) return 'pilar';
  if (/viga|quadro estrutural|framing|beam/.test(s)) return 'viga';
  if (/laje|piso|floor|slab|ifcplate/.test(s)) return 'laje';
  return null;
}

/** Tipo pela forma: laje (fina), pilar (eixo vertical) ou viga. */
export function kindFromShape(triangles: Triangle[]): PieceKind {
  const { axes } = surfacePca(triangles);
  const [l1, l2, l3] = axes.map((d) => {
    const [lo, hi] = range(triangles, d);
    return hi - lo;
  }) as [number, number, number];
  if (l3 < 0.35 * l2 && l2 > 0.25 * l1) return 'laje';
  return Math.abs(dot(axes[0], UP)) > 0.7 ? 'pilar' : 'viga';
}

export interface AxisPoint {
  /** "Eixo" (pilar e laje) ou "Início" / "Fim" (viga) */
  label: string;
  /** coordenadas de mundo do Viewer (para o marcador) */
  world: Vec3;
}

export interface PieceAxis {
  kind: PieceKind;
  rule: string;
  points: AxisPoint[];
}

/** Pontos do eixo pela regra de Z (em coordenadas de mundo do Viewer). */
export function pieceAxis(triangles: Triangle[], kind: PieceKind, rules: AxisZRule = DEFAULT_AXIS_Z_RULE): PieceAxis {
  const rule = rules[kind];
  const pca = surfacePca(triangles);
  const [e1, e2, e3] = pca.axes;

  if (kind === 'laje') {
    const n = dot(e3, UP) < 0 ? mul(e3, -1) : e3;
    const [nlo, nhi] = range(triangles, n);
    const [alo, ahi] = range(triangles, e1);
    const [blo, bhi] = range(triangles, e2);
    const z = rule === 'face superior' ? nhi : nlo;
    const p = add(add(mul(e1, (alo + ahi) / 2), mul(e2, (blo + bhi) / 2)), mul(n, z));
    return { kind, rule, points: [{ label: 'Eixo', world: p }] };
  }

  const line = axisLine(triangles, kind === 'pilar' && dot(e1, UP) < 0 ? mul(e1, -1) : e1, e2);
  const [tlo, thi] = trimmedRange(triangles, line);
  // face inferior/superior da viga: meia seção abaixo/acima do eixo (direção v, "para cima")
  const shift = kind === 'viga' && rule !== 'meia altura' ? mul(line.v, ((rule === 'face superior' ? 1 : -1) * line.section[1]) / 2) : ([0, 0, 0] as Vec3);
  const onAxis = (t: number): Vec3 => add(add(line.point, mul(line.dir, t - dot(line.point, line.dir))), shift);

  if (kind === 'pilar') {
    return { kind, rule, points: [{ label: 'Eixo', world: onAxis(rule === 'topo' ? thi : tlo) }] };
  }
  // viga: início e fim em ordem estável (menor X, depois menor Y)
  const a = onAxis(tlo);
  const b = onAxis(thi);
  const [start, end] = a[0] - b[0] < 0 || (a[0] === b[0] && a[1] <= b[1]) ? [a, b] : [b, a];
  return {
    kind,
    rule,
    points: [
      { label: 'Início', world: start },
      { label: 'Fim', world: end },
    ],
  };
}

// ------------------------------------------------------------------ conversão

/**
 * Mundo do Viewer → ponto base do projeto, em METROS:
 * modelo = mundo + globalOffset; pbp = Rᵀ·(modelo − t), R e t da refPointTransformation
 * (colunas X, Y, Z e origem); × unitScaleToM.
 */
export function toProjectBase(world: Vec3, frame: ModelFrame): Vec3 {
  const m = add(world, frame.globalOffset);
  const ref = frame.refPointTransformation;
  if (!ref || ref.length < 12) return mul(m, frame.unitScaleToM);
  const col = (i: number): Vec3 => [ref[3 * i] ?? 0, ref[3 * i + 1] ?? 0, ref[3 * i + 2] ?? 0];
  const d = sub(m, col(3));
  return mul([dot(col(0), d), dot(col(1), d), dot(col(2), d)], frame.unitScaleToM);
}

// ------------------------------------------------------------------ peça clicada → membro

/** O que o cálculo precisa do Viewer (ViewerAdapter). */
export interface GeometrySource {
  getModelFrame(): ModelFrame | null;
  getNodes(dbIds: DbId[]): Promise<ModelNode[]>;
  getTriangles(dbId: DbId): Triangle[];
}

const NOT_CONCRETE =
  /vergalh|armadur|rebar|reinforc|estribo|insert|chumbador|conex|connection|fastener|ferragem|alça|içamento|neoprene|elastômero|ifcopening|opening|abertura|ifcreinforcing|ifcmechanicalfastener|ifcdiscreteaccessory|ifcfastener/i;
const ASSEMBLY = /montage|assembl|ifcelementassembly/i;
const CONCRETE = /concreto|concrete|betão|beton/i;

const text = (n: ModelNode): string => `${n.name} ${n.category} ${n.ifcClass}`;
const isGeometryItem = (n: ModelNode): boolean => !n.category && !n.ifcClass;

export interface MainMember {
  /** elemento da peça (montagem ou o próprio elemento clicado) */
  piece: DbId;
  member: ModelNode;
  triangles: Triangle[];
}

async function node(source: GeometrySource, dbId: DbId): Promise<ModelNode | null> {
  return (await source.getNodes([dbId]))[0] ?? null;
}

/** Peça clicada → membro principal de concreto e a geometria dele. */
export async function mainMember(source: GeometrySource, clicked: DbId): Promise<MainMember> {
  let element = await node(source, clicked);
  if (!element) throw new Error('Peça não encontrada no modelo.');
  for (let i = 0; i < 4 && isGeometryItem(element) && element.parent !== null; i++) {
    const up = await node(source, element.parent);
    if (!up || up.parent === null) break; // não sobe até a raiz
    element = up;
  }
  let top = element;
  for (let p = element.parent, i = 0; p !== null && i < 4; i++) {
    const up = await node(source, p);
    if (!up || up.parent === null) break;
    if (ASSEMBLY.test(text(up))) top = up;
    p = up.parent;
  }
  const members = top.dbId !== element.dbId || ASSEMBLY.test(text(top)) ? await source.getNodes(top.children) : [element];

  const candidates: { node: ModelNode; triangles: Triangle[]; volume: number; concrete: boolean; ignored: boolean }[] = [];
  for (const m of members) {
    const parts: ModelNode[] = [];
    let level = [m];
    for (let depth = 0; depth < 6 && level.length; depth++) {
      parts.push(...level.filter((n) => n.hasGeometry));
      const next = level.flatMap((n) => n.children);
      level = next.length ? await source.getNodes(next) : [];
    }
    const used = parts.filter((p) => !NOT_CONCRETE.test(`${text(p)} ${p.material}`));
    const triangles = used.flatMap((p) => source.getTriangles(p.dbId));
    candidates.push({
      node: m,
      triangles,
      volume: triangles.length ? meshVolume(triangles) : 0,
      concrete: CONCRETE.test(`${m.material} ${used.map((p) => `${p.name} ${p.material}`).join(' ')}`),
      ignored: NOT_CONCRETE.test(`${text(m)} ${m.material}`),
    });
  }
  const usable = candidates.filter((c) => !c.ignored && c.triangles.length > 0);
  const concrete = usable.filter((c) => c.concrete);
  const pool = concrete.length ? concrete : usable;
  const best = [...pool].sort((a, b) => b.volume - a.volume)[0];
  if (!best) throw new Error('A peça não tem geometria de concreto.');
  return { piece: top.dbId, member: best.node, triangles: best.triangles };
}

export interface AxisRow {
  label: string;
  /** metros, relativos ao ponto base do projeto */
  xyz: Vec3;
}

export interface AxisCoordinates {
  kind: PieceKind;
  rule: string;
  member: { dbId: DbId; name: string };
  rows: AxisRow[];
  /** pontos de mundo do Viewer para o marcador (1 = ponto; 2 = linha) */
  marker: Vec3[];
  /** o modelo não tem ponto de referência: coordenadas relativas à origem do arquivo */
  noReference: boolean;
}

/** Coordenadas do eixo da peça clicada (a instância, não a marca). */
export async function pieceCoordinates(
  source: GeometrySource,
  clicked: DbId,
  rules: AxisZRule = DEFAULT_AXIS_Z_RULE,
): Promise<AxisCoordinates> {
  const frame = source.getModelFrame();
  if (!frame) throw new Error('O modelo ainda não terminou de carregar.');
  const { member, triangles } = await mainMember(source, clicked);
  const kind = kindFromCategory(`${member.category} ${member.ifcClass} ${member.name}`) ?? kindFromShape(triangles);
  const axis = pieceAxis(triangles, kind, rules);
  return {
    kind,
    rule: axis.rule,
    member: { dbId: member.dbId, name: member.name },
    rows: axis.points.map((p) => ({ label: p.label, xyz: toProjectBase(p.world, frame) })),
    marker: axis.points.map((p) => p.world),
    noReference: !frame.refPointTransformation,
  };
}

// ------------------------------------------------------------------ apresentação

const meters = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 3, maximumFractionDigits: 3, useGrouping: false });

/** 12.3456 → "12,346" (metros, 3 casas, vírgula; nunca "-0,000"). */
export function formatMeters(value: number): string {
  const text = meters.format(value);
  return /^-0,0+$/.test(text) ? text.slice(1) : text;
}

/** Texto do botão copiar: "X; Y; Z". */
export const copyText = (xyz: Vec3): string => xyz.map(formatMeters).join('; ');
