import type { Orphan } from '../../api/reconcile';
import { formatParamValue } from '../../lib/format';

/** "Parâmetro: valor · …" (valores que a órfã leva: marca órfã ou unidade de peça órfã). */
export function describeValues(o: Pick<Orphan, 'values'>): string {
  if (o.values.length === 0) return 'sem valores';
  return o.values.map((v) => `${v.name}: ${formatParamValue(v.type, v.value) ?? '—'}`).join(' · ');
}
