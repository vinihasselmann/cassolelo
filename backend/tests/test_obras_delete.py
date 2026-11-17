"""Exclusão de obra (para corrigir um cadastro errado). Decisão de 2026-11-17: obra com
valores preenchidos pela fábrica só o admin exclui; tudo vai para o audit_log."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    ObraParam,
    Orphan,
    ParamDef,
    ParamValue,
    PieceProp,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
)
from app.models.enums import Role
from tests.apsfakes import BASE, FOLDER, mock_token
from tests.conftest import as_user, build_app
from tests.factories import ready_version

HOOKS = f"{BASE}/webhooks/v1/systems/data/hooks"
PUBLIC_URL = "https://app.example"


async def _obra(session: AsyncSession, code: str = "OB-DEL", folder: str = FOLDER) -> Obra:
    obra = Obra(code=code, name="Obra errada", acc_folder_id=folder, acc_item_id=f"urn:{code}")
    session.add(obra)
    await session.flush()
    return obra


async def _populate(session: AsyncSession, obra: Obra, *, values: bool) -> ParamDef:
    """Versão pronta com marcas, unidade, ligação, prop, órfã e parâmetros (obra e
    biblioteca). Com `values`, um valor por marca e um por peça preenchidos."""
    version, marks = await ready_version(session, obra, [("P1", "Pilar", 1), ("P2", "Pilar", 1)])
    mark = marks["P1"]
    element = await session.scalar(select(Element).where(Element.mark_id == mark.id))
    assert element is not None
    unit = PieceUnit(obra_id=obra.id, mark_id=mark.id, number=1)
    global_def = ParamDef(name=f"Concretagem {obra.code}", type="text", scope="global")
    obra_def = ParamDef(name="Forma", type="text", scope="obra", obra_id=obra.id)
    session.add_all([unit, global_def, obra_def])
    await session.flush()
    session.add_all(
        [
            ObraParam(obra_id=obra.id, def_id=global_def.id),
            PieceUnitLink(
                version_id=version.id, unit_id=unit.id, element_id=element.id, method="key"
            ),
            PieceProp(
                version_id=version.id,
                piece_id=element.id,
                mark_id=mark.id,
                source="model",
                key="Dados/Marca",
                value_text="P1",
            ),
            Orphan(mark_id=marks["P2"].id, since_version_id=version.id),
            # valor apagado (nulo) não conta como preenchido
            ParamValue(mark_id=marks["P2"].id, def_id=obra_def.id, value=None),
        ]
    )
    if values:
        session.add_all(
            [
                ParamValue(mark_id=mark.id, def_id=global_def.id, value="17/11/2026"),
                PieceValue(unit_id=unit.id, def_id=obra_def.id, value="F1"),
            ]
        )
    await session.flush()
    return global_def


async def _total(session: AsyncSession, model: Any, *where: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def test_preview_counts_what_goes_away(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra = await _obra(session)
    await _populate(session, obra, values=True)
    r = await client.get(
        f"/api/obras/{obra.id}/delete-preview", headers=as_user(users[Role.PROJETOS])
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "versions": 1,
        "marks": 2,
        "units": 1,
        "filled_values": 2,
        "admin_only": True,
    }


@pytest.mark.parametrize("role", [Role.PROJETOS, Role.ADMIN])
async def test_editor_deletes_obra_without_values(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], role: Role
) -> None:
    obra = await _obra(session)
    global_def = await _populate(session, obra, values=False)
    obra_id, global_id = obra.id, global_def.id

    r = await client.delete(f"/api/obras/{obra_id}", headers=as_user(users[role]))
    assert r.status_code == 200, r.text
    assert r.json()["filled_values"] == 0

    session.expunge_all()
    assert await session.get(Obra, obra_id) is None
    assert await _total(session, ModelVersion, ModelVersion.obra_id == obra_id) == 0
    assert await _total(session, Mark, Mark.obra_id == obra_id) == 0
    assert await _total(session, PieceUnit, PieceUnit.obra_id == obra_id) == 0
    assert await _total(session, ObraParam, ObraParam.obra_id == obra_id) == 0
    assert await _total(session, Orphan) == 0
    assert await _total(session, Element) == 0
    assert await _total(session, ParamValue) == 0
    # o parâmetro da biblioteca fica; o da obra sai junto
    assert await session.get(ParamDef, global_id) is not None
    assert await _total(session, ParamDef, ParamDef.obra_id == obra_id) == 0

    log = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "obra", AuditLog.action == "delete")
    )
    assert log is not None and log.entity_id == str(obra_id)
    assert log.user_id == users[role].id
    assert log.before is not None and log.before["code"] == "OB-DEL"
    assert log.before["deleted"] == {"versions": 1, "marks": 2, "units": 1, "filled_values": 0}
    assert log.after is None


async def test_obra_with_values_only_admin_deletes(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra = await _obra(session)
    await _populate(session, obra, values=True)
    obra_id = obra.id

    r = await client.delete(f"/api/obras/{obra_id}", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 403
    assert "administrador" in r.json()["detail"]
    assert await session.get(Obra, obra_id) is not None

    r = await client.delete(f"/api/obras/{obra_id}", headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 200, r.text
    assert r.json()["filled_values"] == 2
    session.expunge_all()
    assert await session.get(Obra, obra_id) is None
    assert await _total(session, PieceValue) == 0
    assert await _total(session, ParamValue) == 0
    log = await session.scalar(
        select(AuditLog).where(AuditLog.entity == "obra", AuditLog.action == "delete")
    )
    assert log is not None and log.before is not None
    assert log.before["deleted"]["filled_values"] == 2


@pytest.mark.parametrize("role", [Role.FABRICA, Role.LEITURA])
async def test_delete_forbidden_for_other_roles(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User], role: Role
) -> None:
    obra = await _obra(session)
    r = await client.delete(f"/api/obras/{obra.id}", headers=as_user(users[role]))
    assert r.status_code == 403
    assert await session.get(Obra, obra.id) is not None


async def test_delete_missing_obra_is_404(
    client: httpx.AsyncClient, users: dict[Role, User]
) -> None:
    r = await client.delete("/api/obras/999999", headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 404


async def test_other_obras_untouched(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    keep = await _obra(session, "OB-KEEP", folder="urn:outra-pasta")
    await _populate(session, keep, values=True)
    gone = await _obra(session)
    await _populate(session, gone, values=False)
    keep_id = keep.id

    r = await client.delete(f"/api/obras/{gone.id}", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 200, r.text
    session.expunge_all()
    assert await session.get(Obra, keep_id) is not None
    assert await _total(session, Mark, Mark.obra_id == keep_id) == 2
    assert await _total(session, PieceValue) == 1
    assert await _total(session, ParamValue, func.jsonb_typeof(ParamValue.value) != "null") == 1


def _hooked_client(session: AsyncSession, aps: ApsClient) -> httpx.AsyncClient:
    app = build_app(session, aps=aps, public_base_url=PUBLIC_URL)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@respx.mock
async def test_delete_removes_obra_hooks(
    session: AsyncSession, aps: ApsClient, users: dict[Role, User]
) -> None:
    mock_token()
    obra = await _obra(session)
    hooks = [
        {"hookId": "a", "event": "dm.version.added", "hookAttribute": {"obra_id": str(obra.id)}},
        {"hookId": "z", "event": "dm.version.added", "hookAttribute": {"obra_id": "999"}},
    ]
    respx.get(HOOKS).respond(200, json={"data": hooks})
    mine = respx.delete(url__regex=r".*/hooks/a$").respond(204)
    other = respx.delete(url__regex=r".*/hooks/z$").respond(204)
    async with _hooked_client(session, aps) as c:
        r = await c.delete(f"/api/obras/{obra.id}", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 200, r.text
    assert mine.called and not other.called


@respx.mock
async def test_delete_keeps_hooks_shared_with_obra_in_same_folder(
    session: AsyncSession, aps: ApsClient, users: dict[Role, User]
) -> None:
    obra = await _obra(session)
    await _obra(session, "OB-VIZINHA")  # mesma pasta: o hook serve as duas
    listing = respx.get(HOOKS).respond(200, json={"data": []})
    async with _hooked_client(session, aps) as c:
        r = await c.delete(f"/api/obras/{obra.id}", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 200, r.text
    assert not listing.called


@respx.mock
async def test_aps_failure_does_not_undo_delete(
    session: AsyncSession, aps: ApsClient, users: dict[Role, User]
) -> None:
    mock_token()
    obra = await _obra(session)
    obra_id = obra.id
    respx.get(HOOKS).respond(404, json={})
    async with _hooked_client(session, aps) as c:
        r = await c.delete(f"/api/obras/{obra_id}", headers=as_user(users[Role.PROJETOS]))
    assert r.status_code == 200, r.text
    session.expunge_all()
    assert await session.get(Obra, obra_id) is None
