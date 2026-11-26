import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type ChangeEvent } from 'react';

import {
  applyImport,
  previewImport,
  type ImportApplied,
  type ImportChange,
  type ImportIssue,
  type ImportPreview,
  type PlannixPreview,
} from '../../api/excelImport';
import { Modal } from '../../components/Modal';
import { errorMessage } from '../../lib/errors';
import { formatValue, plural } from '../../lib/format';
import { invalidateValueQueries } from '../params/invalidate';

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Valor para a prévia: datas em dd/mm/aaaa, sim/não, vazio = —. */
function show(value: unknown): string {
  if (value === true) return 'Sim';
  if (value === false) return 'Não';
  if (typeof value === 'string') {
    const m = ISO_DATE.exec(value);
    if (m) return `${m[3] ?? ''}/${m[2] ?? ''}/${m[1] ?? ''}`;
  }
  return formatValue(value);
}

const where = (i: { sheet: string; row: number | null; column?: string | null }) =>
  [i.sheet, i.row ? `linha ${String(i.row)}` : null, i.column].filter(Boolean).join(' · ');

function IssueList({ items, total, className }: { items: ImportIssue[]; total: number; className: string }) {
  return (
    <ul className={`import__issues ${className}`}>
      {items.map((i, k) => (
        <li key={k}>
          <span className="import__where">{where(i)}</span> {i.message}
        </li>
      ))}
      {total > items.length && <li className="muted">… e mais {total - items.length}.</li>}
    </ul>
  );
}

function ChangeTable({
  items,
  total,
  caption,
  source = 'No arquivo',
}: {
  items: ImportChange[];
  total: number;
  caption: string;
  source?: string;
}) {
  return (
    <div className="import__table">
      <table className="table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th>Linha</th>
            <th>Marca / peça</th>
            <th>Parâmetro</th>
            <th>No app</th>
            <th>{source}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={`${c.sheet}-${String(c.row)}-${c.param}`}>
              <td className="muted">{`${c.sheet} ${String(c.row)}`}</td>
              <td>{c.target}</td>
              <td>{c.param}</td>
              <td className="muted">{show(c.old)}</td>
              <td>
                {c.new === null ? <em className="muted">apagar</em> : <strong>{show(c.new)}</strong>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > items.length && <p className="hint">Mostrando {items.length} de {total}.</p>}
    </div>
  );
}

/** O que só a planilha do Plannix tem: peças ligadas, recusadas, conferir, fora do modelo. */
function PlannixSummary({ px }: { px: PlannixPreview }) {
  return (
    <>
      <p className="hint" data-testid="plannix-summary">
        Planilha do Plannix · {plural(px.rows, 'peça lida', 'peças lidas')} ·{' '}
        {plural(px.linked, 'ligada', 'ligadas')} a peças do modelo
        {px.new_links > 0 && ` (${plural(px.new_links, 'nova', 'novas')})`}
        {px.rejected > 0 && ` · ${plural(px.rejected, 'recusada ignorada', 'recusadas ignoradas')}`}
        {px.leftovers > 0 && ` · ${plural(px.leftovers, 'sem peça', 'sem peça')} no modelo`}
      </p>
      <p className="hint">
        O Plannix manda nestas datas: valores diferentes são substituídos e célula vazia apaga. Na tela elas
        ficam só leitura.
      </p>
      {px.new_params.length > 0 && (
        <p className="hint">Parâmetros a criar na biblioteca (por peça, data): {px.new_params.join(', ')}.</p>
      )}
      {px.check_marks.length > 0 && (
        <details className="import__block" open>
          <summary>{plural(px.check_marks.length, 'marca', 'marcas')} com quantidade diferente (conferir)</summary>
          <ul className="import__issues">
            {px.check_marks.map((m) => (
              <li key={m.code}>
                <strong>{m.code}</strong>: {String(m.plannix)} no Plannix, {String(m.model)} no modelo
              </li>
            ))}
          </ul>
        </details>
      )}
      {px.outside_model.length > 0 && (
        <details className="import__block">
          <summary>{plural(px.outside_model.length, 'marca', 'marcas')} da planilha fora deste modelo</summary>
          <p className="import__issues">
            {px.outside_model.map((m) => `${m.code} (${String(m.rows)})`).join(', ')}
          </p>
        </details>
      )}
    </>
  );
}

