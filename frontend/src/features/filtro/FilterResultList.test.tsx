import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MarkPieces } from '../../api/versions';
import { FilterResultList } from './FilterResultList';
import { markAlt, versionOrigin } from './markOrigin';

/** Origem da marca e parâmetros secundários na coluna esquerda (2026-11-18). */

const NOME = 'Nome da montagem';
const mk = (id: number, code: string, count: number, extra: Partial<MarkPieces> = {}): MarkPieces => ({
  mark_id: id,
  code,
  category: 'Pilares estruturais',
  count,
  dbids: [],
  ...extra,
});

const MIXED: MarkPieces[] = [
  mk(1, 'PP001', 8, {
    sources: [{ name: NOME, pieces: 8 }],
    secondary: [{ name: 'Marca', values: ['P01'], pieces: 8 }],
  }),
  mk(2, 'PP002', 2, { sources: [{ name: 'Marca', pieces: 2 }] }),
  mk(3, 'PP003', 4, {
    sources: [{ name: NOME, pieces: 4 }],
    secondary: [{ name: 'Marca', values: ['P01', 'P03'], pieces: 3 }],
  }),
];

function renderList(marks: MarkPieces[]) {
  return render(
    <FilterResultList
      marks={marks}
      evaluation={undefined}
      filtered={false}
      loading={false}
      error={null}
      selectedMarkIds={new Set()}
      onPickMark={vi.fn()}
      onPickPieces={vi.fn()}
      onSelectAll={vi.fn()}
    />,
  );
}

const row = (code: string) => screen.getByText(code).closest('button') as HTMLElement;

describe('origem da marca na coluna esquerda', () => {
  afterEach(() => {
    localStorage.clear();
  });

  it('origem principal e divisão', () => {
    expect(versionOrigin(MIXED)).toEqual({
      main: NOME,
      split: [
        { name: NOME, pieces: 12 },
        { name: 'Marca', pieces: 2 },
      ],
    });
    expect(versionOrigin([mk(9, 'X', 1)])).toEqual({ main: null, split: [] });
    const alt = markAlt(MIXED[2] as MarkPieces, NOME);
    expect(alt.via).toEqual([]);
    expect(alt.secondary[0]).toMatchObject({ divergent: true, partial: true });
  });

  it('título usa o parâmetro quando todas as peças vêm dele', () => {
    renderList([mk(1, 'PP001', 8, { sources: [{ name: NOME, pieces: 8 }] })]);
    expect(screen.getByRole('heading', { name: 'Nome da montagem (1)' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Parâmetros secundários')).not.toBeInTheDocument();
  });

  it('sem origem gravada, o título continua "Marcas"', () => {
    renderList([mk(1, 'PP001', 8)]);
    expect(screen.getByRole('heading', { name: 'Marcas (1)' })).toBeInTheDocument();
  });

  it('origem mista: "Marcas", a divisão, "via" e os secundários com aviso', () => {
    renderList(MIXED);
    expect(screen.getByRole('heading', { name: 'Marcas (3)' })).toBeInTheDocument();
    expect(screen.getByText('Origem: Nome da montagem 12 · Marca 2 peças')).toBeInTheDocument();

    expect(within(row('PP001')).getByText('Marca: P01')).toBeInTheDocument();
    expect(within(row('PP002')).getByText('via Marca')).toBeInTheDocument();
    const warn = within(row('PP003')).getByText(/Marca: P01, P03/);
    expect(warn).toHaveClass('mark-item__warn');
    expect(warn).toHaveTextContent('(3 de 4)');
    expect(warn).toHaveAttribute('title', expect.stringContaining('Vale Nome da montagem'));
  });

  it('"Parâmetros secundários" desliga a 2ª linha e fica guardado (o "via" fica)', async () => {
    const view = renderList(MIXED);
    const box = screen.getByLabelText('Parâmetros secundários');
    expect(box).toBeChecked(); // ligado por padrão
    await userEvent.click(box);
    expect(within(row('PP001')).queryByText('Marca: P01')).not.toBeInTheDocument();
    expect(within(row('PP002')).getByText('via Marca')).toBeInTheDocument();
    view.unmount();

    renderList(MIXED);
    expect(screen.getByLabelText('Parâmetros secundários')).not.toBeChecked();
  });
});
