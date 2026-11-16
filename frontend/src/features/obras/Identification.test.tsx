import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { setDevUser } from '../../api/client';
import type { MarkCandidates, MarkRule } from '../../api/markRule';
import type { ModelVersion, Obra } from '../../api/obras';
import type { User } from '../../api/users';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderApp } from '../../test/render';

const LEITURA: User = { id: 4, name: 'Lia Leitura', email: 'l@dev.local', role: 'leitura' };

const OBRA: Obra = {
  id: 7,
  code: 'OB-001',
  name: 'Galpão',
  acc_hub_id: 'b.h',
  acc_project_id: 'b.p',
  acc_folder_id: 'urn:f',
  acc_item_id: 'urn:i',
  acc_item_name: 'OBRA-001.rvt',
  active: true,
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
};

const version = (id: number, status: ModelVersion['status'] = 'ready'): ModelVersion => ({
  id,
  version_number: id,
  status,
  published_by: null,
  published_at: null,
  comment: null,
  error: null,
  has_urn: true,
  urn: 'dXJu',
});

const RULE: MarkRule = {
  mark_property_names: ['Marca', 'Mark'],
  category_property_names: ['Category'],
  custom_marks: false,
  custom_categories: false,
  default_mark_property_names: ['Marca', 'Mark'],
  default_category_property_names: ['Category'],
  piece_category_names: null,
  default_piece_category_names: ['Pilares estruturais', 'Quadro estrutural'],
};

const CANDIDATES: MarkCandidates = {
  version_id: 2,
  pieces: 5,
  mark_property_names: ['Marca', 'Mark'],
  dimensions_checked: true,
  candidates: [
    {
      name: 'Nome da montagem',
      groups: ['Dados de identidade'],
      pieces_with_value: 5,
      marks: 3,
      inconsistent_marks: 0,
      inconsistent_pieces: 0,
      unique_per_piece: false,
      constant: false,
      measure: false,
      current: false,
      examples: [['PP001', 2], ['PP002', 2]],
    },
    {
      name: 'Marca',
      groups: ['Dados de identidade'],
      pieces_with_value: 4,
      marks: 1,
      inconsistent_marks: 1,
      inconsistent_pieces: 4,
      unique_per_piece: false,
      constant: true,
      measure: false,
      current: true,
      examples: [['P1', 4]],
    },
  ],
};

function api(saved: FakeRequest[], enqueued = true) {
  return installFakeApi({
    'GET /api/me': LEITURA,
    'GET /api/dev/users': [LEITURA],
    'GET /api/obras/7': OBRA,
    'GET /api/obras/7/versions': [version(3, 'processing'), version(2), version(1)],
    'GET /api/obras/7/mark-rule': RULE,
    'GET /api/versions/2/mark-candidates': CANDIDATES,
    'PUT /api/obras/7/mark-rule': (req: FakeRequest) => {
      saved.push(req);
      const body = req.body as { mark_property_names: string[] | null };
      return {
        ...RULE,
        mark_property_names: body.mark_property_names ?? RULE.default_mark_property_names,
        custom_marks: body.mark_property_names !== null,
        changed: true,
        reprocess_version_id: 2,
        reprocess_version_number: 2,
        enqueued,
      };
    },
  });
}

