import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import {
  colorSchemesKey,
  createColorScheme,
  evaluateScheme,
  fetchColorSchemes,
  updateColorScheme,
  type ColorScheme,
  type SchemeRule,
} from '../../api/colors';
import {
  createSavedFilter,
  fetchSavedFilters,
  savedFiltersKey,
  type FilterField,
  type FilterOp,
  type FilterScope,
  type SavedFilter,
} from '../../api/filters';
import type { User } from '../../api/users';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import { FieldList } from '../filtro/FieldPicker';
import { defaultOp, defaultValue, isComplete, type ActiveRule } from '../filtro/filterModel';
import { OpSelect, ValueInput } from '../filtro/RuleInputs';
import { RULE_PALETTE } from './coloringModel';

const num = (n: number) => n.toLocaleString('pt-BR');

function ruleName(rule: SchemeRule, saved: readonly SavedFilter[]): string {
  if (typeof rule.filter === 'number') {
    const id = rule.filter;
    return saved.find((f) => f.id === id)?.name ?? rule.label ?? `Filtro ${String(id)}`;
  }
  return rule.label || 'Filtro';
}

interface Props {
  obraId: number;
  versionId: number;
  fields: readonly FilterField[];
  me: User | undefined;
  /** esquema em uso (abre a janela já com ele) */
  currentSchemeId: number | null;
  onApply: (scheme: ColorScheme) => void;
  onClose: () => void;
}

/**
 * "Editar cores" → janela "Cores": tabela de regras (cor + filtro salvo + contagem). A
 * ORDEM define a prioridade: a peça fica com a cor da primeira regra que ela satisfaz.
 * Salvar grava um esquema pessoal ou compartilhado e o aplica no modelo.
 */
