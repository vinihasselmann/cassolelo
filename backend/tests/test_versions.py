from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import AuditLog, ModelVersion, Obra, User
from app.models.enums import Role
from app.services.errors import ConflictError
from app.services.versions import PROCESS_VERSION_JOB, sync_versions
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

VERSIONS_URL = f"{BASE}/data/v1/projects/{PROJECT}/items/{ITEM}/versions"


async def _obra(session: AsyncSession, linked: bool = True) -> Obra:
    obra = Obra(code="OB-V", name="Obra versões")
    if linked:
        obra.acc_hub_id, obra.acc_project_id = HUB, PROJECT
        obra.acc_folder_id, obra.acc_item_id = FOLDER, ITEM
    session.add(obra)
    await session.flush()
    return obra


def _versions_with_v3() -> dict[str, Any]:
    body: dict[str, Any] = copy.deepcopy(fixture("versions.json"))
    v3 = copy.deepcopy(body["data"][1])
    v3["id"] = v3["id"].replace("version=2", "version=3")
    v3["attributes"]["versionNumber"] = 3
    body["data"].append(v3)
    return body


async def _count(session: AsyncSession, obra_id: int) -> int:
    n = await session.scalar(
        select(func.count()).select_from(ModelVersion).where(ModelVersion.obra_id == obra_id)
    )
    return int(n or 0)


@respx.mock
async def test_sync_twice_does_not_duplicate(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue, users: dict[Role, User]
) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    obra = await _obra(session)

    first = await sync_versions(session, aps, queue, obra.id, users[Role.PROJETOS])
    assert first.total_in_docs == 2 and len(first.created_ids) == 2
    second = await sync_versions(session, aps, queue, obra.id, users[Role.PROJETOS])
    assert second.created_ids == [] and second.enqueued == 0
    assert await _count(session, obra.id) == 2
    # v1 não tem derivativo (no_translation); só a v2 vai para processamento, e só 1 vez
    assert [j[0] for j in queue.jobs] == [PROCESS_VERSION_JOB]


@respx.mock
async def test_sync_stores_version_data_with_status_pending(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    obra = await _obra(session)
    await sync_versions(session, aps, queue, obra.id)

    rows = list(
        await session.scalars(
            select(ModelVersion)
            .where(ModelVersion.obra_id == obra.id)
            .order_by(ModelVersion.version_number)
        )
    )
    v1, v2 = rows
    assert (v1.version_number, v2.version_number) == (1, 2)
    assert (v1.status, v2.status) == ("no_translation", "pending")
    assert v1.urn is None and v2.urn is not None and "=" not in v2.urn
    assert v2.published_by == "Usuário Projetos"
    assert v2.published_at is not None and v2.published_at.year == 2026
    assert v2.comment == "Revisão das vigas do pavimento 2"
    assert v2.acc_version_id.endswith("version=2")


@respx.mock
async def test_only_new_versions_are_inserted_and_enqueued(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    route = respx.get(VERSIONS_URL)
    route.respond(200, json=fixture("versions.json"))
    obra = await _obra(session)
    await sync_versions(session, aps, queue, obra.id)
    queue.jobs.clear()

    route.respond(200, json=_versions_with_v3())
    result = await sync_versions(session, aps, queue, obra.id)
    assert len(result.created_ids) == 1
    v3 = await session.get(ModelVersion, result.created_ids[0])
    assert v3 is not None and v3.version_number == 3
    assert queue.jobs == [(PROCESS_VERSION_JOB, (v3.id,), f"{PROCESS_VERSION_JOB}:{v3.id}")]


@respx.mock
async def test_queue_down_keeps_versions(session: AsyncSession, aps: ApsClient) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    obra = await _obra(session)
    result = await sync_versions(session, aps, FakeQueue(fail=True), obra.id)
    assert result.enqueue_failed == 1 and result.enqueued == 0
    assert await _count(session, obra.id) == 2


@respx.mock
async def test_sync_writes_audit_with_batch(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue, users: dict[Role, User]
) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    obra = await _obra(session)
    await sync_versions(session, aps, queue, obra.id, users[Role.FABRICA])
    logs = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "model_version", AuditLog.action == "create")
        )
    )
    assert len(logs) == 2
    assert len({log.batch_id for log in logs}) == 1
    assert {log.user_id for log in logs} == {users[Role.FABRICA].id}


async def test_sync_requires_linked_obra(
    session: AsyncSession, aps: ApsClient, queue: FakeQueue
) -> None:
    obra = await _obra(session, linked=False)
    with pytest.raises(ConflictError, match="não está vinculada"):
        await sync_versions(session, aps, queue, obra.id)


# --------------------------------------------------------------------------- API


@respx.mock
async def test_sync_and_list_endpoints(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], queue: FakeQueue
) -> None:
    mock_token()
    mock_manifest()
    respx.get(VERSIONS_URL).respond(200, json=fixture("versions.json"))
    obra = await _obra(session)

    r = await client.post(f"/api/obras/{obra.id}/sync", headers=as_user(users[Role.FABRICA]))
    assert r.status_code == 200
    assert r.json() == {
        "total_in_docs": 2,
        "created": 2,
        "ready": 1,
        "translating": 0,
        "no_translation": 1,
        "failed": 0,
        "enqueued": 1,
        "enqueue_failed": 0,
    }
    again = await client.post(f"/api/obras/{obra.id}/sync", headers=as_user(users[Role.ADMIN]))
    assert again.json()["created"] == 0

    listed = await client.get(
        f"/api/obras/{obra.id}/versions", headers=as_user(users[Role.LEITURA])
    )
    versions = listed.json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert [v["status"] for v in versions] == ["pending", "no_translation"]
    assert versions[0]["comment"] == "Revisão das vigas do pavimento 2"
    assert [v["has_urn"] for v in versions] == [True, False]


async def test_sync_forbidden_for_leitura(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra = await _obra(session)
    r = await client.post(f"/api/obras/{obra.id}/sync", headers=as_user(users[Role.LEITURA]))
    assert r.status_code == 403


async def test_versions_of_missing_obra_404(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    r = await client.get("/api/obras/999999/versions", headers=as_user(users[Role.LEITURA]))
    assert r.status_code == 404
