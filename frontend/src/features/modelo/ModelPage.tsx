import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { ApiError } from '../../api/client';
import { fetchObra, fetchVersions, type ModelVersion } from '../../api/obras';
import { fetchParamDefs, type ParamDef } from '../../api/paramDefs';
import { fetchFields, fetchSavedFilters, savedFiltersKey } from '../../api/filters';
import { fetchMarkStatus, markStatusKey } from '../../api/status';
import { fetchFacets, fetchMarks, type MarkPieces } from '../../api/versions';
import { errorMessage } from '../../lib/errors';
import { formatDateTime, plural, versionName } from '../../lib/format';
import { useViewerAdapter } from '../../viewer/viewerContext';
import { hasRole, PARAM_EDITOR_ROLES, useCurrentUser } from '../dev-user/useCurrentUser';
import { useObraId } from '../obras/useObraId';
import { CatalogDialog } from '../params/CatalogDialog';
import { ParamDefDialog } from '../params/ParamDefDialog';
import { UndoToast } from '../params/UndoToast';
import { ExportButton } from './ExportButton';
import { NumberingNotice } from './NumberingNotice';
import { useCentroidSync } from './useCentroidSync';
import { ManageMenu } from './ManageMenu';
import { LiveNotices } from '../live/LiveNotices';
import { useObraEvents } from '../live/useObraEvents';
import { OrphansDialog } from '../reconcile/OrphansDialog';
import { RelinkConfirm } from '../reconcile/RelinkConfirm';
import { UnitOrphansDialog } from '../reconcile/UnitOrphansDialog';
import { VersionBanner } from '../reconcile/VersionBanner';
import type { Orphan } from '../../api/reconcile';
import { FilterPopover } from '../filtro/FilterPopover';
import { FilterResultList } from '../filtro/FilterResultList';
import { fromSaved } from '../filtro/filterModel';
import { useActiveFilter } from '../filtro/useActiveFilter';
import { ViewerToolbar } from '../filtro/ViewerToolbar';
import { ColorLegend } from '../cores/ColorLegend';
import { ColorPopover } from '../cores/ColorPopover';
import { ColorRulesDialog } from '../cores/ColorRulesDialog';
import { DEFAULT_COLORING, type ColoringChoice } from '../cores/coloringModel';
import { useModelColoring } from '../cores/useModelColoring';
import { usePanels } from './usePanels';
import { PiecePanel } from './PiecePanel';
import { useAxisCoordinates } from './useAxisCoordinates';
import { ProgressFooter } from './ProgressFooter';
import {
  buildMarkIndex,
  EMPTY_SELECTION,
  selectPieces,
  refreshSelection,
  resolveClick,
  selectionDbIds,
  type MarkIndex,
  type Selection,
} from './selection';
import { Icon } from '../../components/Icon';

type ParamDialog =
  | { kind: 'new'; category: string | null }
  | { kind: 'edit'; param: ParamDef }
  | { kind: 'catalog' };

type LoadState = { kind: 'idle' } | { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; message: string };

/** Marca de desempenho (o E2E mede o tempo até o modelo aparecer). */
export const MODEL_READY_MARK = 'modelo:pronto';

/** Erros do adapter já vêm em português (ex.: falha ao carregar o Viewer); os da API, via errorMessage. */
function viewerError(err: unknown): string {
  if (!(err instanceof ApiError) && err instanceof Error && err.message) return err.message;
  return errorMessage(err);
}

/** "Rev.02": número da versão do Docs, como o escritório chama as revisões. */

function versionLabel(v: ModelVersion, latest: boolean): string {
  const date = v.published_at ? ` · ${formatDateTime(v.published_at)}` : '';
  return `${versionName(v.version_number)}${date}${latest ? ' (ativa)' : ''}`;
}

