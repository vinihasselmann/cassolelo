from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import viewer_app as va


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_cache_reuses_until_near_expiry() -> None:
    calls: list[int] = []

    def fetch() -> tuple[str, int]:
        calls.append(1)
        return f"t{len(calls)}", 3600

    clock = FakeClock()
    cache = va.TokenCache(fetch, clock=clock, margin=60)
    assert cache.get() == ("t1", 3600)
    clock.now = 3000
    assert cache.get() == ("t1", 600)
    clock.now = 3541  # dentro da margem: renova
    assert cache.get()[0] == "t2"
    assert len(calls) == 2


@respx.mock
def test_fetch_viewer_token_requests_only_viewables_read() -> None:
    route = respx.post(f"{va.BASE_URL}{va.TOKEN_PATH}").respond(
        200, json={"access_token": "v", "expires_in": 3599}
    )
    with httpx.Client(base_url=va.BASE_URL) as http:
        assert va.fetch_viewer_token("id", "s", http) == ("v", 3599)
    body = route.calls.last.request.content.decode()
    assert "scope=viewables%3Aread" in body
    assert "data%3A" not in body


@pytest.mark.parametrize(("status", "msg"), [(401, "credenciais"), (403, "Custom Integrations")])
@respx.mock
def test_fetch_viewer_token_errors(status: int, msg: str) -> None:
    respx.post(f"{va.BASE_URL}{va.TOKEN_PATH}").respond(status)
    with httpx.Client(base_url=va.BASE_URL) as http, pytest.raises(va.TokenError, match=msg):
        va.fetch_viewer_token("id", "s", http)


def client(fetch: va.TokenCache | None = None) -> TestClient:
    cache = fetch or va.TokenCache(lambda: ("abc", 3600))
    return TestClient(va.create_app(cache=cache, mark_names=["Marca", "Mark"]))


def test_token_endpoint() -> None:
    r = client().get("/token")
    assert r.status_code == 200
    assert r.json()["access_token"] == "abc"
    assert r.headers["cache-control"] == "no-store"


def test_token_endpoint_error_is_502() -> None:
    def boom() -> tuple[str, int]:
        raise va.TokenError("app não liberado em Custom Integrations")

    r = client(va.TokenCache(boom)).get("/token")
    assert r.status_code == 502
    assert "Custom Integrations" in r.json()["detail"]


def test_config_and_index() -> None:
    c = client()
    assert c.get("/config").json()["mark_property_names"] == ["Marca", "Mark"]
    html = c.get("/").text
    assert "viewers/7." in html
    assert "AutodeskProduction2" in html and "streamingV2" in html
