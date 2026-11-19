import { lazy, Suspense } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';

import { Logo } from './components/Logo';
import { useAuth } from './features/auth/AuthContext';
import { UserMenu } from './features/auth/UserMenu';
import { useCurrentUser } from './features/dev-user/useCurrentUser';

/**
 * Seletor do usuário simulado: só no servidor de desenvolvimento do Vite. No build de
 * produção `import.meta.env.DEV` vira `false` e o módulo nem entra no pacote (11.2).
 */
const DevUserSelector = import.meta.env.DEV
  ? lazy(() => import('./features/dev-user/DevUserSelector').then((m) => ({ default: m.DevUserSelector })))
  : null;

export function Layout() {
  const auth = useAuth();
  const me = useCurrentUser();
  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">
          <Link to="/" aria-label="Cassol Elo — início">
            <Logo height={38} />
          </Link>
        </h1>
        {me.data?.role === 'admin' && (
          <nav className="app__nav" aria-label="Administração">
            <NavLink to="/usuarios">Usuários</NavLink>
          </nav>
        )}
        {auth.mode === 'microsoft' ? (
          <UserMenu />
        ) : (
          DevUserSelector && (
            <Suspense fallback={null}>
              <DevUserSelector />
            </Suspense>
          )
        )}
      </header>
      <main className="app__main">
        <Outlet />
      </main>
    </div>
  );
}
