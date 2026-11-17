import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  createSavedFilter,
  fetchSavedFilters,
  savedFiltersKey,
  updateSavedFilter,
  type FilterField,
  type SavedFilter,
} from '../../api/filters';
import type { User } from '../../api/users';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { FieldPicker } from './FieldPicker';
import { FilterEditorDialog } from './FilterEditorDialog';
import {
  DEFAULT_MODE,
  differsFrom,
  fromSaved,
  isComplete,
  ruleText,
  sameField,
  str,
  typedRule,
  type ActiveFilter,
  type ActiveRule,
} from './filterModel';
import { ValueChecklist } from './RuleInputs';
import type { ActiveFilterState } from './useActiveFilter';

const fieldKey = (f: { source: string; key: string }) => `${f.source}:${f.key}`;

/** Lista de filtros salvos por seção: sistema, compartilhados e os meus. */
function sections(all: readonly SavedFilter[], me: User | undefined) {
  return [
    { title: 'Sistema', items: all.filter((f) => f.system_key !== null) },
    { title: 'Compartilhados', items: all.filter((f) => f.system_key === null && f.scope === 'shared') },
    { title: 'Meus', items: all.filter((f) => f.scope === 'personal' && f.owner_id === me?.id) },
  ].filter((s) => s.items.length > 0);
}

interface QuickProps {
  label: string;
  versionId: number;
  field: FilterField | undefined;
  filter: ActiveFilter;
  onChange: (next: ActiveFilter) => void;
}

/** Menu rápido (Categoria, Nível): marca os valores; vira a regra "é um de" (Isolar). */
function QuickMenu({ label, versionId, field, filter, onChange }: QuickProps) {
  const [open, setOpen] = useState(false);
  if (!field) return null;
  const at = filter.rules.findIndex((r) => sameField(r.field, field) && r.op === 'in' && r.mode === DEFAULT_MODE);
  const current = at >= 0 ? filter.rules[at]?.value : undefined;
  const chosen = Array.isArray(current) ? current.map(str) : [];
  const set = (values: string[]) => {
    const rules = [...filter.rules];
    const rule: ActiveRule = { field: { source: field.source, key: field.key }, op: 'in', value: values, mode: DEFAULT_MODE };
    if (at >= 0) {
      if (values.length) rules[at] = rule;
      else rules.splice(at, 1);
    } else if (values.length) rules.push(rule);
    onChange({ ...filter, rules });
  };
  return (
    <div className="quick">
      <button type="button" className="chip" aria-expanded={open} onClick={() => { setOpen(!open); }}>
        {label}
        {chosen.length > 0 && ` (${String(chosen.length)})`} ▾
      </button>
      {open && (
        <div className="popover quick__menu" role="group" aria-label={label}>
          <ValueChecklist versionId={versionId} field={field} value={chosen} onChange={set} label={label} />
        </div>
      )}
    </div>
  );
}

interface Props {
  obraId: number;
  versionId: number;
  fields: readonly FilterField[];
  fieldsError: unknown;
  state: ActiveFilterState;
  me: User | undefined;
}

