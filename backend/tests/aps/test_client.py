from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
import respx

from app.aps.auth import TOKEN_PATH
from app.aps.client import ApsClient, check_allowed
from app.aps.errors import (
    ApsError,
    ApsForbiddenError,
    ApsForbiddenOperationError,
    ApsHttpError,
    ApsNotFoundError,
)
from tests.aps.conftest import BASE, Sleeps, fixture

HUBS = f"{BASE}/project/v1/hubs"


def token_route() -> respx.Route:
    return respx.post(f"{BASE}{TOKEN_PATH}").respond(200, json=fixture("token.json"))


@respx.mock
async def test_sends_bearer_and_returns_json(aps: ApsClient) -> None:
    token_route()
    route = respx.get(HUBS).respond(200, json=fixture("hubs.json"))
    body = await aps.get_json("/project/v1/hubs")
    assert body["data"][0]["type"] == "hubs"
    assert route.calls.last.request.headers["authorization"] == "Bearer FAKE-ACCESS-TOKEN"


@pytest.mark.parametrize("status", [429, 500, 502, 503])
@respx.mock
async def test_retries_with_exponential_backoff(
    aps: ApsClient, sleeps: Sleeps, status: int
) -> None:
    token_route()
    route = respx.get(HUBS).mock(
        side_effect=[httpx.Response(status), httpx.Response(status), httpx.Response(200, json={})]
    )
    assert await aps.get_json("/project/v1/hubs") == {}
    assert route.call_count == 3
    assert len(sleeps.calls) == 2
    base = 0.01  # backoff_base do fixture `aps`
    for attempt, delay in enumerate(sleeps.calls):  # base*2^n + jitter em [0, base]
        assert base * 2**attempt <= delay <= base * 2**attempt + base


@respx.mock
async def test_429_respects_retry_after(aps: ApsClient, sleeps: Sleeps) -> None:
    token_route()
    respx.get(HUBS).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={}),
        ]
    )
    await aps.get_json("/project/v1/hubs")
    assert sleeps.calls == [7.0]


@respx.mock
async def test_gives_up_after_max_retries(aps: ApsClient, sleeps: Sleeps) -> None:
    token_route()
    route = respx.get(HUBS).respond(503)
    with pytest.raises(ApsHttpError) as exc:
        await aps.get_json("/project/v1/hubs")
    assert exc.value.status_code == 503
    assert route.call_count == 5  # 1 + 4 retentativas
    assert len(sleeps.calls) == 4


@respx.mock
async def test_retries_network_errors(aps: ApsClient) -> None:
    token_route()
    respx.get(HUBS).mock(side_effect=[httpx.ConnectError("x"), httpx.Response(200, json={})])
    assert await aps.get_json("/project/v1/hubs") == {}


@respx.mock
async def test_401_renews_token_once_then_forbidden(aps: ApsClient) -> None:
    tok = token_route()
    respx.get(HUBS).respond(401)
    with pytest.raises(ApsForbiddenError, match="Custom Integrations"):
        await aps.get_json("/project/v1/hubs")
    assert tok.call_count == 2


@pytest.mark.parametrize(
    ("status", "exc"), [(403, ApsForbiddenError), (404, ApsNotFoundError), (400, ApsHttpError)]
)
@respx.mock
async def test_error_mapping(aps: ApsClient, status: int, exc: type[ApsError]) -> None:
    token_route()
    respx.get(HUBS).respond(status)
    with pytest.raises(exc):
        await aps.get_json("/project/v1/hubs")


@respx.mock
async def test_paginate_follows_next_links(aps: ApsClient) -> None:
    token_route()
    path = "/project/v1/hubs/b.00000000-0000-0000-0000-000000000001/projects"
    respx.get(f"{BASE}{path}", params={"page[number]": "1"}).respond(
        200, json=fixture("projects_page2.json")
    )
    respx.get(f"{BASE}{path}").respond(200, json=fixture("projects_page1.json"))
    names = [d["attributes"]["name"] async for d in aps.paginate(path)]
    assert names == ["OBRA TESTE 001", "OBRA TESTE 002"]


@respx.mock
async def test_logs_never_contain_token(aps: ApsClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    token_route()
    respx.get(HUBS).mock(side_effect=[httpx.Response(500), httpx.Response(200, json={})])
    await aps.get_json("/project/v1/hubs")
    assert "APS GET /project/v1/hubs -> 200" in caplog.text
    assert "FAKE-ACCESS-TOKEN" not in caplog.text
    assert "secret" not in caplog.text


# --------------------------------------------------------------------------- regras do projeto


@pytest.mark.parametrize(
    "path",
    [
        "/modelderivative/v2/designdata/job",
        "/modelderivative/v2/designdata/job/",
        "/modelderivative/v2/regions/eu/designdata/job",
        "https://developer.api.autodesk.com/modelderivative/v2/designdata/job?x=1",
    ],
)
async def test_post_job_is_forbidden_and_never_sent(aps: ApsClient, path: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        sent = router.route()  # qualquer requisição
        with pytest.raises(ApsForbiddenOperationError, match="proibido"):
            await aps.request("POST", path)
    assert not sent.called


async def test_aec_data_model_is_forbidden(aps: ApsClient) -> None:
    with pytest.raises(ApsForbiddenOperationError, match="AEC"):
        await aps.request("POST", "/aec/graphql")


def test_get_manifest_path_is_allowed() -> None:
    check_allowed("GET", "/modelderivative/v2/designdata/abc/manifest")
    check_allowed("GET", "/modelderivative/v2/designdata/job")  # GET não converte nada


def test_no_source_code_calls_post_job_or_aec() -> None:
    """Nenhum módulo do app (fora a trava em client.py) menciona o endpoint /job ou AEC."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    offenders = []
    for py in app_dir.rglob("*.py"):
        if py.name == "client.py" and py.parent.name == "aps":
            continue
        src = py.read_text(encoding="utf-8").lower()
        if "designdata/job" in src or "/aec/" in src or "aecdatamodel" in src:
            offenders.append(str(py.relative_to(app_dir)))
    assert offenders == []
