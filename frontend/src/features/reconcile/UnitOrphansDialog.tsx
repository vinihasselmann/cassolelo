import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiError } from '../../api/client';
import {
  archiveUnit,
  fetchMarkUnits,
  fetchUnitOrphans,
  markUnitsKey,
  relinkUnit,
  unitOrphansKey,
  type PieceUnit,
  type UnitOrphan,
  type UnitRelinkResult,
} from '../../api/units';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { rowsOf, shortId } from '../pecas/unitTable';
import { invalidateValueQueries } from '../params/invalidate';
import { describeValues } from './orphanText';


const filled = (u: PieceUnit) => u.values.some((v) => v.value !== null && v.value !== '');

interface ChooserProps {
  obraId: number;
  versionId: number;
  orphan: UnitOrphan;
  onCancel: () => void;
  onDone: (r: UnitRelinkResult) => void;
}

/** Religar: escolher a peça da mesma marca (versão ativa) que passa a ser desta unidade. */
function TargetChooser({ obraId, versionId, orphan, onCancel, onDone }: ChooserProps) {
  const queryClient = useQueryClient();
  const units = useQuery({
    queryKey: markUnitsKey(obraId, orphan.mark_id, versionId),
    queryFn: () => fetchMarkUnits(obraId, orphan.mark_id, versionId),
    retry: false,
  });
  const [pending, setPending] = useState<PieceUnit | null>(null); // destino com valores: confirmar
  const relink = useMutation({
    mutationFn: ({ target, confirm }: { target: PieceUnit; confirm: boolean }) =>
      relinkUnit(obraId, orphan.id, target.id, confirm),
    onSuccess: async (r) => {
      await invalidateValueQueries(queryClient);
      onDone(r);
    },
    onError: (err, { target }) => {
      if (err instanceof ApiError && err.status === 409 && err.code === 'unit_relink_conflict') setPending(target);
    },
  });
  const rows = rowsOf(units.data?.units ?? []);
  const conflict = relink.error instanceof ApiError && relink.error.code === 'unit_relink_conflict';

  return (
    <div className="unit-chooser" role="group" aria-label={`Religar ${orphan.label}`}>
      <p className="small">
        Escolha a peça de <b>{orphan.code}</b> que passa a ser a <b>{orphan.label}</b> (ela recupera os valores). A unidade que
        está nessa peça sai dela; nada é apagado.
      </p>
      {units.isPending && <p className="muted small">Carregando…</p>}
      {units.isError && <p role="alert" className="error small">{errorMessage(units.error)}</p>}
      {rows.length > 0 && !pending && (
        <ul className="unit-targets" aria-label={`Peças de ${orphan.code}`}>
          {rows.map((u) => (
            <li key={u.id}>
              <button
                type="button"
                className="secondary"
                disabled={relink.isPending}
                onClick={() => { relink.mutate({ target: u, confirm: false }); }}
              >
                <b>{u.label}</b> · {u.element?.level ?? '—'} · {shortId(u)} · {filled(u) ? 'com valores' : 'vazia'}
              </button>
            </li>
          ))}
        </ul>
      )}
      {pending && (
        <div className="alert alert--warn" role="alert">
          <b>{pending.label}</b> já tem valores. Se continuar, a {orphan.label} fica com a peça e a {pending.label} vai para a fila
          de órfãs (com os valores dela).
          <div className="btn-row">
            <button type="button" disabled={relink.isPending} onClick={() => { relink.mutate({ target: pending, confirm: true }); }}>
              Religar mesmo assim
            </button>
            <button type="button" className="secondary" onClick={() => { setPending(null); relink.reset(); }}>
              Escolher outra
            </button>
          </div>
        </div>
      )}
      {relink.isError && !conflict && <p role="alert" className="error small">{errorMessage(relink.error)}</p>}
      <div className="btn-row">
        <button type="button" className="link" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

interface Props {
  obraId: number;
  /** Versão ativa (a pronta mais recente): onde a peça de destino está. */
  versionId: number;
  canEdit: boolean;
  onClose: () => void;
  onRelinked: (r: UnitRelinkResult) => void;
}

/** Janela "Peças órfãs": unidades de peça que ficaram sem peça no modelo com valores. */
export function UnitOrphansDialog({ obraId, versionId, canEdit, onClose, onRelinked }: Props) {
  const queryClient = useQueryClient();
  const orphans = useQuery({ queryKey: unitOrphansKey(obraId), queryFn: () => fetchUnitOrphans(obraId), retry: false });
  const [relinking, setRelinking] = useState<number | null>(null);
  const archive = useMutation({
    mutationFn: (o: UnitOrphan) => archiveUnit(obraId, o.id),
    onSuccess: () => invalidateValueQueries(queryClient),
  });

  function confirmArchive(o: UnitOrphan) {
    if (
      window.confirm(
        `Arquivar a peça órfã ${o.label}?\n\nEla sai da fila e não é ligada a outra peça. Os valores continuam guardados, e ela volta sozinha se a peça reaparecer no modelo.`,
      )
    ) {
      archive.mutate(o);
    }
  }

  return (
    <Modal title="Peças órfãs" onClose={onClose} wide>
      <p className="muted small">
        Peças numeradas que sumiram do modelo e tinham valores por peça. Religue a outra peça da mesma marca (os valores
        voltam com ela) ou arquive. Nada é apagado.
        {!canEdit && ' Somente a fábrica religa e arquiva.'}
      </p>
      {orphans.isPending && <p className="muted">Carregando…</p>}
      {orphans.isError && <p role="alert" className="error">{errorMessage(orphans.error)}</p>}
      {archive.isError && <p role="alert" className="error">{errorMessage(archive.error)}</p>}
      {orphans.data?.length === 0 && <p><b>Nenhuma peça órfã pendente.</b></p>}
      {orphans.data && orphans.data.length > 0 && (
        <ul className="orphan-list" aria-label="Peças órfãs abertas">
          {orphans.data.map((o) => (
            <li key={o.id}>
              <div>
                <b>{o.label}</b> · {o.category}
                <div className="hint">
                  {o.since_version_number !== null ? `Sem peça desde a versão ${String(o.since_version_number)}` : 'Sem peça'}
                  {o.external_id && <> · última chave …{o.external_id.slice(-8)}</>}
                </div>
                <div className="small">{describeValues(o)}</div>
                {relinking === o.id && (
                  <TargetChooser
                    obraId={obraId}
                    versionId={versionId}
                    orphan={o}
                    onCancel={() => { setRelinking(null); }}
                    onDone={(r) => {
                      setRelinking(null);
                      onRelinked(r);
                    }}
                  />
                )}
                {!o.mark_in_model && (
                  <div className="hint">A marca {o.code} não está no modelo atual: só é possível arquivar.</div>
                )}
              </div>
              {canEdit && relinking !== o.id && (
                <div className="btn-row">
                  <button
                    type="button"
                    aria-label={`Religar ${o.label}`}
                    disabled={!o.mark_in_model}
                    onClick={() => { setRelinking(o.id); }}
                  >
                    Religar
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    aria-label={`Arquivar ${o.label}`}
                    disabled={archive.isPending}
                    onClick={() => { confirmArchive(o); }}
                  >
                    Arquivar
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          Fechar
        </button>
      </div>
    </Modal>
  );
}
