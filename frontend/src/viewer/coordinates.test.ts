import { describe, expect, it } from 'vitest';

import pilarReal from './__fixtures__/orc-pilar-6657283.json';
import vigaReal from './__fixtures__/orc-viga-6657266.json';
import {
  add,
  copyText,
  cross,
  dot,
  formatMeters,
  mainMember,
  meshVolume,
  mul,
  norm,
  pieceAxis,
  pieceCoordinates,
  sub,
  toProjectBase,
  unit,
  type GeometrySource,
} from './coordinates';
import type { ModelFrame, ModelNode, Triangle, Vec3 } from './ViewerAdapter';

/** Caixa (12 triângulos): canto `origin`, arestas a (comprimento), b e c (seção). */
function box(origin: Vec3, a: Vec3, b: Vec3, c: Vec3): Triangle[] {
  const p = (i: number, j: number, k: number): Vec3 => add(add(add(origin, mul(a, i)), mul(b, j)), mul(c, k));
  const [v0, v1, v2, v3, v4, v5, v6, v7] = [p(0, 0, 0), p(1, 0, 0), p(1, 1, 0), p(0, 1, 0), p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1)];
  const q = (i: Vec3, j: Vec3, k: Vec3, l: Vec3): Triangle[] => [
    [i, j, k],
    [i, k, l],
  ];
  return [...q(v0, v3, v2, v1), ...q(v4, v5, v6, v7), ...q(v0, v1, v5, v4), ...q(v1, v2, v6, v5), ...q(v2, v3, v7, v6), ...q(v3, v0, v4, v7)];
}

/** Prisma com eixo de `start` a `end` e seção w × h centrada no eixo, "de pé". */
function prism(start: Vec3, end: Vec3, w: number, h: number): Triangle[] {
  const a = unit(sub(end, start));
  let v = sub([0, 0, 1], mul(a, dot([0, 0, 1], a)));
  if (norm(v) < 1e-9) v = [0, 1, 0];
  v = unit(v);
  const u = unit(cross(v, a));
  return box(sub(sub(start, mul(u, w / 2)), mul(v, h / 2)), sub(end, start), mul(u, w), mul(v, h));
}

/** ponto ausente: falha na comparação */
const NO: Vec3 = [NaN, NaN, NaN];

const near = (got: Vec3, want: Vec3, tol: number) => {
  const diff = Math.max(...sub(got, want).map(Math.abs));
  expect(diff, `${got.join(', ')} ≠ ${want.join(', ')}`).toBeLessThan(tol);
};

describe('eixo da peça (peças sintéticas)', () => {
  it('pilar inclinado e girado em planta: base no centro da seção', () => {
    const base: Vec3 = [12.3, -4.5, 1.2];
    const dir: Vec3 = [Math.sin(0.17) * Math.cos(0.6), Math.sin(0.17) * Math.sin(0.6), Math.cos(0.17)];
    const top = add(base, mul(dir, 6));
    near(pieceAxis(prism(base, top, 0.4, 0.5), 'pilar').points.at(0)?.world ?? NO, base, 1e-6);
    near(pieceAxis(prism(base, top, 0.4, 0.5), 'pilar', { pilar: 'topo', viga: 'meia altura', laje: 'face inferior' }).points.at(0)?.world ?? NO, top, 1e-6);
  });

  it('pilar com consolo: o consolo não desloca o centro da seção', () => {
    const corbel = box([3.2, 6.8, 4.0], [0.4, 0, 0], [0, 0.4, 0], [0, 0, 0.3]);
    const r = pieceAxis([...prism([3, 7, 0], [3, 7, 6], 0.4, 0.4), ...corbel], 'pilar');
    near(r.points.at(0)?.world ?? NO, [3, 7, 0], 1e-6);
  });

  it('viga girada 37° em planta e inclinada 3°: início e fim na meia altura (ou nas faces)', () => {
    const s: Vec3 = [100, 50, 3.2];
    const ang = (37 * Math.PI) / 180;
    const inc = (3 * Math.PI) / 180;
    const e = add(s, mul([Math.cos(inc) * Math.cos(ang), Math.cos(inc) * Math.sin(ang), Math.sin(inc)], 8));
    const r = pieceAxis(prism(s, e, 0.3, 0.6), 'viga');
    expect(r.points.map((p) => p.label)).toEqual(['Início', 'Fim']);
    near(r.points.at(0)?.world ?? NO, s, 1e-6);
    near(r.points.at(1)?.world ?? NO, e, 1e-6);
    const bottom = pieceAxis(prism(s, e, 0.3, 0.6), 'viga', { pilar: 'base', viga: 'face inferior', laje: 'face inferior' });
    const zMid = (r.points.at(0)?.world ?? NO)[2];
    const zBottom = (bottom.points.at(0)?.world ?? NO)[2];
    expect(zMid - zBottom).toBeCloseTo(0.3 * Math.cos(inc), 6);
  });

  it('viga com neoprene saindo 25 mm da ponta (mesma malha): o eixo termina no concreto', () => {
    const pad = box([17.9, 4.85, 4.39], [0.125, 0, 0], [0, 0.3, 0], [0, 0, 0.01]);
    const r = pieceAxis([...prism([10, 5, 4.8], [18, 5, 4.8], 0.4, 0.8), ...pad], 'viga');
    near(r.points.at(1)?.world ?? NO, [18, 5, 4.8], 1e-4);
  });

  it('laje girada: centro em planta na face inferior (ou superior)', () => {
    const a = mul([Math.cos(0.9), Math.sin(0.9), 0], 5);
    const b = mul([-Math.sin(0.9), Math.cos(0.9), 0], 2.5);
    const slab = box([20, 30, 4], a, b, [0, 0, 0.2]);
    const center = add([20, 30, 4], add(mul(a, 0.5), mul(b, 0.5)));
    near(pieceAxis(slab, 'laje').points.at(0)?.world ?? NO, center, 1e-6);
    near(pieceAxis(slab, 'laje', { pilar: 'base', viga: 'meia altura', laje: 'face superior' }).points.at(0)?.world ?? NO, add(center, [0, 0, 0.2]), 1e-6);
  });

  it('volume da malha', () => {
    expect(meshVolume(prism([0, 0, 0], [0, 0, 6], 0.4, 0.5))).toBeCloseTo(1.2, 9);
  });
});

