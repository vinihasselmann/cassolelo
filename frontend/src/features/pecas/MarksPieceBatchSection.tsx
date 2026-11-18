import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { fetchUnitsOfMarks, previewUnitBatch, type UnitBatchResult } from '../../api/units';
import { errorMessage } from '../../lib/errors';
import { UnitBatchDialog } from './UnitBatchDialog';

const num = (n: number) => n.toLocaleString('pt-BR');
const SHOWN = 3;

interface Props {
  obraId: number;
  versionId: number;
  markIds: number[];
  /** peças sem marca na seleção: ficam de fora (não têm peça numerada) */
  unmarked: number;
  canEdit: boolean;
  onApplied: (result: UnitBatchResult) => void;
}

/**
 * Várias marcas selecionadas (ex.: Tipo > Pilar): preencher um parâmetro POR PEÇA em todas
 * as peças delas de uma vez (2026-11-18). Usa o mesmo diálogo de lote da tabela por peça.
 */
export function MarksPieceBatchSection({ obraId, versionId, markIds, unmarked, canEdit, onApplied }: Props) {
  const [open, setOpen] = useState(false);
  const ids = [...markIds].sort((a, b) => a - b);
  const units = useQuery({
    queryKey: ['units-of-marks', obraId, versionId, ids.join(',')],
    queryFn: () => fetchUnitsOfMarks(obraId, versionId, ids),
    retry: false,
  });
  const unitIds = (units.data ?? []).map((u) => u.unit_id);
  // mesma chave do diálogo: o resumo (campos que valem) é aproveitado ao abrir
  const fields = useQuery({
    queryKey: ['unit-batch', obraId, [...unitIds].sort((a, b) => a - b).join(',')],
    queryFn: () => previewUnitBatch(obraId, { unit_ids: unitIds, changes: {}, mode: 'overwrite' }),
    enabled: unitIds.length > 0,
    retry: false,
  });

  const list = units.data ?? [];
  const marks = new Set(list.map((u) => u.mark_id)).size;
  const labels = list.map((u) => u.label);
  const rest = labels.length - SHOWN;
  const summary =
    `${num(list.length)} ${list.length === 1 ? 'peça' : 'peças'} de ${num(marks)} ${marks === 1 ? 'marca' : 'marcas'} ` +
    `(${labels.slice(0, SHOWN).join(', ')}${rest > 0 ? `… e mais ${num(rest)}` : ''})`;
  const noParams = fields.data !== undefined && fields.data.fields.length === 0;

  return (
    <section className="factory-sub" aria-labelledby="marks-piece-params">
      <h5 id="marks-piece-params">Parâmetros por peça</h5>
      {(units.isPending || fields.isFetching) && <p className="muted small">Carregando…</p>}
      {units.isError && <p role="alert" className="error small">{errorMessage(units.error)}</p>}
      {units.data && list.length === 0 && (
        <p className="muted small">Nenhuma peça numerada destas marcas nesta versão.</p>
      )}
      {list.length > 0 && noParams && (
        <p className="muted small">Nenhum parâmetro por peça para estas categorias.</p>
      )}
      {list.length > 0 && fields.data && !noParams && (
        <div className="reshead">
          <span className="small">
            {num(list.length)} {list.length === 1 ? 'peça' : 'peças'} de {num(marks)} {marks === 1 ? 'marca' : 'marcas'}
          </span>
          {canEdit && (
            <button type="button" className="secondary" onClick={() => { setOpen(true); }}>
              Preencher todas as peças
            </button>
          )}
        </div>
      )}
      {unmarked > 0 && (
        <p className="hint">
          {unmarked === 1 ? '1 peça sem marca ignorada' : `${num(unmarked)} peças sem marca ignoradas`} (não têm peça numerada).
        </p>
      )}
      {open && (
        <UnitBatchDialog
          obraId={obraId}
          unitIds={unitIds}
          labels={labels}
          summary={summary}
          onClose={() => { setOpen(false); }}
          onApplied={onApplied}
        />
      )}
    </section>
  );
}
