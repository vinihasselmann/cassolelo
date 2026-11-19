/**
 * Confere o build de produção (dist/): o usuário simulado não pode estar no pacote (11.2).
 * Roda no fim do `npm run build`; falha (exit 1) se achar algum dos textos abaixo.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const FORBIDDEN = ['X-Dev-User', '/dev/users', 'usuário simulado', 'Usuário (simulado)'];
const dist = resolve(process.argv[2] ?? 'dist');

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const found = [];
for (const file of files(dist).filter((f) => /\.(js|html|css|map)$/.test(f) && !f.endsWith('.map'))) {
  const text = readFileSync(file, 'utf-8');
  for (const needle of FORBIDDEN) if (text.includes(needle)) found.push(`${file}: "${needle}"`);
}

if (found.length > 0) {
  console.error('Build de produção contém o usuário simulado:\n  ' + found.join('\n  '));
  process.exit(1);
}
console.log(`ok: usuário simulado fora do build (${dist})`);