describe('conversão para o ponto base do projeto', () => {
  it('globalOffset, refPointTransformation (giro + translação) e unidade → metros', () => {
    const c = Math.cos(0.3);
    const s = Math.sin(0.3);
    const frame: ModelFrame = { globalOffset: [5, 6, 7], unitScaleToM: 0.3048, refPointTransformation: [c, s, 0, -s, c, 0, 0, 0, 1, 10, 20, 1] };
    const local: Vec3 = [2, 3, 4]; // pés, no sistema do ponto base
    const model = add([10, 20, 1], [c * 2 - s * 3, s * 2 + c * 3, 4]);
    near(toProjectBase(sub(model, frame.globalOffset), frame), mul(local, 0.3048), 1e-9);
    near(toProjectBase([1, 2, 3], { ...frame, refPointTransformation: null }), mul([6, 8, 10], 0.3048), 1e-9);
  });

  it('formato: metros, 3 casas, vírgula decimal; copiar "X; Y; Z"', () => {
    expect(formatMeters(-73.17544)).toBe('-73,175');
    expect(formatMeters(141594.4 / 1000)).toBe('141,594');
    expect(formatMeters(-0.0002)).toBe('0,000');
    expect(formatMeters(12345.6789)).toBe('12345,679'); // sem separador de milhar
    expect(copyText([-73.1754, 141.5944, -1.4])).toBe('-73,175; 141,594; -1,400');
  });
});

/** Fonte de geometria a partir de uma fixture real gravada pelo spike (um nó, uma malha). */
function fixtureSource(fx: { dbId: number; label: string; category: string; globalOffset: number[]; unitScaleToM: number; refPointTransformation: number[]; triangles: number[][][] }): GeometrySource {
  const node: ModelNode = { dbId: fx.dbId, parent: 1, children: [], name: fx.label, category: fx.category, ifcClass: '', material: 'Concreto, Pré-moldado - 50MPa', hasGeometry: true };
  return {
    getModelFrame: () => ({ globalOffset: fx.globalOffset as Vec3, unitScaleToM: fx.unitScaleToM, refPointTransformation: fx.refPointTransformation }),
    getNodes: (ids) => Promise.resolve(ids.map((id) => (id === fx.dbId ? node : { ...node, dbId: id, parent: null, children: [fx.dbId], category: '', hasGeometry: false }))),
    getTriangles: (id) => (id === fx.dbId ? (fx.triangles as Triangle[]) : []),
  };
}

describe('modelo real (ORC.rvt v2, malha do Viewer gravada pelo spike)', () => {
  // Valores do spike, iguais aos do IFC do mesmo projeto a 0,01 mm (docs/coordenadas.md §3).
  it('pilar 6657283: eixo na base = (-73,175; 141,594; -1,400) m, até 1 mm', async () => {
    const r = await pieceCoordinates(fixtureSource(pilarReal), pilarReal.dbId);
    expect(r.kind).toBe('pilar');
    expect(r.rows.map((x) => x.label)).toEqual(['Eixo']);
    near((r.rows.at(0)?.xyz ?? NO), [-73.1754, 141.5944, -1.4], 0.001);
  });

  it('viga 6657266: início e fim na meia altura, até 1 mm', async () => {
    const r = await pieceCoordinates(fixtureSource(vigaReal), vigaReal.dbId);
    expect(r.kind).toBe('viga');
    near((r.rows.at(0)?.xyz ?? NO), [-66.7268, 151.9587, 4.8], 0.001);
    near((r.rows.at(1)?.xyz ?? NO), [-58.7641, 147.3614, 4.8], 0.001);
    expect(r.marker).toHaveLength(2);
  });

  // Meta de docs/coordenadas.md §4: comparar com as medidas do Revit (cota de coordenada
  // relativa ao ponto base do projeto). As medidas ainda não foram informadas; quando
  // chegarem, entram aqui com a mesma tolerância de 1 mm.
  it.todo('pilar 6657283 e viga 6657266: iguais às medidas do Revit (ponto base), até 1 mm');
  it.todo('laje pré-moldada: centro da face inferior igual ao Revit, até 1 mm');
});

