import type { ObraEvent } from '../../api/events';

const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : '');
const num = (v: unknown) => (typeof v === 'number' ? v : 0);

/** Texto do aviso discreto ("J. Silva alterou PP003"), ou null se o evento não gera aviso. */
export function describeEvent(ev: ObraEvent): string | null {
  const d = ev.data;
  const who = d.actor?.name ?? 'Alguém';
  switch (ev.type) {
    case 'values_changed':
      if (d.review === 'kept') return `${who} manteve os valores de ${str(d.mark)} (revisão)`;
      if (d.source === 'relink') return `${who} copiou os valores de ${str(d.from_mark)} para ${str(d.mark)}`;
      return `${who} alterou ${str(d.mark)}`;
    case 'batch_applied': {
      const n = num(d.marks);
      return `${who} alterou ${String(n)} ${n === 1 ? 'marca' : 'marcas'} em lote`;
    }
    case 'batch_undone':
      return `${who} desfez uma edição em lote`;
    case 'orphan_changed':
      if (d.status === 'relinked') return `${who} religou a órfã ${str(d.mark)} a ${str(d.target)}`;
      if (d.status === 'archived') return `${who} arquivou a órfã ${str(d.mark)}`;
      return `Órfã ${str(d.mark)} atualizada`;
    case 'param_def_changed': {
      const verb = d.action === 'created' ? 'criou' : d.action === 'deleted' ? 'excluiu' : 'alterou';
      return `${who} ${verb} o parâmetro “${str(d.name)}”`;
    }
    case 'version_failed':
      return `A versão ${str(d.version_number)} não pôde ser processada`;
    case 'obra_file_state':
      return d.state === 'ok' ? 'O arquivo da obra foi restaurado no Docs' : 'O arquivo da obra foi excluído do Docs';
    case 'units_renumbered':
      return Number(d.renumbered) > 0
        ? 'As peças foram numeradas pela sequência de montagem'
        : 'As peças da versão foram religadas pela sequência de montagem';
    case 'version_ready':
      return null; // vira o banner "Nova versão disponível"
    case 'unit_values_changed':
      return `${who} alterou a peça ${str(d.unit)}`;
    case 'unit_batch_applied': {
      const n = num(d.units);
      return `${who} alterou ${String(n)} ${n === 1 ? 'peça' : 'peças'} em lote`;
    }
    case 'unit_batch_undone':
      return `${who} desfez uma edição em lote de peças`;
    case 'unit_orphan_changed':
      if (d.status === 'relinked') return `${who} religou a peça órfã ${str(d.unit)} (no lugar de ${str(d.target_unit)})`;
      if (d.status === 'archived') return `${who} arquivou a peça órfã ${str(d.unit)}`;
      return `Peça órfã ${str(d.unit)} atualizada`;
    default:
      return null; // tipo novo que esta versão da tela ainda não conhece
  }
}
