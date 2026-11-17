import { useEffect, useState } from 'react';

import { copyText, formatMeters, type PieceKind } from '../../viewer/coordinates';
import type { AxisState } from './useAxisCoordinates';

const KIND_TEXT: Record<PieceKind, string> = { pilar: 'Pilar', viga: 'Viga', laje: 'Laje' };

/** "Pilar · centro da seção na base", "Viga · eixo na meia altura"… */
function ruleText(kind: PieceKind, rule: string): string {
  if (kind === 'pilar') return `centro da seção ${rule === 'topo' ? 'no topo' : 'na base'}`;
  if (kind === 'viga') return rule === 'meia altura' ? 'eixo na meia altura' : `eixo na ${rule}`;
  return `centro em planta na ${rule}`;
}

/** "Coordenadas do eixo (ponto base do projeto)": metros, 3 casas, copiar "X; Y; Z". */
export function AxisCoordinatesSection({ state }: { state: AxisState }) {
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => {
    if (copied === null) return;
    const t = window.setTimeout(() => { setCopied(null); }, 2000);
    return () => { window.clearTimeout(t); };
  }, [copied]);

  if (state.status === 'unavailable' || state.status === 'idle') return null;

  const copy = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
    } catch {
      setCopied(null);
    }
  };

  return (
    <section className="model-sec" aria-labelledby="axis-coords">
      <h4 id="axis-coords">Coordenadas do eixo (ponto base do projeto)</h4>
      {state.status === 'loading' && <p className="muted small">Calculando…</p>}
      {state.status === 'error' && (
        <p role="alert" className="error small">
          {state.message}
        </p>
      )}
      {state.status === 'ready' && (
        <>
          <p className="muted small">
            {KIND_TEXT[state.data.kind]} · {ruleText(state.data.kind, state.data.rule)} · em metros
          </p>
          <table className="axis-table" aria-label="Coordenadas do eixo">
            <thead>
              <tr>
                <th scope="col">{state.data.kind === 'viga' ? 'Ponto' : ''}</th>
                <th scope="col">X</th>
                <th scope="col">Y</th>
                <th scope="col">Z</th>
                <th scope="col">
                  <span className="sr-only">Copiar</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {state.data.rows.map((row) => {
                const text = copyText(row.xyz);
                const name = state.data.kind === 'viga' ? row.label : KIND_TEXT[state.data.kind];
                return (
                  <tr key={row.label}>
                    <th scope="row">{state.data.kind === 'viga' ? row.label : ''}</th>
                    {row.xyz.map((v, i) => (
                      <td key={['x', 'y', 'z'][i]}>{formatMeters(v)}</td>
                    ))}
                    <td>
                      <button
                        type="button"
                        className="secondary btn-sm"
                        aria-label={`Copiar ${name}: ${text}`}
                        onClick={() => { void copy(row.label, text); }}
                      >
                        {copied === row.label ? 'Copiado' : 'Copiar'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {state.data.noReference && (
            <p className="hint">O modelo não informa o ponto base do projeto: valores relativos à origem do arquivo.</p>
          )}
        </>
      )}
    </section>
  );
}
