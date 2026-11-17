// Spike "coordenadas": eixo de uma peça a partir dos triângulos da malha (sem Viewer).
// Módulo puro (ES module): usado pela página do spike e pelos testes (node --test).
//
// Método:
// 1. PCA da SUPERFÍCIE (centroides dos triângulos ponderados pela área): e1 = direção
//    principal (comprimento), e2/e3 = seção. Funciona para peças inclinadas e giradas em
//    planta (não supõe eixos X/Y/Z).
// 2. Extensões ao longo de e1/e2/e3 pelos vértices (caixa orientada, OBB).
// 3. A seção é medida por um CORTE da malha por um plano perpendicular ao eixo (não pela
//    caixa toda): consolos, dentes e chanfros fora do corte não deslocam o centro.
//    Pilar: corte perto da base; viga: corte no meio do vão.
// 4. Laje: normal = e3 (menor variância); centro em planta = centro da OBB em e1/e2;
//    face inferior = menor projeção na normal.

/** @typedef {[number, number, number]} Vec */

export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
export const norm = (a) => Math.hypot(a[0], a[1], a[2]);
export const unit = (a) => mul(a, 1 / (norm(a) || 1));

/** Autovalores/autovetores de uma matriz 3x3 simétrica (Jacobi). Ordem decrescente. */
export function eigenSym3(m) {
  const a = m.map((r) => r.slice());
  const v = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ];
  for (let sweep = 0; sweep < 50; sweep++) {
    const off = Math.abs(a[0][1]) + Math.abs(a[0][2]) + Math.abs(a[1][2]);
    if (off < 1e-18) break;
    for (const [p, q] of [
      [0, 1],
      [0, 2],
      [1, 2],
    ]) {
      if (Math.abs(a[p][q]) < 1e-30) continue;
      const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
      const c = 1 / Math.sqrt(t * t + 1);
      const s = t * c;
      for (let k = 0; k < 3; k++) {
        const akp = a[k][p];
        const akq = a[k][q];
        a[k][p] = c * akp - s * akq;
        a[k][q] = s * akp + c * akq;
      }
      for (let k = 0; k < 3; k++) {
        const apk = a[p][k];
        const aqk = a[q][k];
        a[p][k] = c * apk - s * aqk;
        a[q][k] = s * apk + c * aqk;
      }
      for (let k = 0; k < 3; k++) {
        const vkp = v[k][p];
        const vkq = v[k][q];
        v[k][p] = c * vkp - s * vkq;
        v[k][q] = s * vkp + c * vkq;
      }
    }
  }
  const pairs = [0, 1, 2].map((i) => ({ value: a[i][i], vector: [v[0][i], v[1][i], v[2][i]] }));
  pairs.sort((x, y) => y.value - x.value);
  return pairs;
}

/**
 * PCA da superfície: { center, axes: [e1, e2, e3] } (e1 = maior variância).
 * Momentos EXATOS de cada triângulo (área A, vértices a, b, c, s = a + b + c):
 *   ∫x dA = A·s/3      ∫x·xᵀ dA = A/12 · (a·aᵀ + b·bᵀ + c·cᵀ + s·sᵀ)
 * (usar só o centroide enviesaria a direção: a diagonal que divide cada face não é
 * simétrica).
 */
export function surfacePca(triangles) {
  let total = 0;
  let first = [0, 0, 0];
  const second = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (const [a, b, c] of triangles) {
    const area = norm(cross(sub(b, a), sub(c, a))) / 2;
    if (!(area > 0)) continue;
    const s = add(add(a, b), c);
    total += area;
    first = add(first, mul(s, area / 3));
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        second[i][j] += (area / 12) * (a[i] * a[j] + b[i] * b[j] + c[i] * c[j] + s[i] * s[j]);
      }
    }
  }
  if (total <= 0) throw new Error('malha sem área');
  const center = mul(first, 1 / total);
  const cov = second.map((row, i) => row.map((x, j) => x / total - center[i] * center[j]));
  const eig = eigenSym3(cov);
  const e1 = unit(eig[0].vector);
  let e2 = unit(sub(eig[1].vector, mul(e1, dot(eig[1].vector, e1))));
  const e3 = unit(cross(e1, e2));
  e2 = unit(cross(e3, e1));
  return { center, axes: [e1, e2, e3], variances: eig.map((e) => e.value) };
}

