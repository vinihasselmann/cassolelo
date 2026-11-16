import type { LiveNotice } from './useObraEvents';

/** Avisos discretos no canto (ações dos colegas em tempo real). */
export function LiveNotices({ notices, onDismiss }: { notices: LiveNotice[]; onDismiss: (key: string) => void }) {
  return (
    <div className="live-notices" role="log" aria-live="polite" aria-label="Atualizações da obra">
      {notices.map((n) => (
        <div key={n.key} className="live-notice">
          <span>{n.text}</span>
          <button type="button" className="link" aria-label="Fechar aviso" onClick={() => { onDismiss(n.key); }}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