describe('Aba Identificação das peças', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('mostra a regra e os candidatos da versão ativa; qualquer papel salva', async () => {
    const saved: FakeRequest[] = [];
    api(saved);
    setDevUser('4'); // leitura também pode definir a regra
    const user = userEvent.setup();
    renderApp('/obras/7/identificacao');

    const list = await screen.findByRole('list', { name: 'Parâmetros da marca' });
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Marca'),
      expect.stringContaining('Mark'),
    ]);
    expect(screen.getByText('(padrão do servidor)')).toBeInTheDocument();

    // candidatos da v2 (a v3 ainda processa)
    expect(
      await screen.findByRole('heading', { name: 'Qual parâmetro identifica as peças? — v2' }),
    ).toBeInTheDocument();
    const table = await screen.findByRole('table', { name: 'Parâmetros candidatos' });
    const rows = within(table).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('Nome da montagem');
    expect(rows[1]).toHaveTextContent('5 (100%)');
    expect(rows[1]).toHaveTextContent('PP001 ×2, PP002 ×2');
    expect(rows[2]).toHaveTextContent('(em uso)');
    expect(rows[2]).toHaveTextContent('mesmo valor em todas');
    expect(rows[2]).toHaveTextContent('1 marca · 4 peças');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();

    // salvar sem mudar nada fica desabilitado
    const salvar = screen.getByRole('button', { name: 'Salvar regra' });
    expect(salvar).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Usar Nome da montagem como principal' }));
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('Nome da montagem');
    await user.click(salvar);

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Regra salva. A v2 está sendo reprocessada com a regra nova.',
    );
    expect(saved[0]?.body).toEqual({
      mark_property_names: ['Nome da montagem', 'Marca', 'Mark'],
      category_property_names: null, // categoria não mexida = padrão
      piece_category_names: null, // modo montagens desligado
    });
  });

  it('edita a prioridade (subir, remover, adicionar) e avisa se a fila falhar', async () => {
    const saved: FakeRequest[] = [];
    api(saved, false);
    setDevUser('4');
    const user = userEvent.setup();
    renderApp('/obras/7/identificacao');

    const list = await screen.findByRole('list', { name: 'Parâmetros da marca' });
    await user.click(screen.getByRole('button', { name: 'Remover Mark' }));
    await user.type(screen.getByLabelText('Adicionar a Parâmetros da marca'), 'PILAR_ID');
    await user.click(screen.getAllByRole('button', { name: 'Adicionar' })[0] as HTMLElement);
    await user.click(screen.getByRole('button', { name: 'Subir PILAR_ID' }));
    expect(within(list).getAllByRole('listitem').map((li) => li.firstChild?.textContent)).toEqual([
      'PILAR_ID',
      'Marca',
    ]);

    await user.click(screen.getByRole('button', { name: 'Remover PILAR_ID' }));
    await user.click(screen.getByRole('button', { name: 'Remover Marca' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Informe pelo menos um parâmetro da marca.');
    expect(screen.getByRole('button', { name: 'Salvar regra' })).toBeDisabled();

    await user.type(screen.getByLabelText('Adicionar a Parâmetros da marca'), 'PILAR_ID{Enter}');
    await user.click(screen.getByRole('button', { name: 'Salvar regra' }));
    expect(await screen.findByRole('status')).toHaveTextContent(
      'não foi possível iniciar o reprocessamento da v2',
    );
    expect(saved[0]?.body).toMatchObject({ mark_property_names: ['PILAR_ID'] });
  });

  it('modelo sem dimensões configuradas (ex.: IFC): avisa que a inconsistência não foi conferida', async () => {
    installFakeApi({
      'GET /api/me': LEITURA,
      'GET /api/dev/users': [LEITURA],
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(2)],
      'GET /api/obras/7/mark-rule': RULE,
      'GET /api/versions/2/mark-candidates': { ...CANDIDATES, dimensions_checked: false },
    });
    setDevUser('4');
    renderApp('/obras/7/identificacao');
    expect(await screen.findByRole('note')).toHaveTextContent(
      'a coluna Inconsistentes não pôde ser conferida',
    );
  });

  it('liga o modo montagens com as categorias do corpo sugeridas', async () => {
    const saved: FakeRequest[] = [];
    api(saved);
    setDevUser('4');
    const user = userEvent.setup();
    renderApp('/obras/7/identificacao');

    const box = await screen.findByRole('checkbox', { name: /Modelo com montagens/ });
    expect(box).not.toBeChecked();
    await user.click(box);
    const bodies = screen.getByRole('list', { name: 'Categorias do corpo da peça' });
    expect(within(bodies).getAllByRole('listitem').map((li) => li.firstChild?.textContent)).toEqual([
      'Pilares estruturais',
      'Quadro estrutural',
    ]);
    await user.click(screen.getByRole('button', { name: 'Salvar regra' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Regra salva');
    expect(saved[0]?.body).toMatchObject({
      piece_category_names: ['Pilares estruturais', 'Quadro estrutural'],
    });
  });

  it('sem versão pronta: explica que não há o que analisar', async () => {
    installFakeApi({
      'GET /api/me': LEITURA,
      'GET /api/dev/users': [LEITURA],
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(1, 'translating')],
      'GET /api/obras/7/mark-rule': { ...RULE, custom_marks: true },
    });
    setDevUser('4');
    renderApp('/obras/7/identificacao');
    expect(await screen.findByText('Ainda não há versão pronta para analisar.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Voltar ao padrão' })).toBeInTheDocument();
  });
});
