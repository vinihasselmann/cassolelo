import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { installFakeApi, jsonError } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { AccPicker } from './AccPicker';

const HUB = 'b.hub-1';
const PROJECT = 'b.proj-1';
const TOP = 'urn:adsk.wipprod:fs.folder:co.TOP';
const MODELOS = 'urn:adsk.wipprod:fs.folder:co.MODELOS';
const VAZIA = 'urn:adsk.wipprod:fs.folder:co.VAZIA';
const PDFS = 'urn:adsk.wipprod:fs.folder:co.PDFS';
const RVT = 'urn:adsk.wipprod:dm.lineage:RVT';

const folder = (id: string, name: string) => ({ kind: 'folder', id, name, file_type: null, supported: false });
const item = (id: string, name: string, supported: boolean) => ({
  kind: 'item',
  id,
  name,
  file_type: name.split('.').pop() ?? null,
  supported,
});

function docs() {
  return installFakeApi({
    'GET /api/acc/hubs': [{ id: HUB, name: 'Cassol' }],
    [`GET /api/acc/hubs/${HUB}/projects`]: [{ id: PROJECT, name: 'OBRA 001' }],
    [`GET /api/acc/hubs/${HUB}/projects/${PROJECT}/top-folders`]: [folder(TOP, 'Project Files')],
    [`GET /api/acc/projects/${PROJECT}/folders/${TOP}`]: [
      folder(MODELOS, 'Modelos'),
      folder(VAZIA, 'Vazia'),
      folder(PDFS, 'Pranchas'),
    ],
    [`GET /api/acc/projects/${PROJECT}/folders/${MODELOS}`]: [
      item(RVT, 'OBRA-001.rvt', true),
      item('urn:pdf', 'Memorial.pdf', false),
    ],
    [`GET /api/acc/projects/${PROJECT}/folders/${VAZIA}`]: [],
    [`GET /api/acc/projects/${PROJECT}/folders/${PDFS}`]: [item('urn:p1', 'P-01.pdf', false)],
  });
}

async function openPath(user: ReturnType<typeof userEvent.setup>, names: string[]) {
  for (const name of names) {
    await user.click(await screen.findByRole('button', { name: new RegExp(name) }));
  }
}

describe('AccPicker', () => {
  it('navega hub › projeto › pastas e seleciona um modelo suportado', async () => {
    const fetchMock = docs();
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<AccPicker onSelect={onSelect} />);

    await openPath(user, ['Cassol', 'OBRA 001', 'Project Files', 'Modelos']);

    expect(screen.queryByRole('button', { name: /Memorial\.pdf/ })).not.toBeInTheDocument();
    expect(screen.getByText(/1 arquivo de outro formato oculto/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /OBRA-001\.rvt/ }));
    expect(onSelect).toHaveBeenCalledWith({
      hubId: HUB,
      projectId: PROJECT,
      folderId: MODELOS,
      itemId: RVT,
      itemName: 'OBRA-001.rvt',
    });

    // ids com ":" vão codificados na URL
    const urls = fetchMock.mock.calls.map(([input]) => input as string);
    expect(urls).toContain(`/api/acc/projects/${PROJECT}/folders/${encodeURIComponent(MODELOS)}`);
  });

  it('volta pelo caminho (breadcrumb)', async () => {
    docs();
    const user = userEvent.setup();
    renderWithProviders(<AccPicker onSelect={vi.fn()} />);
    await openPath(user, ['Cassol', 'OBRA 001', 'Project Files', 'Modelos']);

    await user.click(screen.getByRole('button', { name: 'OBRA 001' }));
    expect(await screen.findByRole('button', { name: /Project Files/ })).toBeInTheDocument();
  });

  it('avisa quando a pasta está vazia', async () => {
    docs();
    const user = userEvent.setup();
    renderWithProviders(<AccPicker onSelect={vi.fn()} />);
    await openPath(user, ['Cassol', 'OBRA 001', 'Project Files', 'Vazia']);
    expect(await screen.findByText('Esta pasta está vazia.')).toBeInTheDocument();
  });

  it('avisa quando a pasta não tem modelos suportados', async () => {
    docs();
    const user = userEvent.setup();
    renderWithProviders(<AccPicker onSelect={vi.fn()} />);
    await openPath(user, ['Cassol', 'OBRA 001', 'Project Files', 'Pranchas']);
    expect(await screen.findByText('Nenhum modelo .rvt, .nwd ou .ifc nesta pasta.')).toBeInTheDocument();
  });

  it('mostra mensagem clara de falta de permissão', async () => {
    installFakeApi({
      'GET /api/acc/hubs': jsonError(
        403,
        'Sem permissão no Autodesk Docs: o app não foi liberado em Custom Integrations.',
      ),
    });
    renderWithProviders(<AccPicker onSelect={vi.fn()} />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Sem permissão para ver este conteúdo');
    expect(alert).toHaveTextContent('Custom Integrations');
  });
});
