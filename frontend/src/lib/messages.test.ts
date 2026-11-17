import { ApiError, fallbackMessage, toApiError } from '../api/client';
import { errorMessage } from './errors';
import { plural, versionName } from './format';

describe('mensagens ao usuário', () => {
  it('sem conexão (fetch rejeita com TypeError) diz o que houve e o que fazer', () => {
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe('Sem conexão com o servidor. Confira o Wi-Fi e tente de novo.');
  });

  it('erro sem mensagem do servidor vira texto em português, nunca o statusText em inglês', async () => {
    const proxy = await toApiError(new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }));
    expect(proxy.message).toBe('O servidor não respondeu (erro 502). Tente de novo em instantes.');
    const validation = await toApiError(
      new Response(JSON.stringify({ detail: [{ msg: 'field required' }] }), { status: 422, statusText: 'Unprocessable Entity' }),
    );
    expect(validation.message).toBe('Dados inválidos. Confira os campos e tente de novo.');
    expect(fallbackMessage(403)).toBe('Seu papel não permite esta ação.');
  });

  it('a mensagem em português do servidor é mantida', async () => {
    const err = await toApiError(new Response(JSON.stringify({ detail: 'Data inválida: use dd/mm/aaaa' }), { status: 422 }));
    expect(err).toBeInstanceOf(ApiError);
    expect(errorMessage(err)).toBe('Data inválida: use dd/mm/aaaa');
  });

  it('plural de verdade, sem "(s)"; versão como no Docs', () => {
    expect(plural(1, 'peça', 'peças')).toBe('1 peça');
    expect(plural(0, 'marca', 'marcas')).toBe('0 marcas');
    expect(plural(1234, 'parâmetro', 'parâmetros')).toBe('1.234 parâmetros');
    expect(versionName(3)).toBe('V3');
  });
});
