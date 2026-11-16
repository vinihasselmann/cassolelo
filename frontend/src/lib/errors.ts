import { ApiError } from '../api/client';

/** Mensagem amigável para exibir ao usuário. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Selecione um usuário no cabeçalho.';
    return error.message;
  }
  return 'Erro inesperado. Tente novamente.';
}
