import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useState } from 'react';

import {
  fetchVersions,
  NO_TRANSLATION_MESSAGE,
  syncVersions,
  VERSION_STATUS_LABELS,
} from '../../api/obras';
import { errorMessage } from '../../lib/errors';
import { formatDateTime } from '../../lib/format';
import { EDITOR_ROLES, hasRole, SYNC_ROLES, useCurrentUser } from '../dev-user/useCurrentUser';
import { syncMessage } from './syncMessage';
import { ValidationPanel } from './ValidationPanel';
import { useObraId } from './useObraId';

export function VersionsTab() {
  const obraId = useObraId();
  const queryClient = useQueryClient();
  const me = useCurrentUser();
  const key = ['obras', obraId, 'versions'];

  const versions = useQuery({
    queryKey: key,
    queryFn: () => fetchVersions(obraId),
    retry: false,
    // Versões chegam sozinhas (webhook / verificação periódica): atualiza a cada minuto.
    refetchInterval: 60_000,
  });
  const sync = useMutation({
    mutationFn: () => syncVersions(obraId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  // Painel "Validação": só para quem cuida do modelo (projetos/admin).
  const canValidate = hasRole(me.data, EDITOR_ROLES);
  const [chosenId, setChosenId] = useState<number | null>(null);
  const readyVersions = versions.data?.filter((v) => v.status === 'ready') ?? [];
  const validated =
    readyVersions.find((v) => v.id === chosenId) ?? readyVersions[0]; // padrão: a mais recente
  const columns = canValidate ? 6 : 5;

  return (
    <div>
      <div className="page-head">
        <h3>Histórico de versões</h3>
        {hasRole(me.data, SYNC_ROLES) && (
          <button type="button" onClick={() => { sync.mutate(); }} disabled={sync.isPending}>
            {sync.isPending ? 'Sincronizando…' : 'Sincronizar agora'}
          </button>
        )}
      </div>

      {sync.isSuccess && <p role="status">{syncMessage(sync.data)}</p>}
      {sync.isError && (
        <p role="alert" className="error">
          {errorMessage(sync.error)}
        </p>
      )}

      {versions.isPending && <p className="muted">Carregando…</p>}
      {versions.isError && (
        <p role="alert" className="error">
          {errorMessage(versions.error)}
        </p>
      )}
      {versions.data?.length === 0 && (
        <p className="muted">Nenhuma versão sincronizada ainda. Use "Sincronizar agora".</p>
      )}
      {versions.data && versions.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Versão</th>
              <th>Publicado por</th>
              <th>Data</th>
              <th>Comentário</th>
              <th>Situação</th>
              {canValidate && <th>Validação</th>}
            </tr>
          </thead>
          <tbody>
            {versions.data.map((v) => (
              <Fragment key={v.id}>
                <tr>
                  <td>v{v.version_number}</td>
                  <td>{v.published_by ?? '—'}</td>
                  <td>{formatDateTime(v.published_at)}</td>
                  <td>{v.comment ?? '—'}</td>
                  <td>
                    <span className={`status status--${v.status}`}>
                      {VERSION_STATUS_LABELS[v.status]}
                    </span>
                    {v.status === 'translating' && (
                      <span className="muted small"> (verificação automática a cada 2 min)</span>
                    )}
                    {v.error && <span className="error small"> {v.error}</span>}
                  </td>
                  {canValidate && (
                    <td>
                      {v.status === 'ready' && (
                        <button
                          type="button"
                          className="secondary"
                          aria-pressed={validated?.id === v.id}
                          aria-label={`Validação da v${v.version_number}`}
                          onClick={() => { setChosenId(v.id); }}
                        >
                          {validated?.id === v.id ? 'Exibindo' : 'Ver validação'}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
                {v.status === 'no_translation' && (
                  <tr className="notice-row">
                    <td colSpan={columns}>
                      <p className="notice" role="note">
                        {NO_TRANSLATION_MESSAGE}
                      </p>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      {canValidate && validated && (
        <ValidationPanel
          key={validated.id}
          versionId={validated.id}
          versionNumber={validated.version_number}
        />
      )}
    </div>
  );
}
