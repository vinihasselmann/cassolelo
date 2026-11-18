import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { connectObraEvents, type ObraEvent } from '../../api/events';
import { useCurrentUser } from '../dev-user/useCurrentUser';
import { invalidateValueQueries } from '../params/invalidate';
import { describeEvent } from './eventText';

export const NOTICE_MS = 6000;
const MAX_NOTICES = 3;

export interface LiveNotice {
  key: string;
  text: string;
}

export interface NewVersion {
  versionId: number;
  versionNumber: number;
}

/**
 * Assina os eventos da obra enquanto ela está aberta:
 * - invalida as queries afetadas (versões, valores, status, cores, progresso, busca,
 *   órfãs, catálogo);
 * - avisos discretos das ações dos OUTROS usuários ("J. Silva alterou PP003");
 * - `newVersion` quando uma versão fica pronta (a tela oferece "Carregar").
 */
export function useObraEvents(obraId: number | null) {
  const queryClient = useQueryClient();
  const me = useCurrentUser();
  const myId = me.data?.id ?? null;
  const [notices, setNotices] = useState<LiveNotice[]>([]);
  const [newVersion, setNewVersion] = useState<NewVersion | null>(null);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((key: string) => {
    setNotices((list) => list.filter((n) => n.key !== key));
    clearTimeout(timers.current.get(key));
    timers.current.delete(key);
  }, []);

  const handle = useCallback(
    (ev: ObraEvent) => {
      if (ev.type === 'obra_file_state') {
        // arquivo excluído/restaurado no Docs: a obra (e a lista) mudam de situação
        void queryClient.invalidateQueries({ queryKey: ['obras'] });
      } else if (ev.type === 'units_renumbered') {
        // numeração das peças (PP001-1…) e a situação dos centros mudaram
        void queryClient.invalidateQueries({ queryKey: ['obras', obraId] });
        void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'versions' && q.queryKey[2] === 'centroids' });
        void invalidateValueQueries(queryClient);
      } else if (ev.type === 'version_ready' || ev.type === 'version_failed') {
        void queryClient.invalidateQueries({ queryKey: ['obras', obraId, 'versions'] });
        if (ev.type === 'version_ready' && typeof ev.data.version_id === 'number') {
          setNewVersion({ versionId: ev.data.version_id, versionNumber: Number(ev.data.version_number) });
        }
      } else {
        void invalidateValueQueries(queryClient);
      }
      const mine = ev.data.actor !== null && ev.data.actor.id === myId;
      const text = mine ? null : describeEvent(ev);
      if (text === null) return;
      const key = ev.id || `${ev.type}-${ev.data.at}`;
      setNotices((list) => [...list.filter((n) => n.key !== key), { key, text }].slice(-MAX_NOTICES));
      timers.current.set(key, setTimeout(() => { dismiss(key); }, NOTICE_MS));
    },
    [queryClient, obraId, myId, dismiss],
  );

  // O listener sempre usa a versão atual de `handle` (usuário, obra).
  const live = useRef(handle);
  live.current = handle;

  useEffect(() => {
    if (obraId === null || !Number.isFinite(obraId) || myId === null) return;
    return connectObraEvents(obraId, { onEvent: (ev) => { live.current(ev); } });
  }, [obraId, myId]);

  useEffect(() => {
    const all = timers.current;
    return () => { all.forEach((t) => { clearTimeout(t); }); };
  }, []);

  return { notices, dismiss, newVersion, clearNewVersion: () => { setNewVersion(null); } };
}
