"""Fixtures compartilhadas.

Banco: cria um banco temporário `bim_test_*` no Postgres de DATABASE_URL /
TEST_DATABASE_URL, aplica as migrações e apaga no fim. Cada teste roda numa
transação desfeita ao final (savepoints para os commits do código).

Sem Postgres acessível os testes de banco são PULADOS, exceto com
REQUIRE_DB=1 (CI), em que FALHAM.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_aps_client, get_queue
from app.aps.auth import TokenProvider
from app.aps.client import ApsClient
from app.auth import DEV_USER_HEADER
from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.models import User
from app.models.enums import Role
from app.observability import metrics as obs_metrics
from app.security import MemoryRateLimiter, RateLimiter
from app.seed import seed_users
from app.services import events as events_service
from app.workers.queue import JobQueue
from tests import dbutil
from tests.apsfakes import BASE, FakeQueue, Sleeps

DUMMY_DB_URL = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"


class IsolatedSettings(Settings):
    """Settings que ignora .env e variáveis de ambiente: testes determinísticos."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_settings(**overrides: object) -> Settings:
    data: dict[str, object] = {"app_env": "dev", "database_url": DUMMY_DB_URL}
    data.update(overrides)
    return IsolatedSettings.model_validate(data)


def _db_unavailable(reason: str) -> None:
    if os.getenv("REQUIRE_DB"):
        pytest.fail(f"REQUIRE_DB=1 mas {reason}")
    pytest.skip(f"{reason} (rode `make up` para subir o Postgres)")


@pytest.fixture(scope="session")
def postgres_base_url() -> str:
    url = dbutil.base_database_url()
    if not url:
        _db_unavailable("DATABASE_URL não definido")
    assert url is not None
    if not dbutil.server_available(url):
        _db_unavailable("PostgreSQL inacessível")
    return url


@pytest.fixture(scope="session")
def database_url(postgres_base_url: str) -> Iterator[str]:
    url = dbutil.create_temp_database(postgres_base_url)
    try:
        dbutil.upgrade(url)
        yield url
    finally:
        dbutil.drop_database(url)


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            s = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            try:
                yield s
            finally:
                await s.close()
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def users(session: AsyncSession) -> dict[Role, User]:
    return await seed_users(session)


# --------------------------------------------------------------------------- APS e fila


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest_asyncio.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=BASE) as c:
        yield c


@pytest.fixture
def tokens(http: httpx.AsyncClient) -> TokenProvider:
    return TokenProvider(client_id="cid", client_secret=SecretStr("secret"), http=http)


@pytest.fixture
def aps(http: httpx.AsyncClient, tokens: TokenProvider, sleeps: Sleeps) -> ApsClient:
    return ApsClient(http=http, tokens=tokens, sleep=sleeps, backoff_base=0.01)


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest_asyncio.fixture(autouse=True)
async def event_bus() -> AsyncIterator[events_service.MemoryEventBus]:
    """Eventos em tempo real (8.1) em memória, um barramento novo por teste."""
    bus = events_service.MemoryEventBus()
    events_service.configure(bus)
    yield bus
    await events_service.drain()
    events_service.configure(None)


@pytest.fixture(autouse=True)
def metrics_store() -> Iterator[obs_metrics.MemoryMetricsStore]:
    """Métricas (10.1) em memória, um store novo por teste."""
    store = obs_metrics.MemoryMetricsStore()
    obs_metrics.configure(store)
    yield store
    obs_metrics.configure(None)


# --------------------------------------------------------------------------- app


def build_app(
    session: AsyncSession | None = None,
    *,
    aps: ApsClient | None = None,
    queue: JobQueue | None = None,
    rate_limiter: RateLimiter | None = None,
    **settings: object,
) -> FastAPI:
    bus = events_service.current_bus() or events_service.MemoryEventBus()
    store = obs_metrics.current_store() or obs_metrics.MemoryMetricsStore()
    app = create_app(
        make_settings(**settings),
        event_bus=bus,
        metrics_store=store,
        rate_limiter=rate_limiter or MemoryRateLimiter(),
    )
    if session is not None:

        async def _override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = _override
    if aps is not None:
        app.dependency_overrides[get_aps_client] = lambda: aps
    if queue is not None:
        app.dependency_overrides[get_queue] = lambda: queue
    return app


@pytest_asyncio.fixture
async def client(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(session, aps=aps, queue=queue)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def as_user(user: User) -> dict[str, str]:
    return {DEV_USER_HEADER: str(user.id)}


async def include_params(session: AsyncSession, obra_id: int, *defs: Any) -> None:
    """Inclui parâmetros da BIBLIOTECA (scope global, ativos) na obra: sem isso eles não
    valem para ela (decisão de 2026-11-13). Os de obra e os inativos são ignorados."""
    from app.models import ObraParam

    for d in defs:
        if d.scope == "global" and d.active is not False:
            session.add(ObraParam(obra_id=obra_id, def_id=d.id))
    await session.flush()