export function ColorRulesDialog({ obraId, versionId, fields, me, currentSchemeId, onApply, onClose }: Props) {
  const qc = useQueryClient();
  const schemes = useQuery({ queryKey: colorSchemesKey(obraId), queryFn: () => fetchColorSchemes(obraId), retry: false });
  const saved = useQuery({ queryKey: savedFiltersKey(obraId), queryFn: () => fetchSavedFilters(obraId), retry: false });
  const canShare = me?.can_share_filters === true;

  const [loadedId, setLoadedId] = useState<number | null>(currentSchemeId);
  const [rules, setRules] = useState<SchemeRule[]>([]);
  const [name, setName] = useState('');
  const [scope, setScope] = useState<FilterScope>('personal');
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState<{ index: number | null } | null>(null);
  const [initialized, setInitialized] = useState(currentSchemeId === null);

  const load = (s: ColorScheme | null) => {
    setLoadedId(s?.id ?? null);
    setRules(s ? s.rules.map((r) => ({ ...r })) : []);
    setName(s?.name ?? '');
    setScope(s?.scope ?? 'personal');
    setSelected(null);
  };
  useEffect(() => {
    if (initialized || !schemes.data) return;
    load(schemes.data.find((s) => s.id === currentSchemeId) ?? null);
    setInitialized(true);
  }, [initialized, schemes.data, currentSchemeId]);

  const loaded = schemes.data?.find((s) => s.id === loadedId);
  const previewKey = useDebouncedValue(JSON.stringify(rules), 250);
  const preview = useQuery({
    queryKey: ['versions', versionId, 'color-scheme-preview', previewKey],
    queryFn: () => evaluateScheme(versionId, { rules: JSON.parse(previewKey) as SchemeRule[] }),
    enabled: previewKey !== '[]',
    placeholderData: keepPreviousData,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), scope, rules };
      return loaded?.editable ? updateColorScheme(loaded.id, body) : createColorScheme({ ...body, obra_id: obraId });
    },
    onSuccess: (scheme) => {
      void qc.invalidateQueries({ queryKey: ['color-schemes'] });
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'versions' && q.queryKey[2] === 'color-scheme' });
      onApply(scheme);
    },
  });

  const move = (from: number, to: number) => {
    setRules((prev) => {
      const next = [...prev];
      const [item] = next.splice(from, 1);
      if (item) next.splice(to, 0, item);
      return next;
    });
    setSelected(to);
  };
  const savedList = saved.data ?? [];
  const sel = selected !== null && selected < rules.length ? selected : null;

  return (
    <Modal title="Cores" onClose={onClose} wide>
      <label className="field">
        <span>Esquema</span>
        <select
          aria-label="Esquema de cores"
          value={loadedId ?? ''}
          onChange={(e) => { load(schemes.data?.find((s) => s.id === Number(e.target.value)) ?? null); }}
        >
          <option value="">Novo esquema</option>
          {schemes.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} {s.scope === 'shared' ? '(compartilhado)' : '(pessoal)'}
            </option>
          ))}
        </select>
      </label>
      {schemes.isError && <p className="error small">{errorMessage(schemes.error)}</p>}
      <p className="hint">A ordem define a prioridade: cada peça fica com a cor da primeira regra que ela satisfaz.</p>

      <table className="rules-table">
        <thead>
          <tr>
            <th scope="col">Cor</th>
            <th scope="col">Filtro</th>
            <th scope="col">Peças</th>
          </tr>
        </thead>
        <tbody>
          {rules.length === 0 && (
            <tr>
              <td colSpan={3} className="muted small">Nenhuma regra. Use Adicionar.</td>
            </tr>
          )}
          {rules.map((r, i) => {
            const res = preview.data?.rules[i];
            const n = String(i + 1);
            return (
              <tr key={i} aria-selected={sel === i} className={sel === i ? 'is-selected' : undefined} onClick={() => { setSelected(i); }}>
                <td>
                  <input
                    type="color"
                    aria-label={`Cor da regra ${n}`}
                    value={r.color.toLowerCase()}
                    onChange={(e) => { setRules((prev) => prev.map((x, j) => (j === i ? { ...x, color: e.target.value.toUpperCase() } : x))); }}
                  />
                </td>
                <td>
                  <label className="rules-table__pick">
                    <input type="radio" name="color-rule" aria-label={`Regra ${n}: ${ruleName(r, savedList)}`} checked={sel === i} onChange={() => { setSelected(i); }} />
                    {ruleName(r, savedList)}
                  </label>
                </td>
                <td className="rules-table__n" title={res ? `${num(res.matched)} batem no filtro` : undefined}>
                  {res ? num(res.pieces) : '…'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {preview.isError && <p role="alert" className="error small">{errorMessage(preview.error)}</p>}
      {preview.data?.notes.map((n) => <p key={n} className="hint">{n}</p>)}

      <div className="btn-row rules-actions">
        <button type="button" className="secondary" onClick={() => { setEditing({ index: null }); }}>Adicionar</button>
        <button type="button" className="secondary" disabled={sel === null} onClick={() => { setEditing({ index: sel }); }}>Editar</button>
        <button
          type="button"
          className="secondary"
          disabled={sel === null}
          onClick={() => { setRules((prev) => prev.filter((_, j) => j !== sel)); setSelected(null); }}
        >
          Remover
        </button>
        <button type="button" className="secondary" disabled={sel === null || sel === 0} onClick={() => { if (sel !== null) move(sel, sel - 1); }}>
          Mover para cima
        </button>
        <button type="button" className="secondary" disabled={sel === null || sel === rules.length - 1} onClick={() => { if (sel !== null) move(sel, sel + 1); }}>
          Mover para baixo
        </button>
      </div>

      <div className="rules-save">
        <label className="field">
          <span>Nome do esquema</span>
          <input value={name} maxLength={120} onChange={(e) => { setName(e.target.value); }} />
        </label>
        <label className="field">
          <span>Visível para</span>
          <select aria-label="Visível para" value={scope} onChange={(e) => { setScope(e.target.value as FilterScope); }}>
            <option value="personal">Só para mim (pessoal)</option>
            {(canShare || scope === 'shared') && <option value="shared">Todos (compartilhado)</option>}
          </select>
        </label>
      </div>
      {loaded && !loaded.editable && <p className="hint">Você não pode alterar "{loaded.name}": salvar cria um esquema novo.</p>}
      {save.isError && <p role="alert" className="error small">{errorMessage(save.error)}</p>}
      <div className="modal__actions">
        <button type="button" className="secondary" onClick={onClose}>Cancelar</button>
        <button type="button" disabled={rules.length === 0 || !name.trim() || save.isPending} onClick={() => { save.mutate(); }}>
          Salvar
        </button>
      </div>

      {editing && (
        <RuleDialog
          obraId={obraId}
          versionId={versionId}
          fields={fields}
          saved={savedList}
          canShare={canShare}
          initial={editing.index !== null ? rules[editing.index] : undefined}
          defaultColor={RULE_PALETTE[rules.length % RULE_PALETTE.length] ?? '#E8743B'}
          onClose={() => { setEditing(null); }}
          onSave={(rule) => {
            const at = editing.index;
            setRules((prev) => (at === null ? [...prev, rule] : prev.map((x, j) => (j === at ? rule : x))));
            setSelected(at ?? rules.length);
            setEditing(null);
          }}
        />
      )}
    </Modal>
  );
}

interface RuleProps {
  obraId: number;
  versionId: number;
  fields: readonly FilterField[];
  saved: readonly SavedFilter[];
  canShare: boolean;
  initial: SchemeRule | undefined;
  defaultColor: string;
  onSave: (rule: SchemeRule) => void;
  onClose: () => void;
}

/** Adicionar/Editar regra: um filtro salvo (ou um novo, criado aqui) e a cor. */
function RuleDialog({ obraId, versionId, fields, saved, canShare, initial, defaultColor, onSave, onClose }: RuleProps) {
  const qc = useQueryClient();
  const [source, setSource] = useState<'saved' | 'new'>('saved');
  const [filterId, setFilterId] = useState<number | ''>(typeof initial?.filter === 'number' ? initial.filter : '');
  const [color, setColor] = useState((initial?.color ?? defaultColor).toLowerCase());
  const [newName, setNewName] = useState('');
  const [shared, setShared] = useState(false);
  const [field, setField] = useState<FilterField | null>(null);
  const [op, setOp] = useState<FilterOp>('eq');
  const [value, setValue] = useState<unknown>(undefined);

  const rule: ActiveRule | null = field ? { field: { source: field.source, key: field.key }, op, value, mode: 'isolate' } : null;
  const create = useMutation({
    mutationFn: () =>
      createSavedFilter({
        name: newName.trim(),
        scope: shared ? 'shared' : 'personal',
        obra_id: obraId,
        definition: { mode: 'isolate', logic: 'and', rules: rule ? [rule] : [] },
      }),
    onSuccess: (f) => {
      void qc.invalidateQueries({ queryKey: ['saved-filters'] });
      onSave({ filter: f.id, color: color.toUpperCase() });
    },
  });
  const ready = source === 'saved' ? filterId !== '' : newName.trim() !== '' && rule !== null && isComplete(rule);

  return (
    <Modal title={initial ? 'Editar regra' : 'Adicionar regra'} onClose={onClose} wide>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          if (source === 'saved') onSave({ filter: Number(filterId), color: color.toUpperCase() });
          else create.mutate();
        }}
      >
        <div className="seg seg--inline" role="radiogroup" aria-label="Filtro da regra">
          <button type="button" role="radio" aria-checked={source === 'saved'} aria-pressed={source === 'saved'} onClick={() => { setSource('saved'); }}>
            Filtro salvo
          </button>
          <button type="button" role="radio" aria-checked={source === 'new'} aria-pressed={source === 'new'} onClick={() => { setSource('new'); }}>
            Novo filtro
          </button>
        </div>
        {source === 'saved' ? (
          <label className="field">
            <span>Filtro salvo</span>
            <select aria-label="Filtro salvo" value={filterId} onChange={(e) => { setFilterId(e.target.value === '' ? '' : Number(e.target.value)); }}>
              <option value="">Escolha…</option>
              {saved.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                  {f.system_key ? ' (sistema)' : f.scope === 'shared' ? ' (compartilhado)' : ' (pessoal)'}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="rule-new">
            <label className="field">
              <span>Nome do filtro</span>
              <input value={newName} maxLength={120} onChange={(e) => { setNewName(e.target.value); }} />
            </label>
            {field ? (
              <div>
                <p className="hint">
                  <b>{field.name}</b>{' '}
                  <button type="button" className="link" onClick={() => { setField(null); }}>trocar</button>
                </p>
                <div className="rule-step__row">
                  <OpSelect field={field} op={op} onChange={(o, v) => { setOp(o); setValue(v); }} />
                  <ValueInput versionId={versionId} field={field} op={op} value={value} onChange={setValue} />
                </div>
              </div>
            ) : (
              <FieldList
                fields={fields}
                onPick={(f) => {
                  const first = defaultOp(f.type);
                  setField(f);
                  setOp(first);
                  setValue(defaultValue(f.type, first));
                }}
              />
            )}
            {canShare && (
              <label className="check">
                <input type="checkbox" checked={shared} onChange={(e) => { setShared(e.target.checked); }} />
                <span>Compartilhar o filtro com todos</span>
              </label>
            )}
          </div>
        )}
        <label className="field rule-color">
          <span>Cor</span>
          <input type="color" aria-label="Cor" value={color} onChange={(e) => { setColor(e.target.value); }} />
        </label>
        {create.isError && <p role="alert" className="error small">{errorMessage(create.error)}</p>}
        <div className="modal__actions">
          <button type="button" className="secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" disabled={!ready || create.isPending}>OK</button>
        </div>
      </form>
    </Modal>
  );
}