/** Faixa [min, max] das projeções dos vértices numa direção. */
export function range(triangles, dir) {
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

/** Pontos onde o plano {x : dot(x, n) = t} corta as arestas dos triângulos. */
export function slice(triangles, n, t) {
  const out = [];
  for (const tri of triangles) {
    const d = tri.map((p) => dot(p, n) - t);
    for (const [i, j] of [
      [0, 1],
      [1, 2],
      [2, 0],
    ]) {
      if ((d[i] < 0 && d[j] > 0) || (d[i] > 0 && d[j] < 0)) {
        const k = d[i] / (d[i] - d[j]);
        out.push(add(tri[i], mul(sub(tri[j], tri[i]), k)));
      } else if (d[i] === 0) {
        out.push(tri[i]);
      }
    }
  }
  return out;
}

/** Centro (meio da faixa) dos pontos nas direções u e v. */
function center2(points, u, v) {
  const [ulo, uhi] = rangePts(points, u);
  const [vlo, vhi] = rangePts(points, v);
  return { u: (ulo + uhi) / 2, v: (vlo + vhi) / 2, du: uhi - ulo, dv: vhi - vlo };
}
function rangePts(points, dir) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of points) {
    const t = dot(p, dir);
    if (t < lo) lo = t;
    if (t > hi) hi = t;
  }
  return [lo, hi];
}

/** Volume (com sinal) da malha fechada: escolhe o membro de concreto da montagem. */
export function meshVolume(triangles) {
  let v = 0;
  for (const [a, b, c] of triangles) v += dot(a, cross(b, c)) / 6;
  return Math.abs(v);
}

const UP = [0, 0, 1];

/** Tipo pela forma, quando a categoria não diz: laje (fina), pilar (eixo vertical) ou viga. */
export function guessKind(pca, extents) {
  const [l1, l2, l3] = extents;
  if (l3 < 0.35 * l2 && l2 > 0.25 * l1) return 'laje';
  return Math.abs(dot(pca.axes[0], UP)) > 0.7 ? 'pilar' : 'viga';
}

/** Tipo pela categoria (Revit pt/en, IFC). null = decidir pela forma. */
export function kindFromCategory(text) {
  const s = (text || '').toLowerCase();
  if (/pilar|column|ifccolumn/.test(s)) return 'pilar';
  if (/viga|quadro estrutural|framing|beam|ifcbeam/.test(s)) return 'viga';
  if (/laje|piso|floor|slab|ifcslab|ifcplate/.test(s)) return 'laje';
  return null;
}

/**
 * Eixo da peça. `triangles` em coordenadas de mundo do Viewer (ou quaisquer, desde que
 * consistentes); `kind` = 'pilar' | 'viga' | 'laje' | null (decide pela forma).
 * Devolve os pontos pedidos no mesmo sistema dos triângulos.
 */
export function pieceAxis(triangles, kind = null) {
  const pca = surfacePca(triangles);
  let [e1, e2, e3] = pca.axes;
  const r = [e1, e2, e3].map((d) => range(triangles, d));
  const ext = r.map(([lo, hi]) => hi - lo);
  const k = kind || guessKind(pca, ext);

  if (k === 'laje') {
    // normal = direção de menor extensão; para cima
    let n = e3;
    if (dot(n, UP) < 0) n = mul(n, -1);
    const [nlo] = range(triangles, n);
    const [alo, ahi] = range(triangles, e1);
    const [blo, bhi] = range(triangles, e2);
    const p = add(add(mul(e1, (alo + ahi) / 2), mul(e2, (blo + bhi) / 2)), mul(n, nlo));
    return { kind: k, point: p, axes: [e1, e2, n], extents: ext };
  }

  // pilar e viga: eixo longitudinal refinado pelos centros das seções do corpo prismático
  if (k === 'pilar' && dot(e1, UP) < 0) e1 = mul(e1, -1);
  const line = axisLine(triangles, e1, e2);
  const [tlo, thi] = trimmedRange(triangles, line, e2);
  const at = (t) => add(line.point, mul(line.dir, t - dot(line.point, line.dir)));
  if (k === 'pilar') {
    return { kind: k, point: at(tlo), top: at(thi), section: line.section, cuts: line.cuts, axes: [line.dir], extents: ext };
  }
  return { kind: k, start: at(tlo), end: at(thi), section: line.section, cuts: line.cuts, axes: [line.dir], extents: ext };
}

/**
 * Base (u, v) da seção, com v o mais "para cima" possível (meia altura = centro em v).
 * Peça vertical (pilar): v = `hint` (2º eixo da PCA), para as medidas da seção saírem
 * nas faces da peça.
 */
function sectionBasis(dir, hint) {
  let v = sub(UP, mul(dir, dot(UP, dir)));
  if (norm(v) < 0.2) v = sub(hint, mul(dir, dot(hint, dir)));
  if (norm(v) < 1e-6) v = Math.abs(dir[0]) < 0.9 ? cross(dir, [1, 0, 0]) : cross(dir, [0, 1, 0]);
  v = unit(v);
  return { u: unit(cross(v, dir)), v };
}

/**
 * Faixa do eixo onde a peça tem CORPO: anda de cada extremo para dentro (até 15% do
 * comprimento) e descarta o trecho cuja seção é menor que `frac` da seção do corpo.
 * Tira o que sobra fora do concreto na mesma malha (ex.: neoprene da família, no RVT,
 * que o SVF2 junta ao concreto); dentes e consolos (seção grande) ficam.
 */
