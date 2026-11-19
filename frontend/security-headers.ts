/**
 * Cabeçalhos de segurança da PÁGINA do app (10.2). Fonte única: o Vite aplica em
 * dev/preview e a TI copia para o proxy que servir o `dist/` (docs/operacao.md).
 * A API tem os próprios cabeçalhos (backend/app/security/headers.py).
 *
 * Compatível com o Viewer v7 da Autodesk (SVF2):
 * - script/style do CDN oficial (developer.api.autodesk.com/modelderivative/v2/viewers);
 * - o Viewer cria workers por blob: e injeta estilos inline;
 * - geometria SVF2 vem de cdn.derivative.autodesk.com por https e WebSocket (wss);
 * - texturas, mapas de ambiente e ícones por https, data: e blob:.
 * - login Microsoft (MSAL, Fase 11): troca de código e renovação do token por fetch em
 *   login.microsoftonline.com (connect-src) e, se o refresh token falhar, iframe oculto
 *   (frame-src). O login em si é um redirect de página inteira (não precisa de CSP).
 * - a telemetria do Viewer (api-js.mixpanel.com) fica BLOQUEADA de propósito: não afeta
 *   o modelo e nenhum dado de uso da fábrica vai para terceiros.
 */

const AUTODESK = 'https://*.autodesk.com';
const AUTODESK_WS = 'wss://*.autodesk.com';
const VIEWER_CDN = 'https://developer.api.autodesk.com';
const MS_LOGIN = 'https://login.microsoftonline.com';

const DIRECTIVES: Record<string, string[]> = {
  'default-src': ["'self'"],
  'script-src': ["'self'", VIEWER_CDN, 'blob:'],
  'worker-src': ["'self'", 'blob:'],
  'style-src': ["'self'", "'unsafe-inline'", VIEWER_CDN],
  'img-src': ["'self'", 'data:', 'blob:', AUTODESK],
  'font-src': ["'self'", 'data:', AUTODESK],
  'connect-src': ["'self'", AUTODESK, AUTODESK_WS, MS_LOGIN],
  'frame-src': ["'self'", MS_LOGIN],
  'media-src': ["'self'", 'blob:'],
  'object-src': ["'none'"],
  'base-uri': ["'self'"],
  'form-action': ["'self'"],
  'frame-ancestors': ["'none'"],
};

function serialize(directives: Record<string, string[]>): string {
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(' ')}`)
    .join('; ');
}

/** CSP de produção (o que o proxy deve enviar com o index.html). */
export const APP_CSP = serialize(DIRECTIVES);

/**
 * CSP do servidor de desenvolvimento do Vite: a de produção + o preâmbulo inline do
 * React Fast Refresh e o WebSocket do HMR. Nunca usar em produção.
 */
export const DEV_CSP = serialize({
  ...DIRECTIVES,
  'script-src': [...(DIRECTIVES['script-src'] ?? []), "'unsafe-inline'"],
  'connect-src': [...(DIRECTIVES['connect-src'] ?? []), 'ws:'],
});

const COMMON: Record<string, string> = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
};

/** Produção (HTTPS): CSP, HSTS e os demais. */
export const PRODUCTION_HEADERS: Record<string, string> = {
  ...COMMON,
  'Content-Security-Policy': APP_CSP,
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
};

/** `vite preview` roda em http local: sem HSTS (o navegador ignoraria). */
export const PREVIEW_HEADERS: Record<string, string> = { ...COMMON, 'Content-Security-Policy': APP_CSP };

export const DEV_HEADERS: Record<string, string> = { ...COMMON, 'Content-Security-Policy': DEV_CSP };

/** Trecho do nginx (`include`) com os cabeçalhos: gerado no build da imagem (10.3). */
export function nginxHeaders(headers: Record<string, string>): string {
  const lines = Object.entries(headers).map(([name, value]) => {
    if (value.includes('"') || value.includes('\n') || value.includes('\\')) {
      throw new Error(`Valor inválido para o nginx em ${name}`);
    }
    return `add_header ${name} "${value}" always;`;
  });
  return `# Gerado de frontend/security-headers.ts (scripts/nginx-headers.mjs). Não editar.\n${lines.join('\n')}\n`;
}
