import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { MarkPieces, PieceType } from '../../api/versions';
import { FilterResultList } from './FilterResultList';

/** Filtro "Tipo" da lista (2026-11-18): marcar um tipo filtra a lista e seleciona no 3D. */

const mk = (id: number, code: string, type: PieceType): MarkPieces => ({
  mark_id: id,
  code,
  category: type === 'pilar' ? 'Pilares estruturais' : 'Quadro estrutural',
  count: 1,
  dbids: [id * 10],
  piece_type: type,
});

const MARKS = [
  mk(1, 'PP001', 'pilar'),
  mk(2, 'PP002', 'pilar'),
  mk(3, 'VA001', 'quadro'),
  mk(4, 'LA002', 'laje'),
  mk(5, 'EC001', 'escada'),
];

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
  within(screen.getByRole('list')).getAllByRole('button').map((b) => b.textContent ?? '');

describe('filtro Tipo da lista', () => {
  it('fica ao lado do título (sem "Selecionar todas") e só mostra os tipos que existem, com contagem', async () => {
    renderList();
    const head = screen.getByRole('heading', { level: 3 }).parentElement as HTMLElement;
    const buttons = within(head).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent);
    expect(buttons).toEqual(['Buscar peça pelo nome', 'Tipo ▾']);
    await userEvent.setup().click(screen.getByRole('button', { name: /Tipo/ }));
    const menu = screen.getByRole('group', { name: 'Tipo de peça' });
    expect(within(menu).getAllByRole('checkbox').map((c) => c.parentElement?.textContent)).toEqual([
      'Marcar tudo (5)',
      'Pilar (2)',
      'Quadro estrutural (1)',
      'Laje (1)',
      'Escada (1)',
    ]);
  });

  it('marcar Pilar filtra a lista e seleciona todos os pilares; Escada soma; desmarcar tudo limpa', async () => {
    const onSelectAll = renderList();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Tipo/ }));
    await user.click(screen.getByRole('checkbox', { name: /Pilar/ }));
    expect(onSelectAll).toHaveBeenLastCalledWith([1, 2]);
    expect(listCodes().every((t) => t.includes('PP00'))).toBe(true);
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('(2)');
    expect(screen.getByRole('button', { name: 'Pilar ▾' })).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: /Escada/ }));
    expect(onSelectAll).toHaveBeenLastCalledWith([5, 1, 2]); // na ordem da lista (EC001, PP001, PP002)
    expect(listCodes()).toHaveLength(3);

    await user.click(screen.getByRole('button', { name: 'Limpar' }));
    expect(onSelectAll).toHaveBeenLastCalledWith([]);
    expect(listCodes()).toHaveLength(5);
  });

  it('Marcar tudo seleciona todas as marcas; parcial com alguns tipos; desmarcar limpa', async () => {
    const onSelectAll = renderList();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Tipo/ }));
    const all = screen.getByRole('checkbox', { name: /Marcar tudo/ });
    await user.click(all);
    expect(onSelectAll).toHaveBeenLastCalledWith([5, 4, 1, 2, 3]); // ordem da lista
    expect(all).toBeChecked();
    expect(screen.getByRole('button', { name: 'Tipo: todos ▾' })).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /Laje/ }));
    expect((all as HTMLInputElement).indeterminate).toBe(true);
    await user.click(all); // parcial → marca tudo de novo
    expect(all).toBeChecked();
    await user.click(all);
    expect(onSelectAll).toHaveBeenLastCalledWith([]);
    expect(listCodes()).toHaveLength(5);
  });

  it('Esc fecha o menu', async () => {
    renderList();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Tipo/ }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('group', { name: 'Tipo de peça' })).not.toBeInTheDocument();
  });
});