export function trimmedRange(triangles, line, hint = [1, 0, 0], frac = 0.2) {
  const { u, v } = sectionBasis(line.dir, hint);
  const [tlo, thi] = range(triangles, line.dir);
  const len = thi - tlo;
  const body = line.section[0] * line.section[1];
  const solid = (t) => {
    const pts = slice(triangles, line.dir, t);
    if (pts.length < 3) return false;
    const c = center2(pts, u, v);
    return c.du * c.dv >= frac * body;
  };
  const edge = (from, sign) => {
    const step = len / 3000;
    let prev = from;
    for (let t = from + sign * step * 0.5; sign * (t - from) <= 0.15 * len; t += sign * step) {
      if (solid(t)) {
        // bissecção entre o último vazio e o primeiro cheio
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

/**
 * Reta do eixo: corta a peça em 9 planos (5% a 95% do comprimento), fica com os cortes de
 * MENOR seção (o corpo prismático: consolos, dentes e chanfros aumentam a seção) e passa
 * a reta pelos centros deles (PCA dos centros). Duas iterações a partir da PCA da malha.
 */
export function axisLine(triangles, first, hint = [1, 0, 0]) {
  let dir = unit(first);
  let point = null;
  let section = null;
  let cuts = 0;
  for (let iter = 0; iter < 3; iter++) {
    const { u, v } = sectionBasis(dir, hint);
    const [tlo, thi] = range(triangles, dir);
    const len = thi - tlo;
    const found = [];
    for (let i = 0; i <= 8; i++) {
      const t = tlo + len * (0.05 + (0.9 * i) / 8);
      const pts = slice(triangles, dir, t);
      if (pts.length < 3) continue;
      const c = center2(pts, u, v);
      found.push({ t, c, area: c.du * c.dv });
    }
    if (found.length === 0) throw new Error('nenhum corte com pontos');
    const minArea = Math.min(...found.map((f) => f.area));
    const kept = found.filter((f) => f.area <= minArea * 1.02 + 1e-12);
    const centers = kept.map((f) => add(add(mul(dir, f.t), mul(u, f.c.u)), mul(v, f.c.v)));
    point = mul(centers.reduce((acc, p) => add(acc, p), [0, 0, 0]), 1 / centers.length);
    section = [kept[0].c.du, kept[0].c.dv];
    cuts = kept.length;
    if (centers.length < 2) break;
    // direção principal dos centros (reta de mínimos quadrados)
    const cov = [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ];
    for (const p of centers) {
      const d = sub(p, point);
      for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) cov[i][j] += d[i] * d[j];
    }
    let next = unit(eigenSym3(cov)[0].vector);
    if (dot(next, dir) < 0) next = mul(next, -1);
    const change = norm(sub(next, dir));
    dir = next;
    if (change < 1e-12) break;
  }
  return { point, dir, section, cuts };
}

/**
 * Conversão Viewer → ponto base do projeto.
 *  modelo = mundo do Viewer + globalOffset          (unidades do modelo)
 *  pbp    = Rᵀ · (modelo − t)                         (R, t = refPointTransformation)
 *  saída  = pbp · escala (unidade do modelo → mm)
 * `ref` = { rotation: 3x3 (linhas), translation: Vec } ou null (identidade).
 * `inverse` = hipótese B (pbp = R·modelo + t). Qual vale é conferido contra o Revit.
 */
export function toProjectBase(world, globalOffset, ref, toMm, inverse = false) {
  const m = add(world, globalOffset || [0, 0, 0]);
  if (!ref) return mul(m, toMm);
  if (inverse) {
    // hipótese B: a matriz leva do sistema do arquivo ao do ponto base (pbp = R·m + t)
    const R = ref.rotation;
    const p = [0, 1, 2].map((i) => R[i][0] * m[0] + R[i][1] * m[1] + R[i][2] * m[2]);
    return mul(add(p, ref.translation), toMm);
  }
  const d = sub(m, ref.translation);
  const R = ref.rotation;
  const local = [
    R[0][0] * d[0] + R[1][0] * d[1] + R[2][0] * d[2],
    R[0][1] * d[0] + R[1][1] * d[1] + R[2][1] * d[2],
    R[0][2] * d[0] + R[1][2] * d[1] + R[2][2] * d[2],
  ];
  return mul(local, toMm);
}

/**
 * refPointTransformation do AEC model data (12 números, colunas: X, Y, Z, origem) →
 * { rotation (linhas), translation }.
 */
export function refFromAec(arr) {
  if (!Array.isArray(arr) || arr.length < 12) return null;
  const col = (i) => [arr[3 * i], arr[3 * i + 1], arr[3 * i + 2]];
  const [x, y, z, o] = [col(0), col(1), col(2), col(3)];
  return {
    rotation: [
      [x[0], y[0], z[0]],
      [x[1], y[1], z[1]],
      [x[2], y[2], z[2]],
    ],
    translation: o,
  };
}
