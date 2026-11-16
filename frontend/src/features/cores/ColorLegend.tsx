import { useState } from 'react';

import type { Coloring, LegendRow } from './coloringModel';

const num = (n: number) => n.toLocaleString('pt-BR');
const plural = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;

interface Props {
  coloring: Coloring;
  onPick: (row: LegendRow) => void;
}

/** Legenda flutuante: cor, valor e nº de peças; clicar seleciona as peças do valor. */
export function ColorLegend({ coloring, onPick }: Props) {
  const [hidden, setHidden] = useState(false);
  if (hidden) {
    return (
      <button type="button" className="legend-show secondary" onClick={() => { setHidden(false); }}>
        Mostrar legenda
      </button>
    );
  }
  return (
    <div className="legend" role="region" aria-label="Legenda">
      <div className="legend__head">
        <h5>{coloring.title}</h5>
        <button type="button" className="link legend__hide" aria-label="Ocultar legenda" title="Ocultar legenda" onClick={() => { setHidden(true); }}>
          ×
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
      <p className="hint">Clique para selecionar</p>
    </div>
  );
}
