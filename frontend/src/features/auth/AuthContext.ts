import { createContext, useContext } from 'react';

/** Como o usuário entrou. Sem AuthGate (testes de telas), vale o usuário simulado. */
export type AuthState =
  | { mode: 'dev' }
  | { mode: 'microsoft'; name: string; email: string; signOut: () => void };

export const AuthContext = createContext<AuthState>({ mode: 'dev' });

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
