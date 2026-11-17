import type { FilterField } from '../../api/filters';
import { FieldList } from '../filtro/FieldPicker';
import { CATEGORY_FIELD, NOT_COLORABLE, sameRef, STATUS_FIELD, type ColoringChoice } from './coloringModel';

interface Props {
  fields: readonly FilterField[];
  choice: ColoringChoice | null;
  onChoose: (choice: ColoringChoice) => void;
  /** "Editar cores": abre a janela de esquemas de cores (regras por filtro). */
  onEditColors?: () => void;
}

const isRangeable = (f: FilterField | undefined) => f?.type === 'number' || f?.type === 'date';

/**
 * Popover "Colorir": Status e Categoria fixos no topo e a busca em todos os campos (a
 * mesma lista do "Selecionar parâmetro"). Escolher um campo pinta cada valor com uma cor;
 * "Cor por gama" (números e datas) pinta por faixas.
 */
export function ColorPopover({ fields, choice, onChoose, onEditColors }: Props) {
  const current = choice?.kind === 'field' ? choice : null;
  const currentField = current ? fields.find((f) => sameRef(f, current.field)) : undefined;
  const byRange = current?.mode === 'range';
  const colorable = fields.filter(
    (f) => f.type !== 'bool' && !NOT_COLORABLE.has(`${f.source}:${f.key}`) && !sameRef(f, STATUS_FIELD) && !sameRef(f, CATEGORY_FIELD),
  );
  const pick = (f: FilterField | { source: FilterField['source']; key: string }, range: boolean) => {
    onChoose({ kind: 'field', field: { source: f.source, key: f.key }, mode: range ? 'range' : 'distinct' });
  };
  const fixed = [
    { label: 'Status', field: STATUS_FIELD },
    { label: 'Categoria', field: CATEGORY_FIELD },
  ];

  return (
    <div className="color-pop" role="dialog" aria-label="Colorir">
      <div className="model-sec">
        <h4 id="color-by">Colorir por</h4>
        <div className="seg" role="group" aria-labelledby="color-by">
          {fixed.map((x) => (
            <button
              key={x.label}
              type="button"
              aria-pressed={current !== null && sameRef(current.field, x.field)}
              onClick={() => { pick(x.field, false); }}
            >
              {x.label}
            </button>
          ))}
        </div>
        {choice?.kind === 'scheme' && <p className="hint">Usando o esquema de cores "{choice.name}".</p>}
        {current && currentField && !fixed.some((x) => sameRef(x.field, current.field)) && (
          <p className="hint" role="status">
            Colorindo por <b>{currentField.name}</b>
            {byRange ? ' (por gama)' : ''}.
          </p>
        )}
        <label className="check" title="Faixas de valores, do menor ao maior (números e datas)">
          <input
            type="checkbox"
            checked={byRange}
            disabled={!isRangeable(currentField)}
            onChange={(e) => { if (current) pick(current.field, e.target.checked); }}
          />
          <span>Cor por gama</span>
        </label>
        <FieldList fields={colorable} onPick={(f) => { pick(f, byRange && isRangeable(f)); }} />
      </div>
      {onEditColors && (
        <div className="model-sec color-pop__more">
          <button type="button" className="ghost btn-sm" onClick={onEditColors}>
            Editar cores
          </button>
          <span className="hint">Esquemas com regras por filtro</span>
        </div>
      )}
    </div>
  );
}
