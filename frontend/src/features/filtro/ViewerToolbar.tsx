import { useEffect, useRef, useState, type ReactNode } from 'react';

type Pop = 'filter' | 'color';

interface Props {
  disabled: boolean;
  filterActive: boolean;
  filtering: boolean;
  coloringActive: boolean;
  onFitAll: () => void;
  onClearFilter: () => void;
  onClearColoring: () => void;
  /** "Editar cores": abre a janela Cores (esquemas de cores). */
  onEditColors: () => void;
  /** Conteúdo dos popovers (abrem para cima). */
  filterPopover: ReactNode;
  colorPopover: ReactNode;
}

/**
 * Barra inferior do visualizador: Filtro ▾ · Ampliar tudo · Editar cores · Colorir ▾ e, à
 * direita, "Remover filtros" / "Remover coloração" (só com algo ativo). "Medida" entra
 * quando o ViewerAdapter tiver a ferramenta.
 */
export function ViewerToolbar({
  disabled,
  filterActive,
  filtering,
  coloringActive,
  onFitAll,
  onClearFilter,
  onClearColoring,
  onEditColors,
  filterPopover,
  colorPopover,
}: Props) {
  const [open, setOpen] = useState<Pop | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (e.target instanceof Node && !root.current?.contains(e.target)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      // Esc numa janela aberta pelo popover fecha só a janela
      if (e.key === 'Escape' && !document.querySelector('.modal-bg')) setOpen(null);
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = (p: Pop) => { setOpen(open === p ? null : p); };

  return (
    <div ref={root} className="viewer-bar" role="toolbar" aria-label="Barra do visualizador">
      {open === 'filter' && <div className="viewer-bar__pop">{filterPopover}</div>}
      {open === 'color' && <div className="viewer-bar__pop viewer-bar__pop--color">{colorPopover}</div>}
      <div className="viewer-bar__main">
        <button
          type="button"
          aria-expanded={open === 'filter'}
          aria-pressed={filterActive}
          disabled={disabled}
          onClick={() => { toggle('filter'); }}
        >
          Filtro ▾{filtering && <span className="viewer-bar__spin" role="status" aria-label="Filtrando" />}
        </button>
        <button type="button" disabled={disabled} onClick={onFitAll}>
          Ampliar tudo
        </button>
        <button type="button" disabled={disabled} onClick={() => { setOpen(null); onEditColors(); }}>
          Editar cores
        </button>
        <button type="button" aria-expanded={open === 'color'} aria-pressed={coloringActive} disabled={disabled} onClick={() => { toggle('color'); }}>
          Colorir ▾
        </button>
      </div>
      {(filterActive || coloringActive) && (
        <div className="viewer-bar__right">
          {filterActive && (
            <button type="button" className="secondary" onClick={() => { setOpen(null); onClearFilter(); }}>
              Remover filtros
            </button>
          )}
          {coloringActive && (
            <button type="button" className="secondary" onClick={() => { setOpen(null); onClearColoring(); }}>
              Remover coloração
            </button>
          )}
        </div>
      )}
    </div>
  );
}
