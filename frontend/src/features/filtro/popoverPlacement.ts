import type { CSSProperties } from 'react';

export type Pop = 'filter' | 'color';

const GAP = 6; // distância entre a barra e o popover
const EDGE = 8; // folga até a borda do 3D
const WIDTH: Record<Pop, number> = { filter: 620, color: 340 };

/**
 * Onde abrir o popover: para baixo ou para cima, para onde houver mais espaço, sem sair do 3D.
 * Coordenadas relativas ao painel flutuante (o bloco de contenção do popover).
 */
export function popoverPlacement(pop: Pop, panel: DOMRect, area: DOMRect): CSSProperties {
  const below = area.bottom - panel.bottom - GAP - EDGE;
  const above = panel.top - area.top - GAP - EDGE;
  const down = below >= above;
  const width = Math.max(0, Math.min(WIDTH[pop], area.width - 2 * EDGE));
  const centered = panel.left + (panel.width - width) / 2;
  const left = Math.min(Math.max(centered, area.left + EDGE), area.right - EDGE - width) - panel.left;
  const maxHeight = Math.max(120, down ? below : above);
  return down
    ? { left, width, maxHeight, top: `calc(100% + ${String(GAP)}px)` }
    : { left, width, maxHeight, bottom: `calc(100% + ${String(GAP)}px)` };
}
