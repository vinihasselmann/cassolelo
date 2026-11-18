import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { fetchElement, type ElementDetail, type MarkPieces, type PropertyGroup } from '../../api/versions';
import type { BatchApplyResult } from '../../api/markBatch';
import type { UnitBatchResult } from '../../api/units';
import { PieceUnitsSection } from '../pecas/PieceUnitsSection';
import { BatchValuesSection } from '../params/BatchValuesSection';
import { MarkValuesSection } from '../params/MarkValuesSection';
import { errorMessage } from '../../lib/errors';
import { formatValue } from '../../lib/format';
import type { MarkStatus } from '../../api/status';
import { AxisCoordinatesSection } from './AxisCoordinatesSection';
import { StatusBadge } from './StatusBadge';
import { pieceCount, type Selection } from './selection';
import type { AxisState } from './useAxisCoordinates';
import { Icon } from '../../components/Icon';

const num = (n: number) => n.toLocaleString('pt-BR');
const pieces = (n: number) => `${num(n)} ${n === 1 ? 'peça' : 'peças'}`;

function SelectionHeader({ selection }: { selection: Selection }) {
  const { marks, unmarked } = selection;
  if (marks.length === 1 && unmarked.length === 0) {
    const [mark] = marks;
    return (
      <h3 className="piece-head">
        {mark?.code} · {mark?.category} · {pieces(mark?.count ?? 0)}
      </h3>
    );
  }
  if (marks.length === 0) {
    return <h3 className="piece-head">{unmarked.length === 1 ? 'Peça sem Marca' : `${pieces(unmarked.length)} sem Marca`}</h3>;
  }
  return (
    <>
      <h3 className="piece-head">
        {num(marks.length)} {marks.length === 1 ? 'marca' : 'marcas'} · {pieces(pieceCount(selection))}
      </h3>
      <ul className="piece-marks" aria-label="Marcas selecionadas">
        {marks.map((m) => (
          <li key={m.mark_id}>
            {m.code} · {m.category} · {pieces(m.count)}
          </li>
        ))}
        {unmarked.length > 0 && <li>{pieces(unmarked.length)} sem Marca</li>}
      </ul>
    </>
  );
}

/**
 * De onde veio o nome da peça clicada e os outros parâmetros da regra preenchidos nela
 * (ex.: "Nome da montagem: PP001 · Marca: P01"). Na marca, avisa quando as peças divergem
 * num parâmetro secundário (vale o primeiro da regra).
 */
export function PieceIdentification({ element, mark }: { element: ElementDetail; mark: MarkPieces | undefined }) {
  const alt = element.mark_alt ?? [];
  const divergent = (mark?.secondary ?? []).filter((s) => s.values.length > 1);
  if (!element.mark_source && alt.length === 0 && divergent.length === 0) return null;
  return (
    <>
      <dl className="kv piece-ident" aria-label="Identificação da peça">
        {element.mark_source && (
          <div className="kv__row">
            <dt>{element.mark_source}</dt>
            <dd>
              {element.mark_raw ?? '—'} <span className="ro">nome da peça</span>
            </dd>
          </div>
        )}
        {alt.map((a) => (
          <div key={a.name} className="kv__row">
            <dt>{a.name}</dt>
            <dd>{a.value}</dd>
          </div>
        ))}
      </dl>
      {divergent.map((s) => (
        <p key={s.name} className="hint mark-item__warn" role="note">
          ⚠ As peças desta marca têm valores diferentes em {s.name}: {s.values.join(', ')}.
        </p>
      ))}
    </>
  );
}

function matches(text: string, filter: string): boolean {
  return text.toLocaleLowerCase('pt-BR').includes(filter);
}

function filterGroups(groups: PropertyGroup[], filter: string): PropertyGroup[] {
  if (!filter) return groups;
  return groups
    .map((g) =>
      matches(g.name, filter)
        ? g
        : { ...g, properties: g.properties.filter((p) => matches(p.name, filter) || matches(formatValue(p.value), filter)) },
    )
    .filter((g) => g.properties.length > 0);
}

