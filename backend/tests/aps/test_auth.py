from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.aps.auth import TOKEN_PATH, TokenProvider
from app.aps.errors import ApsAuthError, ApsForbiddenError
from tests.aps.conftest import BASE, fixture


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


@respx.mock
async def test_token_cached_until_60s_before_expiry(http: httpx.AsyncClient) -> None:
    route = respx.post(f"{BASE}{TOKEN_PATH}").respond(200, json=fixture("token.json"))
    clock = Clock()
    tp = TokenProvider(client_id="cid", client_secret=SecretStr("s"), http=http, clock=clock)

    assert await tp.get_token() == "FAKE-ACCESS-TOKEN"
    clock.now += 3500  # ainda > 60 s de validade
    await tp.get_token()
    assert route.call_count == 1
    clock.now += 40  # faltam 59 s: renova
    await tp.get_token()
    assert route.call_count == 2

    req = route.calls.last.request
    assert req.headers["authorization"].startswith("Basic ")
    assert "grant_type=client_credentials" in req.content.decode()


@respx.mock
async def test_cache_is_per_scope_set(tokens: TokenProvider) -> None:
    route = respx.post(f"{BASE}{TOKEN_PATH}").respond(200, json=fixture("token.json"))
    await tokens.get_token(["data:read", "viewables:read"])
    await tokens.get_token(["viewables:read", "data:read"])  # mesma chave
    _, ttl = await tokens.get_token_with_ttl(["viewables:read"])
    assert route.call_count == 2
    assert 3500 < ttl <= 3599
    assert "scope=viewables%3Aread" in route.calls.last.request.content.decode()


@pytest.mark.parametrize("scope", ["data:write", "data:create", "account:read", "bucket:create"])
async def test_disallowed_scopes_rejected(tokens: TokenProvider, scope: str) -> None:
    with pytest.raises(ValueError, match="não permitidos"):
        await tokens.get_token([scope])


@pytest.mark.parametrize(
    ("status", "exc"), [(401, ApsAuthError), (400, ApsAuthError), (403, ApsForbiddenError)]
)
@respx.mock
async def test_token_errors(tokens: TokenProvider, status: int, exc: type[Exception]) -> None:
    respx.post(f"{BASE}{TOKEN_PATH}").respond(status)
    with pytest.raises(exc):
        await tokens.get_token()


async def test_missing_credentials(http: httpx.AsyncClient) -> None:
    tp = TokenProvider(client_id="", client_secret=SecretStr(""), http=http)
    with pytest.raises(ApsAuthError, match="não configurados"):
        await tp.get_token()


def test_access_token_repr_hides_value() -> None:
    from app.aps.auth import AccessToken

    assert "SEGREDO" not in repr(AccessToken(value="SEGREDO", expires_at=1.0))
