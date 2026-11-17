import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { installFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import pilarReal from '../../viewer/__fixtures__/orc-pilar-6657283.json';
import vigaReal from '../../viewer/__fixtures__/orc-viga-6657266.json';
import type { DbId, ModelNode, Triangle, Vec3, ViewerAdapter } from '../../viewer/ViewerAdapter';
import { AxisCoordinatesSection } from './AxisCoordinatesSection';
import { useAxisCoordinates } from './useAxisCoordinates';

/** Adapter falso com as malhas REAIS do pilar 6657283 (dbId 86) e da viga 6657266 (7084). */
function fakeAdapter() {
  const meshes: Record<number, { label: string; category: string; triangles: number[][][] }> = {
    86: pilarReal,
    7084: vigaReal,
  };
  const node = (dbId: DbId): ModelNode => ({
    dbId,
    parent: 1,
    children: [],
    name: meshes[dbId]?.label ?? '',
    category: meshes[dbId]?.category ?? '',
    ifcClass: '',
    material: 'Concreto',
    hasGeometry: dbId in meshes,
  });
  const markers: (Vec3[] | null)[] = [];
  const adapter = {
    getModelFrame: () => ({
      globalOffset: pilarReal.globalOffset as Vec3,
      unitScaleToM: pilarReal.unitScaleToM,
      refPointTransformation: pilarReal.refPointTransformation,
    }),
    getNodes: (ids: DbId[]) => Promise.resolve(ids.map(node)),
    getTriangles: (id: DbId) => (meshes[id]?.triangles ?? []) as Triangle[],
    showAxisMarker: (p: Vec3[] | null) => { markers.push(p); },
  } as unknown as ViewerAdapter;
  return { adapter, markers };
}

function Harness({ viewer, dbId, next = null }: { viewer: ViewerAdapter; dbId: DbId | null; next?: DbId | null }) {
  const [current, setCurrent] = useState(dbId);
  const state = useAxisCoordinates(viewer, current, true);
  return (
    <>
      <button type="button" onClick={() => { setCurrent(next); }}>
        trocar peça
      </button>
      <AxisCoordinatesSection state={state} />
    </>
  );
}

function row(rows: HTMLElement[], i: number): HTMLElement {
  const r = rows[i];
  if (!r) throw new Error(`linha ${String(i)} não existe`);
  return r;
}

const RULE = { axis_z_rule: { pilar: 'base', viga: 'meia altura', laje: 'face inferior' } };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Coordenadas do eixo no painel', () => {
  it('pilar: X, Y, Z da base em metros (3 casas, vírgula) e copiar "X; Y; Z"; marcador no ponto', async () => {
    installFakeApi({ 'GET /api/viewer-config': RULE });
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const { adapter, markers } = fakeAdapter();
    renderWithProviders(<Harness viewer={adapter} dbId={86} />);

    const table = await screen.findByRole('table', { name: 'Coordenadas do eixo' });
    expect(screen.getByRole('heading', { name: 'Coordenadas do eixo (ponto base do projeto)' })).toBeInTheDocument();
    expect(screen.getByText(/Pilar · centro da seção na base · em metros/)).toBeInTheDocument();
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(2); // cabeçalho + 1
    expect(within(row(rows, 1)).getAllByRole('cell').slice(0, 3).map((c) => c.textContent)).toEqual(['-73,175', '141,594', '-1,400']);
    await userEvent.click(within(table).getByRole('button', { name: 'Copiar Pilar: -73,175; 141,594; -1,400' }));
    expect(writeText).toHaveBeenCalledWith('-73,175; 141,594; -1,400');
    expect(within(table).getByRole('button', { name: /Copiar Pilar/ })).toHaveTextContent('Copiado');
    expect(markers.at(-1)).toHaveLength(1);
  });

  it('viga: "Início" e "Fim" na meia altura; marcador na linha do eixo', async () => {
    installFakeApi({ 'GET /api/viewer-config': RULE });
    const { adapter, markers } = fakeAdapter();
    renderWithProviders(<Harness viewer={adapter} dbId={7084} />);
    const table = await screen.findByRole('table', { name: 'Coordenadas do eixo' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((r) => within(r).getByRole('rowheader').textContent)).toEqual(['Início', 'Fim']);
    expect(within(row(rows, 0)).getAllByRole('cell').slice(0, 3).map((c) => c.textContent)).toEqual(['-66,727', '151,959', '4,800']);
    expect(within(row(rows, 1)).getAllByRole('cell').slice(0, 3).map((c) => c.textContent)).toEqual(['-58,764', '147,361', '4,800']);
    expect(within(table).getByRole('button', { name: 'Copiar Fim: -58,764; 147,361; 4,800' })).toBeInTheDocument();
    expect(markers.at(-1)).toHaveLength(2);
  });

  it('a regra de Z vem da configuração (AXIS_Z_RULE): Pilar=topo', async () => {
    installFakeApi({ 'GET /api/viewer-config': { axis_z_rule: { ...RULE.axis_z_rule, pilar: 'topo' } } });
    const { adapter } = fakeAdapter();
    renderWithProviders(<Harness viewer={adapter} dbId={86} />);
    const table = await screen.findByRole('table', { name: 'Coordenadas do eixo' });
    expect(screen.getByText(/centro da seção no topo/)).toBeInTheDocument();
    expect(within(table).getAllByRole('cell')[2]).toHaveTextContent('5,200'); // topo = EMBARQUE
  });

  it('sem peça clicada: nada no painel e o marcador apagado; erro aparece', async () => {
    installFakeApi({ 'GET /api/viewer-config': RULE });
    const { adapter, markers } = fakeAdapter();
    renderWithProviders(<Harness viewer={adapter} dbId={null} next={999} />);
    await vi.waitFor(() => { expect(markers).toContainEqual(null); });
    expect(screen.queryByRole('heading', { name: /Coordenadas do eixo/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'trocar peça' })); // 999: sem geometria
    expect(await screen.findByRole('alert')).toHaveTextContent('A peça não tem geometria de concreto.');
  });
});