interface DialogProps {
  obraId: number;
  onClose: () => void;
  /** gravou: o lote (para o "Desfazer") e o texto do aviso */
  onApplied: (batchId: string, text: string) => void;
}

/**
 * Importar valores pelo Excel exportado pelo app: escolhe o arquivo, vê a prévia (nada é
 * gravado) e aplica. Por padrão só preenche campos vazios; "também alterar" grava os
 * valores diferentes. Célula vazia no arquivo nunca apaga. Linhas com erro ficam de fora.
 *
 * Planilha do Plannix (o servidor reconhece, 2026-11-24): datas das etapas de produção,
 * por peça. Sempre sobrescreve e célula vazia apaga (sem "também alterar").
 */
export function ImportExcelDialog({ obraId, onClose, onApplied }: DialogProps) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);

  const preview = useMutation({ mutationFn: (f: File) => previewImport(obraId, f) });
  const apply = useMutation({
    mutationFn: ({ f, p }: { f: File; p: ImportPreview }) => applyImport(obraId, f, p.fingerprint, overwrite),
    onSuccess: async (r: ImportApplied) => {
      await invalidateValueQueries(queryClient);
      if (r.batch_id) {
        const parts = [
          r.marks_changed > 0 ? plural(r.marks_changed, 'marca', 'marcas') : null,
          r.units_changed > 0 ? plural(r.units_changed, 'peça', 'peças') : null,
        ].filter(Boolean);
        const what = preview.data?.plannix ? 'Importação do Plannix' : 'Importação';
        onApplied(r.batch_id, `${what}: ${plural(r.fields_changed, 'valor gravado', 'valores gravados')} (${parts.join(', ')}).`);
      }
      onClose();
    },
  });

  const choose = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setOverwrite(false);
    apply.reset();
    if (f) preview.mutate(f);
    else preview.reset();
  };

  const p = preview.data;
  const px = p?.plannix ?? null;
  // o Plannix sempre sobrescreve (e célula vazia apaga)
  const toApply = p ? p.fills + (overwrite || px ? p.changes : 0) : 0;
  const canApply = toApply > 0 || (px?.new_links ?? 0) > 0;
  // 409 (alguém gravou depois da prévia): refaz a prévia com o mesmo arquivo
  const stale = apply.error !== null && (apply.error as { status?: number }).status === 409;

  return (
    <Modal title="Importar valores do Excel" onClose={onClose} wide>
      <div className="import">
        <p className="hint">
          Use o Excel exportado pelo app (preencha as colunas dos parâmetros e envie de volta; célula vazia
          não apaga nada) ou a planilha exportada do Plannix (datas das etapas de produção). Você vê o que muda
          antes de gravar.
        </p>
        <label className="field">
          <span>Arquivo (.xlsx)</span>
          <input
            ref={input}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={choose}
          />
        </label>

        {preview.isPending && <p className="muted" role="status">Lendo o arquivo…</p>}
        {preview.isError && (
          <p role="alert" className="error">
            {errorMessage(preview.error)}
          </p>
        )}

        {p && (
          <section aria-label="Prévia da importação">
            <p className="import__summary" data-testid="import-summary">
              Obra <strong>{p.obra_code}</strong>
              {p.file_version ? ` · arquivo da ${p.file_version}` : ''} ·{' '}
              <strong>{plural(p.fills, 'campo a preencher', 'campos a preencher')}</strong>
              {p.changes > 0 && <> · {plural(p.changes, 'valor diferente', 'valores diferentes')} do app</>}
              {px && (p.clears ?? 0) > 0 && <> ({plural(p.clears ?? 0, 'a apagar', 'a apagar')})</>}
              {p.unchanged > 0 && <> · {plural(p.unchanged, 'igual', 'iguais')}</>}
              {p.errors.length > 0 && (
                <> · <span className="error">{plural(p.errors.length, 'erro', 'erros')}</span></>
              )}
            </p>

            {px && <PlannixSummary px={px} />}

            {p.params.length > 0 && (
              <ul className="import__params">
                {p.params.map((s) => (
                  <li key={s.def_id}>
                    <strong>{s.name}</strong> <span className="muted">({s.level === 'piece' ? 'por peça' : 'por marca'})</span>:{' '}
                    {plural(s.fills, 'a preencher', 'a preencher')}
                    {s.changes > 0 && `, ${plural(s.changes, 'diferente', 'diferentes')}`}
                  </li>
                ))}
              </ul>
            )}

            {p.errors.length > 0 && (
              <details className="import__block" open>
                <summary>
                  {plural(p.errors.length, 'linha recusada', 'linhas recusadas')} (não serão gravadas)
                </summary>
                <IssueList items={p.errors} total={p.errors.length} className="import__issues--error" />
              </details>
            )}
            {p.warnings.length > 0 && (
              <details className="import__block" open>
                <summary>{plural(p.warnings.length, 'aviso', 'avisos')} para conferir</summary>
                <IssueList items={p.warnings} total={p.warnings.length} className="" />
              </details>
            )}
            {p.fills > 0 && (
              <details className="import__block">
                <summary>{p.fills === 1 ? 'Ver o campo a preencher' : `Ver os ${plural(p.fills, 'campo', 'campos')} a preencher`}</summary>
                <ChangeTable
                  items={p.fill_items}
                  total={p.fills}
                  caption="Campos a preencher"
                  source={px ? 'No Plannix' : 'No arquivo'}
                />
              </details>
            )}
            {p.changes > 0 && (
              <details className="import__block">
                <summary>{p.changes === 1 ? 'Ver o valor diferente do app' : `Ver os ${plural(p.changes, 'valor', 'valores')} diferentes do app`}</summary>
                <ChangeTable
                  items={p.change_items}
                  total={p.changes}
                  caption="Valores diferentes do app"
                  source={px ? 'No Plannix' : 'No arquivo'}
                />
              </details>
            )}
            {p.ignored_columns.length > 0 && (
              <p className="hint">Colunas ignoradas (não são parâmetros desta obra): {p.ignored_columns.join(', ')}.</p>
            )}

            {p.changes > 0 && !px && (
              <label className="check">
                <input type="checkbox" checked={overwrite} onChange={(e) => { setOverwrite(e.target.checked); }} />
                {p.changes === 1
                  ? 'Também alterar o valor já preenchido no app'
                  : `Também alterar os ${plural(p.changes, 'valor já preenchido', 'valores já preenchidos')} no app`}
              </label>
            )}
            {!canApply && <p className="muted">Nada para gravar.</p>}
          </section>
        )}

        {apply.isError && (
          <p role="alert" className="error">
            {errorMessage(apply.error)}
          </p>
        )}

        <div className="actions">
          {stale && file ? (
            <button type="button" onClick={() => { apply.reset(); preview.mutate(file); }}>
              Conferir de novo
            </button>
          ) : (
            <button
              type="button"
              disabled={!p || !file || !canApply || apply.isPending}
              onClick={() => { if (file && p) apply.mutate({ f: file, p }); }}
            >
              {apply.isPending
                ? 'Gravando…'
                : toApply === 0 && px && px.new_links > 0
                  ? `Guardar ${plural(px.new_links, 'ligação', 'ligações')}`
                  : `Aplicar ${plural(toApply, 'valor', 'valores')}`}
            </button>
          )}
          <button type="button" className="secondary" onClick={onClose}>
            Cancelar
          </button>
        </div>
      </div>
    </Modal>
  );
}

interface ButtonProps {
  obraId: number;
  onApplied: (batchId: string, text: string) => void;
}

/** "Importar Excel" na barra da obra (só fábrica e admin). */
export function ImportExcelButton({ obraId, onApplied }: ButtonProps) {
  const [open, setOpen] = useState(false);
  return (
    <span className="export">
      <button type="button" className="secondary" onClick={() => { setOpen(true); }}>
        Importar Excel
      </button>
      {open && <ImportExcelDialog obraId={obraId} onClose={() => { setOpen(false); }} onApplied={onApplied} />}
    </span>
  );
}
