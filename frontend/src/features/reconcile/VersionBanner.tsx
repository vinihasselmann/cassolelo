import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { diffKey, fetchDiff } from '../../api/reconcile';
import { versionName } from '../../lib/format';
import { Icon } from '../../components/Icon';

const num = (n: number) => n.toLocaleString('pt-BR');

interface Props {
  versionId: number;
  onShowNew: () => void;
  onShowReview: () => void;
  onShowOrphans: () => void;
  /** Fila de unidades de peça órfãs (P5). */
  onShowUnitOrphans: () => void;
}

const pecas = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;
/** "PP001-3, PP001-5 e mais 3" */
function labels(list: { label: string }[], max = 4): string {
  const shown = list.slice(0, max).map((u) => u.label).join(', ');
  return list.length > max ? `${shown} e mais ${num(list.length - max)}` : shown;
}

/** Banner da versão nova: "N novas · N a revisar · N órfãs" (comparada com a anterior). */
export function VersionBanner({ versionId, onShowNew, onShowReview, onShowOrphans, onShowUnitOrphans }: Props) {
  const [closed, setClosed] = useState<number | null>(null);
  const diff = useQuery({ queryKey: diffKey(versionId), queryFn: () => fetchDiff(versionId), retry: false });
  const d = diff.data;
  if (!d || d.prev_version_number === null || closed === versionId) return null;
  const news = d.totals.new;
  const u = d.units;
  const unitNews = u ? u.lost + u.new + u.orphans_open + u.returned > 0 : false;
  if (
    news === 0 &&
    d.review_open === 0 &&
    d.orphans_open === 0 &&
    d.totals.count_changed === 0 &&
    d.totals.removed === 0 &&
    !unitNews
  ) {
    return null;
  }
  return (
    <div className="version-banner" role="region" aria-label="Versão nova">
      <span>
        <b>{versionName(d.version_number)}</b> comparada com a {versionName(d.prev_version_number)}:
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
      {u && unitNews && (
        <span className="version-banner__units" role="group" aria-label="Peças">
          · Peças:{' '}
          <button type="button" className="link" onClick={onShowUnitOrphans}>
            {pecas(u.orphans_open, 'peça órfã', 'peças órfãs')}
          </button>
          {u.lost > 0 && (
            <span className="small">
              {' '}
              ({pecas(u.lost, 'perdeu', 'perderam')} a peça nesta versão, com valores: {labels(u.lost_units)})
            </span>
          )}
          {u.new > 0 && (
            <span className="small">
              {' '}
              · {pecas(u.new, 'peça nova', 'peças novas')}: {labels(u.new_units)}
            </span>
          )}
          {u.returned > 0 && <span className="small"> · {pecas(u.returned, 'voltou', 'voltaram')} pela chave</span>}
        </span>
      )}
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
        <Icon name="close" />
      </button>
    </div>
  );
}
