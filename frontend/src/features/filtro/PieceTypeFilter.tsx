import { useEffect, useRef, useState } from 'react';

import { PIECE_TYPES, PIECE_TYPE_LABELS, type PieceType } from '../../api/versions';

const num = (n: number) => n.toLocaleString('pt-BR');

interface Props {
  /** marcas de cada tipo na lista (só os tipos com marcas aparecem) */
  counts: ReadonlyMap<PieceType, number>;
  selected: ReadonlySet<PieceType>;
  onChange: (next: Set<PieceType>) => void;
}

/**
 * "Tipo" no cabeçalho da lista (2026-11-18): caixas de seleção por tipo de peça. Marcar um
 * tipo deixa na lista só as marcas dele e as seleciona no 3D (para preencher parâmetros
 * em todas de uma vez). "Marcar tudo" (no lugar do antigo "Selecionar todas") seleciona
 * todas as marcas da lista. Laje = "Laje", LA, LAA, LP ou LM no nome, tipo ou marca.
 */
export function PieceTypeFilter({ counts, selected, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  const available = PIECE_TYPES.filter((t) => (counts.get(t) ?? 0) > 0);
  const all = available.length > 0 && available.every((t) => selected.has(t));
  const some = !all && available.some((t) => selected.has(t));
  const allBox = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (allBox.current) allBox.current.indeterminate = some;
  }, [some, open]);
  if (available.length === 0) return null;
  const total = available.reduce((n, t) => n + (counts.get(t) ?? 0), 0);
  const label =
    selected.size === 0
      ? 'Tipo'
      : all
        ? 'Tipo: todos'
        : selected.size === 1
        ? PIECE_TYPE_LABELS[[...selected][0] as PieceType]
        : `Tipo (${String(selected.size)})`;
  const toggle = (t: PieceType, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(t);
    else next.delete(t);
    onChange(next);
  };

  return (
    <span className="type-filter" ref={box}>
      <button
        type="button"
        className={selected.size > 0 ? 'link type-filter__btn type-filter__btn--on' : 'link type-filter__btn'}
        aria-expanded={open}
        aria-haspopup="true"
        title="Filtrar a lista por tipo de peça e selecionar no 3D"
        onClick={() => { setOpen((o) => !o); }}
      >
        {label} ▾
      </button>
      {open && (
        <div className="type-filter__menu" role="group" aria-label="Tipo de peça">
          {/* no lugar do antigo "Selecionar todas": todas as marcas da lista */}
          <label className="check type-filter__all">
            <input
              ref={allBox}
              type="checkbox"
              checked={all}
              onChange={(e) => { onChange(e.target.checked ? new Set(available) : new Set()); }}
            />
            Marcar tudo <span className="muted">({num(total)})</span>
          </label>
          {available.map((t) => (
            <label key={t} className="check">
              <input
                type="checkbox"
                checked={selected.has(t)}
                onChange={(e) => { toggle(t, e.target.checked); }}
              />
              {PIECE_TYPE_LABELS[t]} <span className="muted">({num(counts.get(t) ?? 0)})</span>
            </label>
          ))}
          {selected.size > 0 && (
            <button type="button" className="link" onClick={() => { onChange(new Set()); }}>
              Limpar
            </button>
          )}
        </div>
      )}
    </span>
  );
}
