# Visualizador BIM Cassol

## Objetivo
App web interno (PWA) que liga o escritório de projetos à fábrica de pré-moldados. O escritório publica modelos no Autodesk Docs (ACC). A fábrica abre o modelo no navegador/tablet, encontra peças clicando no 3D ou buscando, e cria/preenche parâmetros de produção (ex.: Tipo de forma). Os parâmetros persistem entre versões do modelo.

## Regras de arquitetura (não negociáveis)
- Modelos ficam no Autodesk Docs, que converte para SVF2. NUNCA chamar POST /modelderivative/v2/designdata/job (pago e bloqueado no Docs). NUNCA usar a AEC Data Model API (paga).
- APIs permitidas: Authentication v2 (2-legged client_credentials com escopos data:read viewables:read; 3-legged só na Fase 11), Data Management, Model Derivative apenas GET (manifest, metadata, properties), Webhooks, Viewer v7 (SVF2).
- A fonte da verdade dos parâmetros da fábrica é o PostgreSQL do app. Nunca escrever no arquivo BIM.
- Entidade central: MARCA = (obra, código da marca, categoria). Uma marca agrupa N peças físicas idênticas. Marcas podem se repetir entre obras. Valores de parâmetros ligam-se à marca, nunca à versão.
- O nome do parâmetro de marca no modelo é configurável (env MARK_PROPERTY_NAMES, padrão "Marca,Mark").
- Reconciliação entre versões por obra + marca + categoria. Marca que some com valores vira ÓRFÃ (nunca apagar dados em silêncio). Toda alteração vai para audit_log.
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
