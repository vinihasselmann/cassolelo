import { ApiError } from '../api/client';

/** Mensagem amigável para exibir ao usuário. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Selecione um usuário no cabeçalho.';
    return error.message;
  }
  // fetch rejeita com TypeError quando não chega ao servidor (Wi-Fi caiu, servidor fora do ar)
  if (error instanceof TypeError) return 'Sem conexão com o servidor. Confira o Wi-Fi e tente de novo.';
  return 'Erro inesperado. Tente de novo.';
}