/** Tela da obra: barra superior + 3 colunas (lista e filtros | modelo 3D | painel). */
export function ModelPage() {
  const obraId = useObraId();
  const [params, setParams] = useSearchParams();

  const obra = useQuery({
    queryKey: ['obras', obraId],
    queryFn: () => fetchObra(obraId),
    enabled: Number.isFinite(obraId),
    retry: false,
  });
  const versions = useQuery({
    queryKey: ['obras', obraId, 'versions'],
    queryFn: () => fetchVersions(obraId),
    enabled: Number.isFinite(obraId),
    retry: false,
  });

  // Versões que o Viewer consegue abrir: prontas e com derivativo. A lista vem da mais nova.
  const viewable = (versions.data ?? []).filter((v) => v.status === 'ready' && v.urn);
  const chosen = Number(params.get('versao'));
  const active = viewable.find((v) => v.id === chosen) ?? viewable.at(0);

  // A versão aberta fica fixa na URL: uma versão nova (tempo real) não troca o modelo
  // sozinha; aparece o banner "Nova versão disponível" com "Carregar".
  // Trocar de versão mantém o filtro da URL (?f=...).
  const goVersion = useCallback(
    (id: number, replace = false) => {
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          out.set('versao', String(id));
          return out;
        },
        { replace },
      );
    },
    [setParams],
  );
  useEffect(() => {
    if (active && params.get('versao') === null) goVersion(active.id, true);
  }, [active, params, goVersion]);
  const realtime = useObraEvents(Number.isFinite(obraId) ? obraId : null);
  const newVersion =
    realtime.newVersion &&
    realtime.newVersion.versionId !== active?.id &&
    viewable.some((v) => v.id === realtime.newVersion?.versionId)
      ? realtime.newVersion
      : null;

  const marks = useQuery({
    queryKey: ['versions', active?.id, 'marks'],
    queryFn: () => fetchMarks(active?.id ?? 0),
    enabled: active !== undefined,
    retry: false,
    staleTime: Infinity, // marcas de uma versão processada não mudam
  });
  const index = useMemo(() => buildMarkIndex(marks.data ?? []), [marks.data]);
  const marksById = useMemo(() => new Map((marks.data ?? []).map((m) => [m.mark_id, m])), [marks.data]);
  // Peças da versão (todas as marcas): o Excel calcula o centro de gravidade de cada uma.
  const pieceDbIds = useMemo(() => (marks.data ?? []).flatMap((m) => m.dbids), [marks.data]);
  // Status de produção de cada marca (agregado das peças): lista e painel da peça.
  const markStatus = useQuery({
    queryKey: markStatusKey(active?.id ?? 0),
    queryFn: () => fetchMarkStatus(active?.id ?? 0),
    enabled: active !== undefined,
    retry: false,
  });
  const statusById = useMemo(
    () => new Map((markStatus.data?.items ?? []).map((i) => [i.mark_id, i.status])),
    [markStatus.data],
  );
  // Filtro da tela (F3): estado único na URL, avaliado no backend.
  const filterState = useActiveFilter(active?.id);
  const fields = useQuery({
    queryKey: ['versions', active?.id, 'fields'],
    queryFn: () => fetchFields(active?.id ?? 0),
    enabled: active !== undefined,
    retry: false,
    staleTime: 60_000,
  });
  const savedFilters = useQuery({
    queryKey: savedFiltersKey(obraId),
    queryFn: () => fetchSavedFilters(obraId),
    enabled: Number.isFinite(obraId),
    retry: false,
  });
  /** Aplica um filtro de sistema (antigos atalhos: "new", "review"...). */
  const applySystemFilter = (key: string) => {
    const found = savedFilters.data?.find((f) => f.system_key === key);
    if (found) filterState.set(fromSaved(found));
  };

  // Parâmetros da fábrica (globais + desta obra) e janelas do catálogo.
  const me = useCurrentUser();
  // Versão anterior (8.2): modo consulta, somente leitura. A ativa é a pronta mais recente.
  const latest = viewable.at(0);
  const consulting = active !== undefined && latest !== undefined && active.id !== latest.id;
  const canEditParams = hasRole(me.data, PARAM_EDITOR_ROLES) && !consulting;
  const paramDefs = useQuery({
    queryKey: ['param-defs', obraId],
    queryFn: () => fetchParamDefs(obraId),
    enabled: Number.isFinite(obraId),
    retry: false,
  });
  const facets = useQuery({
    queryKey: ['versions', active?.id, 'facets'],
    queryFn: () => fetchFacets(active?.id ?? 0),
    enabled: active !== undefined,
    retry: false,
    staleTime: Infinity,
  });
  const versionCategories = facets.data?.categories.map((c) => c.value) ?? [];
  const [dialog, setDialog] = useState<ParamDialog | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);
  const viewer = useViewerAdapter(canvasRef);
  const [load, setLoad] = useState<LoadState>({ kind: 'idle' });
  const [selection, setSelection] = useState<Selection>(EMPTY_SELECTION);
  // P4: peça escolhida na tabela "Parâmetros por peça": o 3D seleciona só ela (a marca
  // continua selecionada no painel). Um clique no 3D volta a selecionar a marca inteira.
  const [pieceFocus, setPieceFocus] = useState<{ markId: number; dbid: number } | null>(null);
  const [undo, setUndo] = useState<{ batchId: string; text: string } | null>(null);
  const closeUndo = useCallback(() => { setUndo(null); }, []);
  const [multi, setMulti] = useState(false);
  const { panels, toggle: togglePanel } = usePanels();
  // Painel aberto/fechado muda a largura do 3D: o Viewer recalcula o desenho depois do novo layout.
  useEffect(() => {
    const frame = requestAnimationFrame(() => { viewer?.resize(); });
    return () => { cancelAnimationFrame(frame); };
  }, [panels.left, panels.right, viewer]);
  // Coloração (F4): por campo ou por esquema; null = cores originais do modelo.
  const [colorChoice, setColorChoice] = useState<ColoringChoice | null>(DEFAULT_COLORING);
  const [showColors, setShowColors] = useState(false);
  // Órfãs (7.2): janela, modo "escolha a marca de destino" e a confirmação.
  const [showOrphans, setShowOrphans] = useState(false);
  const [showUnitOrphans, setShowUnitOrphans] = useState(false); // P5: peças órfãs
  const [relinkFrom, setRelinkFrom] = useState<Orphan | null>(null);
  const [relinkTarget, setRelinkTarget] = useState<MarkPieces | null>(null);
  const [relinkDone, setRelinkDone] = useState<string | null>(null);
  const [isolated, setIsolated] = useState(false);

  const urn = active?.urn ?? null;
  useEffect(() => {
    if (!viewer || !urn) return;
    let current = true;
    setLoad({ kind: 'loading' });
    setSelection(EMPTY_SELECTION);
    setIsolated(false);
    const started = performance.now();
    viewer.load(urn).then(
      () => {
        if (!current) return;
        performance.mark(MODEL_READY_MARK, { detail: { ms: performance.now() - started } });
        setLoad({ kind: 'ready' });
      },
      (err: unknown) => { if (current) setLoad({ kind: 'error', message: viewerError(err) }); },
    );
    return () => { current = false; };
  }, [viewer, urn]);

  // O listener do Viewer sempre lê o índice de marcas e o modo atuais.
  const live = useRef<{ index: MarkIndex; multi: boolean; relinking: boolean }>({ index, multi, relinking: false });
  live.current = { index, multi, relinking: relinkFrom !== null };
  useEffect(
    () =>
      viewer?.onSelect((ids) => {
        setPieceFocus(null);
        setSelection((prev) => resolveClick(ids, live.current.index, prev, live.current.multi));
        // Religando uma órfã: a peça clicada indica a marca de destino.
        const last = ids.at(-1);
        const target = last === undefined ? undefined : live.current.index.get(last);
        if (live.current.relinking && target) setRelinkTarget(target);
      }),
    [viewer],
  );

  // Clique antes de as marcas carregarem (tablet lento): a peça entrou "sem Marca";
  // quando o índice chega, ela passa para a marca dela.
  useEffect(() => { setSelection((prev) => refreshSelection(prev, index)); }, [index]);

  // A seleção do app (marca inteira) é refletida no Viewer.
  const selectedIds = useMemo(() => selectionDbIds(selection), [selection]);
  const onlyMarkId = selection.marks.length === 1 && selection.unmarked.length === 0 ? selection.marks[0]?.mark_id : undefined;
  const pieceDbid = pieceFocus !== null && pieceFocus.markId === onlyMarkId ? pieceFocus.dbid : null;
  useEffect(() => {
    viewer?.selectDbIds(pieceDbid !== null ? [pieceDbid] : selectedIds);
  }, [viewer, selectedIds, pieceDbid]);
  const pickPiece = (dbid: number) => {
    if (onlyMarkId === undefined) return;
    setPieceFocus({ markId: onlyMarkId, dbid });
    setSelection((prev) => ({ ...prev, focus: dbid })); // propriedades da peça escolhida
    viewer?.fitTo([dbid]);
  };

  const hasSelection = selectedIds.length > 0;
  const modelReady = load.kind === 'ready';
  // Coordenadas do eixo da peça CLICADA (selection.focus), não da marca inteira.
  const axis = useAxisCoordinates(viewer, selection.focus, modelReady);
  // Centros de gravidade para o servidor (1ª abertura da versão): numeração das peças pela
  // sequência de montagem e X/Y/Z do Excel.
  const centroids = useCentroidSync({
    obraId,
    versionId: active?.id ?? null,
    viewer,
    modelReady,
    pieceDbIds,
  });

  // O que o 3D mostra. Filtro: o backend diz o modo ("isolate": só o resultado;
  // "highlight": resultado normal, o resto esmaecido e as peças fora das visíveis ocultas).
  // "Isolar" (barra do topo) esconde o resto: alvo = a seleção ou, sem ela, o resultado.
  const result = filterState.evaluation?.data;
  const resultIds = result?.dbids;
  const isolateIds = useMemo(
    () => (hasSelection ? selectedIds : (resultIds ?? [])),
    [hasSelection, selectedIds, resultIds],
  );
  useEffect(() => {
    if (!viewer || !modelReady) return;
    if (isolated) viewer.isolate(isolateIds);
    else if (result) {
      if (result.view === 'isolate') viewer.isolate(result.dbids);
      else viewer.highlight(result.dbids);
      if (result.hidden_dbids.length > 0) viewer.hide(result.hidden_dbids);
    } else viewer.showAll();
  }, [viewer, modelReady, isolated, isolateIds, result]);

  // Coloração: o filtro decide o que aparece; a coloração, a cor (independentes).
  const markOf = useCallback((dbid: number) => index.get(dbid)?.mark_id, [index]);
  const { coloring, error: coloringError } = useModelColoring(active?.id ?? null, colorChoice, markOf);
  useEffect(() => {
    if (!viewer || !modelReady) return;
    if (coloring) viewer.setColors(coloring.colors);
    else if (colorChoice === null) viewer.clearColors();
  }, [viewer, modelReady, coloring, colorChoice]);

  const canIsolate = isolated || hasSelection || (resultIds?.length ?? 0) > 0;
  const toggleIsolate = () => { setIsolated(!isolated); };

  const pickMark = (markId: number) => {
    const mark = marksById.get(markId); // a marca inteira (a linha pode contar só parte)
    const first = mark?.dbids[0];
    if (!mark || first === undefined) return;
    setPieceFocus(null);
    setSelection({ marks: [mark], unmarked: [], focus: first });
    viewer?.fitTo(mark.dbids);
    if (relinkFrom) setRelinkTarget(mark);
  };
  const pickPieces = (dbids: number[]) => {
    if (dbids.length === 0) return;
    setSelection({ marks: [], unmarked: dbids, focus: dbids[0] ?? null });
    viewer?.fitTo(dbids);
  };
  const selectAll = (markIds: number[]) => {
    const wanted = new Set(markIds);
    const all = (marks.data ?? []).filter((m) => wanted.has(m.mark_id));
    setSelection({ marks: all, unmarked: [], focus: all[0]?.dbids[0] ?? null });
  };
  const selectedMarkIds = useMemo(() => new Set(selection.marks.map((m) => m.mark_id)), [selection]);

  let overlay: string | null = null;
  if (versions.isPending) overlay = 'Carregando versões…';
  else if (versions.isError) overlay = errorMessage(versions.error);
  else if (!active) overlay = 'Nenhuma versão pronta para visualizar. Veja a aba Versões.';
  else if (load.kind === 'loading') overlay = 'Carregando modelo…';
  else if (load.kind === 'error') overlay = load.message;

  // Ferramentas de seleção: vivem na barra única do visualizador (rótulo curto, nome completo no aria-label).
  const selectionTools = (
    <>
      <button
        type="button"
        aria-label="Enquadrar seleção"
        disabled={!modelReady || !hasSelection}
        onClick={() => { viewer?.fitTo(selectedIds); }}
      >
        Enquadrar
      </button>
      <button type="button" aria-pressed={isolated} disabled={!modelReady || !canIsolate} onClick={toggleIsolate}>
        Isolar
      </button>
      <button
        type="button"
        aria-label="Limpar seleção"
        disabled={!modelReady || !hasSelection}
        onClick={() => { setSelection(EMPTY_SELECTION); }}
      >
        Limpar
      </button>
      <button
        type="button"
        aria-label="Seleção múltipla"
        aria-pressed={multi}
        title="Acumula marcas a cada toque. No computador, Ctrl+clique faz o mesmo."
        disabled={!modelReady}
        onClick={() => { setMulti(!multi); }}
      >
        Múltipla
      </button>
    </>
  );

  return (
    <div className="model-page">
      <div className="model-bar">
        <Link to="/obras" className="small back-link"><Icon name="chevron-left" size={12} />Obras</Link>
        <div className="model-bar__item">
          <small>Obra</small>
          <strong>{obra.data ? `${obra.data.code} — ${obra.data.name}` : '…'}</strong>
        </div>
        <label className="model-bar__item">
          <small>Versão ativa</small>
          <select
            aria-label="Versão ativa"
            value={active?.id ?? ''}
            disabled={viewable.length === 0}
            onChange={(e) => { goVersion(Number(e.target.value)); }}
          >
            {viewable.length === 0 && <option value="">—</option>}
            {viewable.map((v, i) => (
              <option key={v.id} value={v.id}>
                {versionLabel(v, i === 0)}
              </option>
            ))}
          </select>
        </label>
        <span className="model-bar__spacer" />
        {active && (
          <ExportButton
            obraId={obraId}
            versionId={active.id}
            filter={filterState.active ? filterState.definition : null}
            viewer={viewer}
            modelReady={modelReady}
            pieceDbIds={pieceDbIds}
            centroidsStored={
              centroids.status !== undefined &&
              centroids.status.pieces > 0 &&
              centroids.status.stored >= centroids.status.pieces
            }
          />
        )}
        <NumberingNotice numbering={obra.data?.unit_numbering} state={centroids.state} />
        <Link to={`/obras/${obraId}/versoes`} className="small">Versões e validação</Link>
      </div>

      <div className="model-banner-slot">
        {consulting && (
          <div className="consult-banner" role="region" aria-label="Modo consulta">
            <span>
              Visualizando <b>{versionName(active.version_number)}</b> · somente leitura
            </span>
            <button type="button" onClick={() => { goVersion(latest.id); }}>
              Voltar para a versão ativa
            </button>
          </div>
        )}
        {newVersion && (
          <div className="version-banner version-banner--new" role="region" aria-label="Nova versão disponível">
            <span>
              <b>Nova versão disponível:</b> {versionName(newVersion.versionNumber)} acabou de ficar pronta.
            </span>
            <button
              type="button"
              onClick={() => {
                goVersion(newVersion.versionId);
                realtime.clearNewVersion();
              }}
            >
              Carregar
            </button>
            <button
              type="button"
              className="link version-banner__close"
              aria-label="Fechar aviso de nova versão"
              onClick={realtime.clearNewVersion}
            >
              <Icon name="close" />
            </button>
          </div>
        )}
        {active && (
          <VersionBanner
            versionId={active.id}
            onShowNew={() => { applySystemFilter('new'); }}
            onShowReview={() => { applySystemFilter('review'); }}
            onShowOrphans={() => { setShowOrphans(true); }}
            onShowUnitOrphans={() => { setShowUnitOrphans(true); }}
          />
        )}
        {relinkDone && (
          <div className="version-banner" role="status">
            {relinkDone}
            <button type="button" className="link version-banner__close" aria-label="Fechar aviso" onClick={() => { setRelinkDone(null); }}>
              <Icon name="close" />
            </button>
          </div>
        )}
      </div>

      <div className={`model-cols${panels.left ? '' : ' hide-left'}${panels.right ? '' : ' hide-right'}`}>
        <aside id="painel-esquerdo" className="model-left" aria-label="Marcas e filtros" hidden={!panels.left}>
          <h2 className="sr-only">Marcas e filtros</h2>
          {active ? (
            <>
              <ManageMenu
                summary={
                  paramDefs.data
                    ? `${plural(paramDefs.data.length, 'parâmetro', 'parâmetros')} no catálogo desta obra.`
                    : paramDefs.isError
                      ? errorMessage(paramDefs.error)
                      : 'Carregando…'
                }
                canEditParams={canEditParams}
                onNewParam={() => { setDialog({ kind: 'new', category: null }); }}
                onCatalog={() => { setDialog({ kind: 'catalog' }); }}
                onMarkOrphans={() => { setShowOrphans(true); }}
                onUnitOrphans={() => { setShowUnitOrphans(true); }}
              />
              <FilterResultList
                statusById={statusById}
                marks={marks.data ?? []}
                evaluation={result}
                filtered={filterState.active}
                loading={filterState.loading}
                error={filterState.error ?? (marks.isError ? marks.error : null)}
                selectedMarkIds={selectedMarkIds}
                onPickMark={pickMark}
                onPickPieces={pickPieces}
                onSelectAll={selectAll}
              />
            </>
          ) : (
            <div className="model-sec">
              <p className="muted small">Nenhuma versão pronta.</p>
            </div>
          )}
        </aside>

        <section className="model-viewer" aria-label="Modelo 3D" data-load={load.kind}>
          <div ref={canvasRef} className="model-viewer__canvas" data-testid="viewer-container" />
          <button
            type="button"
            className="panel-toggle panel-toggle--left"
            aria-controls="painel-esquerdo"
            aria-expanded={panels.left}
            aria-label={panels.left ? 'Esconder painel esquerdo' : 'Mostrar painel esquerdo'}
            title={panels.left ? 'Esconder marcas e filtros' : 'Mostrar marcas e filtros'}
            onClick={() => { togglePanel('left'); }}
          >
            <Icon name={panels.left ? 'chevron-left' : 'chevron-right'} size={18} />
          </button>
          <button
            type="button"
            className="panel-toggle panel-toggle--right"
            aria-controls="painel-direito"
            aria-expanded={panels.right}
            aria-label={panels.right ? 'Esconder painel direito' : 'Mostrar painel direito'}
            title={panels.right ? 'Esconder o painel da peça' : 'Mostrar o painel da peça'}
            onClick={() => { togglePanel('right'); }}
          >
            <Icon name={panels.right ? 'chevron-right' : 'chevron-left'} size={18} />
          </button>
          {overlay && (
            <div className={`model-viewer__overlay${load.kind === 'error' || versions.isError ? ' error' : ''}`} role="status">
              {overlay}
            </div>
          )}
          {relinkFrom && (
            <div className="relink-bar" role="status" aria-label="Religar órfã">
              <span>
                Religar <b>{relinkFrom.code}</b>: clique na marca de destino no 3D ou na lista.
              </span>
              <button type="button" className="secondary" onClick={() => { setRelinkFrom(null); setRelinkTarget(null); }}>
                Cancelar
              </button>
            </div>
          )}
          {active && (
            <ViewerToolbar
              disabled={!modelReady}
              filterActive={filterState.active}
              filtering={filterState.loading}
              coloringActive={colorChoice !== null}
              onFitAll={() => { viewer?.fitTo(); }}
              onClearFilter={filterState.clear}
              onClearColoring={() => { setColorChoice(null); }}
              selectionTools={selectionTools}
              storageKey={`viewer-bar:${me.data ? String(me.data.id) : 'anon'}`}
              filterPopover={
                <FilterPopover
                  obraId={obraId}
                  versionId={active.id}
                  fields={fields.data ?? []}
                  fieldsError={fields.isError ? fields.error : null}
                  state={filterState}
                  me={me.data}
                />
              }
              colorPopover={
                <ColorPopover
                  fields={fields.data ?? []}
                  choice={colorChoice}
                  onChoose={setColorChoice}
                  onEditColors={() => { setShowColors(true); }}
                />
              }
            />
          )}
          {modelReady && coloring && (
            <ColorLegend
              coloring={coloring}
              onPick={(item) => { setSelection(selectPieces(item.dbids, index)); }}
              storageKey={`legend:${me.data ? String(me.data.id) : 'anon'}`}
            />
          )}
          {modelReady && coloringError !== null && (
            <div className="coloring-error error small" role="alert">
              {errorMessage(coloringError)}
            </div>
          )}
        </section>

        <aside id="painel-direito" className="model-right" aria-label="Peça selecionada" hidden={!panels.right}>
          <h2 className="sr-only">Peça selecionada</h2>
          {active ? (
            <PiecePanel
              versionId={active.id}
              selection={selection}
              statusById={statusById}
              obraId={obraId}
              canEditParams={canEditParams}
              activeLabel={consulting ? versionName(latest.version_number) : null}
              onNewParam={(category) => { setDialog({ kind: 'new', category }); }}
              onPickPiece={pickPiece}
              axis={axis}
              onUnitBatchApplied={(r) => {
                const n = r.units_changed;
                setUndo(
                  r.batch_id
                    ? { batchId: r.batch_id, text: `Valores aplicados a ${n.toLocaleString('pt-BR')} ${n === 1 ? 'peça' : 'peças'}.` }
                    : null,
                );
              }}
              onBatchApplied={(r) => {
                const n = r.marks_changed;
                setUndo(
                  r.batch_id
                    ? { batchId: r.batch_id, text: `Valores aplicados a ${n.toLocaleString('pt-BR')} ${n === 1 ? 'marca' : 'marcas'}.` }
                    : null,
                );
              }}
            />
          ) : (
            <div className="model-sec">
              <p className="muted">Nenhuma versão pronta.</p>
            </div>
          )}
        </aside>
      </div>
      {active && (
        <ProgressFooter versionId={active.id} label={`${obra.data?.code ?? ''} · ${versionName(active.version_number)}`} />
      )}
      <LiveNotices notices={realtime.notices} onDismiss={realtime.dismiss} />
      {undo && <UndoToast key={undo.batchId} batchId={undo.batchId} text={undo.text} onClose={closeUndo} />}
      {showOrphans && (
        <OrphansDialog
          obraId={obraId}
          canEdit={canEditParams}
          onClose={() => { setShowOrphans(false); }}
          onRelink={(o) => {
            setShowOrphans(false);
            setRelinkDone(null);
            setRelinkTarget(null);
            setRelinkFrom(o);
          }}
        />
      )}
      {showUnitOrphans && latest && (
        <UnitOrphansDialog
          obraId={obraId}
          versionId={latest.id}
          canEdit={canEditParams}
          onClose={() => { setShowUnitOrphans(false); }}
          onRelinked={(r) => {
            setShowUnitOrphans(false);
            setRelinkDone(
              `${r.label} religada à peça que era da ${r.displaced_label}: os valores voltaram.` +
                (r.displaced_status === 'orphan' ? ` ${r.displaced_label} foi para a fila de peças órfãs.` : ''),
            );
          }}
        />
      )}
      {relinkFrom && relinkTarget && (
        <RelinkConfirm
          orphan={relinkFrom}
          target={relinkTarget}
          onCancel={() => { setRelinkTarget(null); }}
          onDone={(r) => {
            const n = r.copied.length;
            setRelinkDone(
              `${relinkFrom.code} religada a ${relinkTarget.code}: ${String(n)} ${n === 1 ? 'valor copiado' : 'valores copiados'}.` +
                (r.skipped.length ? ` Não se aplicam a ${relinkTarget.category}: ${r.skipped.join(', ')}.` : ''),
            );
            setRelinkFrom(null);
            setRelinkTarget(null);
          }}
        />
      )}
      {showColors && active && (
        <ColorRulesDialog
          obraId={obraId}
          versionId={active.id}
          fields={fields.data ?? []}
          me={me.data}
          currentSchemeId={colorChoice?.kind === 'scheme' ? colorChoice.schemeId : null}
          onClose={() => { setShowColors(false); }}
          onApply={(scheme) => {
            setColorChoice({ kind: 'scheme', schemeId: scheme.id, name: scheme.name });
            setShowColors(false);
          }}
        />
      )}
      {dialog?.kind === 'catalog' && (
        <CatalogDialog
          obraId={obraId}
          canEdit={canEditParams}
          onClose={() => { setDialog(null); }}
          onNew={() => { setDialog({ kind: 'new', category: null }); }}
          onEdit={(param) => { setDialog({ kind: 'edit', param }); }}
        />
      )}
      {(dialog?.kind === 'new' || dialog?.kind === 'edit') && (
        <ParamDefDialog
          obraId={obraId}
          obraCode={obra.data?.code ?? null}
          categories={versionCategories}
          {...(dialog.kind === 'edit' ? { param: dialog.param } : { presetCategory: dialog.category })}
          onClose={() => { setDialog(null); }}
        />
      )}
    </div>
  );
}
