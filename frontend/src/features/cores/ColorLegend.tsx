import { useEffect, useState } from 'react';

import { FloatingPanel } from '../../components/FloatingPanel';
import { Icon } from '../../components/Icon';
import type { Coloring, LegendRow } from './coloringModel';
import { legendSummary, shortTitle } from './legendSummary';

const num = (n: number) => n.toLocaleString('pt-BR');
const plural = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;
const PREFIX = 'cassol-elo:legenda-retraida:';

function loadCollapsed(key: string | undefined): boolean {
  if (!key) return false;
  try {
    return window.localStorage.getItem(PREFIX + key) === '1';
  } catch {
    return false; // sem armazenamento: começa expandida
  }
}

function saveCollapsed(key: string | undefined, collapsed: boolean): void {
  if (!key) return;
  try {
    if (collapsed) window.localStorage.setItem(PREFIX + key, '1');
    else window.localStorage.removeItem(PREFIX + key);
  } catch {
    // sem armazenamento: vale só nesta visita
  }
}

interface Props {
  coloring: Coloring;
  onPick: (row: LegendRow) => void;
  /** Lembra posição e retraída/expandida por usuário (ex.: `legend:3`). */
  storageKey?: string | undefined;
}

/**
 * Legenda da coloração (status ou qualquer "Colorir por"), num painel flutuante móvel
 * (padrão: canto superior direito do 3D). Retraída, vira uma pílula com o resumo; clicar expande.
 * Remover a coloração é o ✕ ao lado de "Colorir", na barra.
 */
export function ColorLegend({ coloring, onPick, storageKey }: Props) {
  const [collapsed, setCollapsed] = useState(() => loadCollapsed(storageKey));
  useEffect(() => { setCollapsed(loadCollapsed(storageKey)); }, [storageKey]);
  const set = (v: boolean) => {
    setCollapsed(v);
    saveCollapsed(storageKey, v);
  };
  const summary = legendSummary(coloring);

  return (
    <FloatingPanel
      storageKey={storageKey}
      label="a legenda"
      placement="top-right"
      className={`legend-float${collapsed ? ' legend-float--collapsed' : ''}`}
    >
      {(grip) =>
        collapsed ? (
          <div className="legend-pill">
            {grip}
            <button
              type="button"
              className="legend-pill__btn"
              aria-expanded="false"
              aria-label={`Expandir legenda: ${summary}`}
              title="Expandir legenda"
              onClick={() => { set(false); }}
            >
              <span className="legend-pill__text">
                <b>{shortTitle(coloring.title)}</b>
                {summary.slice(shortTitle(coloring.title).length)}
              </span>
              <Icon name="chevron-down" size={10} />
            </button>
          </div>
        ) : (
          <div className="legend" role="region" aria-label="Legenda">
            <div className="legend__head">
              {grip}
              <h5>{coloring.title}</h5>
              <button
                type="button"
                className="legend__collapse"
                aria-expanded="true"
                aria-label="Retrair legenda"
                title="Retrair legenda"
                onClick={() => { set(true); }}
              >
                <Icon name="chevron-up" size={11} />
              </button>
            </div>
            {coloring.legend.length === 0 && <p className="hint">Nenhuma peça.</p>}
            <ul>
              {coloring.legend.map((item) => (
                <li key={item.key}>
                  <button
                    type="button"
                    className="legend__row"
                    disabled={item.pieces === 0}
                    title={`${plural(item.marks, 'marca', 'marcas')} · ${plural(item.pieces, 'peça', 'peças')}`}
                    aria-label={`${item.label}: ${plural(item.marks, 'marca', 'marcas')} · ${plural(item.pieces, 'peça', 'peças')}`}
                    onClick={() => { onPick(item); }}
                  >
                    <span className="legend__dot" style={{ background: item.color }} aria-hidden="true" />
                    <span className="legend__label">{item.label}</span>
                    <span className="legend__n">{num(item.pieces)}</span>
                  </button>
                </li>
              ))}
            </ul>
            {coloring.note && <p className="hint">{coloring.note}</p>}
            <p className="hint legend__tip">Escolha um item para selecionar as peças</p>
          </div>
        )
      }
    </FloatingPanel>
  );
}
