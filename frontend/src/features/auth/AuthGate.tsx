import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { setTokenProvider } from '../../api/client';
import { useCurrentUser } from '../dev-user/useCurrentUser';
import { AuthContext, type AuthState } from './AuthContext';
import { LoginPage } from './LoginPage';
import { signIn, signOut, tokenProviderFor, type AuthBoot } from './microsoft';

type GateState = { status: 'loading' } | { status: 'error' } | { status: 'ready'; boot: AuthBoot };

const DEV: AuthState = { mode: 'dev' };

/**
 * Porta de entrada do app: sem login, mostra a tela "Entrar com Microsoft"; com login,
 * registra o token no cliente HTTP e confere o usuário no backend (/api/me) antes de
 * desenhar as telas. Em dev, sem Microsoft configurado, segue com o usuário simulado.
 */
export function AuthGate({ boot, children }: { boot: Promise<AuthBoot>; children: ReactNode }) {
  const [state, setState] = useState<GateState>({ status: 'loading' });
  const [devChosen, setDevChosen] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    let alive = true;
    boot.then(
      (b) => {
        if (b.kind === 'microsoft') setTokenProvider(tokenProviderFor(b.pca, b.account, b.config));
        if (alive) setState({ status: 'ready', boot: b });
      },
      () => {
        if (alive) setState({ status: 'error' });
      },
    );
    return () => {
      alive = false;
    };
  }, [boot]);

  const microsoft = useMemo<AuthState | null>(() => {
    if (state.status !== 'ready' || state.boot.kind !== 'microsoft') return null;
    const { pca, account } = state.boot;
    return {
      mode: 'microsoft',
      name: account.name ?? account.username,
      email: account.username,
      signOut: () => {
        setTokenProvider(null);
        queryClient.clear();
        void signOut(pca, account);
      },
    };
  }, [state, queryClient]);

  if (state.status === 'loading') {
    return (
      <main className="login">
        <p className="login__hint">Carregando…</p>
      </main>
    );
  }
  if (state.status === 'error') {
    return (
      <main className="login">
        <div className="login__card">
          <p role="alert" className="login__error">
            Não foi possível falar com o servidor. Confira a rede e tente de novo.
          </p>
          <button type="button" onClick={() => { window.location.reload(); }}>
            Tentar de novo
          </button>
        </div>
      </main>
    );
  }

  const b = state.boot;
  if (microsoft !== null) {
    return (
      <AuthContext.Provider value={microsoft}>
        <MeGate onSignOut={microsoft.mode === 'microsoft' ? microsoft.signOut : undefined}>
          {children}
        </MeGate>
      </AuthContext.Provider>
    );
  }
  // usuário simulado: só no servidor de desenvolvimento (fora do build de produção)
  if (import.meta.env.DEV && (b.kind === 'dev' || (b.kind === 'login' && devChosen))) {
    return <AuthContext.Provider value={DEV}>{children}</AuthContext.Provider>;
  }
  if (b.kind === 'login') {
    const { pca, config } = b;
    return (
      <LoginPage
        onMicrosoft={pca ? () => signIn(pca, config) : undefined}
        onDev={import.meta.env.DEV && config.dev_login ? () => { setDevChosen(true); } : undefined}
      />
    );
  }
  return <LoginPage />;
}

/** Confere o usuário no backend: e-mail fora do domínio ou desativado não passa daqui. */
function MeGate({ children, onSignOut }: { children: ReactNode; onSignOut?: (() => void) | undefined }) {
  const me = useCurrentUser();
  if (me.isPending) {
    return (
      <main className="login">
        <p className="login__hint">Entrando…</p>
      </main>
    );
  }
  if (me.isError) {
    return (
      <main className="login">
        <div className="login__card">
          <p role="alert" className="login__error">{me.error.message}</p>
          <div className="btn-row">
            <button type="button" onClick={() => { void me.refetch(); }}>
              Tentar de novo
            </button>
            {onSignOut && (
              <button type="button" className="secondary" onClick={onSignOut}>
                Sair e usar outra conta
              </button>
            )}
          </div>
        </div>
      </main>
    );
  }
  return <>{children}</>;
}
