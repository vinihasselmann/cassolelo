import { APP_CSP, DEV_CSP, PREVIEW_HEADERS, PRODUCTION_HEADERS, nginxHeaders } from '../security-headers';

function directives(csp: string): Map<string, string[]> {
  return new Map(
    csp.split(';').map((part) => {
      const [name = '', ...values] = part.trim().split(/\s+/);
      return [name, values];
    }),
  );
}

describe('CSP do app (10.2)', () => {
  const prod = directives(APP_CSP);

  it('libera o que o Viewer v7 da Autodesk precisa', () => {
    expect(prod.get('script-src')).toEqual(expect.arrayContaining(["'self'", 'https://developer.api.autodesk.com']));
    expect(prod.get('worker-src')).toContain('blob:');
    expect(prod.get('style-src')).toContain('https://developer.api.autodesk.com');
    expect(prod.get('connect-src')).toEqual(expect.arrayContaining(['https://*.autodesk.com', 'wss://*.autodesk.com']));
    expect(prod.get('img-src')).toEqual(expect.arrayContaining(['data:', 'blob:']));
  });

  it('produção não aceita script inline, eval nem ser embutida em frame', () => {
    expect(prod.get('script-src')).not.toContain("'unsafe-inline'");
    expect(APP_CSP).not.toContain("'unsafe-eval'");
    expect(prod.get('object-src')).toEqual(["'none'"]);
    expect(prod.get('frame-ancestors')).toEqual(["'none'"]);
    expect(prod.get('default-src')).toEqual(["'self'"]);
  });

  it('o relaxamento do dev (Fast Refresh e HMR) não vaza para produção', () => {
    const dev = directives(DEV_CSP);
    expect(dev.get('script-src')).toContain("'unsafe-inline'");
    expect(dev.get('connect-src')).toContain('ws:');
    expect(prod.get('connect-src')).not.toContain('ws:');
    expect(PRODUCTION_HEADERS['Content-Security-Policy']).toBe(APP_CSP);
    expect(PREVIEW_HEADERS['Content-Security-Policy']).toBe(APP_CSP);
  });

  it('HSTS e nosniff em produção; preview (http local) sem HSTS', () => {
    expect(PRODUCTION_HEADERS['Strict-Transport-Security']).toMatch(/^max-age=31536000/);
    expect(PRODUCTION_HEADERS['X-Content-Type-Options']).toBe('nosniff');
    expect(PREVIEW_HEADERS['Strict-Transport-Security']).toBeUndefined();
  });
});

describe('cabeçalhos no nginx (10.3)', () => {
  it('gera um add_header ... always por cabeçalho de produção, com a CSP inteira', () => {
    const conf = nginxHeaders(PRODUCTION_HEADERS);
    const lines = conf.split('\n').filter((l) => l.startsWith('add_header '));
    expect(lines).toHaveLength(Object.keys(PRODUCTION_HEADERS).length);
    expect(conf).toContain(`add_header Content-Security-Policy "${APP_CSP}" always;`);
    expect(conf).toContain('add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;');
  });

  it('recusa valores que quebrariam a configuração do nginx', () => {
    expect(() => nginxHeaders({ X: 'a"b' })).toThrow(/inválido/);
    expect(() => nginxHeaders({ X: 'a\nb' })).toThrow(/inválido/);
  });
});
