import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  fetchMarkCandidates,
  fetchMarkRule,
  saveMarkRule,
  type MarkCandidate,
  type MarkRule,
  type MarkRuleUpdate,
} from '../../api/markRule';
import { fetchVersions } from '../../api/obras';
import { errorMessage } from '../../lib/errors';
import { versionName } from '../../lib/format';
import { useObraId } from './useObraId';

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const sameList = (a: string[], b: string[]) =>
  a.length === b.length && a.every((v, i) => v.toLowerCase() === b[i]?.toLowerCase());

/** Lista ordenada de nomes de parâmetro (prioridade = ordem). */
function NameList({
  label,
  names,
  onChange,
}: {
  label: string;
  names: string[];
  onChange: (names: string[]) => void;
}) {
  const [draft, setDraft] = useState('');
  const move = (i: number, delta: number) => {
    const next = [...names];
    const [item] = next.splice(i, 1);
    if (item === undefined) return;
    next.splice(i + delta, 0, item);
    onChange(next);
  };
  const add = () => {
    const name = draft.trim();
    if (name && !names.some((n) => n.toLowerCase() === name.toLowerCase())) {
      onChange([...names, name]);
    }
    setDraft('');
  };
  return (
    <div>
      <ol aria-label={label} className="name-list">
        {names.map((name, i) => (
          <li key={name}>
            <span>{name}</span>{' '}
            <button
              type="button"
              className="link"
              aria-label={`Subir ${name}`}
              disabled={i === 0}
              onClick={() => { move(i, -1); }}
            >
              ↑
            </button>{' '}
            <button
              type="button"
              className="link"
              aria-label={`Descer ${name}`}
              disabled={i === names.length - 1}
              onClick={() => { move(i, 1); }}
            >
              ↓
            </button>{' '}
            <button
              type="button"
              className="link"
              aria-label={`Remover ${name}`}
              onClick={() => { onChange(names.filter((_, j) => j !== i)); }}
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <input
          aria-label={`Adicionar a ${label}`}
          placeholder="Nome do parâmetro no modelo"
          value={draft}
          onChange={(e) => { setDraft(e.target.value); }}
        />
        <button type="submit" disabled={!draft.trim()}>
          Adicionar
        </button>
      </form>
    </div>
  );
}

function savedMessage(r: MarkRuleUpdate): string {
  if (!r.changed) return 'Nada mudou: a regra já era essa.';
  if (r.reprocess_version_number === null) {
    return 'Regra salva. Ela vale para as próximas versões processadas.';
  }
  if (!r.enqueued) {
    return `Regra salva, mas não foi possível iniciar o reprocessamento da ${versionName(r.reprocess_version_number)}. Tente salvar de novo em alguns minutos.`;
  }
  return `Regra salva. A ${versionName(r.reprocess_version_number)} está sendo reprocessada com a regra nova.`;
}

function signals(c: MarkCandidate): string {
  const out: string[] = [];
  if (c.unique_per_piece) out.push('quase um valor por peça');
  if (c.constant) out.push('mesmo valor em todas');
  if (c.measure) out.push('parece medida');
  return out.join(' · ');
}

function RuleEditor({ obraId, rule }: { obraId: number; rule: MarkRule }) {
  const queryClient = useQueryClient();
  const [marks, setMarks] = useState(rule.mark_property_names);
  const [categories, setCategories] = useState(rule.category_property_names);
  const [assemblies, setAssemblies] = useState(rule.piece_category_names !== null);
  const [bodies, setBodies] = useState(
    rule.piece_category_names ?? rule.default_piece_category_names,
  );
  const save = useMutation({
    mutationFn: (body: Parameters<typeof saveMarkRule>[1]) => saveMarkRule(obraId, body),
    onSuccess: async (r) => {
      setMarks(r.mark_property_names);
      setCategories(r.category_property_names);
      setAssemblies(r.piece_category_names !== null);
      setBodies(r.piece_category_names ?? r.default_piece_category_names);
      await queryClient.invalidateQueries({ queryKey: ['obras', obraId] });
    },
  });
  const dirty =
    !sameList(marks, rule.mark_property_names) ||
    !sameList(categories, rule.category_property_names) ||
    assemblies !== (rule.piece_category_names !== null) ||
    (assemblies && !sameList(bodies, rule.piece_category_names ?? []));

  const versions = useQuery({ queryKey: ['obras', obraId, 'versions'], queryFn: () => fetchVersions(obraId) });
  const active = versions.data?.find((v) => v.status === 'ready');
  const candidates = useQuery({
    queryKey: ['versions', active?.id, 'mark-candidates'],
    queryFn: () => fetchMarkCandidates(active?.id ?? 0),
    enabled: active !== undefined,
  });

  const makeFirst = (name: string) => {
    setMarks([name, ...marks.filter((n) => n.toLowerCase() !== name.toLowerCase())]);
  };

  return (
    <div>
      <p className="muted">
        Quais parâmetros do modelo dão o código da marca, em ordem de prioridade: em cada
        peça vale o primeiro que tiver valor. Ex.: nas montagens detalhadas pela equipe,
        &quot;Nome da montagem&quot; antes de &quot;Marca&quot;; num modelo de terceiros, o
        parâmetro onde o projetista colocou o nome do pilar.
      </p>

      <h4>
        Parâmetros da marca{' '}
        {!rule.custom_marks && <span className="muted small">(padrão do servidor)</span>}
      </h4>
      <NameList label="Parâmetros da marca" names={marks} onChange={setMarks} />

      <details>
        <summary>Categoria (opcional)</summary>
        <p className="hint">
          Parâmetros que dão a categoria da peça. Sem nenhum encontrado, vale a categoria do
          modelo (Pilares, Vigas...).
          {!rule.custom_categories && ' Hoje: padrão do servidor.'}
        </p>
        <NameList label="Parâmetros da categoria" names={categories} onChange={setCategories} />
      </details>

      <h4>Montagens</h4>
      <label className="check">
        <input
          type="checkbox"
          checked={assemblies}
          onChange={(e) => { setAssemblies(e.target.checked); }}
        />{' '}
        Modelo com montagens (.nwd ou .rvt com um vínculo por peça)
      </label>
      <p className="hint">
        Cada pilar, viga ou laje (o &quot;corpo&quot;) é uma peça; consolos, alças e esperas
        da mesma montagem fazem parte dela. Montagem sem corpo (escada, laje maciça) conta
        como uma peça. No IFC a montagem é reconhecida sozinha.
      </p>
      {assemblies && (
        <NameList label="Categorias do corpo da peça" names={bodies} onChange={setBodies} />
      )}

      <p className="hint">
        Ao salvar, a versão ativa é processada de novo com a regra nova. Uma marca com
        valores cujas peças vão todas para <strong>uma</strong> marca nova leva os valores
        junto. As outras (peças divididas entre marcas, ou destino com outro valor) viram{' '}
        <strong>órfãs</strong>: decida em Marcas órfãs, na coluna esquerda da tela do modelo. Nenhum valor é apagado.
      </p>
      <div className="actions">
        <button
          type="button"
          disabled={!dirty || marks.length === 0 || save.isPending}
          onClick={() => {
            // categoria vazia, ou igual ao padrão sem regra própria = padrão do servidor
            const keepDefault =
              categories.length === 0 ||
              (!rule.custom_categories &&
                sameList(categories, rule.default_category_property_names));
            save.mutate({
              mark_property_names: marks,
              category_property_names: keepDefault ? null : categories,
              piece_category_names: assemblies && bodies.length > 0 ? bodies : null,
            });
          }}
        >
          {save.isPending ? 'Salvando…' : 'Salvar regra'}
        </button>{' '}
        {(rule.custom_marks || rule.custom_categories || rule.piece_category_names !== null) && (
          <button
            type="button"
            className="secondary"
            disabled={save.isPending}
            onClick={() => {
              save.mutate({
                mark_property_names: null,
                category_property_names: null,
                piece_category_names: null,
              });
            }}
          >
            Voltar ao padrão
          </button>
        )}
      </div>
      {marks.length === 0 && (
        <p role="alert" className="error">
          Informe pelo menos um parâmetro da marca.
        </p>
      )}
      {save.isSuccess && <p role="status">{savedMessage(save.data)}</p>}
      {save.isError && (
        <p role="alert" className="error">
          {errorMessage(save.error)}
        </p>
      )}

      <h4>Qual parâmetro identifica as peças?{active && ` — ${versionName(active.version_number)}`}</h4>
      {versions.isSuccess && !active && (
        <p className="muted">Ainda não há versão pronta para analisar.</p>
      )}
      {candidates.isError && (
        <p role="alert" className="error">
          {errorMessage(candidates.error)}
        </p>
      )}
      {candidates.data && (
        <>
          <p className="hint">
            O app testou cada parâmetro das {plural(candidates.data.pieces, 'peça', 'peças')} como
            se fosse a marca. O melhor tem valor em todas as peças e nenhuma marca
            inconsistente (peças com dimensões diferentes na mesma marca).
          </p>
          {!candidates.data.dimensions_checked && (
            <p role="note" className="error">
              Este modelo não tem as propriedades de dimensão configuradas no servidor: a
              coluna Inconsistentes não pôde ser conferida. Confira os exemplos antes de escolher.
            </p>
          )}
          <table className="table" aria-label="Parâmetros candidatos">
            <thead>
              <tr>
                <th>Parâmetro</th>
                <th>Peças com valor</th>
                <th>Marcas</th>
                <th>Inconsistentes</th>
                <th>Exemplos</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {candidates.data.candidates.map((c) => {
                const pct = Math.round((100 * c.pieces_with_value) / Math.max(candidates.data.pieces, 1));
                const first = marks[0]?.toLowerCase() === c.name.toLowerCase();
                return (
                  <tr key={c.name}>
                    <td>
                      {c.name}
                      {c.current && <span className="muted small"> (em uso)</span>}
                      {signals(c) && <div className="hint">{signals(c)}</div>}
                    </td>
                    <td>
                      {c.pieces_with_value} ({pct}%)
                    </td>
                    <td>{c.marks}</td>
                    <td className={c.inconsistent_marks > 0 ? 'error' : undefined}>
                      {c.inconsistent_marks === 0
                        ? '0'
                        : `${plural(c.inconsistent_marks, 'marca', 'marcas')} · ${plural(c.inconsistent_pieces, 'peça', 'peças')}`}
                    </td>
                    <td className="small">
                      {c.examples.map(([v, n]) => `${v} ×${n}`).join(', ')}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="link"
                        disabled={first}
                        aria-label={`Usar ${c.name} como principal`}
                        onClick={() => { makeFirst(c.name); }}
                      >
                        {first ? 'Principal' : 'Usar como principal'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

export function IdentificationTab() {
  const obraId = useObraId();
  const rule = useQuery({
    queryKey: ['obras', obraId, 'mark-rule'],
    queryFn: () => fetchMarkRule(obraId),
    retry: false,
  });
  return (
    <div>
      <div className="page-head">
        <h3>Identificação das peças</h3>
      </div>
      {rule.isError && (
        <p role="alert" className="error">
          {errorMessage(rule.error)}
        </p>
      )}
      {rule.data && (
        <RuleEditor key={obraId} obraId={obraId} rule={rule.data} />
      )}
    </div>
  );
}
