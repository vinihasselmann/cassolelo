"""Aplicação FastAPI.

Rodar em desenvolvimento:  uv run uvicorn app.main:create_app --factory --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    acc,
    batches,
    color_schemes,
    dev,
    errors,
    events,
    export,
    health,
    marks,
    me,
    obras,
    orphans,
    param_defs,
    saved_filters,
    units,
    versions,
    viewer,
    webhooks,
)
from app.aps import ApsClient, build_aps_client
from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.observability import metrics
from app.observability.logging import RequestContextMiddleware, configure_logging
from app.observability.metrics import MetricsStore, RedisMetricsStore
from app.security import (
    RateLimiter,
    RedisRateLimiter,
    SecurityHeadersMiddleware,
    add_cors,
)
from app.services import events as events_service
from app.services.events import EventBus, RedisEventBus
from app.workers.queue import ArqQueue


def ready_checks(
    settings: Settings, aps: ApsClient, store: MetricsStore
) -> dict[str, Callable[[], Awaitable[str | None]]]:
    """Checagens do /api/ready além do banco: Redis e APS."""

    async def redis() -> str | None:
        if not isinstance(store, RedisMetricsStore):
            return "métricas em memória (sem Redis)"
        await store.ping()
        return None

    async def aps_token() -> str | None:
        if not settings.aps_client_id:
            if settings.is_dev:
                return "skipped: APS_CLIENT_ID não configurado (dev)"
            raise RuntimeError("APS_CLIENT_ID não configurado.")
        await aps.tokens.get_token()  # 2-legged (cache): credenciais válidas e APS no ar
        return None

    return {"redis": redis, "aps": aps_token}


def create_app(
    settings: Settings | None = None,
    *,
    event_bus: EventBus | None = None,
    metrics_store: MetricsStore | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)  # JSON, sem segredos (10.1)
    engine = create_engine(settings.database_url)
    aps = build_aps_client(settings)
    queue = ArqQueue(settings.redis_url)
    bus = event_bus or RedisEventBus(settings.redis_url)
    events_service.configure(bus)  # publicação depois do commit (services/events.py)
    store = metrics_store or RedisMetricsStore(settings.redis_url)
    metrics.configure(store)
    limiter = rate_limiter or RedisRateLimiter(settings.redis_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await events_service.drain()
        await bus.close()
        if isinstance(store, RedisMetricsStore):
            await store.close()
        await limiter.close()
        await queue.close()
        await aps.http.aclose()
        await engine.dispose()

    # Swagger/ReDoc só em dev (fora dele a API não se descreve publicamente)
    app = FastAPI(
        title="Cassol Elo",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_dev else None,
        redoc_url="/redoc" if settings.is_dev else None,
        openapi_url="/openapi.json" if settings.is_dev else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.aps = aps
    app.state.queue = queue
    app.state.events = bus
    app.state.metrics = store
    app.state.ready_checks = ready_checks(settings, aps, store)
    app.state.rate_limiter = limiter  # escritas por usuário por minuto (10.2)
    add_cors(app, settings)  # só o domínio do app (10.2)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)  # CSP, HSTS, nosniff
    app.add_middleware(RequestContextMiddleware)  # request_id, obra e linha de acesso

    errors.register(app)
    core = (health, me, dev, acc, obras, events, export, batches, marks, orphans, units)
    views = (saved_filters, color_schemes)
    for module in (*core, param_defs, *views, versions, viewer, webhooks):
        app.include_router(module.router, prefix="/api")
    return app
