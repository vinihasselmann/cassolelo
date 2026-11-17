import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';

import { FloatingPanel } from '../../components/FloatingPanel';
import { Icon } from '../../components/Icon';
import { popoverPlacement, type Pop } from './popoverPlacement';

interface Props {
  disabled: boolean;
  filterActive: boolean;
  filtering: boolean;
  coloringActive: boolean;
  onFitAll: () => void;
  onClearFilter: () => void;
  onClearColoring: () => void;
  /** Conteúdo dos popovers (abrem junto da barra, para baixo ou para cima). */
  filterPopover: ReactNode;
  colorPopover: ReactNode;
  /** Ferramentas de seleção (Enquadrar, Isolar, Limpar, Seleção múltipla): grupo do meio. */
  selectionTools?: ReactNode;
  /** Posição da barra lembrada por usuário (ex.: `viewer-bar:3`). */
  storageKey?: string | undefined;
}

/**
 * A barra do visualizador, num painel flutuante móvel (padrão: topo, centralizada, longe da
 * barra nativa do Viewer, que fica embaixo): Filtro (✕) · Colorir (✕) │ seleção │ Ampliar tudo.
 * O ✕ ("Remover filtros" / "Remover coloração") só aparece com algo ativo.
 */
export function ViewerToolbar({
  disabled,
  filterActive,
  filtering,
  coloringActive,
  onFitAll,
  onClearFilter,
  onClearColoring,
  filterPopover,
  colorPopover,
  selectionTools = null,
  storageKey,
}: Props) {
  const [open, setOpen] = useState<Pop | null>(null);
  const [place, setPlace] = useState<CSSProperties>({});
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: globalThis.PointerEvent) => {
      const panel = root.current?.closest('.floating');
      if (e.target instanceof Node && !panel?.contains(e.target)) setOpen(null);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
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

  // posição do popover: medida ao abrir e quando a janela muda de tamanho
  useLayoutEffect(() => {
    if (!open) return undefined;
    const measure = () => {
      const panel = root.current?.closest('.floating');
      const area = panel?.parentElement;
      if (panel && area) setPlace(popoverPlacement(open, panel.getBoundingClientRect(), area.getBoundingClientRect()));
    };
    measure();
    window.addEventListener('resize', measure);
    return () => { window.removeEventListener('resize', measure); };
  }, [open]);

  const toggle = (p: Pop) => { setOpen(open === p ? null : p); };

  return (
    <FloatingPanel
      storageKey={storageKey}
      label="a barra do visualizador"
      className="viewer-float"
      onMoveStart={() => { setOpen(null); }}
    >
      <div ref={root} className="viewer-bar" role="toolbar" aria-label="Barra do visualizador">
        {open === 'filter' && (
          <div className="popover viewer-bar__pop" style={place}>
            {filterPopover}
          </div>
        )}
        {open === 'color' && (
          <div className="popover viewer-bar__pop" style={place}>
            {colorPopover}
          </div>
        )}
        <span className="bar-split">
          <button
            type="button"
            aria-expanded={open === 'filter'}
            aria-pressed={filterActive}
            disabled={disabled}
            onClick={() => { toggle('filter'); }}
          >
            Filtro <Icon name="chevron-down" size={10} />
            {filtering && <span className="viewer-bar__spin" role="status" aria-label="Filtrando" />}
          </button>
          {filterActive && (
            <button
              type="button"
              className="bar-clear"
              aria-label="Remover filtros"
              title="Remover filtros"
              onClick={() => { setOpen(null); onClearFilter(); }}
            >
              <Icon name="close" size={11} />
            </button>
          )}
        </span>
        <span className="bar-split">
          <button type="button" aria-expanded={open === 'color'} aria-pressed={coloringActive} disabled={disabled} onClick={() => { toggle('color'); }}>
            Colorir <Icon name="chevron-down" size={10} />
          </button>
          {coloringActive && (
            <button
              type="button"
              className="bar-clear"
              aria-label="Remover coloração"
              title="Remover coloração"
              onClick={() => { setOpen(null); onClearColoring(); }}
            >
              <Icon name="close" size={11} />
            </button>
          )}
        </span>
        {selectionTools && (
          <>
            <span className="bar-sep" aria-hidden="true" />
            <span className="bar-group" role="group" aria-label="Seleção">
              {selectionTools}
            </span>
          </>
        )}
        <span className="bar-sep" aria-hidden="true" />
        <button type="button" disabled={disabled} onClick={onFitAll}>
          Ampliar tudo
        </button>
      </div>
    </FloatingPanel>
  );
}
