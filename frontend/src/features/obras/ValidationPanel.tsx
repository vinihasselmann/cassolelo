import { useQuery } from '@tanstack/react-query';

import { fetchVersionReport, type DimensionDifference } from '../../api/versions';
import { errorMessage } from '../../lib/errors';
import { formatDateTime } from '../../lib/format';

const num = (n: number) => n.toLocaleString('pt-BR');

function plural(n: number, one: string, many: string): string {
  return `${num(n)} ${n === 1 ? one : many}`;
}

function describeDifference(d: DimensionDifference): string {
  const values = d.values.map((v) => `${v.value} (${plural(v.count, 'peça', 'peças')})`).join(', ');
  const diff = d.diff_mm === null ? '' : ` — diferença de ${num(d.diff_mm)} mm`;
  return `${d.property}: ${values}${diff}`;
}

interface Props {
  versionId: number;
  versionNumber: number;
}

/** Painel "Validação" (papel projetos): peças sem Marca, marcas inconsistentes e totais. */
export function ValidationPanel({ versionId, versionNumber }: Props) {
  const query = useQuery({
    queryKey: ['versions', versionId, 'report'],
    queryFn: () => fetchVersionReport(versionId),
    retry: false,
  });

  return (
    <section className="card" aria-labelledby="validation-title">
      <div className="page-head">
        <h3 id="validation-title">Validação — v{versionNumber}</h3>
        {query.data && <Counter report={query.data.report} />}
      </div>

      {query.isPending && <p className="muted">Carregando…</p>}
      {query.isError && (
        <p role="alert" className="error">
          {errorMessage(query.error)}
        </p>
      )}
      {query.data && <ReportBody data={query.data} />}
    </section>
  );
}

function Counter({
  report,
}: {
  report: { totals: { without_mark: number; inconsistent_marks: number; divergent_pieces?: number } };
}) {
  const { without_mark, inconsistent_marks } = report.totals;
  const divergent = report.totals.divergent_pieces ?? 0;
  const total = without_mark + inconsistent_marks + divergent;
  if (total === 0) {
    return <span className="counter counter--ok">Nenhum alerta</span>;
  }
  return (
    <span className="counter counter--warn">
      {plural(total, 'alerta', 'alertas')}: {plural(without_mark, 'peça sem Marca', 'peças sem Marca')},{' '}
      {plural(inconsistent_marks, 'marca inconsistente', 'marcas inconsistentes')}
      {divergent > 0 &&
        `, ${plural(divergent, 'peça com identificadores divergentes', 'peças com identificadores divergentes')}`}
    </span>
  );
}

function ReportBody({ data }: { data: Awaited<ReturnType<typeof fetchVersionReport>> }) {
  const { report } = data;
  const { totals } = report;
  return (
    <>
      <p className="muted small">
        Gerado em {formatDateTime(data.updated_at)}. Dimensões comparadas:{' '}
        {report.config.dimension_property_names.join(', ') || '(nenhuma)'}; tolerância de{' '}
        {num(report.config.tolerance_mm)} mm.
      </p>

      <h4>Totais</h4>
      <p>
        {plural(totals.pieces, 'peça', 'peças')} · {plural(totals.marks, 'marca', 'marcas')}
      </p>
      <table className="table" aria-label="Totais por categoria">
        <thead>
          <tr>
            <th>Categoria</th>
            <th>Peças</th>
            <th>Marcas</th>
            <th>Sem Marca</th>
          </tr>
        </thead>
        <tbody>
          {totals.by_category.map((c) => (
            <tr key={c.category}>
              <td>{c.category}</td>
              <td>{num(c.pieces)}</td>
              <td>{num(c.marks)}</td>
              <td>{num(c.without_mark)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Marcas inconsistentes ({num(report.inconsistent.length)})</h4>
      {report.inconsistent.length === 0 ? (
        <p className="muted">Nenhuma: peças da mesma marca têm as mesmas dimensões.</p>
      ) : (
        <table className="table" aria-label="Marcas inconsistentes">
          <thead>
            <tr>
              <th>Marca</th>
              <th>Categoria</th>
              <th>Peças</th>
              <th>Diferenças</th>
            </tr>
          </thead>
          <tbody>
            {report.inconsistent.map((m) => (
              <tr key={`${m.mark}|${m.category}`}>
                <td>{m.mark}</td>
                <td>{m.category}</td>
                <td>{num(m.pieces)}</td>
                <td>
                  {m.differences.map((d) => (
                    <div key={d.property}>{describeDifference(d)}</div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {report.divergent && report.divergent.length > 0 && (
        <>
          <h4>Identificadores divergentes ({num(report.divergent.length)})</h4>
          <p className="muted small">
            A peça traz valores diferentes nos parâmetros da regra de identificação. Vale o
            primeiro da lista (coluna Marca); os outros servem de apelido na busca.
          </p>
          <table className="table" aria-label="Identificadores divergentes">
            <thead>
              <tr>
                <th>Marca</th>
                <th>Valores no modelo</th>
                <th>Categoria</th>
                <th>dbId</th>
              </tr>
            </thead>
            <tbody>
              {report.divergent.map((p) => (
                <tr key={p.dbid}>
                  <td>{p.mark ?? '—'}</td>
                  <td>{p.values.map((v) => `${v.property}: ${v.value}`).join(' · ')}</td>
                  <td>{p.category}</td>
                  <td>{p.dbid}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h4>Peças sem Marca ({num(report.without_mark.length)})</h4>
      {report.without_mark.length === 0 ? (
        <p className="muted">Todas as peças têm Marca.</p>
      ) : (
        <table className="table" aria-label="Peças sem Marca">
          <thead>
            <tr>
              <th>dbId</th>
              <th>externalId</th>
              <th>Categoria</th>
              <th>Nome</th>
            </tr>
          </thead>
          <tbody>
            {report.without_mark.map((p) => (
              <tr key={p.dbid}>
                <td>{p.dbid}</td>
                <td className="small">{p.external_id ?? '—'}</td>
                <td>{p.category}</td>
                <td>{p.name ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
