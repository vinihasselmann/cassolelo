// node --test spikes/coordenadas  (Node 18+; sem dependências)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { add, cross, dot, meshVolume, mul, norm, pieceAxis, refFromAec, sub, toProjectBase, unit } from './axis.js';

/** Caixa: base local (a = comprimento, b, c = seção), canto em `origin`, 12 triângulos. */
function box(origin, a, b, c) {
  const p = (i, j, k) => add(add(add(origin, mul(a, i)), mul(b, j)), mul(c, k));
  const v = [p(0, 0, 0), p(1, 0, 0), p(1, 1, 0), p(0, 1, 0), p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1)];
  const q = (i, j, k, l) => [
    [v[i], v[j], v[k]],
    [v[i], v[k], v[l]],
  ];
  return [...q(0, 3, 2, 1), ...q(4, 5, 6, 7), ...q(0, 1, 5, 4), ...q(1, 2, 6, 5), ...q(2, 3, 7, 6), ...q(3, 0, 4, 7)];
}

/** Base ortonormal com o eixo `dir` e a seção (largura w, altura h) "de pé". */
function frame(dir) {
  const a = unit(dir);
  let v = sub([0, 0, 1], mul(a, dot([0, 0, 1], a)));
  if (norm(v) < 1e-9) v = [0, 1, 0];
  v = unit(v);
  const u = unit(cross(v, a));
  return { a, u, v };
}

/** Prisma com eixo de `start` a `end` e seção w x h centrada no eixo. */
function prism(start, end, w, h) {
  const { u, v } = frame(sub(end, start));
  const origin = sub(sub(start, mul(u, w / 2)), mul(v, h / 2));
  return box(origin, sub(end, start), mul(u, w), mul(v, h));
}

const close = (got, want, tol = 1e-6) => {
  for (let i = 0; i < 3; i++) assert.ok(Math.abs(got[i] - want[i]) < tol, `${String(got)} != ${String(want)}`);
};

test('pilar inclinado e girado em planta: base = centro da seção no pé do eixo', () => {
  const base = [12.3, -4.5, 1.2];
  const dir = [Math.sin(0.17) * Math.cos(0.6), Math.sin(0.17) * Math.sin(0.6), Math.cos(0.17)];
  const top = add(base, mul(dir, 6));
  const r = pieceAxis(prism(base, top, 0.4, 0.5), 'pilar');
  close(r.point, base);
  close(r.top, top);
});

test('pilar com consolo: o consolo não desloca o centro da seção', () => {
  const base = [3, 7, 0];
  const top = [3, 7, 6];
  const corbel = box([3.2, 6.8, 4.0], [0.4, 0, 0], [0, 0.4, 0], [0, 0, 0.3]); // saliente em +X
  const r = pieceAxis([...prism(base, top, 0.4, 0.4), ...corbel], 'pilar');
  close(r.point, base);
});

test('viga girada 37° em planta e com 3° de inclinação: início e fim na meia altura', () => {
  const s = [100, 50, 3.2];
  const ang = (37 * Math.PI) / 180;
  const inc = (3 * Math.PI) / 180;
  const e = add(s, mul([Math.cos(inc) * Math.cos(ang), Math.cos(inc) * Math.sin(ang), Math.sin(inc)], 8));
  const r = pieceAxis(prism(s, e, 0.3, 0.6), 'viga');
  const ends = [r.start, r.end].sort((x, y) => x[0] - y[0]);
  close(ends[0], s);
  close(ends[1], e);
});

test('viga com dentes nas pontas: o corte no meio do vão dá a meia altura da seção cheia', () => {
  const s = [0, 0, 0];
  const e = [8, 0, 0];
  const beam = prism(s, e, 0.3, 0.6);
  const dente = box([-0.3, -0.15, -0.3], [0.3, 0, 0], [0, 0.3, 0], [0, 0, 0.3]); // abaixo, na ponta
  const r = pieceAxis([...beam, ...dente], 'viga');
  close(r.start[1] === 0 ? [r.start[0], 0, r.start[2]] : r.start, r.start);
  assert.ok(Math.abs(r.start[2]) < 1e-6 && Math.abs(r.end[2]) < 1e-6, 'meia altura = 0');
});

test('viga com neoprene saindo da ponta (mesma malha): o eixo termina no concreto', () => {
  const s = [10, 5, 4.8];
  const e = [18, 5, 4.8];
  const beam = prism(s, e, 0.4, 0.8);
  const pad = box([17.9, 4.85, 4.39], [0.125, 0, 0], [0, 0.3, 0], [0, 0, 0.01]); // 25 mm além da ponta
  const r = pieceAxis([...beam, ...pad], 'viga');
  const ends = [r.start, r.end].sort((x, y) => x[0] - y[0]);
  close(ends[0], s, 1e-4);
  close(ends[1], e, 1e-4);
});

test('laje girada: centro em planta e face inferior', () => {
  const ang = 0.9;
  const a = mul([Math.cos(ang), Math.sin(ang), 0], 5);
  const b = mul([-Math.sin(ang), Math.cos(ang), 0], 2.5);
  const origin = [20, 30, 4];
  const slab = box(origin, a, b, [0, 0, 0.2]);
  const r = pieceAxis(slab, 'laje');
  close(r.point, add(origin, add(mul(a, 0.5), mul(b, 0.5))));
});

test('tipo pela forma quando a categoria não diz', () => {
  assert.equal(pieceAxis(prism([0, 0, 0], [0, 0, 5], 0.4, 0.4)).kind, 'pilar');
  assert.equal(pieceAxis(prism([0, 0, 0], [6, 1, 0], 0.3, 0.6)).kind, 'viga');
  assert.equal(pieceAxis(box([0, 0, 0], [5, 0, 0], [0, 3, 0], [0, 0, 0.2])).kind, 'laje');
});

test('volume da malha (membro de concreto x armadura)', () => {
  assert.ok(Math.abs(meshVolume(prism([0, 0, 0], [0, 0, 6], 0.4, 0.5)) - 1.2) < 1e-9);
});

test('conversão: globalOffset, ponto base do projeto (giro + translação) e pés → mm', () => {
  const ang = 0.3;
  const c = Math.cos(ang);
  const s = Math.sin(ang);
  // ponto base em (10, 20, 1) pés, girado 0,3 rad: colunas X, Y, Z e origem
  const ref = refFromAec([c, s, 0, -s, c, 0, 0, 0, 1, 10, 20, 1]);
  assert.ok(ref);
  const local = [2, 3, 4]; // pés, no sistema do ponto base
  const model = add([10, 20, 1], [c * 2 - s * 3, s * 2 + c * 3, 4]);
  const offset = [5, 6, 7];
  const world = sub(model, offset);
  close(toProjectBase(world, offset, ref, 304.8), mul(local, 304.8), 1e-6);
  close(toProjectBase(world, offset, null, 304.8), mul(model, 304.8), 1e-6);
});
