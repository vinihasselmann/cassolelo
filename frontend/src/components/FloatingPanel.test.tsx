import { fireEvent, render, screen } from '@testing-library/react';

import { popoverPlacement } from '../features/filtro/popoverPlacement';
import { FloatingPanel } from './FloatingPanel';

const KEY = 'cassol-elo:painel:barra:7';

function renderPanel(storageKey: string | undefined = 'barra:7') {
  return render(
    <div style={{ position: 'relative' }}>
      <FloatingPanel storageKey={storageKey} label="a barra">
        <button type="button">Ação</button>
      </FloatingPanel>
    </div>,
  );
}

const grip = () => screen.getByRole('button', { name: 'Mover a barra' });
const panel = () => grip().parentElement as HTMLElement;

describe('FloatingPanel', () => {
  afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

  it('começa na posição padrão (CSS: topo, centralizado) e mostra o conteúdo', () => {
    renderPanel();
    expect(panel()).toHaveAttribute('data-moved', 'false');
    expect(panel().style.left).toBe('');
    expect(screen.getByRole('button', { name: 'Ação' })).toBeInTheDocument();
  });

  it('teclado na alça: setas movem 10 px, Shift+setas 50 px; a posição fica gravada', () => {
    renderPanel();
    fireEvent.keyDown(grip(), { key: 'ArrowRight' });
    fireEvent.keyDown(grip(), { key: 'ArrowDown' });
    expect(panel().style.left).toBe('10px');
    expect(panel().style.top).toBe('10px');
    fireEvent.keyDown(grip(), { key: 'ArrowRight', shiftKey: true });
    expect(panel().style.left).toBe('60px');
    expect(JSON.parse(localStorage.getItem(KEY) ?? 'null')).toEqual({ x: 60, y: 10 });
    fireEvent.keyDown(grip(), { key: 'Enter' }); // outras teclas não movem
    expect(panel().style.left).toBe('60px');
  });

  it('posição lembrada ao reabrir; duplo clique na alça volta ao padrão e esquece', () => {
    localStorage.setItem(KEY, JSON.stringify({ x: 40, y: 30 }));
    const { unmount } = renderPanel();
    expect(panel()).toHaveAttribute('data-moved', 'true');
    expect(panel().style.left).toBe('40px');
    fireEvent.doubleClick(grip());
    expect(panel()).toHaveAttribute('data-moved', 'false');
    expect(localStorage.getItem(KEY)).toBeNull();
    unmount();
  });

  it('posição é por usuário: outra chave não herda a posição', () => {
    localStorage.setItem(KEY, JSON.stringify({ x: 40, y: 30 }));
    renderPanel('barra:8');
    expect(panel()).toHaveAttribute('data-moved', 'false');
  });

  it('sem armazenamento (aba privada) usa a posição padrão e continua funcionando', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloqueado'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloqueado'); });
    renderPanel();
    expect(panel()).toHaveAttribute('data-moved', 'false');
    fireEvent.keyDown(grip(), { key: 'ArrowLeft' });
    expect(panel()).toHaveAttribute('data-moved', 'true');
  });
});

describe('popoverPlacement', () => {
  const rect = (left: number, top: number, width: number, height: number) =>
    ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
  const area = rect(0, 0, 800, 600);

  it('barra no topo: abre para baixo, centralizado e com a altura que cabe embaixo', () => {
    const p = popoverPlacement('filter', rect(200, 12, 400, 32), area);
    expect(p.top).toBe('calc(100% + 6px)');
    expect(p.bottom).toBeUndefined();
    expect(p.width).toBe(620);
    expect(p.left).toBe(-110); // centro da barra
    expect(p.maxHeight).toBe(600 - 44 - 6 - 8);
  });

  it('barra embaixo: abre para cima', () => {
    const p = popoverPlacement('color', rect(200, 540, 400, 32), area);
    expect(p.bottom).toBe('calc(100% + 6px)');
    expect(p.top).toBeUndefined();
  });

  it('barra encostada na borda: o popover não sai da área do 3D', () => {
    const p = popoverPlacement('filter', rect(700, 12, 100, 32), area);
    const left = 700 + Number(p.left);
    expect(left + Number(p.width)).toBeLessThanOrEqual(800 - 8);
    expect(left).toBeGreaterThanOrEqual(8);
  });

  it('área estreita: a largura encolhe para caber', () => {
    expect(popoverPlacement('filter', rect(0, 12, 300, 32), rect(0, 0, 400, 600)).width).toBe(384);
  });
});
