import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { diffKey, fetchDiff } from '../../api/reconcile';

const num = (n: number) => n.toLocaleString('pt-BR');

interface Props {
  versionId: number;
  onShowNew: () => void;
  onShowReview: () => void;
  onShowOrphans: () => void;
}

/** Banner da versão nova: "N novas · N a revisar · N órfãs" (comparada com a anterior). */
export function VersionBanner({ versionId, onShowNew, onShowReview, onShowOrphans }: Props) {
  const [closed, setClosed] = useState<number | null>(null);
  const diff = useQuery({ queryKey: diffKey(versionId), queryFn: () => fetchDiff(versionId), retry: false });
  const d = diff.data;
  if (!d || d.prev_version_number === null || closed === versionId) return null;
  const news = d.totals.new;
  if (news === 0 && d.review_open === 0 && d.orphans_open === 0 && d.totals.count_changed === 0 && d.totals.removed === 0) {
    return null;
  }
  return (
    <div className="version-banner" role="region" aria-label="Versão nova">
      <span>
        <b>Versão {d.version_number}</b> comparada com a {d.prev_version_number}:
      </span>
      <button type="button" className="link" onClick={onShowNew}>
        {num(news)} {news === 1 ? 'nova' : 'novas'}
      </button>
      ·
      <button type="button" className="link" onClick={onShowReview}>
        {num(d.review_open)} a revisar
      </button>
      ·
      <button type="button" className="link" onClick={onShowOrphans}>
        {num(d.orphans_open)} {d.orphans_open === 1 ? 'órfã' : 'órfãs'}
      </button>
      {d.totals.count_changed > 0 && (
        <span className="muted small">
          · {num(d.totals.count_changed)} com quantidade alterada (valores seguem a marca)
        </span>
      )}
      <button
        type="button"
        className="link version-banner__close"
        aria-label="Fechar aviso da versão"
        onClick={() => { setClosed(versionId); }}
      >
        ×
      </button>
    </div>
  );
}
