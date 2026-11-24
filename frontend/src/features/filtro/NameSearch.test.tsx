import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { MarkPieces, PieceType } from '../../api/versions';
import { normalizeName } from '../../lib/normalizeName';
import { FilterResultList } from './FilterResultList';

/** Lupa da lista de marcas (2026-11-24): busca a peça pelo nome, junto com o filtro Tipo. */

const mk = (id: number, code: string, type: PieceType): MarkPieces => ({
  mark_id: id,
  code,
  category: type === 'pilar' ? 'Pilares estruturais' : 'Quadro estrutural',
  count: 1,
  dbids: [id * 10],
  piece_type: type,
});

const MARKS = [mk(1, 'PP001', 'pilar'), mk(2, 'PP012', 'pilar'), mk(3, 'VA001', 'quadro'), mk(4, 'VA012', 'quadro')];

function renderList(onSelectAll = vi.fn()) {
  render(
    <FilterResultList
      marks={MARKS}
      evaluation={undefined}
      filtered={false}
      loading={false}
      error={null}
      selectedMarkIds={new Set()}
      onPickMark={vi.fn()}
      onPickPieces={vi.fn()}
      onSelectAll={onSelectAll}
    />,
  );
  return onSelectAll;
}

const listCodes = () =>
  within(screen.getByRole('list')).getAllByRole('button').map((b) => b.querySelector('.mark-item__code')?.textContent);

describe('lupa: busca por nome', () => {
  it('normaliza caixa e acento', () => {
    expect(normalizeName(' Pré-Laje ')).toBe('pre-laje');
  });

  it('abre o campo com foco, filtra sem caixa e não mexe na seleção do 3D', async () => {
    const onSelectAll = renderList();
    const user = userEvent.setup();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Buscar peça pelo nome' }));
    const box = screen.getByRole('searchbox', { name: 'Nome da peça' });
    expect(box).toHaveFocus();
    await user.type(box, '012');
    expect(listCodes()).toEqual(['PP012', 'VA012']);
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('(2)');
    await user.clear(box);
    await user.type(box, 'va0');
    expect(listCodes()).toEqual(['VA001', 'VA012']);
    expect(onSelectAll).not.toHaveBeenCalled();
  });

  it('soma com o filtro Tipo', async () => {
    renderList();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Tipo/ }));
    await user.click(screen.getByRole('checkbox', { name: /Pilar/ }));
    await user.click(screen.getByRole('button', { name: 'Buscar peça pelo nome' }));
    await user.type(screen.getByRole('searchbox'), '012');
    expect(listCodes()).toEqual(['PP012']);
  });

  it('sem resultado avisa; Esc fecha e limpa a busca', async () => {
    renderList();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Buscar peça pelo nome' }));
    await user.type(screen.getByRole('searchbox'), 'XX9');
    expect(screen.getByText('Nenhuma peça com "XX9" no nome.')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(listCodes()).toHaveLength(4);
  });
});
