import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ModelNode, Triangle, Vec3, ViewerAdapter } from '../../viewer/ViewerAdapter';
import { resetCentroidJobs } from './centroidSync';
import { ExportButton } from './ExportButton';

/** Excel com X/Y/Z do centro de gravidade de cada peça (2026-11-18). */

const cube = (o: Vec3): Triangle[] => {
  const p = (i: number, j: number, k: number): Vec3 => [o[0] + i, o[1] + j, o[2] + k];
  const [a, b, c, d, e, f, g, h] = [p(0, 0, 0), p(1, 0, 0), p(1, 1, 0), p(0, 1, 0), p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1)];
  const q = (i: Vec3, j: Vec3, k: Vec3, l: Vec3): Triangle[] => [[i, j, k], [i, k, l]];
  return [...q(a, d, c, b), ...q(e, f, g, h), ...q(a, b, f, e), ...q(b, c, g, f), ...q(c, d, h, g), ...q(d, a, e, h)];
};

function fakeViewer(): ViewerAdapter {
  const node = (dbId: number): ModelNode => ({
    dbId, parent: dbId === 1 ? null : 1, children: dbId === 1 ? [10, 11] : [], name: `n${String(dbId)}`,
    category: dbId === 1 ? '' : 'Pilares', ifcClass: '', material: 'Concreto', hasGeometry: dbId !== 1,
  });
  const geometry: Record<number, Triangle[]> = { 10: cube([0, 0, 0]), 11: cube([4, 0, 2]) };
  return {
    getModelFrame: () => ({ globalOffset: [0, 0, 0], unitScaleToM: 1, refPointTransformation: null }),
    getNodes: (ids: number[]) => Promise.resolve(ids.map(node)),
    getTriangles: (id: number) => geometry[id] ?? [],
  } as unknown as ViewerAdapter;
}

describe('Exportar Excel com coordenadas', () => {
  afterEach(() => {
    resetCentroidJobs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('calcula o centro de gravidade das peças, manda no pedido e reaproveita na 2ª vez', async () => {
    const calls: FakeRequest[] = [];
    const stored: FakeRequest[] = [];
    installFakeApi({
      'PUT /api/versions/3/centroids': (req) => {
        stored.push(req);
        return { pieces: 2, stored: 2, numbering: 'sequence', renumbered: 2, relinked: false };
      },
      'POST /api/obras/7/export.xlsx': (req) => {
        calls.push(req);
        return new Response(new Blob(['xlsx']), { headers: { 'Content-Disposition': 'attachment; filename="a.xlsx"' } });
      },
    });
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const viewer = fakeViewer();
    const triangles = vi.spyOn(viewer as { getTriangles: (id: number) => Triangle[] }, 'getTriangles');

    renderWithProviders(<ExportButton obraId={7} versionId={3} filter={null} viewer={viewer} modelReady pieceDbIds={[10, 11]} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await vi.waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toEqual({
      version_id: 3,
      filter: null,
      coordinates: { '10': [0.5, 0.5, 0.5], '11': [4.5, 0.5, 2.5] },
    });

    const used = triangles.mock.calls.length;
    await vi.waitFor(() => { expect(screen.getByRole('button', { name: 'Exportar Excel' })).toBeEnabled(); });
    await user.click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await vi.waitFor(() => { expect(calls).toHaveLength(2); });
    expect(triangles.mock.calls.length).toBe(used); // mesma versão: não recalcula
    expect(calls[1]?.body).toEqual(calls[0]?.body);
    // o mesmo cálculo foi para o servidor (numeração pela sequência de montagem)
    expect(stored).toHaveLength(1);
    expect(stored[0]?.body).toEqual({ coordinates: { '10': [0.5, 0.5, 0.5], '11': [4.5, 0.5, 2.5] } });
  });

  it('com os centros já no servidor, não recalcula: o servidor usa os guardados', async () => {
    const calls: FakeRequest[] = [];
    installFakeApi({
      'POST /api/obras/7/export.xlsx': (req) => {
        calls.push(req);
        return new Response(new Blob(['xlsx']));
      },
    });
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const viewer = fakeViewer();
    const triangles = vi.spyOn(viewer as { getTriangles: (id: number) => Triangle[] }, 'getTriangles');
    renderWithProviders(
      <ExportButton obraId={7} versionId={3} filter={null} viewer={viewer} modelReady pieceDbIds={[10, 11]} centroidsStored />,
    );
    await userEvent.setup().click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await vi.waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toEqual({ version_id: 3, filter: null });
    expect(triangles).not.toHaveBeenCalled();
  });

  it('sem o modelo carregado, exporta sem coordenadas (ordem por marca)', async () => {
    const calls: FakeRequest[] = [];
    installFakeApi({
      'POST /api/obras/7/export.xlsx': (req) => {
        calls.push(req);
        return new Response(new Blob(['xlsx']));
      },
    });
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    renderWithProviders(<ExportButton obraId={7} versionId={3} filter={null} viewer={fakeViewer()} modelReady={false} pieceDbIds={[10]} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Exportar Excel' }));
    await vi.waitFor(() => { expect(calls).toHaveLength(1); });
    expect(calls[0]?.body).toEqual({ version_id: 3, filter: null });
  });
});
