# Visualizador BIM Cassol

## Objetivo
App web interno (PWA) que liga o escritório de projetos à fábrica de pré-moldados. O escritório publica modelos no Autodesk Docs (ACC). A fábrica abre o modelo no navegador/tablet, encontra peças clicando no 3D ou buscando, e cria/preenche parâmetros de produção (ex.: Tipo de forma). Os parâmetros persistem entre versões do modelo.

## Regras de arquitetura (não negociáveis)
- Modelos ficam no Autodesk Docs, que converte para SVF2. NUNCA chamar POST /modelderivative/v2/designdata/job (pago e bloqueado no Docs). NUNCA usar a AEC Data Model API (paga).
- APIs permitidas: Authentication v2 (2-legged client_credentials com escopos data:read viewables:read; 3-legged só na Fase 11), Data Management, Model Derivative apenas GET (manifest, metadata, properties), Webhooks, Viewer v7 (SVF2).
- A fonte da verdade dos parâmetros da fábrica é o PostgreSQL do app. Nunca escrever no arquivo BIM.
- Entidade central: MARCA = (obra, código da marca, categoria). Uma marca agrupa N peças físicas idênticas, cada uma uma UNIDADE DE PEÇA numerada no app (PP001-1, PP001-2…; o número nunca é reaproveitado). Marcas podem se repetir entre obras.
- Numeração das unidades: provisória (nível, nome, externalId) até o 3D mandar os centros de gravidade; então renumerada UMA vez pela sequência de montagem (Z → X → Y, crescente, faixas de 0,10 m, centro de gravidade; decisão de 2026-11-19. Obras numeradas antes em X → Y → Z guardam a sua ordem em obras.sequence_axes e seguem ligando por ela), como permutação dos números da marca, só se a versão é a mais recente e nenhuma unidade da obra tem valor por peça. O primeiro valor por peça trava a numeração. Fora essa exceção, o número nunca muda (decisão de 2026-11-18, docs/pecas/verificacao.md).
- Cada parâmetro da fábrica é POR MARCA ou POR PEÇA (escolhido na criação, imutável depois que houver valores). Valores por marca ligam-se à marca; valores por peça ligam-se à unidade de peça. Nunca à versão (decisão de 2026-11-16, docs/pecas/verificacao.md).
- Status de produção (Pendente / Parcial / Completa / Revisar) é calculado POR PEÇA: parâmetros por marca contam pelo valor da marca da peça; parâmetros por peça, pelo valor da unidade ligada àquela peça. Contam os obrigatórios que valem para a categoria; sem obrigatórios, todos os que valem. Preencher um parâmetro por peça muda só o status daquela peça; um por marca muda o de todas as peças da marca. O status da MARCA é o agregado das peças (todas iguais → esse; diferentes → Parcial; alguma em Revisar → Revisar). A legenda conta peças (decisão de 2026-11-17, docs/bugs/data-por-peca.md).
- Datas de parâmetros: completas e com ano entre 1900 e 2100, validadas no frontend e no backend (422 "Data inválida: use dd/mm/aaaa"). Editores de data nunca gravam no onChange: só ao confirmar (Enter, sair do campo ou Salvar); Esc cancela.
- A unidade liga-se ao elemento do modelo pelo externalId (UniqueId no Revit, GlobalId no IFC); nunca pelo dbId. Sem par pelo externalId, liga-se pela ordem estável dentro da marca, marcada "conferir". Unidade com valores que fica sem peça vira ÓRFÃ (nunca apagar dados em silêncio). NWD não tem chave estável: lá a ligação é sempre pela ordem.
- O nome do parâmetro de marca no modelo é configurável: padrão do servidor no env MARK_PROPERTY_NAMES ("Marca,Mark"); cada obra pode ter a sua regra de identificação (lista de parâmetros em ordem de prioridade, ex.: "Nome da montagem, Marca"), definida por qualquer papel e auditada. Trocar a regra reprocessa a versão ativa; marcas com valores que somem viram órfãs (decisão de 2026-11-13).
- Reconciliação entre versões por obra + marca + categoria e, dentro da marca, das unidades de peça pelo externalId. Marca que some com valores vira ÓRFÃ (nunca apagar dados em silêncio). Toda alteração vai para audit_log.
- O frontend só acessa o visualizador pela interface ViewerAdapter.
- Até a Fase 11 não há login: usuário simulado pelo header X-Dev-User (id, nome, papel: projetos | fabrica | admin | leitura). Toda tabela tem created_by/updated_by.
- Credenciais do APS só no backend. O frontend recebe apenas tokens de visualização curtos (viewables:read).

## Stack
Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, Pydantic v2, pydantic-settings, httpx, Arq (Redis), pytest, respx, ruff, mypy.
Frontend: React 18, TypeScript strict, Vite, TanStack Query, AG Grid Community, Vitest, Playwright, ESLint.
Infra: PostgreSQL 16, Redis 7, Docker Compose, GitHub Actions.

## Estrutura
backend/ (app/, app/aps/, app/models/, app/api/, app/services/, app/workers/, migrations/, tests/)
frontend/ (src/viewer/, src/features/, src/api/, e2e/)
spikes/ (scripts da Fase 0)
infra/ (docker-compose.yml, .env.example)
docs/ (ROADMAP.md, PROGRESS.md, DATA_MODEL.md, decisões)

## Convenções
- Código, nomes de tabelas e variáveis em inglês; textos de interface em português do Brasil.
- Toda funcionalidade nova vem com testes. Nunca declarar tarefa concluída com teste falhando.
- Segredos só em .env (no .gitignore). Nunca logar tokens.
- Mudanças de banco só por migração Alembic.

## Como trabalhar comigo
- Trabalhe apenas na fase e no passo pedidos. Não adiante fases.
- Antes de escrever código, mostre um plano curto (arquivos e testes).
- Ao terminar: rode lint, typecheck e testes; mostre o resultado; atualize docs/PROGRESS.md com o que foi feito e o que falta.
- Se uma regra acima impedir o pedido, pare e me diga em vez de contorná-la.
