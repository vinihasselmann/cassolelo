# Visualizador BIM Cassol - tarefas do dia a dia.
# Funciona no Linux/macOS/CI e no Windows (make do ezwinports + PowerShell/cmd):
# as receitas usam só comandos portáveis (cd X && Y, uv, npm, docker, python).

COMPOSE := docker compose -f infra/docker-compose.yml --env-file infra/.env

.PHONY: help env install up down migrate seed worker dev dev-local lint test test-backend test-frontend lint-backend lint-frontend e2e

help:
	@echo make dev      - sobe banco/redis, migra, cria usuarios de teste e roda backend + frontend
	@echo make test     - testes do backend e do frontend
	@echo make lint     - lint + typecheck do backend e do frontend
	@echo make e2e      - testes Playwright (precisa do Postgres: make up + make migrate)
	@echo make migrate  - aplica as migracoes Alembic
	@echo make up/down  - sobe/derruba postgres e redis
	@echo make worker   - worker Arq (jobs de processamento de versoes)

infra/.env:
	python -c "import shutil; shutil.copyfile('infra/.env.example', 'infra/.env')"
	@echo Criado infra/.env a partir do exemplo. Revise as senhas.

env: infra/.env

install:
	cd backend && uv sync
	cd frontend && npm ci

up: infra/.env
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed

# Worker Arq (precisa do Redis: make up)
worker:
	cd backend && uv run arq app.workers.settings.WorkerSettings

dev: up install migrate seed
	python infra/dev.py

# Sem Docker: usa um Postgres já rodando em DATABASE_URL (ex.: binários portáteis).
dev-local: infra/.env install migrate seed
	python infra/dev.py

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run mypy .

lint-frontend:
	cd frontend && npm run lint
	cd frontend && npm run typecheck

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test

# E2E (Playwright): sobe backend :8001 e Vite :5174, semeia a obra de teste e usa um
# Viewer falso. Com E2E_REAL_VIEWER=1 e E2E_OBRA_ID usa o Viewer e o APS reais.
e2e:
	cd frontend && npx playwright test
