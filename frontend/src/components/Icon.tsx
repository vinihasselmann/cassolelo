/**
 * Ícones da interface: traço único de 1,75 px, cantos arredondados, cor do texto.
 * Substituem glifos de texto (‹ › ▾ ▸ ×) que mudavam de forma conforme a fonte.
 * Sempre decorativos: o nome acessível fica no botão ou link.
 */
export type IconName = 'close' | 'chevron-down' | 'chevron-up' | 'chevron-left' | 'chevron-right' | 'search';

const PATHS: Record<IconName, string> = {
  close: 'M4 4l8 8M12 4l-8 8',
  'chevron-down': 'M4 6l4 4 4-4',
  'chevron-up': 'M4 10l4-4 4 4',
  'chevron-left': 'M10 4L6 8l4 4',
  'chevron-right': 'M6 4l4 4-4 4',
  search: 'M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9M10.3 10.3L13.5 13.5',
};

export function Icon({ name, size = 14 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" focusable="false">
      <path d={PATHS[name]} stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
