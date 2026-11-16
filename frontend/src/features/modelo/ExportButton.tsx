import { useMutation } from '@tanstack/react-query';

import { downloadObraExcel } from '../../api/export';
import type { FilterDefinition } from '../../api/filters';
import { errorMessage } from '../../lib/errors';

interface Props {
  obraId: number;
  versionId: number;
  /** Filtro da tela (null = sem filtro): o Excel traz só o resultado, como a lista. */
  filter: FilterDefinition | null;
}

/** "Exportar Excel": as marcas da lista (versão aberta + filtro ativo) e as peças. */
export function ExportButton({ obraId, versionId, filter }: Props) {
  const exporter = useMutation({ mutationFn: () => downloadObraExcel(obraId, versionId, filter) });
  const filtered = filter !== null;
  return (
    <span className="export">
      <button
        type="button"
        className="secondary"
        disabled={exporter.isPending}
        title={filtered ? 'Exporta só as marcas da lista (filtro ativo)' : 'Exporta todas as marcas da versão aberta'}
        onClick={() => { exporter.mutate(); }}
      >
        {exporter.isPending ? 'Gerando…' : 'Exportar Excel'}
      </button>
      {filtered && <span className="hint">com o filtro ativo</span>}
      {exporter.isError && (
        <span role="alert" className="error small">
          {errorMessage(exporter.error)}
        </span>
      )}
    </span>
  );
}
