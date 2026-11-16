// Gera o trecho do nginx com os cabeçalhos de segurança da página (10.3), a partir da
// fonte única `security-headers.ts`. Usado no build da imagem (frontend/Dockerfile).
//   node scripts/nginx-headers.mjs > security-headers.conf
// Node 22.18+/24 executa o .ts direto (remoção de tipos).
import { PRODUCTION_HEADERS, nginxHeaders } from '../security-headers.ts';

process.stdout.write(nginxHeaders(PRODUCTION_HEADERS));
