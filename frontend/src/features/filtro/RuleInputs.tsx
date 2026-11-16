import { useId, useState } from 'react';

import type { FilterField, FilterOp } from '../../api/filters';
import { defaultValue, needsValue, OP_LABELS, OPS_BY_TYPE, str } from './filterModel';
import { useFieldValues } from './useFieldValues';

const num = (n: number) => n.toLocaleString('pt-BR');

interface OpProps {
  field: FilterField;
  op: FilterOp;
  onChange: (op: FilterOp, value: unknown) => void;
  label?: string;
}

/** Operador conforme o tipo do campo (trocar de operador reinicia o valor). */
export function OpSelect({ field, op, onChange, label = 'Operador' }: OpProps) {
  return (
    <select
      aria-label={label}
      value={op}
      onChange={(e) => {
        const next = e.target.value as FilterOp;
        onChange(next, defaultValue(field.type, next));
      }}
    >
      {OPS_BY_TYPE[field.type].map((o) => (
        <option key={o} value={o}>
          {OP_LABELS[o]}
        </option>
      ))}
    </select>
  );
}

interface ValueProps {
  versionId: number;
  field: FilterField;
  op: FilterOp;
  value: unknown;
  onChange: (value: unknown) => void;
  label?: string;
}

/** Valor da regra: autocompletar (texto), calendário (data), número, sim/não ou lista. */
export function ValueInput({ versionId, field, op, value, onChange, label = 'Valor' }: ValueProps) {
  if (!needsValue(op)) return null;
  if (field.type === 'bool') {
    return (
      <select aria-label={label} value={value === false ? 'false' : 'true'} onChange={(e) => { onChange(e.target.value === 'true'); }}>
        <option value="true">Sim</option>
        <option value="false">Não</option>
      </select>
    );
  }
  if (op === 'last_n_days') {
    return (
      <label className="rule-days">
        <input
          type="number"
          min={1}
          max={3650}
          aria-label={label}
          value={typeof value === 'number' || typeof value === 'string' ? value : ''}
          onChange={(e) => { onChange(e.target.value === '' ? '' : Number(e.target.value)); }}
        />{' '}
        dias
      </label>
    );
  }
  if (op === 'between') {
    const pair = Array.isArray(value) ? value : ['', ''];
    const kind = field.type === 'date' ? 'date' : 'text';
    return (
      <span className="rule-between">
        <input
          type={kind}
          aria-label={`${label} (de)`}
          inputMode={field.type === 'number' ? 'decimal' : undefined}
          value={str(pair[0])}
          onChange={(e) => { onChange([e.target.value, pair[1] ?? '']); }}
        />
        <span>e</span>
        <input
          type={kind}
          aria-label={`${label} (até)`}
          inputMode={field.type === 'number' ? 'decimal' : undefined}
          value={str(pair[1])}
          onChange={(e) => { onChange([pair[0] ?? '', e.target.value]); }}
        />
      </span>
    );
  }
  if (field.type === 'date') {
    return (
      <input type="date" aria-label={label} value={typeof value === 'string' ? value : ''} onChange={(e) => { onChange(e.target.value); }} />
    );
  }
  if (op === 'in') {
    return <ValueChecklist versionId={versionId} field={field} value={Array.isArray(value) ? value.map(str) : []} onChange={onChange} label={label} />;
  }
  return <TextValue versionId={versionId} field={field} value={value} onChange={onChange} label={label} />;
}

function TextValue({ versionId, field, value, onChange, label }: Omit<ValueProps, 'op'>) {
  const text = typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  const listId = useId();
  const values = useFieldValues(versionId, field, text);
  return (
    <>
      <input
        type="text"
        aria-label={label}
        list={listId}
        autoComplete="off"
        inputMode={field.type === 'number' ? 'decimal' : undefined}
        placeholder={field.type === 'number' ? 'Ex.: 40 ou 40 cm' : 'Digite ou escolha'}
        value={text}
        onChange={(e) => { onChange(e.target.value); }}
      />
      <datalist id={listId}>
        {(values.data ?? []).map((v) => (
          <option key={v.value} value={v.value}>{`${num(v.pieces)} peça(s)`}</option>
        ))}
      </datalist>
    </>
  );
}

interface ChecklistProps {
  versionId: number;
  field: FilterField;
  value: string[];
  onChange: (value: string[]) => void;
  label?: string;
}

/** "é um de": marque os valores (os mais comuns do campo, com busca). */
export function ValueChecklist({ versionId, field, value, onChange, label = 'Valores' }: ChecklistProps) {
  const [q, setQ] = useState('');
  const values = useFieldValues(versionId, field, q);
  const shown = values.data ?? [];
  const extra = value.filter((v) => !shown.some((s) => s.value === v)); // marcados fora da lista
  const toggle = (v: string) => { onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]); };
  return (
    <fieldset className="value-checklist">
      <legend className="sr-only">{label}</legend>
      {field.distinct_values > 8 && (
        <input type="search" aria-label={`Buscar em ${field.name}`} placeholder="Buscar valor…" value={q} onChange={(e) => { setQ(e.target.value); }} />
      )}
      {values.isPending && <p className="hint">Carregando valores…</p>}
      {[...extra.map((v) => ({ value: v, pieces: null as number | null })), ...shown].map((v) => (
        <label key={v.value} className="check">
          <input type="checkbox" checked={value.includes(v.value)} onChange={() => { toggle(v.value); }} />
          <span>{v.value}</span>
          {v.pieces !== null && <span className="muted small">{num(v.pieces)}</span>}
        </label>
      ))}
      {!values.isPending && shown.length === 0 && extra.length === 0 && <p className="hint">Nenhum valor.</p>}
    </fieldset>
  );
}
