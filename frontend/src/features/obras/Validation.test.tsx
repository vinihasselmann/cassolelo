import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { setDevUser } from '../../api/client';
import type { ModelVersion, Obra } from '../../api/obras';
import type { User } from '../../api/users';
import type { ValidationReport, VersionReportResponse } from '../../api/versions';
import { installFakeApi, type FakeRequest } from '../../test/fakeApi';
import { renderApp } from '../../test/render';

const USERS: Record<string, User> = {
  '1': { id: 1, name: 'Paula Projetos', email: 'p@dev.local', role: 'projetos' },
  '2': { id: 2, name: 'Fábio Fábrica', email: 'f@dev.local', role: 'fabrica' },
};
const me = (req: FakeRequest) =>
  USERS[req.headers.get('X-Dev-User') ?? ''] ?? Response.json({}, { status: 401 });

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
  acc_file_state: 'ok',
  acc_file_state_at: null,
  unit_numbering: 'sequence',
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
};

const version = (id: number, status: ModelVersion['status'] = 'ready'): ModelVersion => ({
  id,
  version_number: id,
  status,
  published_by: 'Usuário Projetos',
  published_at: '2026-11-01T12:00:00Z',
  comment: null,
  error: null,
  has_urn: true,
  urn: 'dXJu',
});

const report = (overrides: Partial<ValidationReport> = {}): VersionReportResponse => ({
  version_id: 2,
  status: 'ready',
  updated_at: '2026-11-11T12:00:00Z',
  report: {
    version_id: 2,
    generated_at: '2026-11-11T12:00:00Z',
    config: { dimension_property_names: ['Comprimento', 'Largura', 'Altura'], tolerance_mm: 5 },
    totals: {
      pieces: 7,
      marks: 3,
      without_mark: 1,
      inconsistent_marks: 1,
      by_category: [
        { category: 'Structural Columns', pieces: 5, marks: 2, without_mark: 1 },
        { category: 'Structural Framing', pieces: 2, marks: 1, without_mark: 0 },
      ],
    },
    without_mark: [
      { dbid: 30, external_id: 'val-0030', category: 'Structural Columns', name: 'Pilar [30]' },
    ],
    inconsistent: [
      {
        mark: 'PP001',
        category: 'Structural Columns',
        pieces: 2,
        differences: [
          {
            property: 'Altura',
            diff_mm: 100,
            values: [
              { value: '40.0 cm', mm: 400, count: 1, dbids: [10] },
              { value: '50.0 cm', mm: 500, count: 1, dbids: [11] },
            ],
          },
        ],
      },
    ],
    ...overrides,
  },
});

describe('Painel Validação', () => {
  afterEach(() => {
    setDevUser(null);
  });

  it('projetos vê alertas, peças sem Marca, marcas inconsistentes e totais', async () => {
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(3, 'processing'), version(2), version(1)],
      'GET /api/versions/2/report': report(),
    });
    setDevUser('1');
    renderApp('/obras/7/versoes');

    // padrão: a versão pronta mais recente (v2); a v3 ainda está processando
    expect(await screen.findByRole('heading', { name: 'Validação — V2' })).toBeInTheDocument();
    const counter = await screen.findByText(/2 alertas/);
    expect(counter).toHaveClass('counter--warn');
    expect(counter).toHaveTextContent('1 peça sem Marca, 1 marca inconsistente');

    const semMarca = screen.getByRole('table', { name: 'Peças sem Marca' });
    expect(within(semMarca).getByText('val-0030')).toBeInTheDocument();
    expect(within(semMarca).getByText('Pilar [30]')).toBeInTheDocument();

    const inconsistentes = screen.getByRole('table', { name: 'Marcas inconsistentes' });
    expect(within(inconsistentes).getByText('PP001')).toBeInTheDocument();
    expect(
      within(inconsistentes).getByText(
        'Altura: 40.0 cm (1 peça), 50.0 cm (1 peça) — diferença de 100 mm',
      ),
    ).toBeInTheDocument();

    const totais = screen.getByRole('table', { name: 'Totais por categoria' });
    expect(within(totais).getByText('Structural Framing')).toBeInTheDocument();
    expect(screen.getByText('7 peças · 3 marcas')).toBeInTheDocument();
  });

  it('contador verde quando não há alertas; troca de versão pelo botão', async () => {
    const clean = report({
      version_id: 1,
      totals: { pieces: 2, marks: 1, without_mark: 0, inconsistent_marks: 0, by_category: [] },
      without_mark: [],
      inconsistent: [],
    });
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(2), version(1)],
      'GET /api/versions/2/report': report(),
      'GET /api/versions/1/report': clean,
    });
    setDevUser('1');
    const user = userEvent.setup();
    renderApp('/obras/7/versoes');

    expect(await screen.findByText(/2 alertas/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Validação da V1' }));
    expect(await screen.findByRole('heading', { name: 'Validação — V1' })).toBeInTheDocument();
    expect(await screen.findByText('Nenhum alerta')).toHaveClass('counter--ok');
    expect(screen.getByText('Todas as peças têm Marca.')).toBeInTheDocument();
  });

  it('fábrica não vê o painel', async () => {
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(1)],
      'GET /api/versions/1/report': report(),
    });
    setDevUser('2');
    renderApp('/obras/7/versoes');
    expect(await screen.findByText('V1')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Validação/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Validação da/ })).not.toBeInTheDocument();
  });

  it('mostra a mensagem quando o relatório ainda não existe', async () => {
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(1)],
      'GET /api/versions/1/report': Response.json(
        { detail: 'O relatório de validação desta versão ainda não foi gerado.', code: 'report_not_ready' },
        { status: 404 },
      ),
    });
    setDevUser('1');
    renderApp('/obras/7/versoes');
    expect(await screen.findByRole('alert')).toHaveTextContent('ainda não foi gerado');
  });
  it('lista peças com identificadores divergentes (Nome da montagem × Marca)', async () => {
    const base = report();
    installFakeApi({
      'GET /api/me': me,
      'GET /api/dev/users': Object.values(USERS),
      'GET /api/obras/7': OBRA,
      'GET /api/obras/7/versions': [version(2)],
      'GET /api/versions/2/report': {
        ...base,
        report: {
          ...base.report,
          totals: { ...base.report.totals, divergent_pieces: 1 },
          divergent: [
            {
              dbid: 10,
              external_id: 'x-10',
              category: 'Structural Columns',
              name: 'Pilar [10]',
              mark: 'PP012',
              values: [
                { property: 'Nome da montagem', value: 'PP012' },
                { property: 'Marca', value: 'P12' },
              ],
            },
          ],
        },
      },
    });
    setDevUser('1');
    renderApp('/obras/7/versoes');
    expect(await screen.findByText(/3 alertas/)).toHaveTextContent(
      '1 peça com identificadores divergentes',
    );
    const table = screen.getByRole('table', { name: 'Identificadores divergentes' });
    expect(within(table).getByText('Nome da montagem: PP012 · Marca: P12')).toBeInTheDocument();
  });
});
