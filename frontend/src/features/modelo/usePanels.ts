import { useCallback, useEffect, useState } from 'react';

/** Painéis laterais da tela do modelo (esquerdo: marcas e filtros; direito: peça). */
export interface Panels {
  left: boolean;
  right: boolean;
}

const KEY = 'cassol-elo:paineis';
const ALL_OPEN: Panels = { left: true, right: true };

function read(): Panels {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return ALL_OPEN;
    const v = JSON.parse(raw) as Partial<Panels>;
    return { left: v.left !== false, right: v.right !== false };
  } catch {
    return ALL_OPEN; // navegador sem armazenamento (aba privada etc.)
  }
}

/**
 * Mostrar/esconder os painéis laterais, para dar mais espaço ao 3D (útil no tablet).
 * A escolha fica no navegador (conveniência de cada pessoa; não vai para o servidor).
 */
export function usePanels() {
  const [panels, setPanels] = useState<Panels>(read);
  useEffect(() => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(panels));
    } catch {
      // sem armazenamento: vale só nesta visita
    }
  }, [panels]);
  const toggle = useCallback((side: keyof Panels) => {
    setPanels((p) => ({ ...p, [side]: !p[side] }));
  }, []);
  return { panels, toggle };
}
