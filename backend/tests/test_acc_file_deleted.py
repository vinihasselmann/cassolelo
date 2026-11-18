"""Arquivo da obra excluído no Autodesk Docs (decisão de 2026-11-18).

Excluir no Docs cria uma versão "Deleted" (sem derivativo, displayName = GUID) e deixa o
item oculto. A obra fica bloqueada (só editar/excluir) até o arquivo ser restaurado.
A fixture `versions_deleted.json` segue a resposta real (IDs sanitizados).
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.aps.errors import ApsNotFoundError
from app.aps.schemas import Item, Version
from app.models import AuditLog, ModelVersion, Obra, User, WebhookEvent
from app.models.enums import AccFileState, Role, VersionStatus
from app.services.versions import PROCESS_VERSION_JOB, sync_all_obras, sync_versions
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
from tests.conftest import as_user
from tests.factories import ready_version

VERSIONS_URL = f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}/versions"


async def _obra(session: AsyncSession, state: AccFileState = AccFileState.OK) -> Obra:
    obra = Obra(code="OB-EXC", name="Obra com arquivo excluído", acc_file_state=state.value)
    obra.acc_hub_id, obra.acc_project_id = HUB, PROJECT
    obra.acc_folder_id, obra.acc_item_id = FOLDER, ITEM
    session.add(obra)
    await session.flush()
    return obra


def _deleted() -> dict[str, Any]:
    body: dict[str, Any] = fixture("versions_deleted.json")
    return body


def _restored() -> dict[str, Any]:
    """Restaurar no Docs cria a v3, uma versão normal por cima da "Deleted"."""
    body = copy.deepcopy(_deleted())
    v3 = copy.deepcopy(body["data"][1])
    v3["id"] = v3["id"].replace("version=1", "version=3")
    v3["attributes"]["versionNumber"] = 3
    v3["relationships"]["derivatives"]["data"]["id"] += "M"
    body["data"].insert(0, v3)
    return body


async def _versions(session: AsyncSession, obra_id: int) -> dict[int, ModelVersion]:
    rows = await session.scalars(select(ModelVersion).where(ModelVersion.obra_id == obra_id))
    return {v.version_number: v for v in rows}


# --------------------------------------------------------------------------- schemas


def test_deleted_version_is_recognized_with_original_name() -> None:
    deleted, normal = (Version.from_api(d) for d in _deleted()["data"])
    assert deleted.is_deleted and deleted.derivative_id is None
    assert deleted.name == "OBRA-001-PRE.ifc"  # não o GUID do displayName
    assert not normal.is_deleted and normal.derivative_id


def test_item_hidden_flag() -> None:
    raw = {"id": "urn:x", "attributes": {"displayName": "A.ifc", "hidden": True}}
    assert Item.from_api(raw).hidden
    assert not Item.from_api({"id": "urn:y", "attributes": {"displayName": "B.ifc"}}).hidden


# --------------------------------------------------------------------------- sync


@respx.mock
async def test_sync_marks_obra_deleted_and_version_as_deleted(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue, users: dict[Role, User]
) -> None:
    mock_token()
    manifest = mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=_deleted())
    obra = await _obra(session)

    result = await sync_versions(session, aps, queue, obra.id, users[Role.PROJETOS])

    assert result.file_state == "deleted" and result.deleted == 1
    assert result.no_translation == 0  # nada de "não foi convertido pelo Docs"
    versions = await _versions(session, obra.id)
    assert versions[2].status == VersionStatus.DELETED.value
    assert versions[2].urn is None and versions[2].error is None
    assert versions[1].status == VersionStatus.PENDING.value  # a v1 segue normal
    assert manifest.call_count == 1  # só a v1 consulta o manifest
    await session.refresh(obra)
    assert obra.acc_file_state == "deleted" and obra.acc_file_state_at is not None
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "obra",
            AuditLog.entity_id == str(obra.id),
            AuditLog.action == "file_state",
        )
    )
    assert audit is not None
    assert audit.before is not None and audit.before["acc_file_state"] == "ok"
    assert audit.after is not None and audit.after["acc_file_state"] == "deleted"


@respx.mock
async def test_sync_fixes_deleted_version_saved_as_no_translation(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    """A v2 "Deleted" gravada antes deste tratamento (no_translation) é corrigida."""
    mock_token()
    mock_manifest()
    obra = await _obra(session)
    session.add(
        ModelVersion(
            obra_id=obra.id,
            acc_version_id=_deleted()["data"][0]["id"],
            version_number=2,
            status=VersionStatus.NO_TRANSLATION.value,
            error="Este arquivo não foi convertido pelo Docs.",
        )
    )
    await session.flush()
    respx.get(VERSIONS_URL).respond(200, json=_deleted())

    await sync_versions(session, aps, queue, obra.id)

    v2 = (await _versions(session, obra.id))[2]
    await session.refresh(v2)
    assert v2.status == VersionStatus.DELETED.value and v2.error is None


@respx.mock
async def test_restored_file_releases_obra_and_processes_new_version(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    obra = await _obra(session)
    respx.get(VERSIONS_URL).respond(200, json=_deleted())
    await sync_versions(session, aps, queue, obra.id)
    queue.jobs.clear()

    respx.get(VERSIONS_URL).respond(200, json=_restored())
    result = await sync_versions(session, aps, queue, obra.id)

    assert result.file_state == "ok"
    await session.refresh(obra)
    assert obra.acc_file_state == "ok"
    v3 = (await _versions(session, obra.id))[3]
    assert [j[0] for j in queue.jobs] == [PROCESS_VERSION_JOB]
    assert queue.jobs[0][1][0] == v3.id


@respx.mock
async def test_item_not_found_marks_missing_and_leaves_periodic_check(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    route = respx.get(VERSIONS_URL).respond(404, json={"errors": []})
    obra = await _obra(session)

    with pytest.raises(ApsNotFoundError):
        await sync_versions(session, aps, queue, obra.id)
    await session.refresh(obra)
    assert obra.acc_file_state == "missing"

    calls = route.call_count
    assert await sync_all_obras(session, aps, queue) == []
    assert route.call_count == calls  # não insiste a cada 10 min


@respx.mock
async def test_periodic_check_keeps_deleted_obra_to_notice_restore(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=_restored())
    obra = await _obra(session, AccFileState.DELETED)

    assert obra.id in await sync_all_obras(session, aps, queue)
    await session.refresh(obra)
    assert obra.acc_file_state == "ok"


# --------------------------------------------------------------------------- API


async def test_deleted_obra_blocks_everything_but_edit_and_delete(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra = await _obra(session)
    version, marks = await ready_version(session, obra, [("P1", "Pilar", 1)])
    obra.acc_file_state = AccFileState.DELETED.value
    await session.commit()
    h = as_user(users[Role.ADMIN])

    blocked = [
        ("GET", f"/api/obras/{obra.id}/versions"),
        ("GET", f"/api/obras/{obra.id}/mark-rule"),
        ("GET", f"/api/obras/{obra.id}/marks/{marks['P1'].id}/values"),
        ("GET", f"/api/obras/{obra.id}/export.xlsx"),
        ("GET", f"/api/versions/{version.id}/marks"),
        ("GET", f"/api/versions/{version.id}/progress"),
        ("POST", f"/api/marks/{marks['P1'].id}/review/keep"),
    ]
    for method, url in blocked:
        r = await client.request(method, url, headers=h)
        assert r.status_code == 409, (url, r.text)
        assert r.json()["code"] == "obra_file_deleted"
        assert r.json()["file_state"] == "deleted"
        assert "excluído do Autodesk Docs" in r.json()["detail"]

    listed = (await client.get("/api/obras", headers=h)).json()
    assert [o["acc_file_state"] for o in listed if o["id"] == obra.id] == ["deleted"]
    assert (await client.get(f"/api/obras/{obra.id}", headers=h)).status_code == 200
    r = await client.patch(f"/api/obras/{obra.id}", json={"name": "Renomeada"}, headers=h)
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/obras/{obra.id}/delete-preview", headers=h)
    assert r.status_code == 200, r.text
    r = await client.delete(f"/api/obras/{obra.id}", headers=h)
    assert r.status_code == 200, r.text


async def test_ok_obra_is_not_blocked(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra = await _obra(session)
    version, _ = await ready_version(session, obra, [("P1", "Pilar", 1)])
    await session.commit()
    h = as_user(users[Role.ADMIN])
    assert (await client.get(f"/api/versions/{version.id}/marks", headers=h)).status_code == 200
    assert (await client.get(f"/api/obras/{obra.id}/versions", headers=h)).status_code == 200


@respx.mock
async def test_folder_picker_hides_files_in_docs_trash(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    mock_token()
    body = copy.deepcopy(fixture("folder_contents.json"))
    items = [d for d in body["data"] if d["type"] == "items"]
    items[0]["attributes"]["hidden"] = True
    hidden_name = items[0]["attributes"]["displayName"]
    respx.get(f"{BASE}/data/v1/projects/{PROJECT}/folders/{FOLDER}/contents").respond(
        200, json=body
    )
    r = await client.get(
        f"/api/acc/projects/{PROJECT}/folders/{FOLDER}", headers=as_user(users[Role.ADMIN])
    )
    names = [e["name"] for e in r.json()]
    assert hidden_name not in names and len(names) == len(body["data"]) - 1


# --------------------------------------------------------------------------- exclusão


async def test_deleting_obra_removes_its_webhook_events(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra = await _obra(session, AccFileState.DELETED)
    other = Obra(code="OB-OUTRA", name="Outra")
    session.add(other)
    await session.flush()
    session.add_all(
        [
            WebhookEvent(event_id="evt-1", obra_id=obra.id, payload={}),
            WebhookEvent(event_id="evt-2", obra_id=other.id, payload={}),
        ]
    )
    await session.commit()

    r = await client.delete(f"/api/obras/{obra.id}", headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 200, r.text
    left = await session.scalars(select(WebhookEvent.event_id))
    assert list(left) == ["evt-2"]
    gone = await session.scalar(select(func.count()).select_from(Obra).where(Obra.id == obra.id))
    assert gone == 0
