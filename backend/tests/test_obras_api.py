from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, ModelVersion, Obra, User
from app.models.enums import Role
from tests.apsfakes import BASE, FOLDER, HUB, ITEM, PROJECT, fixture, mock_token
from tests.conftest import as_user

PDF_ITEM = "urn:adsk.wipprod:dm.lineage:LINEAGE_PDF"


def payload(code: str = "OB-001", item: str = ITEM) -> dict[str, Any]:
    return {
        "code": code,
        "name": "Galpão Logístico",
        "acc": {"hub_id": HUB, "project_id": PROJECT, "folder_id": FOLDER, "item_id": item},
    }


def mock_item(item: str = ITEM, name: str = "OBRA-001-PRE.rvt") -> respx.Route:
    body = fixture("item.json")
    body["data"]["id"] = item
    body["data"]["attributes"]["displayName"] = name
    return respx.get(f"{BASE}/data/v1/projects/{PROJECT}/items/{item}").respond(200, json=body)


@pytest.mark.parametrize("role", [Role.PROJETOS, Role.ADMIN])
@respx.mock
async def test_create_obra_by_editor_validates_item_and_audits(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], role: Role
) -> None:
    mock_token()
    mock_item()
    r = await client.post("/api/obras", json=payload(), headers=as_user(users[role]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "OB-001" and body["acc_item_id"] == ITEM
    assert body["acc_item_name"] == "OBRA-001-PRE.rvt"

    obra = await session.get(Obra, body["id"])
    assert obra is not None and obra.created_by == users[role].id
    log = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "obra", AuditLog.entity_id == str(obra.id))
    )
    assert log is not None and log.action == "create" and log.user_id == users[role].id


@pytest.mark.parametrize("role", [Role.FABRICA, Role.LEITURA])
async def test_create_obra_forbidden_for_other_roles(
    client: httpx.AsyncClient, users: dict[Role, User], role: Role
) -> None:
    r = await client.post("/api/obras", json=payload(), headers=as_user(users[role]))
    assert r.status_code == 403


@respx.mock
async def test_create_rejects_unsupported_file(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    mock_token()
    mock_item(PDF_ITEM, "Prancha-01.pdf")
    r = await client.post(
        "/api/obras", json=payload(item=PDF_ITEM), headers=as_user(users[Role.PROJETOS])
    )
    assert r.status_code == 422
    assert ".rvt, .nwd ou .ifc" in r.json()["detail"]


@respx.mock
async def test_duplicate_code_is_409(client: httpx.AsyncClient, users: dict[Role, User]) -> None:
    mock_token()
    mock_item()
    h = as_user(users[Role.PROJETOS])
    assert (await client.post("/api/obras", json=payload(), headers=h)).status_code == 201
    r = await client.post("/api/obras", json=payload(), headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
    assert "OB-001" in r.json()["detail"]


async def test_create_validates_body(client: httpx.AsyncClient, users: dict[Role, User]) -> None:
    bad = payload()
    bad["acc"]["item_id"] = ""
    r = await client.post("/api/obras", json=bad, headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 422


@respx.mock
async def test_list_get_and_patch(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    mock_token()
    mock_item()
    editor = as_user(users[Role.PROJETOS])
    created = (await client.post("/api/obras", json=payload(), headers=editor)).json()

    reader = as_user(users[Role.LEITURA])
    listed = (await client.get("/api/obras", headers=reader)).json()
    assert [o["code"] for o in listed] == ["OB-001"]
    assert (await client.get(f"/api/obras/{created['id']}", headers=reader)).status_code == 200
    assert (await client.get("/api/obras/999999", headers=reader)).status_code == 404

    r = await client.patch(
        f"/api/obras/{created['id']}", json={"name": "Novo nome"}, headers=editor
    )
    assert r.status_code == 200 and r.json()["name"] == "Novo nome"
    actions = list(
        await session.scalars(
            select(AuditLog.action).where(AuditLog.entity == "obra").order_by(AuditLog.id)
        )
    )
    assert actions == ["create", "update"]

    denied = await client.patch(f"/api/obras/{created['id']}", json={"name": "x"}, headers=reader)
    assert denied.status_code == 403


@respx.mock
async def test_cannot_change_file_after_versions_synced(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    mock_token()
    mock_item()
    editor = as_user(users[Role.ADMIN])
    obra_id = (await client.post("/api/obras", json=payload(), headers=editor)).json()["id"]
    session.add(ModelVersion(obra_id=obra_id, acc_version_id="urn:v:1", version_number=1))
    await session.flush()

    other = "urn:adsk.wipprod:dm.lineage:LINEAGE_IFC"
    r = await client.patch(
        f"/api/obras/{obra_id}", json={"acc": payload(item=other)["acc"]}, headers=editor
    )
    assert r.status_code == 409
    assert "versões sincronizadas" in r.json()["detail"]


async def test_list_requires_user(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/obras")).status_code == 401


@respx.mock
async def test_same_docs_file_in_two_obras_is_409(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    """Uma obra = um arquivo: a 2ª obra no mesmo arquivo ficaria sem versões, sem aviso
    (as versões do Docs são únicas no app). Vale mesmo com a 1ª obra inativa."""
    mock_token()
    mock_item()
    h = as_user(users[Role.PROJETOS])
    first = (await client.post("/api/obras", json=payload("OB-001"), headers=h)).json()
    await client.patch(f"/api/obras/{first['id']}", json={"active": False}, headers=h)

    r = await client.post("/api/obras", json=payload("OB-002"), headers=h)
    assert r.status_code == 409 and r.json()["code"] == "file_in_use"
    assert "já está vinculado à obra OB-001" in r.json()["detail"]
    assert "(inativa)" in r.json()["detail"]
    assert await session.scalar(select(Obra.id).where(Obra.code == "OB-002")) is None

    # trocar o arquivo de outra obra para um já usado também é recusado
    other = "urn:adsk.wipprod:dm.lineage:LINEAGE_IFC"
    mock_item(other, "OBRA-002.ifc")
    second = (await client.post("/api/obras", json=payload("OB-003", other), headers=h)).json()
    r = await client.patch(
        f"/api/obras/{second['id']}", json={"acc": payload(item=ITEM)["acc"]}, headers=h
    )
    assert r.status_code == 409 and r.json()["code"] == "file_in_use"
