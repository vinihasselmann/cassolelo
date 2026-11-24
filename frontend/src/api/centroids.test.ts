import { describe, expect, it } from 'vitest';

import { roundedCoordinates } from './centroids';

describe('roundedCoordinates', () => {
  it('arredonda a 0,1 mm', () => {
    expect(roundedCoordinates(new Map([[7, [1.23456, -2.00004, 3] as const]]))).toEqual({ 7: [1.2346, -2, 3] });
  });

  it('deixa de fora NaN, infinito e valores acima de ±1.000 km (o servidor recusaria todas)', () => {
    const coords = new Map<number, readonly [number, number, number]>([
      [1, [10, 20, 3]],
      [2, [Number.NaN, 0, 0]],
      [3, [0, Number.POSITIVE_INFINITY, 0]],
      [4, [3746325.2113, -6395179.5653, -742.0118]], // a obra GUI antes da correção
    ]);
    expect(roundedCoordinates(coords)).toEqual({ 1: [10, 20, 3] });
  });
});
