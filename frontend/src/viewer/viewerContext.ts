import { createContext, useContext, useEffect, useState, type RefObject } from 'react';

import { createApsViewer } from './ApsViewerAdapter';
import type { ViewerAdapter, ViewerFactory } from './ViewerAdapter';

export const ViewerFactoryContext = createContext<ViewerFactory>(createApsViewer);

/** Cria o adapter dentro do elemento quando ele monta e o destrói ao desmontar. */
export function useViewerAdapter(container: RefObject<HTMLElement | null>): ViewerAdapter | null {
  const factory = useContext(ViewerFactoryContext);
  const [adapter, setAdapter] = useState<ViewerAdapter | null>(null);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const created = factory(el);
    setAdapter(created);
    return () => {
      created.destroy();
      setAdapter(null);
    };
  }, [factory, container]);

  return adapter;
}
