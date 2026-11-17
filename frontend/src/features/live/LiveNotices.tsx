import type { LiveNotice } from './useObraEvents';
import { Icon } from '../../components/Icon';

/** Avisos discretos no canto (ações dos colegas em tempo real). */
export function LiveNotices({ notices, onDismiss }: { notices: LiveNotice[]; onDismiss: (key: string) => void }) {
  return (
    <div className="live-notices" role="log" aria-live="polite" aria-label="Atualizações da obra">
      {notices.map((n) => (
        <div key={n.key} className="live-notice">
          <span>{n.text}</span>
          <button type="button" className="link" aria-label="Fechar aviso" onClick={() => { onDismiss(n.key); }}>
            <Icon name="close" />
          </button>
        </div>
      ))}
    </div>
  );
}
