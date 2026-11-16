"""2.3 · Webhooks: recebimento, idempotência, registro (CLI) e verificação periódica."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import webhooks as wh
from app.aps.client import ApsClient
from app.cli import run as cli_run
from app.models import Obra, WebhookEvent
from app.services import webhooks as service
from app.services.versions import sync_all_obras
from app.workers.settings import WorkerSettings
from tests.apsfakes import (
    BASE,
    FOLDER,
    HUB,
    ITEM,
    PROJECT,
    FakeQueue,
    fixture,
    mock_manifest,
    mock_token,
)
from tests.conftest import build_app, make_settings

SECRET = "segredo-de-teste-com-mais-de-16"
VERSIONS_URL = f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}/versions"


async def _obra(session: AsyncSession, code: str = "OB-W", **kw: Any) -> Obra:
    fields: dict[str, Any] = {
        "name": "Obra webhook",
        "acc_hub_id": HUB,
        "acc_project_id": PROJECT,
        "acc_folder_id": FOLDER,
        "acc_item_id": ITEM,
    }
    obra = Obra(code=code, **(fields | kw))
    session.add(obra)
    await session.flush()
    return obra


def _payload(obra_id: int | None, version: int = 3, lineage: str = ITEM) -> dict[str, Any]:
    attrs = {"obra_id": str(obra_id)} if obra_id is not None else {}
    return {
        "version": "1.0",
        "resourceUrn": f"urn:adsk.wipprod:fs.file:vf.X?version={version}",
        "hook": {
            "hookId": "h-1",
            "event": "dm.version.added",
            "scope": {"folder": FOLDER},
            "hookAttribute": attrs,
        },
        "payload": {
            "name": "OBRA-001-PRE.rvt",
            "version": version,
            "lineageUrn": lineage,
            "parentFolderUrn": FOLDER,
        },
    }


def _signed(payload: dict[str, Any], secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    return body, {
        wh.SIGNATURE_HEADER: wh.compute_signature(secret, body),
        "content-type": "application/json",
    }


@pytest_asyncio.fixture
async def hook_client(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(session, aps=aps, queue=queue, aps_webhook_secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _events(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(WebhookEvent)) or 0)


# --------------------------------------------------------------------------- assinatura


def test_signature_roundtrip() -> None:
    body = b'{"a":1}'
    sig = wh.compute_signature(SECRET, body)
    assert sig.startswith("sha1hash=") and wh.verify_signature(SECRET, body, sig)
    assert wh.verify_signature(SECRET, body, sig.removeprefix("sha1hash="))
    assert not wh.verify_signature(SECRET, body + b" ", sig)
    assert not wh.verify_signature("", body, sig)


@pytest.mark.parametrize("signature", [None, "sha1hash=00", "lixo"])
async def test_invalid_signature_is_401(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue, signature: str | None
) -> None:
    obra = await _obra(session)
    body = json.dumps(_payload(obra.id)).encode()
    headers = {wh.SIGNATURE_HEADER: signature} if signature else {}
    r = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.status_code == 401
    assert await _events(session) == 0 and queue.jobs == []


async def test_signed_with_other_secret_is_401(
    hook_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    body, headers = _signed(_payload(1), secret="outro-segredo-qualquer-123")
    r = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.status_code == 401


async def test_secret_not_configured_is_503(session: AsyncSession) -> None:
    app = build_app(session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/webhooks/aps", content=b"{}")
    assert r.status_code == 503


# --------------------------------------------------------------------------- recebimento


async def test_valid_event_is_stored_and_enqueues_sync(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    obra = await _obra(session)
    body, headers = _signed(_payload(obra.id))
    r = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.status_code == 200 and r.json() == {"status": "queued"}

    event = await session.scalar(select(WebhookEvent))
    assert event is not None and event.obra_id == obra.id and event.processed_at is None
    assert event.payload["hook"]["event"] == "dm.version.added"
    assert queue.jobs == [
        (service.SYNC_OBRA_JOB, (obra.id, event.id), f"sync_obra:{obra.id}:{event.id}")
    ]


async def test_repeated_event_does_not_enqueue_twice(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    obra = await _obra(session)
    body, headers = _signed(_payload(obra.id))
    first = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    second = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert first.json()["status"] == "queued"
    assert second.status_code == 200 and second.json() == {"status": "duplicate"}
    assert await _events(session) == 1
    assert len(queue.jobs) == 1


async def test_delivery_id_header_is_the_event_id(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    obra = await _obra(session)
    for version in (3, 4):  # corpos diferentes, mesma entrega => duplicado
        body, headers = _signed(_payload(obra.id, version=version))
        headers[service.DELIVERY_ID_HEADER] = "entrega-1"
        await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert await _events(session) == 1 and len(queue.jobs) == 1


async def test_obra_found_by_folder_and_lineage(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    obra = await _obra(session)
    await _obra(session, code="OUTRA", acc_item_id="urn:adsk.wipprod:dm.lineage:OUTRO")
    body, headers = _signed(_payload(None))
    r = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.json()["status"] == "queued"
    assert queue.jobs[0][1][0] == obra.id


async def test_file_wins_over_hook_attribute_when_obras_share_folder(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    """Duas obras na mesma pasta dividem o hook: o evento chega com o obra_id de quem
    registrou, mas a obra certa é a do arquivo (lineage)."""
    a = await _obra(session)
    b = await _obra(session, code="OUTRA", acc_item_id="urn:adsk.wipprod:dm.lineage:OUTRO")
    body, headers = _signed(_payload(a.id, lineage="urn:adsk.wipprod:dm.lineage:OUTRO"))
    await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert queue.jobs[0][1][0] == b.id

    # arquivo da pasta que não é de nenhuma obra: guardado, sem sincronizar nada
    body, headers = _signed(_payload(a.id, version=9, lineage="urn:adsk.wipprod:dm.lineage:SOLTO"))
    r = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.json()["status"] == "no_obra" and len(queue.jobs) == 1


async def test_event_without_obra_is_kept_but_not_enqueued(
    hook_client: httpx.AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    body, headers = _signed(_payload(None, lineage="urn:adsk.wipprod:dm.lineage:DESCONHECIDO"))
    r = await hook_client.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.status_code == 200 and r.json() == {"status": "no_obra"}
    assert await _events(session) == 1 and queue.jobs == []


async def test_queue_down_still_returns_200(session: AsyncSession, aps: ApsClient) -> None:
    obra = await _obra(session)
    app = build_app(session, aps=aps, queue=FakeQueue(fail=True), aps_webhook_secret=SECRET)
    body, headers = _signed(_payload(obra.id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/webhooks/aps", content=body, headers=headers)
    assert r.status_code == 200
    assert await _events(session) == 1


async def test_mark_processed(session: AsyncSession) -> None:
    obra = await _obra(session)
    event, _ = await service.record_event(session, b"x", _payload(obra.id), None)
    assert event is not None
    await service.mark_processed(session, event.id)
    assert event.processed_at is not None


# --------------------------------------------------------------------------- registro de hooks


def _hooks_routes(router: respx.Router | None = None) -> dict[str, respx.Route]:
    r = router if router is not None else respx
    return {
        ev: r.post(f"{BASE}/webhooks/v1/systems/data/events/{ev}/hooks").respond(
            201, headers={"Location": f"{BASE}/webhooks/v1/systems/data/events/{ev}/hooks/id-{ev}"}
        )
        for ev in wh.VERSION_EVENTS
    }


@respx.mock
async def test_cli_register_creates_both_events_on_obra_folder(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_token()
    routes = _hooks_routes()
    obra = await _obra(session)
    settings = make_settings(public_base_url="https://tunel.example/")
    code = await cli_run(["hooks", "register", "--obra", str(obra.id)], settings, session, aps)
    assert code == 0
    out = capsys.readouterr().out
    for ev, route in routes.items():
        sent = json.loads(route.calls.last.request.content)
        assert sent["callbackUrl"] == "https://tunel.example/api/webhooks/aps"
        assert sent["scope"] == {"folder": FOLDER}
        assert sent["hookAttribute"] == {"obra_id": str(obra.id)}
        assert f"{ev}: criado id-{ev}" in out


async def test_cli_register_requires_public_url(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    obra = await _obra(session)
    code = await cli_run(
        ["hooks", "register", "--obra", str(obra.id)], make_settings(), session, aps
    )
    assert code == 2 and "PUBLIC_BASE_URL" in capsys.readouterr().err


@respx.mock
async def test_cli_list_and_delete_only_obra_hooks(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_token()
    obra = await _obra(session)
    hooks = [
        {"hookId": "a", "event": "dm.version.added", "hookAttribute": {"obra_id": str(obra.id)}},
        {"hookId": "b", "event": "dm.version.modified", "hookAttribute": {"obra_id": str(obra.id)}},
        {"hookId": "c", "event": "dm.version.added", "hookAttribute": {"obra_id": "999"}},
    ]
    respx.get(f"{BASE}/webhooks/v1/systems/data/hooks").respond(200, json={"data": hooks})
    deleted = [
        respx.delete(
            f"{BASE}/webhooks/v1/systems/data/events/{h['event']}/hooks/{h['hookId']}"
        ).respond(204)
        for h in hooks[:2]
    ]
    other = respx.delete(url__regex=r".*/hooks/c$").respond(204)
    settings = make_settings()

    assert await cli_run(["hooks", "list", "--obra", str(obra.id)], settings, session, aps) == 0
    out = capsys.readouterr().out
    assert "a  dm.version.added" in out and "c  " not in out

    assert await cli_run(["hooks", "delete", "--obra", str(obra.id)], settings, session, aps) == 0
    assert all(r.called for r in deleted) and not other.called


@respx.mock
async def test_auto_register_on_create_when_public_url_set(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    from app.models.enums import Role
    from app.seed import seed_users
    from tests.conftest import as_user

    users = await seed_users(session)
    mock_token()
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}").respond(
        200, json=fixture("item.json")
    )
    routes = _hooks_routes()
    app = build_app(session, aps=aps, queue=queue, public_base_url="https://tunel.example")
    payload = {
        "code": "OB-AUTO",
        "name": "Auto",
        "acc": {"hub_id": HUB, "project_id": PROJECT, "folder_id": FOLDER, "item_id": ITEM},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/obras", json=payload, headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 201
    assert all(route.called for route in routes.values())


async def test_no_auto_register_without_public_url(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    from app.models.enums import Role
    from app.seed import seed_users
    from tests.conftest import as_user

    users = await seed_users(session)
    payload = {
        "code": "OB-MAN",
        "name": "Manual",
        "acc": {"hub_id": HUB, "project_id": PROJECT, "folder_id": FOLDER, "item_id": ITEM},
    }
    with respx.mock(assert_all_called=False) as router:
        mock_token(router)
        router.get(f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}").respond(
            200, json=fixture("item.json")
        )
        routes = _hooks_routes(router)
        r = await client.post("/api/obras", json=payload, headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 201
    assert not any(route.called for route in routes.values())


# --------------------------------------------------------------------------- verificação periódica


def test_worker_schedules_periodic_jobs() -> None:
    crons = {c.name.split(":")[-1]: c for c in WorkerSettings.cron_jobs}
    assert crons["sync_all_obras"].minute == set(range(0, 60, 10))
    assert crons["check_translations"].minute == set(range(0, 60, 2))
    names = {f.__name__ for f in WorkerSettings.functions}
    assert {"process_version", "sync_obra"} <= names


@respx.mock
async def test_sync_all_obras_only_active_and_linked(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    active = await _obra(session, code="ATIVA")
    await _obra(session, code="INATIVA", active=False)
    unlinked = Obra(code="SEM-ARQ", name="sem arquivo")
    session.add(unlinked)
    await session.flush()

    synced = await sync_all_obras(session, aps, queue)
    assert synced == [active.id]


@respx.mock
async def test_sync_all_obras_continues_after_failure(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    other_item = "urn:adsk.wipprod:dm.lineage:QUEBRADO"
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/items/{other_item}/versions").respond(500)
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    await _obra(session, code="A-QUEBRADA", acc_item_id=other_item)
    ok = await _obra(session, code="B-OK")
    await session.commit()  # como em produção: as obras já existem antes da verificação
    assert await sync_all_obras(session, aps, queue) == [ok.id]


# --------------------------------------------------------------------------- re-registro (10.3)

NEW_URL = "https://bim.cassol.example/api/webhooks/aps"


@respx.mock
async def test_cli_reregister_all_replaces_old_url_and_registers_every_obra(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_token()
    a = await _obra(session, "OB-A")
    b = await _obra(session, "OB-B", acc_folder_id="urn:pasta-b")
    no_folder = await _obra(session, "OB-C", acc_folder_id=None)
    inactive = await _obra(session, "OB-D", active=False)
    old = [
        {
            "hookId": "old1",
            "event": "dm.version.added",
            "callbackUrl": "https://tunel.old/api/webhooks/aps",
        },
        {
            "hookId": "old2",
            "event": "dm.version.modified",
            "callbackUrl": "https://tunel.old/api/webhooks/aps",
        },
        {"hookId": "keep", "event": "dm.version.added", "callbackUrl": NEW_URL},
        {"hookId": "other", "event": "dm.folder.added", "callbackUrl": "https://x"},
    ]
    respx.get(f"{BASE}/webhooks/v1/systems/data/hooks").respond(200, json={"data": old})
    dels = {
        h["hookId"]: respx.delete(
            f"{BASE}/webhooks/v1/systems/data/events/{h['event']}/hooks/{h['hookId']}"
        ).respond(204)
        for h in old
    }
    routes = _hooks_routes()
    settings = make_settings(public_base_url="https://bim.cassol.example")

    code = await cli_run(["hooks", "reregister", "--all"], settings, session, aps)

    assert code == 0
    assert dels["old1"].called and dels["old2"].called
    assert not dels["keep"].called and not dels["other"].called  # URL nova / outro evento
    folders = [
        json.loads(c.request.content)["scope"]["folder"] for c in routes["dm.version.added"].calls
    ]
    assert sorted(folders) == sorted([FOLDER, "urn:pasta-b"])
    sent = [json.loads(c.request.content) for r in routes.values() for c in r.calls]
    assert {s["callbackUrl"] for s in sent} == {NEW_URL}
    assert {s["hookAttribute"]["obra_id"] for s in sent} == {str(a.id), str(b.id)}
    out = capsys.readouterr().out
    assert "2 hook(s) com URL antiga apagado(s)." in out
    assert f"obra {no_folder.id}: ignorada (sem pasta do Docs)" in out
    assert f"obra {inactive.id}: ignorada (inativa)" in out


async def test_cli_reregister_without_public_url_explains_periodic_check(
    session: AsyncSession, aps: ApsClient, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await cli_run(["hooks", "reregister", "--all"], make_settings(), session, aps)
    err = capsys.readouterr().err
    assert code == 2 and "PUBLIC_BASE_URL" in err and "verificação periódica" in err
