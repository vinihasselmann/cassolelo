from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx

import manage_webhooks as mw

B = mw.BASE_URL
FOLDER = "urn:adsk.wipprod:fs.folder:co.F1"
HOOKS = f"{B}/webhooks/v1/systems/data/hooks"


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=B) as c:
        yield c


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mw, "load_dotenv", lambda *_a, **_k: None)
    monkeypatch.setenv("APS_CLIENT_ID", "cid")
    monkeypatch.setenv("APS_CLIENT_SECRET", "s")
    monkeypatch.setenv("APS_REGION", "US")
    monkeypatch.setenv("APS_WEBHOOK_SECRET", "x" * 32)


def token_ok() -> respx.Route:
    return respx.post(f"{B}{mw.TOKEN_PATH}").respond(200, json={"access_token": "tok"})


@respx.mock
def test_create_both_events_with_scope_attribute_and_callback(
    http: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    tok = token_ok()
    routes = {
        ev: respx.post(f"{B}/webhooks/v1/systems/data/events/{ev}/hooks").respond(
            201, headers={"Location": f"{B}/webhooks/v1/systems/data/events/{ev}/hooks/id-{ev}"}
        )
        for ev in mw.EVENTS
    }
    argv = [
        "create",
        "--folder",
        FOLDER,
        "--callback",
        "https://t.example/hooks/aps",
        "--obra-id",
        "OBRA-1",
    ]
    assert mw.main(argv, http=http) == 0
    out = capsys.readouterr().out
    assert "scope=data%3Aread" in tok.calls.last.request.content.decode()
    for ev, route in routes.items():
        body = json.loads(route.calls.last.request.content)
        assert body == {
            "callbackUrl": "https://t.example/hooks/aps",
            "scope": {"folder": FOLDER},
            "hookAttribute": {"obra_id": "OBRA-1"},
        }
        assert f"criado id-{ev}" in out
    assert "tok\n" not in out and " tok" not in out


@respx.mock
def test_create_conflict_reports_existing(http: httpx.Client) -> None:
    respx.post(url__regex=r".*/events/.*/hooks").respond(409)
    wh = mw.WebhooksClient(http, "t")
    assert wh.create("dm.version.added", FOLDER, "https://x/hooks/aps", "O") is None


@respx.mock
def test_list_follows_pagination(http: httpx.Client) -> None:
    respx.get(HOOKS, params={"pageState": "p2"}).respond(
        200, json={"links": {"next": None}, "data": [{"hookId": "2"}]}
    )
    respx.get(HOOKS).respond(
        200,
        json={
            "links": {"next": "/webhooks/v1/systems/data/hooks?pageState=p2"},
            "data": [{"hookId": "1"}],
        },
    )
    assert [h["hookId"] for h in mw.WebhooksClient(http, "t").list()] == ["1", "2"]


@respx.mock
def test_delete_all_only_our_events(http: httpx.Client) -> None:
    token_ok()
    respx.get(HOOKS).respond(
        200,
        json={
            "data": [
                {"hookId": "a", "event": "dm.version.added"},
                {"hookId": "b", "event": "dm.folder.added"},
            ]
        },
    )
    deleted = respx.delete(f"{B}/webhooks/v1/systems/data/events/dm.version.added/hooks/a")
    deleted.respond(204)
    assert mw.main(["delete", "--all"], http=http) == 0
    assert deleted.called
    assert len(respx.calls) == 3  # token, list, 1 delete


@respx.mock
def test_set_secret_creates_or_updates(http: httpx.Client) -> None:
    post = respx.post(f"{B}/webhooks/v1/tokens")
    put = respx.put(f"{B}/webhooks/v1/tokens/@me").respond(204)
    wh = mw.WebhooksClient(http, "t")
    post.respond(200)
    assert wh.set_secret("s" * 20) == "criado"
    post.respond(400)
    assert wh.set_secret("s" * 20) == "atualizado"
    assert json.loads(put.calls.last.request.content) == {"token": "s" * 20}


def test_set_secret_requires_long_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APS_WEBHOOK_SECRET", "curto")
    with respx.mock:
        token_ok()
        with httpx.Client(base_url=B) as http:
            assert mw.main(["set-secret"], http=http) == 1
    assert "16+" in capsys.readouterr().err


@respx.mock
def test_403_message(http: httpx.Client) -> None:
    respx.get(HOOKS).respond(403)
    with pytest.raises(mw.WebhookError, match="Custom Integrations"):
        mw.WebhooksClient(http, "t").list()


def test_region_header(http: httpx.Client) -> None:
    assert "x-ads-region" not in mw.WebhooksClient(http, "t", "US")._headers
    assert mw.WebhooksClient(http, "t", "EMEA")._headers["x-ads-region"] == "EMEA"


def test_delete_requires_target() -> None:
    with pytest.raises(SystemExit):
        mw.parse_args(["delete"])
