import type { ReactNode } from 'react';

import type { ViewerFactory } from './ViewerAdapter';
import { ViewerFactoryContext } from './viewerContext';

/** Troca a implementação do visualizador (os testes usam um adapter falso). */
export function ViewerFactoryProvider({
  factory,
  children,
}: {
  factory: ViewerFactory;
  children: ReactNode;
}) {
  return <ViewerFactoryContext.Provider value={factory}>{children}</ViewerFactoryContext.Provider>;
}
