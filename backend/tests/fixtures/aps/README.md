# Fixtures do APS

**Situação atual: SINTÉTICAS.** Foram montadas a partir do formato documentado
da API (o mesmo usado nos testes de `spikes/`). Os aceites da Fase 0 com
modelos reais ainda não foram feitos.

Quando os spikes rodarem contra o ACC real, substitua cada arquivo pela
resposta gravada, **sanitizada**:

- tokens → `FAKE-ACCESS-TOKEN`;
- ids de hub, projeto, pasta, item e versão → valores fictícios estáveis (ex.: `b.1111...`);
- nomes de pessoas, e-mails, nomes de obra e de cliente → genéricos;
- em `properties.json`, mantenha só alguns elementos representativos (com e sem Marca).

Mantenha os mesmos nomes de arquivo. Os testes em `backend/tests/aps/` usam
estes arquivos.

| Arquivo | Endpoint |
|---|---|
| token.json | POST /authentication/v2/token |
| hubs.json | GET /project/v1/hubs |
| projects_page1.json, projects_page2.json | GET /project/v1/hubs/{hub}/projects (paginação) |
| top_folders.json | GET /project/v1/hubs/{hub}/projects/{project}/topFolders |
| folder_contents.json | GET /data/v1/projects/{project}/folders/{folder}/contents |
| item.json | GET /data/v1/projects/{project}/items/{item} |
| versions.json | GET /data/v1/projects/{project}/items/{item}/versions |
| manifest_success.json, manifest_inprogress.json | GET /modelderivative/v2/designdata/{urn}/manifest |
| metadata.json | GET .../{urn}/metadata |
| object_tree.json | GET .../{urn}/metadata/{guid} |
| properties.json | GET .../{urn}/metadata/{guid}/properties |

## Modelos por formato (`models/rvt`, `models/nwd`, `models/ifc`) — SINTÉTICOS

Usados pelo `process_version` (Fase 3.1). Cada pasta tem `metadata.json`,
`tree.json` (GET .../metadata/{guid}) e `properties.json`. Foram montados para
cobrir um caso de cada: marca com espaços/minúsculas, marca em branco,
componentes aninhados, mesma marca em categorias diferentes, valor em lista,
categoria em propriedade (`Category`, `Categoria`, `IfcClass`) ou da árvore.

Ao trocar pelas respostas reais (sanitizadas, poucas dezenas de elementos),
ajuste `EXPECTED` em `tests/test_process_version.py` e as asserções de
`tests/test_extraction.py` com as contagens conferidas no Revit/Navisworks.

## Modelo de validação (`models/validacao`) — SINTÉTICO

Casos plantados para o relatório de validação (Fase 3.2): dois `PP001` com
alturas diferentes (40 × 50 cm → alerta), `PP002` com 3 mm de diferença (dentro
da tolerância de 5 mm), `V-01` com o mesmo comprimento em unidades diferentes
(6000 mm / 6,0 m) e uma peça sem Marca (dbid 30).

Arquivos `.rvt`, `.nwd` e `.ifc` colocados nestas pastas são ignorados pelo git
(`.gitignore`): os testes usam só as respostas JSON do APS.

## Modelo REAL (`models/rvt_real`) — respostas reais sanitizadas (2026-11-11)

Gravado do Autodesk Docs com `uv run python -m tests.record_fixture --urn <urn> --out rvt_real
--per-type 4 --simulate-marks` (só GET). É o modelo de orçamento `30.327-01`:
categorias em português, árvore Model > categoria > família > tipo > instâncias.

- Sanitização: propriedades do nó raiz descartadas (dados do projeto/cliente); urn
  fictício; só as 4 primeiras instâncias de cada tipo (52 nós, 33 peças).
- **Marca SIMULADA:** o modelo real tem "Marca" vazia. A ferramenta preenche
  `Dados de identidade > Marca` com `<Marca de tipo>-<nn>`, uma por (tipo,
  `PEÇA-Comprimento`). Todo o resto (nomes, valores, estrutura) é real.
- Regravar com outro modelo: troque `--urn` (veja `spikes/aps_docs/read_model.py`) e
  ajuste as contagens em `tests/test_real_fixture.py`.

## Revisões (`models/revisao_v1`, `models/revisao_v2`) — SINTÉTICAS (Fase 7)
Geradas por `uv run python -m tests.make_revisao_fixture` (a tabela dos casos está no
docstring). Duas versões do mesmo modelo com os 7 casos da reconciliação plantados;
propriedade de revisão em texto: "Seção" (use `REVIEW_PROPERTY_NAMES=Seção`).
