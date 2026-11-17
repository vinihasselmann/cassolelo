import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from '../../components/Icon';

interface Props {
  /** "N parâmetros no catálogo…" (ou o erro / carregando). */
  summary: string;
  canEditParams: boolean;
  onNewParam: () => void;
  onCatalog: () => void;
  onMarkOrphans: () => void;
  onUnitOrphans: () => void;
}

/**
 * Gestão da obra (parâmetros e órfãs) recolhida num "Gerenciar": a coluna esquerda
 * começa pela lista de marcas, que é o caminho da produção. Igual para todos os papéis.
 */
export function ManageMenu({ summary, canEditParams, onNewParam, onCatalog, onMarkOrphans, onUnitOrphans }: Props) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const toggle = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || document.querySelector('.modal')) return; // janela aberta: o Esc é dela
      setOpen(false);
      toggle.current?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); };
  }, [open]);

  const pick = (action: () => void) => () => {
    setOpen(false);
    action();
  };

  return (
    <div className="model-sec manage">
      <div className="manage__head">
        <p className="hint params-count">{summary}</p>
        <button
          ref={toggle}
          type="button"
          className="ghost btn-sm"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => { setOpen(!open); }}
        >
          Gerenciar <Icon name={open ? 'chevron-up' : 'chevron-down'} size={12} />
        </button>
      </div>
      <div id={listId} className="manage__list" hidden={!open}>
        {canEditParams && (
          <button type="button" className="list-item" onClick={pick(onNewParam)}>
            + Novo parâmetro
          </button>
        )}
        <button type="button" className="list-item" onClick={pick(onCatalog)}>
          Catálogo
        </button>
        <button type="button" className="list-item" onClick={pick(onMarkOrphans)}>
          Marcas órfãs
        </button>
        <button type="button" className="list-item" onClick={pick(onUnitOrphans)}>
          Peças órfãs
        </button>
      </div>
    </div>
  );
}
