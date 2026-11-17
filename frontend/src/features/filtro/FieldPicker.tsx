import { useMemo, useState } from 'react';

import type { FilterField, FilterOp } from '../../api/filters';
import { Modal } from '../../components/Modal';
import {
  DEFAULT_MODE,
  defaultOp,
  defaultValue,
  FIELD_GROUPS,
  fieldGroup,
  isComplete,
  matchesField,
  TYPE_LABELS,
  type ActiveRule,
} from './filterModel';
import { OpSelect, ValueInput } from './RuleInputs';

const num = (n: number) => n.toLocaleString('pt-BR');

interface ListProps {
  fields: readonly FilterField[];
  onPick: (field: FilterField) => void;
  autoFocus?: boolean;
}

/** Lista pesquisável de campos, agrupada (Fábrica, Montagem, Identificação, Dimensões, Outros). */
export function FieldList({ fields, onPick }: ListProps) {
  const [q, setQ] = useState('');
  const groups = useMemo(() => {
    const found = fields.filter((f) => matchesField(f, q));
    return FIELD_GROUPS.map((g) => ({ name: g, items: found.filter((f) => fieldGroup(f) === g) })).filter((g) => g.items.length);
  }, [fields, q]);
  return (
    <div className="field-list">
      <input
        type="search"
        aria-label="Buscar parâmetro"
        placeholder="Buscar parâmetro…"
        value={q}
        onChange={(e) => { setQ(e.target.value); }}
      />
      {groups.length === 0 && <p className="hint">Nenhum parâmetro encontrado.</p>}
      <div className="field-list__scroll">
        {groups.map((g) => (
          <section key={g.name} aria-label={g.name}>
            <h4>{g.name}</h4>
            <ul>
              {g.items.map((f) => (
                <li key={`${f.source}:${f.key}`}>
                  <button type="button" className="list-item field-item" onClick={() => { onPick(f); }}>
                    <span className="field-item__name">{f.name}</span>
                    {f.source === 'model' && f.group && <span className="field-item__group">{f.group}</span>}
                    <span className="field-item__meta">
                      {TYPE_LABELS[f.type]}
                      {f.type !== 'bool' && ` · ${num(f.distinct_values)} ${f.distinct_values === 1 ? 'valor' : 'valores'}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

interface Props {
  versionId: number;
  fields: readonly FilterField[];
  onAdd: (rule: ActiveRule) => void;
  onClose: () => void;
}

/** "+ Adicionar filtro": escolher o parâmetro e, num passo curto, operador e valor. */
export function FieldPicker({ versionId, fields, onAdd, onClose }: Props) {
  const [field, setField] = useState<FilterField | null>(null);
  const [op, setOp] = useState<FilterOp>('eq');
  const [value, setValue] = useState<unknown>(undefined);

  const pick = (f: FilterField) => {
    const first = defaultOp(f.type);
    setField(f);
    setOp(first);
    setValue(defaultValue(f.type, first));
  };
  const rule: ActiveRule | null = field ? { field: { source: field.source, key: field.key }, op, value, mode: DEFAULT_MODE } : null;

  return (
    <Modal title={field ? field.name : 'Selecionar parâmetro'} onClose={onClose} wide>
      {!field ? (
        <>
          <FieldList fields={fields} onPick={pick} />
          <div className="modal__actions">
            <button type="button" className="secondary" onClick={onClose}>Cancelar</button>
          </div>
        </>
      ) : (
        <form
          className="rule-step"
          onSubmit={(e) => {
            e.preventDefault();
            if (rule && isComplete(rule)) onAdd(rule);
          }}
        >
          <p className="hint">
            {field.group ?? 'Sistema'} · {TYPE_LABELS[field.type]}
          </p>
          <div className="rule-step__row">
            <OpSelect field={field} op={op} onChange={(o, v) => { setOp(o); setValue(v); }} />
            <ValueInput versionId={versionId} field={field} op={op} value={value} onChange={setValue} />
          </div>
          <div className="modal__actions">
            <button type="button" className="secondary" onClick={() => { setField(null); }}>Voltar</button>
            <button type="submit" disabled={!rule || !isComplete(rule)}>Adicionar</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
