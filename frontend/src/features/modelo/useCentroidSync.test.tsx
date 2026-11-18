import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { ModelNode, Triangle, Vec3, ViewerAdapter } from '../../viewer/ViewerAdapter';
import { resetCentroidJobs, type SyncState } from './centroidSync';
import { NumberingNotice } from './NumberingNotice';
import { useCentroidSync } from './useCentroidSync';

/** Passo 2 (2026-11-18): a 1ª abertura do 3D manda os centros e numera as peças. */

const cube = (o: Vec3): Triangle[] => {
  const p = (i: number, j: number, k: number): Vec3 => [o[0] + i, o[1] + j, o[2] + k];
  const [a, b, c, d, e, f, g, h] = [p(0, 0, 0), p(1, 0, 0), p(1, 1, 0), p(0, 1, 0), p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1)];
  const q = (i: Vec3, j: Vec3, k: Vec3, l: Vec3): Triangle[] => [[i, j, k], [i, k, l]];
  return [...q(a, d, c, b), ...q(e, f, g, h), ...q(a, b, f, e), ...q(b, c, g, f), ...q(c, d, h, g), ...q(d, a, e, h)];
};

function fakeViewer(): ViewerAdapter {
  const node = (dbId: number): ModelNode => ({
    dbId, parent: null, children: [], name: `n${String(dbId)}`,
    category: 'Pilares', ifcClass: '', material: 'Concreto', hasGeometry: true,
  });
  const geometry: Record<number, Triangle[]> = { 10: cube([0, 0, 4]), 11: cube([2, 0, 0]) };
  return {
    getModelFrame: () => ({ globalOffset: [0, 0, 0], unitScaleToM: 1, refPointTransformation: null }),
    getNodes: (ids: number[]) => Promise.resolve(ids.map(node)),
    getTriangles: (id: number) => geometry[id] ?? [],
  } as unknown as ViewerAdapter;
}

const DBIDS = [10, 11];

function Probe({ viewer, ready }: { viewer: ViewerAdapter; ready: boolean }) {
  const { state } = useCentroidSync({ obraId: 7, versionId: 3, viewer, modelReady: ready, pieceDbIds: DBIDS });
  return <NumberingNotice numbering="provisional" state={state} />;
}

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe('useCentroidSync', () => {
  afterEach(() => {
    resetCentroidJobs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('com o 3D pronto e centros faltando, calcula uma vez e manda ao servidor', async () => {
    const puts: FakeRequest[] = [];
    installFakeApi({
      'GET /api/versions/3/centroids': { pieces: 2, stored: 0, numbering: 'provisional' },
      'PUT /api/versions/3/centroids': (req) => {
        puts.push(req);
        return { pieces: 2, stored: 2, numbering: 'sequence', renumbered: 2, relinked: false };
      },
    });
    const viewer = fakeViewer();
    renderWithProviders(<Probe viewer={viewer} ready />);
    expect(await screen.findByText('Peças numeradas pela sequência de montagem')).toBeInTheDocument();
    expect(puts).toHaveLength(1);
    expect(puts[0]?.body).toEqual({ coordinates: { '10': [0.5, 0.5, 4.5], '11': [2.5, 0.5, 0.5] } });
    await tick(30); // a lista de peças e o status mudam de identidade: não recalcula
    expect(puts).toHaveLength(1); // uma vez por versão
  });

  it('não calcula se o servidor já tem todos os centros, nem antes de o 3D carregar', async () => {
    const puts: FakeRequest[] = [];
    installFakeApi({
      'GET /api/versions/3/centroids': { pieces: 2, stored: 2, numbering: 'sequence' },
      'PUT /api/versions/3/centroids': (req) => {
        puts.push(req);
        return {};
      },
    });
    const viewer = fakeViewer();
    const triangles = vi.spyOn(viewer as { getTriangles: (id: number) => Triangle[] }, 'getTriangles');
    renderWithProviders(<Probe viewer={viewer} ready />);
    await tick(50);
    expect(puts).toHaveLength(0);
    expect(triangles).not.toHaveBeenCalled();
  });

  it('com o 3D ainda carregando, espera', async () => {
    const puts: FakeRequest[] = [];
    installFakeApi({
      'GET /api/versions/3/centroids': { pieces: 2, stored: 0, numbering: 'provisional' },
      'PUT /api/versions/3/centroids': (req) => {
        puts.push(req);
        return {};
      },
    });
    renderWithProviders(<Probe viewer={fakeViewer()} ready={false} />);
    await tick(50);
    expect(puts).toHaveLength(0);
    expect(screen.getByRole('status')).toHaveTextContent('Numeração provisória das peças');
  });
});

describe('NumberingNotice', () => {
  const idle: SyncState = { progress: null, result: null, coords: null, error: null };

  it('provisória: avisa e mostra o progresso do cálculo', () => {
    const { rerender } = renderWithProviders(<NumberingNotice numbering="provisional" state={idle} />);
    expect(screen.getByRole('status')).toHaveTextContent('Numeração provisória das peças');
    expect(screen.getByRole('status')).toHaveAttribute('title', expect.stringContaining('uma única vez'));
    rerender(<NumberingNotice numbering="provisional" state={{ ...idle, progress: { done: 1200, total: 1433 } }} />);
    expect(screen.getByRole('status')).toHaveTextContent('calculando a sequência de montagem 1.200/1.433…');
  });

  it('sequência ou travada: nada a avisar', () => {
    const { container, rerender } = renderWithProviders(<NumberingNotice numbering="sequence" state={idle} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<NumberingNotice numbering="fixed" state={idle} />);
    expect(container).toBeEmptyDOMElement();
  });
});
