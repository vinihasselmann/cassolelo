import { useEffect, useId, useRef, type ReactNode } from 'react';

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}

/** Janela modal simples: Esc ou clique fora fecha; o foco vai para o primeiro campo. */
export function Modal({ title, onClose, children, wide = false }: Props) {
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // janela dentro de janela: o Esc fecha só a de cima
      const open = document.querySelectorAll('.modal');
      if (open[open.length - 1] === box.current) onClose();
    };
    document.addEventListener('keydown', onKey);
    box.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus();
    return () => { document.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div className="modal-bg" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={box} className={`modal${wide ? ' modal--wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}