function ModelProperties({ groups }: { groups: PropertyGroup[] }) {
  const [filter, setFilter] = useState('');
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const needle = filter.trim().toLocaleLowerCase('pt-BR');
  const visible = filterGroups(groups, needle);

  const toggle = (name: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <>
      <input
        type="search"
        className="prop-filter"
        placeholder="Filtrar propriedades…"
        aria-label="Filtrar propriedades"
        value={filter}
        onChange={(e) => { setFilter(e.target.value); }}
      />
      {visible.length === 0 && <p className="muted small">Nenhuma propriedade encontrada.</p>}
      {visible.map((g) => {
        const open = Boolean(needle) || !collapsed.has(g.name); // com filtro, tudo aberto
        return (
          <div key={g.name} className="prop-group">
            <button
              type="button"
              className="prop-group__head"
              aria-expanded={open}
              onClick={() => { toggle(g.name); }}
            >
              <Icon name={open ? 'chevron-down' : 'chevron-right'} size={12} /> {g.name}{' '}
              <span className="muted small">({g.properties.length})</span>
            </button>
            {open && (
              <dl className="kv" aria-label={g.name}>
                {g.properties.map((p) => (
                  <div key={p.name} className="kv__row">
                    <dt>{p.name}</dt>
                    <dd>{formatValue(p.value)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        );
      })}
    </>
  );
}

interface FactoryProps {
  obraId: number;
  selection: Selection;
  canEdit: boolean;
  onBatchApplied: (result: BatchApplyResult) => void;
}

/** Valores da fábrica: uma marca (edição normal) ou 2+ marcas (edição em lote). */
function FactoryValues({ obraId, selection, canEdit, onBatchApplied }: FactoryProps) {
  const [only] = selection.marks;
  if (selection.marks.length === 1 && selection.unmarked.length === 0 && only) {
    return <MarkValuesSection obraId={obraId} markId={only.mark_id} canEdit={canEdit} />;
  }
  if (selection.marks.length >= 2) {
    return (
      <BatchValuesSection
        obraId={obraId}
        markIds={selection.marks.map((m) => m.mark_id)}
        canEdit={canEdit}
        unmarked={selection.unmarked.length}
        onApplied={onBatchApplied}
      />
    );
  }
  if (selection.marks.length === 0) {
    return <p className="muted small">Peça sem Marca: os parâmetros da fábrica são preenchidos por marca.</p>;
  }
  return <p className="muted small">Peças sem Marca selecionadas junto: selecione só a marca para editar os valores.</p>;
}

interface PanelProps {
  versionId: number;
  selection: Selection;
  obraId: number;
  canEditParams: boolean;
  onNewParam: (category: string | null) => void;
  onBatchApplied: (result: BatchApplyResult) => void;
  /** Lote de valores POR PEÇA aplicado (aviso com Desfazer). */
  onUnitBatchApplied: (result: UnitBatchResult) => void;
  /** Clique numa linha da tabela por peça: destacar só aquela peça no 3D. */
  onPickPiece: (dbid: number) => void;
  /** Modo consulta (versão anterior): rótulo da versão ativa, para o aviso dos valores. */
  activeLabel?: string | null;
  /** Coordenadas do eixo da peça clicada (a instância, não a marca). */
  axis?: AxisState;
  /** Status de produção de cada marca (agregado das peças). */
  statusById?: ReadonlyMap<number, MarkStatus>;
}

const NO_STATUS: ReadonlyMap<number, MarkStatus> = new Map();

export function PiecePanel({
  versionId,
  obraId,
  selection,
  canEditParams,
  onNewParam,
  onBatchApplied,
  onUnitBatchApplied,
  onPickPiece,
  activeLabel = null,
  axis = { status: 'unavailable' },
  statusById = NO_STATUS,
}: PanelProps) {
  const focus = selection.focus;
  const element = useQuery({
    queryKey: ['versions', versionId, 'elements', focus],
    queryFn: () => fetchElement(versionId, focus ?? 0),
    enabled: focus !== null,
    retry: false,
    staleTime: Infinity, // dados do BIM de uma versão não mudam
  });

  // Categoria da marca (uma só marca) ou da peça clicada: decide quais parâmetros valem.
  const category =
    selection.marks.length === 1 ? (selection.marks[0]?.category ?? null) : (element.data?.category ?? null);

  // Uma marca só: a tabela "Parâmetros por peça" (se houver parâmetros por peça).
  const onlyMark = selection.marks.length === 1 && selection.unmarked.length === 0 ? selection.marks[0] : undefined;

  const status = onlyMark ? statusById.get(onlyMark.mark_id) : undefined;

  if (focus === null) {
    return (
      <div className="model-sec">
        <h3 className="section-title">Seleção</h3>
        <p className="muted">Toque numa peça no modelo, ou escolha uma marca na lista, para ver e preencher os parâmetros da fábrica.</p>
      </div>
    );
  }

  return (
    <>
      <div className="model-sec piece-sec">
        <SelectionHeader selection={selection} />
        {status && (
          <p className="piece-status">
            <StatusBadge status={status} />
          </p>
        )}
        {element.data && (
          <p className="muted small">Peça clicada: {element.data.name ?? '—'}</p>
        )}
        {element.data && <PieceIdentification element={element.data} mark={onlyMark} />}
      </div>

      {/* Ordem do painel = caminho da produção: quem é → status → preencher → conferir no modelo. */}
      <section className="model-sec" aria-labelledby="factory-params">
        <div className="reshead">
          <h4 id="factory-params">Parâmetros da fábrica</h4>
          {canEditParams && (
            <button type="button" className="link" onClick={() => { onNewParam(category); }}>
              + Novo parâmetro
            </button>
          )}
        </div>
        {activeLabel && (
          <p className="consult-note" role="note">
            Valores atuais da marca: valem para a versão ativa ({activeLabel}). Nesta versão só é possível consultar.
          </p>
        )}
        <section className="factory-sub" aria-labelledby="mark-params">
          <h5 id="mark-params">Parâmetros por marca</h5>
          <FactoryValues obraId={obraId} selection={selection} canEdit={canEditParams} onBatchApplied={onBatchApplied} />
        </section>
        {onlyMark && (
          <PieceUnitsSection
            obraId={obraId}
            markId={onlyMark.mark_id}
            versionId={versionId}
            canEdit={canEditParams}
            focus={focus}
            onPickPiece={onPickPiece}
            onBatchApplied={onUnitBatchApplied}
          />
        )}
      </section>

      <AxisCoordinatesSection state={axis} />

      <section className="model-sec" aria-labelledby="model-props">
        <h4 id="model-props">
          Propriedades do modelo <span className="ro">somente leitura</span>
        </h4>
        {element.isPending && <p className="muted small">Carregando…</p>}
        {element.isError && (
          <p role="alert" className="error small">
            {errorMessage(element.error)}
          </p>
        )}
        {element.data && <ModelProperties key={element.data.dbid} groups={element.data.groups} />}
        {element.data && (
          <p className="hint tech-ids" title="Identificadores do elemento no modelo (para suporte)">
            Id no modelo: {element.data.external_id ?? '—'} · dbId {element.data.dbid}
          </p>
        )}
      </section>
    </>
  );
}
