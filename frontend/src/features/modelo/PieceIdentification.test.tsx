import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ElementDetail, MarkPieces } from '../../api/versions';
import { PieceIdentification } from './PiecePanel';

/** Painel "Seleção": de onde veio o nome da peça e os parâmetros secundários (2026-11-18). */

const el = (extra: Partial<ElementDetail>): ElementDetail => ({
  dbid: 11,
  external_id: 'ext-11',
  name: 'Pilar [11]',
  category: 'Pilares estruturais',
  mark_raw: 'PP001',
  mark: null,
  groups: [],
  ...extra,
});
const mark: MarkPieces = { mark_id: 1, code: 'PP001', category: 'Pilares estruturais', count: 4, dbids: [] };

describe('identificação da peça no painel Seleção', () => {
  it('mostra o parâmetro de origem e os secundários', () => {
    render(
      <PieceIdentification
        element={el({ mark_source: 'Nome da montagem', mark_alt: [{ name: 'Marca', value: 'P01' }] })}
        mark={mark}
      />,
    );
    const dl = screen.getByLabelText('Identificação da peça');
    expect(dl).toHaveTextContent('Nome da montagemPP001 nome da peça');
    expect(dl).toHaveTextContent('MarcaP01');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('avisa quando as peças da marca divergem num secundário', () => {
    render(
      <PieceIdentification
        element={el({ mark_source: 'Nome da montagem', mark_alt: [] })}
        mark={{ ...mark, secondary: [{ name: 'Marca', values: ['P01', 'P03'], pieces: 4 }] }}
      />,
    );
    expect(screen.getByRole('note')).toHaveTextContent('valores diferentes em Marca: P01, P03');
  });

  it('versão sem origem gravada: não mostra nada', () => {
    const { container } = render(<PieceIdentification element={el({})} mark={mark} />);
    expect(container).toBeEmptyDOMElement();
  });
});
