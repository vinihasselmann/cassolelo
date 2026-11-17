// Roda a página do spike no Chromium (Playwright do frontend) e grava o resultado.
//
//   node spikes/coordenadas/run.mjs --name orc-rvt --urn <URN> [--dbids 87,120 | --find 6657283,...] [--applyRefPoint]
//
// Sem --dbids, mede até 2 peças de cada tipo (pilar, viga, laje) achadas pela categoria.
// Precisa do servidor do spike no ar (spikes/coordenadas/server.py, porta 8010).
// Saída: spikes/out/coordenadas-<name>.json

import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, '../../frontend/package.json'));
const { chromium } = require('@playwright/test');

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => {
    if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : '1']);
    return acc;
  }, []),
);
if (!args.urn || !args.name) {
  console.error('uso: node run.mjs --name <nome> --urn <URN> [--dbids 1,2] [--applyRefPoint]');
  process.exit(2);
}

const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on('console', (m) => { if (m.type() === 'error') console.error('[página]', m.text()); });
const url = `http://127.0.0.1:8010/?urn=${encodeURIComponent(args.urn)}${args.applyRefPoint ? '&applyRefPoint=1' : ''}${args.ignore ? `&ignore=${encodeURIComponent(args.ignore)}` : ''}`;
const started = Date.now();
await page.goto(url);
await page.waitForFunction(() => window.__COORD !== undefined);
await page.evaluate(() => window.__COORD.ready);
const info = await page.evaluate(() => window.__COORD.info());
let ids = args.dbids ? args.dbids.split(',').map(Number) : null;
if (!ids && args.find) {
  ids = [];
  for (const text of args.find.split(',')) {
    const found = await page.evaluate((t) => window.__COORD.find(t), text);
    console.log(`--find ${text}: ${found.join(', ') || 'nada'}`);
    if (found.length) ids.push(...(args.all ? found : found.slice(0, 1)));
  }
}
let samples = null;
if (!ids) {
  samples = await page.evaluate(() => window.__COORD.samples());
  ids = [...samples.pilar, ...samples.viga, ...samples.laje];
}
const pieces = [];
for (const id of ids) {
  try {
    pieces.push(await page.evaluate((d) => window.__COORD.measure(d), id));
  } catch (e) {
    pieces.push({ clicked: id, error: String(e) });
  }
}
await browser.close();

const out = resolve(here, '../out', `coordenadas-${args.name}.json`);
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify({ name: args.name, applyRefPoint: Boolean(args.applyRefPoint), seconds: (Date.now() - started) / 1000, info, samples, pieces }, null, 1));
console.log(`gravado ${out}`);
for (const p of pieces) {
  if (p.error) {
    console.log(p.clicked, 'ERRO', p.error);
    continue;
  }
  for (const [n, v] of Object.entries(p.points)) {
    const show = (x) => (x ? x.map((c) => c.toFixed(1)).join(', ') : '—');
    console.log(`${p.clicked} ${p.kind} ${p.member.name} ${n}: arquivo=[${show(v.arquivo_mm)}] A=[${show(v.pbp_A_mm)}] B=[${show(v.pbp_B_mm)}]`);
  }
}
