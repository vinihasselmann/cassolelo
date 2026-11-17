import { useQuery } from '@tanstack/react-query';

import { fetchProgress, progressKey } from '../../api/status';
import { errorMessage } from '../../lib/errors';

const num = (n: number) => n.toLocaleString('pt-BR');
const pct = (done: number, total: number) => (total > 0 ? Math.round((done / total) * 100) : 0);

/** Rodapé: progresso de cada parâmetro obrigatório (marcas e peças) e totais da versão. */
export function ProgressFooter({ versionId, label }: { versionId: number; label: string }) {
  const progress = useQuery({
    queryKey: progressKey(versionId),
    queryFn: () => fetchProgress(versionId),
    retry: false,
  });
  const data = progress.data;
  return (
    <section className="model-foot" aria-label="Progresso">
      {progress.isError && <span className="error small">{errorMessage(progress.error)}</span>}
      {data && data.required.length === 0 && (
        <span className="muted">
          Nenhum parâmetro obrigatório. Marque um como obrigatório (Gerenciar › Catálogo) para ver o progresso aqui.
        </span>
      )}
      {data?.required.map((p) => {
        const value = pct(p.marks_filled, p.marks_total);
        return (
          <div key={p.def_id} className="prog">
            <b>{p.name}</b>
            <div
              className="prog__bar"
              role="progressbar"
              aria-label={`Progresso de ${p.name}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={value}
            >
              <i style={{ width: `${String(value)}%` }} />
            </div>
            <span>
              {num(p.marks_filled)}/{num(p.marks_total)} marcas · {num(p.pieces_filled)}/{num(p.pieces_total)} peças ({value}%)
            </span>
          </div>
        );
      })}
      {data && (
        <span className="model-foot__total">
          {label} · {num(data.marks)} marcas · {num(data.pieces)} peças
        </span>
      )}
    </section>
  );
}
