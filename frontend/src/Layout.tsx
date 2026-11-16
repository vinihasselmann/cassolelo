import { Link, Outlet } from 'react-router-dom';

import { Logo } from './components/Logo';
import { DevUserSelector } from './features/dev-user/DevUserSelector';

export function Layout() {
  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">
          <Link to="/" aria-label="Cassol Elo — início">
            <Logo height={38} />
          </Link>
        </h1>
        <DevUserSelector />
      </header>
      <main className="app__main">
        <Outlet />
      </main>
    </div>
  );
}
