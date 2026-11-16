# Imagem de produção do backend (API, worker e migrações usam a mesma imagem).
# Build: docker build -t visualizador-bim-backend backend/

# --- estágio 1: dependências (só as de produção) num venv isolado
FROM ghcr.io/astral-sh/uv:0.11.7 AS uv
FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- estágio 2: runtime enxuto, sem uv nem compiladores, usuário sem root
FROM python:3.12-slim-bookworm
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin bim
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SECRETS_DIR=/run/secrets \
    LOG_FORMAT=json
USER bim
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
# O nginx fica na frente (X-Forwarded-*). 2 processos: cabe num servidor de 2+ vCPU.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
