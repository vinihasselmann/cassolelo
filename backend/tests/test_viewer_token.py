"""4.1 · GET /api/viewer-token: só viewables:read, separado do token de dados."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.auth import TOKEN_PATH
from app.aps.client import ApsClient
from app.models import User
from app.models.enums import Role
from tests.apsfakes import BASE, FakeQueue
from tests.conftest import as_user, build_app


def _scope(request: httpx.Request) -> str:
    return parse_qs(request.content.decode())["scope"][0]


def _token_route(expires_in: int = 3599) -> respx.Route:
    def reply(request: httpx.Request) -> httpx.Response:
        scope = _scope(request)
        token = "VIEWER-TOKEN" if scope == "viewables:read" else "DATA-TOKEN"
        return httpx.Response(200, json={"access_token": token, "expires_in": expires_in})

    return respx.post(f"{BASE}{TOKEN_PATH}").mock(side_effect=reply)


@respx.mock
async def test_viewer_token_only_viewables_read(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    route = _token_route()
    r = await client.get("/api/viewer-token", headers=as_user(users[Role.FABRICA]))
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "VIEWER-TOKEN"
    assert body["token_type"] == "Bearer"
    assert body["region"] == "US"
    assert 0 < body["expires_in"] <= 600  # expiração curta informada ao navegador
    assert r.headers["cache-control"] == "no-store"
    assert [_scope(c.request) for c in route.calls] == ["viewables:read"]


@respx.mock
async def test_viewer_token_is_not_the_data_token(
    client: httpx.AsyncClient, users: dict[Role, User], aps: ApsClient
) -> None:
    route = _token_route()
    data_token = await aps.tokens.get_token()  # data:read viewables:read (cache)
    r = await client.get("/api/viewer-token", headers=as_user(users[Role.LEITURA]))
    assert data_token == "DATA-TOKEN"
    assert r.json()["access_token"] == "VIEWER-TOKEN"
    assert sorted(_scope(c.request) for c in route.calls) == [
        "data:read viewables:read",
        "viewables:read",
    ]


@respx.mock
async def test_viewer_token_cached_and_ttl_follows_remaining_time(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    route = _token_route(expires_in=300)
    headers = as_user(users[Role.PROJETOS])
    first = (await client.get("/api/viewer-token", headers=headers)).json()
    second = (await client.get("/api/viewer-token", headers=headers)).json()
    assert route.call_count == 1
    assert first["expires_in"] <= 300 and second["expires_in"] <= 300


async def test_viewer_token_requires_user(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/viewer-token")
    assert r.status_code == 401


@respx.mock
async def test_viewer_token_without_credentials_is_502(
    session: AsyncSession, users: dict[Role, User], http: httpx.AsyncClient
) -> None:
    app = build_app(session, queue=FakeQueue())  # cliente APS real, sem credenciais
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/viewer-token", headers=as_user(users[Role.FABRICA]))
    assert r.status_code == 502 and r.json()["code"] == "aps_auth"
    assert "access_token" not in r.text


async def test_viewer_token_region_from_settings(
    session: AsyncSession, users: dict[Role, User], aps: ApsClient
) -> None:
    with respx.mock:
        _token_route()
        app = build_app(session, aps=aps, queue=FakeQueue(), aps_region="EMEA")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/viewer-token", headers=as_user(users[Role.FABRICA]))
    assert r.json()["region"] == "EMEA"
