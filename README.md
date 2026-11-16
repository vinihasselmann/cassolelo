# Visualizador BIM Cassol

App web interno (PWA) que liga o escritório de projetos à fábrica de pré-moldados: abre os modelos publicados no Autodesk Docs (ACC) no navegador/tablet e permite à fábrica localizar peças e preencher parâmetros de produção, que persistem entre versões do modelo.

## Como rodar

Pré-requisitos: Docker (com docker compose), [uv](https://docs.astral.sh/uv/), Node 22+ e make.

```bash
make dev    # cria infra/.env, sobe Postgres e Redis, migra, cria os usuários de teste e roda tudo
```

- Frontend: http://localhost:5173. Escolha o usuário simulado no cabeçalho.
- Backend: http://localhost:8000/api/health (documentação em `/docs`).

Outros comandos: `make test`, `make lint`, `make migrate`, `make up` / `make down`.

## Documentos

- Regras do projeto: [CLAUDE.md](CLAUDE.md)
- Fases: [docs/ROADMAP.md](docs/ROADMAP.md)
- Progresso: [docs/PROGRESS.md](docs/PROGRESS.md)
- Modelo de dados: [docs/DATA_MODEL.md](docs/DATA_MODEL.md)
- Decisões da Fase 0: [docs/decisoes-fase-0.md](docs/decisoes-fase-0.md)
