import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, Outlet } from 'react-router-dom';

import { fetchObra, isFileBlocked } from '../../api/obras';
import { errorMessage } from '../../lib/errors';
import { LiveNotices } from '../live/LiveNotices';
import { useObraEvents } from '../live/useObraEvents';
import { ObraBlockedNotice } from './ObraBlocked';
import { useObraId } from './useObraId';
import { Icon } from '../../components/Icon';

export function ObraPage() {
  const obraId = useObraId();
  const obra = useQuery({
    queryKey: ['obras', obraId],
    queryFn: () => fetchObra(obraId),
    enabled: Number.isFinite(obraId),
    retry: false,
  });
  // Tempo real: a lista de versões se atualiza sozinha quando uma versão fica pronta.
  const live = useObraEvents(Number.isFinite(obraId) ? obraId : null);
  // Arquivo excluído no Docs: a obra fica bloqueada (sem 3D, versões ou identificação).
  const blocked = obra.data !== undefined && isFileBlocked(obra.data);

  return (
    <section>
      <p className="small">
        <Link to="/obras" className="back-link"><Icon name="chevron-left" size={12} />Obras</Link>
      </p>
      {obra.isError && (
        <p role="alert" className="error">
          {errorMessage(obra.error)}
        </p>
      )}
      {obra.data && (
        <header className="page-head">
          <div>
            <h2>
              {obra.data.code} — {obra.data.name}
            </h2>
            <p className="muted small">Modelo no Docs: {obra.data.acc_item_name ?? '—'}</p>
          </div>
          {!blocked && (
            <Link to={`/obras/${obraId}/modelo`} className="button-link">
              Abrir modelo 3D
            </Link>
          )}
        </header>
      )}
      {obra.data && blocked && <ObraBlockedNotice obra={obra.data} />}
      {obra.data && !blocked && (
        <>
          <nav className="tabs" aria-label="Seções da obra">
            <NavLink to="versoes">Versões</NavLink>
            <NavLink to="identificacao">Identificação das peças</NavLink>
          </nav>
          <Outlet />
        </>
      )}
      <LiveNotices notices={live.notices} onDismiss={live.dismiss} />
    </section>
  );
}
