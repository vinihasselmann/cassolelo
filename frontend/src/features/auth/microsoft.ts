/**
 * Login Microsoft (Fase 11) com MSAL: authorization code + PKCE, por redirect (mais
 * estável que popup em tablet e no PWA). Client ID, tenant e escopo vêm do backend
 * (GET /api/auth/config), então a mesma build serve qualquer servidor.
 *
 * Tokens ficam no sessionStorage da aba (padrão seguro do MSAL para SPA), nunca no
 * localStorage. O backend valida o access token e acha o usuário pelo e-mail.
 */

import {
  createStandardPublicClientApplication,
  InteractionRequiredAuthError,
  type AccountInfo,
  type IPublicClientApplication,
} from '@azure/msal-browser';

import { ApiError, toApiError, type TokenProvider } from '../../api/client';

export interface AuthConfig {
  /** vazios quando o login Microsoft não está configurado no servidor */
  client_id: string;
  tenant_id: string;
  scope: string;
  /** usuário simulado disponível (só APP_ENV=dev) */
  dev_login: boolean;
}

export type MsalFactory = (config: AuthConfig) => Promise<IPublicClientApplication>;

/** Resultado da inicialização, antes de desenhar o app. */
export type AuthBoot =
  | { kind: 'microsoft'; config: AuthConfig; pca: IPublicClientApplication; account: AccountInfo }
  | { kind: 'login'; config: AuthConfig; pca: IPublicClientApplication | null }
  | { kind: 'dev'; config: AuthConfig }
  | { kind: 'unconfigured'; config: AuthConfig };

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await fetch('/api/auth/config', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as AuthConfig;
}

export const createMsal: MsalFactory = (config) =>
  createStandardPublicClientApplication({
    auth: {
      clientId: config.client_id,
      authority: `https://login.microsoftonline.com/${config.tenant_id}`,
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: { cacheLocation: 'sessionStorage' },
  });

/**
 * Lê a configuração e, com Microsoft configurado, termina a volta do redirect (se for o
 * caso) e recupera a conta já logada nesta aba.
 */
export async function bootAuth(factory: MsalFactory = createMsal): Promise<AuthBoot> {
  const config = await fetchAuthConfig();
  if (config.client_id === '' || config.tenant_id === '') {
    return config.dev_login ? { kind: 'dev', config } : { kind: 'unconfigured', config };
  }
  const pca = await factory(config);
  const result = await pca.handleRedirectPromise();
  const account = result?.account ?? pca.getActiveAccount() ?? pca.getAllAccounts()[0] ?? null;
  if (account === null) return { kind: 'login', config, pca };
  pca.setActiveAccount(account);
  return { kind: 'microsoft', config, pca, account };
}

export function signIn(pca: IPublicClientApplication, config: AuthConfig): Promise<void> {
  return pca.loginRedirect({ scopes: [config.scope], prompt: 'select_account' });
}

export function signOut(pca: IPublicClientApplication, account: AccountInfo): Promise<void> {
  return pca.logoutRedirect({ account });
}

/**
 * Token do app para o cliente HTTP. Renova sozinho (refresh token); se a Microsoft
 * pedir interação (sessão vencida, senha trocada), volta para a tela de login dela.
 */
export function tokenProviderFor(
  pca: IPublicClientApplication,
  account: AccountInfo,
  config: AuthConfig,
): TokenProvider {
  return async ({ forceRefresh }) => {
    try {
      const result = await pca.acquireTokenSilent({ scopes: [config.scope], account, forceRefresh });
      return result.accessToken;
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await pca.acquireTokenRedirect({ scopes: [config.scope], account });
      }
      throw new ApiError(401, 'Sua sessão expirou. Entre de novo com a conta Microsoft.');
    }
  };
}
