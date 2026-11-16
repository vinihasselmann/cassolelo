import { useState } from 'react';

import type { FilterField, FilterLogic, FilterMode } from '../../api/filters';
import { Modal } from '../../components/Modal';
import {
  defaultOp,
  defaultValue,
  FIELD_GROUPS,
  fieldGroup,
  isComplete,
  MODE_LABELS,
  sameField,
  type ActiveFilter,
  type ActiveRule,
} from './filterModel';
import { OpSelect, ValueInput } from './RuleInputs';

const fieldId = (f: { source: string; key: string }) => `${f.source}:${f.key}`;
const MODES: FilterMode[] = ['isolate', 'hide', 'highlight'];

interface Props {
  versionId: number;
  fields: readonly FilterField[];
  filter: ActiveFilter;
  onApply: (next: ActiveFilter) => void;
  onClose: () => void;
}

/**
 * "Avançado" → "Editar filtro": linhas [modo] [parâmetro] [operador] [valor] [×], sempre
 * com uma linha vazia no fim, e "todas as regras (E)" / "qualquer regra (OU)".
 * Nada vale até Aplicar; linhas incompletas são descartadas.
 */
export function FilterEditorDialog({ versionId, fields, filter, onApply, onClose }: Props) {
  const [logic, setLogic] = useState<FilterLogic>(filter.logic);
  const [rules, setRules] = useState<ActiveRule[]>(filter.rules);
  const [newMode, setNewMode] = useState<FilterMode>('isolate');
  const byId = new Map(fields.map((f) => [fieldId(f), f]));
  const grouped = FIELD_GROUPS.map((g) => ({ name: g, items: fields.filter((f) => fieldGroup(f) === g) })).filter((g) => g.items.length);

  const update = (i: number, patch: Partial<ActiveRule>) => {
    setRules((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  };
  const setField = (i: number | null, id: string) => {
    const f = byId.get(id);
    if (!f) return;
    const op = defaultOp(f.type);
    const rule: ActiveRule = { field: { source: f.source, key: f.key }, op, value: defaultValue(f.type, op), mode: newMode };
    if (i === null) setRules((prev) => [...prev, rule]);
    else if (!sameField(rules[i]?.field ?? { source: 'system', key: '' }, rule.field)) {
      update(i, { ...rule, mode: rules[i]?.mode ?? newMode }); // outro parâmetro: operador e valor recomeçam
    }
  };

  const fieldSelect = (value: string, onChange: (id: string) => void, label: string) => (
    <select aria-label={label} value={value} onChange={(e) => { onChange(e.target.value); }}>
      <option value="">Escolha o parâmetro…</option>
      {grouped.map((g) => (
        <optgroup key={g.name} label={g.name}>
          {g.items.map((f) => (
            <option key={fieldId(f)} value={fieldId(f)}>
              {f.source === 'model' && f.group ? `${f.name} (${f.group})` : f.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );

  return (
    <Modal title="Editar filtro" onClose={onClose} wide>
      <div className="seg seg--inline" role="radiogroup" aria-label="Combinar regras">
        {(['and', 'or'] as const).map((l) => (
          <button key={l} type="button" role="radio" aria-checked={logic === l} aria-pressed={logic === l} onClick={() => { setLogic(l); }}>
            {l === 'and' ? 'Todas as regras (E)' : 'Qualquer regra (OU)'}
          </button>
        ))}
      </div>
      <p className="hint">
        Isolar mostra só o que bate; Ocultar esconde o que bate em qualquer linha; Destacar deixa o que bate normal e esmaece o resto.
      </p>
      <ol className="rule-rows" aria-label="Regras">
        {rules.map((r, i) => {
          const f = byId.get(fieldId(r.field));
          const n = String(i + 1);
          return (
            <li key={i} className={`rule-row${isComplete(r) ? '' : ' rule-row--incomplete'}`}>
              <select aria-label={`Modo da regra ${n}`} value={r.mode} onChange={(e) => { update(i, { mode: e.target.value as FilterMode }); }}>
                {MODES.map((m) => <option key={m} value={m}>{MODE_LABELS[m]}</option>)}
              </select>
              {fieldSelect(fieldId(r.field), (id) => { setField(i, id); }, `Parâmetro da regra ${n}`)}
              {f ? (
                <>
                  <OpSelect field={f} op={r.op} label={`Operador da regra ${n}`} onChange={(op, value) => { update(i, { op, value }); }} />
                  <ValueInput versionId={versionId} field={f} op={r.op} value={r.value} label={`Valor da regra ${n}`} onChange={(value) => { update(i, { value }); }} />
                </>
              ) : (
                <span className="error small">Parâmetro não existe nesta versão (a regra é ignorada).</span>
              )}
              <button type="button" className="link rule-row__remove" aria-label={`Remover regra ${n}`} onClick={() => { setRules((prev) => prev.filter((_, j) => j !== i)); }}>
                ×
              </button>
            </li>
          );
        })}
        <li className="rule-row rule-row--new">
          <select aria-label="Modo da nova regra" value={newMode} onChange={(e) => { setNewMode(e.target.value as FilterMode); }}>
            {MODES.map((m) => <option key={m} value={m}>{MODE_LABELS[m]}</option>)}
          </select>
          {fieldSelect('', (id) => { setField(null, id); }, 'Parâmetro da nova regra')}
        </li>
      </ol>
      <div className="modal__actions">
        <button type="button" className="secondary" onClick={onClose}>Cancelar</button>
        <button
          type="button"
          onClick={() => {
            onApply({ ...filter, logic, rules: rules.filter((r) => isComplete(r) && byId.has(fieldId(r.field))) });
          }}
        >
          Aplicar
        </button>
      </div>
    </Modal>
  );
}