/** Popover "Filtro" (abre para cima, na barra inferior do visualizador). */
export function FilterPopover({ obraId, versionId, fields, fieldsError, state, me }: Props) {
  const { filter, set } = state;
  const qc = useQueryClient();
  const saved = useQuery({ queryKey: savedFiltersKey(obraId), queryFn: () => fetchSavedFilters(obraId), retry: false });
  const [dialog, setDialog] = useState<'picker' | 'editor' | 'save' | null>(null);
  const [saveMenu, setSaveMenu] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const byKey = new Map(fields.map((f) => [fieldKey(f), f]));
  const find = (source: string, key: string) => byKey.get(`${source}:${key}`);

  const current = saved.data?.find((f) => f.id === filter.savedId);
  const canShare = me?.can_share_filters === true;
  const changed = current !== undefined && differsFrom(filter, current);

  const refresh = (item: SavedFilter, text: string) => {
    void qc.invalidateQueries({ queryKey: ['saved-filters'] });
    setNotice(text);
    set({ ...filter, savedId: item.id });
  };
  const update = useMutation({
    mutationFn: (body: Parameters<typeof updateSavedFilter>[1]) => updateSavedFilter(filter.savedId ?? 0, body),
    onSuccess: (item, body) => { refresh(item, body.scope === 'shared' ? `"${item.name}" agora é compartilhado.` : `"${item.name}" atualizado.`); },
  });

  const removeRule = (i: number) => { set({ ...filter, rules: filter.rules.filter((_, j) => j !== i) }); };
  const tags = filter.rules.map((r, i) => ({ rule: r, i })).filter(({ rule }) => isComplete(rule));

  return (
    <div className="filter-pop" role="dialog" aria-label="Filtro">
      <section className="filter-pop__saved" aria-labelledby="saved-title">
        <h4 id="saved-title">Filtros salvos</h4>
        {saved.isPending && <p className="hint">Carregando…</p>}
        {saved.isError && <p className="error small">{errorMessage(saved.error)}</p>}
        {saved.data && sections(saved.data, me).map((s) => (
          <div key={s.title} className="saved-sec">
            <h5>{s.title}</h5>
            <ul aria-label={s.title}>
              {s.items.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    className="list-item saved-item"
                    aria-pressed={filter.savedId === f.id}
                    onClick={() => { setNotice(null); set(fromSaved(f)); }}
                  >
                    {filter.savedId === f.id && <span aria-hidden="true">✓ </span>}
                    {f.name}
                    {filter.savedId === f.id && changed && <span className="muted small"> (alterado)</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="filter-pop__current" aria-labelledby="filter-title">
        <h4 id="filter-title">
          Filtro{state.loading && <span className="muted small"> filtrando…</span>}
        </h4>
        <input
          type="search"
          className="search-input"
          aria-label="Pesquisar por objetos"
          placeholder="Pesquisar por objetos"
          value={filter.q}
          onChange={(e) => { set({ ...filter, q: e.target.value }); }}
          onKeyDown={(e) => {
            if (e.key !== 'Enter') return;
            const rule = typedRule(filter.q, fields);
            if (rule) set({ ...filter, q: '', rules: [...filter.rules, rule] });
          }}
        />
        <p className="hint">
          Marca, tipo, seção, nível ou valor da fábrica. Também <code>Nome=valor</code> e <code>sem &lt;parâmetro&gt;</code> + Enter.
        </p>
        {fieldsError !== null && fieldsError !== undefined && <p className="error small">{errorMessage(fieldsError)}</p>}
        <div className="quick-row">
          <QuickMenu label="Categoria" versionId={versionId} field={find('system', 'category')} filter={filter} onChange={set} />
          <QuickMenu label="Nível" versionId={versionId} field={find('system', 'level')} filter={filter} onChange={set} />
        </div>
        {tags.length > 0 && (
          <ul className="tags" aria-label="Filtros ativos">
            {tags.map(({ rule, i }) => {
              const text = ruleText(rule, find(rule.field.source, rule.field.key));
              return (
                <li key={i} className={`tag tag--${rule.mode}`}>
                  <span>{text}</span>
                  <button type="button" aria-label={`Remover filtro ${text}`} onClick={() => { removeRule(i); }}>
                    ×
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {filter.logic === 'or' && tags.length > 1 && <p className="hint">Combinando por qualquer regra (OU).</p>}
        {state.evaluation?.data?.notes.map((n) => <p key={n} className="hint">{n}</p>)}
        {state.error !== null && <p role="alert" className="error small">{errorMessage(state.error)}</p>}
        <div className="btn-row">
          <button type="button" className="secondary" disabled={fields.length === 0} onClick={() => { setDialog('picker'); }}>
            + Adicionar filtro
          </button>
          <button type="button" className="secondary" disabled={fields.length === 0} onClick={() => { setDialog('editor'); }}>
            Avançado
          </button>
          <div className="menu">
            <button type="button" aria-expanded={saveMenu} aria-haspopup="menu" onClick={() => { setSaveMenu(!saveMenu); }}>
              Salvar ▾
            </button>
            {saveMenu && (
              <div className="popover menu__list" role="menu" aria-label="Salvar">
                <button type="button" role="menuitem" disabled={!state.active} onClick={() => { setSaveMenu(false); setDialog('save'); }}>
                  Salvar como novo…
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={!current?.editable || !changed || !state.active || update.isPending}
                  title={current && !current.editable ? 'Você não pode alterar este filtro.' : undefined}
                  onClick={() => { setSaveMenu(false); update.mutate({ definition: state.definition }); }}
                >
                  Atualizar o filtro{current ? ` "${current.name}"` : ''}
                </button>
                {canShare && current?.scope === 'personal' && current.owner_id === me.id && (
                  <button type="button" role="menuitem" onClick={() => { setSaveMenu(false); update.mutate({ scope: 'shared' }); }}>
                    Compartilhar
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
        {update.isError && <p role="alert" className="error small">{errorMessage(update.error)}</p>}
        {notice && <p role="status" className="hint">{notice}</p>}
      </section>

      {dialog === 'picker' && (
        <FieldPicker
          versionId={versionId}
          fields={fields}
          onClose={() => { setDialog(null); }}
          onAdd={(rule) => { set({ ...filter, rules: [...filter.rules, rule] }); setDialog(null); }}
        />
      )}
      {dialog === 'editor' && (
        <FilterEditorDialog
          versionId={versionId}
          fields={fields}
          filter={filter}
          onClose={() => { setDialog(null); }}
          onApply={(next) => { set(next); setDialog(null); }}
        />
      )}
      {dialog === 'save' && (
        <SaveDialog
          obraId={obraId}
          canShare={canShare}
          onClose={() => { setDialog(null); }}
          onSaved={(item) => { setDialog(null); refresh(item, `Filtro "${item.name}" salvo.`); }}
          definition={state.definition}
        />
      )}
    </div>
  );
}

interface SaveProps {
  obraId: number;
  canShare: boolean;
  definition: ActiveFilterState['definition'];
  onSaved: (item: SavedFilter) => void;
  onClose: () => void;
}

/** "Salvar como novo": nome e, se o papel permitir, compartilhar com todos. Vale nesta obra. */
function SaveDialog({ obraId, canShare, definition, onSaved, onClose }: SaveProps) {
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  const create = useMutation({
    mutationFn: () => createSavedFilter({ name: name.trim(), scope: shared ? 'shared' : 'personal', obra_id: obraId, definition }),
    onSuccess: onSaved,
  });
  return (
    <Modal title="Salvar filtro" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}>
        <label className="field">
          <span>Nome</span>
          <input value={name} maxLength={120} onChange={(e) => { setName(e.target.value); }} />
        </label>
        {canShare ? (
          <label className="check">
            <input type="checkbox" checked={shared} onChange={(e) => { setShared(e.target.checked); }} />
            <span>Compartilhar com todos (filtro da obra)</span>
          </label>
        ) : (
          <p className="hint">O filtro fica só para você.</p>
        )}
        {create.isError && <p role="alert" className="error small">{errorMessage(create.error)}</p>}
        <div className="modal__actions">
          <button type="button" className="secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" disabled={!name.trim() || create.isPending}>Salvar</button>
        </div>
      </form>
    </Modal>
  );
}