describe('membro principal de concreto', () => {
  const n = (dbId: number, parent: number | null, extra: Partial<ModelNode>): ModelNode => ({
    dbId, parent, children: [], name: `n${String(dbId)}`, category: '', ifcClass: '', material: '', hasGeometry: false, ...extra,
  });

  function source(nodes: ModelNode[], geometry: Record<number, Triangle[]>): GeometrySource {
    const byId = new Map(nodes.map((x) => [x.dbId, x]));
    return {
      getModelFrame: () => ({ globalOffset: [0, 0, 0], unitScaleToM: 1, refPointTransformation: null }),
      getNodes: (ids) => Promise.resolve(ids.map((id) => byId.get(id)).filter((x): x is ModelNode => x !== undefined)),
      getTriangles: (id) => geometry[id] ?? [],
    };
  }

  it('montagem: clicar na alça acha o pilar de concreto (o consolo e o aço ficam de fora)', async () => {
    const nodes = [
      n(1, null, { children: [100] }),
      n(100, 1, { name: 'Montagem Pilares estruturais:PP312', ifcClass: 'IfcElementAssembly', children: [101, 102, 103, 104] }),
      n(101, 100, { name: 'IfcColumn::CASSOL-ACS-Alça', ifcClass: 'IfcColumn', material: 'CP190RB', hasGeometry: true }),
      n(102, 100, { name: 'IfcColumn::Emenda-Superior', ifcClass: 'IfcColumn', material: '<Unnamed>', hasGeometry: true }),
      n(103, 100, { name: 'IfcColumn::CASSOL-PREO-Consolo', ifcClass: 'IfcColumn', material: 'Concreto, Pré-moldado - 50MPa', hasGeometry: true }),
      n(104, 100, { name: 'IfcColumn::CASSOL-PREO-Pilar-R', ifcClass: 'IfcColumn', children: [105, 106] }),
      n(105, 104, { name: 'IfcExtrudedAreaSolid::Concreto, Pré-moldado - 50MPa', hasGeometry: true }),
      n(106, 104, { name: 'IfcExtrudedAreaSolid::Concreto, Pré-moldado - 50MPa_Engastamento', hasGeometry: true }),
    ];
    const geometry = {
      101: prism([0, 0, 0], [0, 0, 8], 0.02, 0.02),
      102: prism([0, 0, 6], [0, 0, 6.3], 2, 2), // aço grande: não é concreto
      103: box([0.2, -0.2, 4], [0.3, 0, 0], [0, 0.4, 0], [0, 0, 0.3]),
      105: prism([0, 0, 0], [0, 0, 6], 0.4, 0.4),
      106: prism([0, 0, -1.4], [0, 0, 0], 0.4, 0.4),
    };
    const m = await mainMember(source(nodes, geometry), 101);
    expect(m.piece).toBe(100);
    expect(m.member.dbId).toBe(104);
    const r = await pieceCoordinates(source(nodes, geometry), 105);
    expect(r.member.dbId).toBe(104);
    near((r.rows.at(0)?.xyz ?? NO), [0, 0, -1.4], 1e-6); // o engastamento entra
  });

  it('IFC: viga sem neoprene nem aberturas; categoria repetida do NWD não exclui', async () => {
    const nodes = [
      n(1, null, { children: [10] }),
      n(10, 1, { name: 'CASSOL-PREO-Viga-R', category: 'Quadro estrutural', children: [11, 12, 13] }),
      n(11, 10, { name: 'Concreto, Pré-moldado - 40MPa', hasGeometry: true }),
      n(12, 10, { name: 'Neoprene', hasGeometry: true }),
      n(13, 10, { name: 'IfcOpeningElement::CASSOL-PREO-Viga-R', ifcClass: 'IfcOpeningElement', hasGeometry: true }),
    ];
    const geometry = {
      11: prism([0, 0, 4.8], [8, 0, 4.8], 0.4, 0.8),
      12: box([7.9, -0.15, 4.39], [0.125, 0, 0], [0, 0.3, 0], [0, 0, 0.01]),
      13: box([9, 0, 4.8], [1, 0, 0], [0, 1, 0], [0, 0, 1]),
    };
    const r = await pieceCoordinates(source(nodes, geometry), 11);
    expect(r.kind).toBe('viga');
    near((r.rows.at(1)?.xyz ?? NO), [8, 0, 4.8], 1e-9);
    expect(r.noReference).toBe(true);
  });
});
