import type { UnitNumbering } from '../../api/obras';
import type { SyncState } from './centroidSync';

const num = (n: number) => n.toLocaleString('pt-BR');

const EXPLAIN =
  'As peças de cada marca (PP001-1, PP001-2…) são numeradas pela sequência de montagem: X, depois ' +
  'Y, depois Z (como o Dynamo), pelo centro de gravidade. Isso é feito uma única vez, na primeira ' +
  'abertura do 3D, e só enquanto nenhuma peça tem valor preenchido. Depois os números não mudam mais.';

/** Situação da numeração das peças na barra do modelo (passo 2, 2026-11-18). */
export function NumberingNotice({ numbering, state }: { numbering: UnitNumbering | undefined; state: SyncState }) {
  if (state.result && state.result.renumbered > 0) {
    return (
      <span className="hint numbering-notice" role="status" title={EXPLAIN}>
        Peças numeradas pela sequência de montagem
      </span>
    );
  }
  if (numbering !== 'provisional') return null;
  const p = state.progress;
  return (
    <span className="hint numbering-notice" role="status" title={EXPLAIN}>
      {p
        ? p.waiting
          ? 'Numeração provisória · aguardando o 3D carregar…'
          : `Numeração provisória · calculando a sequência de montagem ${num(p.done)}/${num(p.total)}…`
        : 'Numeração provisória das peças'}
    </span>
  );
}
