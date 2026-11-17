import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';

export interface Point {
  x: number;
  y: number;
}

interface Props {
  /**
   * Chave da posição lembrada (por usuário e por painel), ex.: `viewer-bar:3`.
   * Sem chave, o painel não lembra a posição.
   */
  storageKey?: string | undefined;
  /** Nome do que a alça move, para o leitor de tela (ex.: "a barra do visualizador"). */
  label: string;
  /** Avisado quando o usuário começa a mover (ex.: fechar um popover aberto). */
  onMoveStart?: () => void;
  className?: string;
  /** Posição padrão (antes de mover / depois do duplo clique). */
  placement?: 'top-center' | 'top-right';
  /**
   * Conteúdo. Como função, recebe a alça para colocá-la onde quiser (ex.: no título);
   * senão a alça fica à esquerda do conteúdo.
   */
  children: ReactNode | ((grip: ReactNode) => ReactNode);
}

const STEP = 10;
const BIG_STEP = 50;
const PREFIX = 'cassol-elo:painel:';

function load(key: string | undefined): Point | null {
  if (!key) return null;
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<Point>;
    return typeof v.x === 'number' && typeof v.y === 'number' ? { x: v.x, y: v.y } : null;
  } catch {
    return null; // sem armazenamento (aba privada etc.): posição padrão
  }
}

function save(key: string | undefined, pos: Point | null): void {
  if (!key) return;
  try {
    if (pos) window.localStorage.setItem(PREFIX + key, JSON.stringify(pos));
    else window.localStorage.removeItem(PREFIX + key);
  } catch {
    // sem armazenamento: vale só nesta visita
  }
}

/**
 * Painel flutuante sobre uma área posicionada (o pai precisa de `position: relative`).
 * - Posição padrão: topo, centralizado (CSS). Movido, guarda {x, y} em px a partir do canto do pai.
 * - Alça: arrasta com mouse ou toque (pointer events), setas movem 10 px e Shift+setas 50 px,
 *   duplo clique volta ao padrão.
 * - Nunca sai do pai: limita às bordas ao mover e quando o pai ou o painel mudam de tamanho.
 * - Ocupa só o próprio tamanho: cliques fora dele chegam ao que está embaixo (o 3D).
 */
export function FloatingPanel({ storageKey, label, onMoveStart, className = '', placement = 'top-center', children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<Point | null>(() => load(storageKey));
  const drag = useRef<{ id: number; dx: number; dy: number } | null>(null);
  const latest = useRef(pos); // última posição (para gravar ao soltar)
  latest.current = pos;

  /** Limita ao pai. Sem medidas (pai sem tamanho, ex.: testes sem layout), devolve como está. */
  const clamp = useCallback((p: Point): Point => {
    const el = ref.current;
    const parent = el?.parentElement;
    if (!el || !parent || parent.clientWidth === 0 || parent.clientHeight === 0) return p;
    const maxX = Math.max(0, parent.clientWidth - el.offsetWidth);
    const maxY = Math.max(0, parent.clientHeight - el.offsetHeight);
    return { x: Math.round(Math.min(Math.max(0, p.x), maxX)), y: Math.round(Math.min(Math.max(0, p.y), maxY)) };
  }, []);

  /** Posição atual em px (também quando ainda está na padrão, centralizada pelo CSS). */
  const current = useCallback((): Point => {
    const el = ref.current;
    const parent = el?.parentElement;
    if (!el || !parent) return { x: 0, y: 0 };
    const a = el.getBoundingClientRect();
    const b = parent.getBoundingClientRect();
    return { x: a.left - b.left, y: a.top - b.top };
  }, []);

  // outro usuário (ou outro painel): outra posição lembrada
  useEffect(() => { setPos(load(storageKey)); }, [storageKey]);

  // pai ou painel mudaram de tamanho (janela, painéis laterais, barra que quebra linha): continua dentro
  useEffect(() => {
    const el = ref.current;
    const parent = el?.parentElement;
    if (!el || !parent) return undefined;
    const keepInside = () => {
      setPos((p) => {
        if (!p) return p;
        const c = clamp(p);
        return c.x === p.x && c.y === p.y ? p : c;
      });
    };
    window.addEventListener('resize', keepInside);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(keepInside);
    observer?.observe(parent);
    observer?.observe(el);
    return () => {
      window.removeEventListener('resize', keepInside);
      observer?.disconnect();
    };
  }, [clamp]);

  const moveTo = (p: Point, persist: boolean) => {
    const c = clamp(p);
    latest.current = c;
    setPos(c);
    if (persist) save(storageKey, c);
  };

  const reset = () => {
    setPos(null);
    save(storageKey, null);
  };

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const el = ref.current;
    if (!el) return;
    e.preventDefault();
    const at = current();
    const rect = el.getBoundingClientRect();
    drag.current = { id: e.pointerId, dx: e.clientX - rect.left, dy: e.clientY - rect.top };
    e.currentTarget.setPointerCapture(e.pointerId);
    latest.current = clamp(at);
    setPos(latest.current); // sai do centralizado pelo CSS sem pular
    onMoveStart?.();
  };

  const onPointerMove = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    const parent = ref.current?.parentElement;
    if (!d || d.id !== e.pointerId || !parent) return;
    const b = parent.getBoundingClientRect();
    moveTo({ x: e.clientX - b.left - d.dx, y: e.clientY - b.top - d.dy }, false);
  };

  const endDrag = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    save(storageKey, latest.current);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const step = e.shiftKey ? BIG_STEP : STEP;
    const delta: Record<string, Point> = {
      ArrowLeft: { x: -step, y: 0 },
      ArrowRight: { x: step, y: 0 },
      ArrowUp: { x: 0, y: -step },
      ArrowDown: { x: 0, y: step },
    };
    const d = delta[e.key];
    if (!d) return;
    e.preventDefault();
    if (!pos) onMoveStart?.();
    const at = pos ?? current();
    moveTo({ x: at.x + d.x, y: at.y + d.y }, true);
  };

  const grip = (
    <button
      type="button"
      className="floating__grip"
      aria-label={`Mover ${label}`}
      title="Arraste para mover · setas: 10 px (Shift: 50 px) · duplo clique: volta ao lugar"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={reset}
      onKeyDown={onKeyDown}
    >
      <svg className="icon" viewBox="0 0 10 16" width="8" height="14" aria-hidden="true" focusable="false">
        {[3, 8, 13].map((cy) => (
          <g key={cy}>
            <circle cx="3" cy={cy} r="1.25" fill="currentColor" />
            <circle cx="7" cy={cy} r="1.25" fill="currentColor" />
          </g>
        ))}
      </svg>
    </button>
  );

  return (
    <div
      ref={ref}
      className={`floating floating--${placement}${pos ? ' floating--moved' : ''} ${className}`.trim()}
      style={pos ? { left: pos.x, top: pos.y } : undefined}
      data-moved={pos ? 'true' : 'false'}
    >
      {typeof children === 'function' ? children(grip) : (
        <>
          {grip}
          {children}
        </>
      )}
    </div>
  );
}
