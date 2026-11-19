"""Segurança HTTP (10.2): CORS, cabeçalhos e limite de taxa nas escritas."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.enums import Role
from app.observability.metrics import MemoryMetricsStore
from app.security import MemoryRateLimiter
from app.security.headers import API_CSP
from tests.conftest import as_user, build_app, make_settings

APP = "https://bim.cassol.local"

# fora de dev o backend exige o login Microsoft configurado (Fase 11)
ENTRA: dict[str, Any] = {"entra_client_id": "cid", "entra_tenant_id": "tid"}


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- config


def test_cors_origins_default_to_app_base_url_outside_dev() -> None:
    s = make_settings(app_env="prod", **ENTRA, app_base_url=APP + "/")
    assert s.cors_origin_list == [APP]
    assert make_settings(app_env="dev", app_base_url=APP).cors_origin_list == []


def test_cors_origins_explicit_list_is_normalized() -> None:
    s = make_settings(cors_origins=f" {APP}/app , http://127.0.0.1:5173 ")
    assert s.cors_origin_list == [APP, "http://127.0.0.1:5173"]


@pytest.mark.parametrize("bad", ["*", "https://*.cassol.local", "bim.cassol.local", "ftp://x"])
def test_cors_rejects_wildcard_and_invalid_origins(bad: str) -> None:
    with pytest.raises(ValueError):
        _ = make_settings(cors_origins=bad).cors_origin_list


def test_app_refuses_to_start_with_wildcard_cors() -> None:
    with pytest.raises(ValueError, match=r"\*"):
        build_app(cors_origins="*")


# --------------------------------------------------------------------------- CORS


async def test_cors_allows_only_the_app_domain() -> None:
    async with _client(build_app(cors_origins=APP)) as c:
        ok = await c.options(
            "/api/obras",
            headers={"Origin": APP, "Access-Control-Request-Method": "PUT"},
        )
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == APP
        assert "PUT" in ok.headers["access-control-allow-methods"]

        evil = await c.options(
            "/api/obras",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "PUT"},
        )
        assert evil.status_code == 400
        assert "access-control-allow-origin" not in evil.headers

        simple = await c.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in simple.headers


async def test_no_cors_headers_without_configured_origins() -> None:
    async with _client(build_app()) as c:  # dev: o Vite repassa /api (mesma origem)
        r = await c.get("/api/health", headers={"Origin": APP})
        assert "access-control-allow-origin" not in r.headers


# --------------------------------------------------------------------------- cabeçalhos


async def test_security_headers_on_api_responses() -> None:
    async with _client(build_app()) as c:
        for path in ("/api/health", "/api/obras", "/api/nao-existe"):
            r = await c.get(path)
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["x-frame-options"] == "DENY"
            assert r.headers["referrer-policy"] == "no-referrer"
            assert r.headers["content-security-policy"] == API_CSP
            assert "strict-transport-security" not in r.headers  # dev (http local)


async def test_hsts_outside_dev_and_configurable() -> None:
    async with _client(build_app(app_env="prod", **ENTRA)) as c:
        r = await c.get("/api/health")
        assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    async with _client(build_app(app_env="prod", **ENTRA, hsts_max_age=0)) as c:
        assert "strict-transport-security" not in (await c.get("/api/health")).headers


async def test_docs_only_in_dev_and_without_api_csp() -> None:
    async with _client(build_app()) as c:
        r = await c.get("/docs")
        assert r.status_code == 200
        assert "content-security-policy" not in r.headers  # Swagger usa CDN
    async with _client(build_app(app_env="prod", **ENTRA)) as c:
        assert (await c.get("/docs")).status_code == 404
        assert (await c.get("/openapi.json")).status_code == 404


async def test_security_headers_on_streaming_responses(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    # resposta em fluxo (Excel/SSE passam pelo mesmo middleware ASGI)
    r = await client.get("/api/obras/999999/export.xlsx", headers=as_user(users[Role.LEITURA]))
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"


# --------------------------------------------------------------------------- limite de taxa


class Clock:
    def __init__(self) -> None:
        self.now = 60.0 * 16_667 + 20  # 20 s dentro de uma janela de 60 s

    def __call__(self) -> float:
        return self.now


@pytest_asyncio.fixture
async def limited(
    session: AsyncSession,
) -> AsyncIterator[tuple[httpx.AsyncClient, Clock, MemoryMetricsStore]]:
    clock = Clock()
    app = build_app(session, rate_limiter=MemoryRateLimiter(clock), rate_limit_writes_per_min=3)
    store = app.state.metrics
    assert isinstance(store, MemoryMetricsStore)
    async with _client(app) as c:
        yield c, clock, store


async def _create_def(c: httpx.AsyncClient, user: User, n: int) -> httpx.Response:
    body = {"name": f"Limite {n}", "type": "text"}
    return await c.post("/api/param-defs", json=body, headers=as_user(user))


async def test_write_limit_per_user_returns_429_with_retry_after(
    limited: tuple[httpx.AsyncClient, Clock, MemoryMetricsStore], users: dict[Role, User]
) -> None:
    c, clock, store = limited
    fab = users[Role.FABRICA]
    for n in range(3):
        assert (await _create_def(c, fab, n)).status_code == 201
    r = await _create_def(c, fab, 3)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "40"
    assert "limite de 3 por minuto" in r.json()["detail"]
    assert (await store.snapshot()).counters["rate_limited_total"] == 1
    # nada foi gravado na tentativa barrada
    names = [d["name"] for d in (await c.get("/api/param-defs", headers=as_user(fab))).json()]
    assert "Limite 3" not in names

    # outro usuário tem a própria conta
    assert (await _create_def(c, users[Role.ADMIN], 10)).status_code == 201
    # leituras não contam
    for _ in range(5):
        assert (await c.get("/api/obras", headers=as_user(fab))).status_code == 200
    # janela nova libera de novo
    clock.now += 60
    assert (await _create_def(c, fab, 4)).status_code == 201


async def test_rejected_by_role_still_counts_only_after_auth(
    limited: tuple[httpx.AsyncClient, Clock, MemoryMetricsStore], users: dict[Role, User]
) -> None:
    c, _, _ = limited
    # anônimo: 401 antes do limite (sem usuário não há conta a somar)
    for n in range(5):
        r = await c.post("/api/param-defs", json={"name": f"x{n}", "type": "text"})
        assert r.status_code == 401


async def test_write_limit_disabled_with_zero(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    app = build_app(session, rate_limit_writes_per_min=0)
    async with _client(app) as c:
        for n in range(5):
            assert (await _create_def(c, users[Role.FABRICA], n)).status_code == 201


class BrokenLimiter(MemoryRateLimiter):
    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        raise ConnectionError("redis fora do ar")


async def test_limiter_failure_does_not_block_writes(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    app = build_app(session, rate_limiter=BrokenLimiter(), rate_limit_writes_per_min=1)
    async with _client(app) as c:
        for n in range(3):
            assert (await _create_def(c, users[Role.FABRICA], n)).status_code == 201
