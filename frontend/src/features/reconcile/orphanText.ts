import type { Orphan } from '../../api/reconcile';
import { formatParamValue } from '../../lib/format';

/** "Tipo de forma: F-12 · Ciclo: 8" (valores que a órfã leva). */
export function describeValues(o: Orphan): string {
  if (o.values.length === 0) return 'sem valores';
  return o.values.map((v) => `${v.name}: ${formatParamValue(v.type, v.value) ?? '—'}`).join(' · ');
}
