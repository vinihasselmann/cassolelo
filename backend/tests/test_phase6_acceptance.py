"""Aceite da Fase 6 pela API: a fábrica cria um parâmetro, preenche uma marca e um lote de
10, desfaz o lote; status e progresso refletem cada passo; edição simultânea gera 409."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Obra, User
from app.models.enums import Role
from tests.conftest import as_user
from tests.factories import ready_version


async def test_phase6_acceptance(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    fab, admin = as_user(users[Role.FABRICA]), as_user(users[Role.ADMIN])
    obra = Obra(code="OB-ACE6", name="Aceite fase 6")
    session.add(obra)
    await session.flush()
    codes = [f"PP{i:03d}" for i in range(1, 13)]
    version, marks = await ready_version(session, obra, [(c, "Pilar", 2) for c in codes])
    vurl = f"/api/versions/{version.id}"

    async def status_counts() -> dict[str, int]:
        body = (await client.get(f"{vurl}/marks/status", headers=fab)).json()
        return {c["status"]: c["marks"] for c in body["counts"]}

    async def progress() -> tuple[int, int, int, int]:
        body = (await client.get(f"{vurl}/progress", headers=fab)).json()
        [p] = body["required"]
        return p["marks_filled"], p["marks_total"], p["pieces_filled"], p["pieces_total"]

    async def pending() -> list[str]:
        r = await client.get(f"{vurl}/marks/search", params={"shortcut": "pending"}, headers=fab)
        return [i["code"] for i in r.json()["items"]]

    # 1. a fábrica cria um parâmetro obrigatório novo
    r = await client.post(
        "/api/param-defs",
        json={
            "name": "Tipo de forma",
            "type": "list",
            "options": ["F-11", "F-12", "F-13"],
            "required": True,
            "categories": ["Pilar"],
            "scope": "obra",
            "obra_id": obra.id,
        },
        headers=fab,
    )
    assert r.status_code == 201, r.text
    def_id = r.json()["id"]
    assert await status_counts() == {"pending": 12, "partial": 0, "complete": 0, "review": 0}
    assert await progress() == (0, 12, 0, 24)

    # 2. preenche uma marca
    first = marks["PP001"]
    r = await client.put(
        f"/api/obras/{obra.id}/marks/{first.id}/values",
        json={"changes": [{"def_id": def_id, "value": "F-11", "row_version": None}]},
        headers=fab,
    )
    assert r.status_code == 200, r.text
    assert (await status_counts())["complete"] == 1
    assert await progress() == (1, 12, 2, 24)

    # 3. lote de 10 marcas
    batch_ids = [marks[c].id for c in codes[1:11]]
    r = await client.post(
        f"/api/obras/{obra.id}/marks/batch-apply",
        json={"mark_ids": batch_ids, "changes": {str(def_id): "F-12"}, "mode": "overwrite"},
        headers=fab,
    )
    assert r.status_code == 200, r.text
    assert r.json()["marks_changed"] == 10
    batch = r.json()["batch_id"]
    assert await status_counts() == {"pending": 1, "partial": 0, "complete": 11, "review": 0}
    assert await progress() == (11, 12, 22, 24)
    assert await pending() == ["PP012"]
    r = await client.get(f"{vurl}/params/{def_id}/values", headers=fab)
    values = {i["mark_id"]: i["value"] for i in r.json()["items"]}
    assert sorted(v for v in values.values() if v) == ["F-11"] + ["F-12"] * 10

    # 4. desfaz o lote: volta a 1 completa
    r = await client.post(f"/api/batches/{batch}/undo", headers=fab)
    assert r.status_code == 200, r.text
    assert await status_counts() == {"pending": 11, "partial": 0, "complete": 1, "review": 0}
    assert await progress() == (1, 12, 2, 24)
    assert await pending() == codes[1:]

    # 5. edição simultânea: dois usuários leem a mesma versão; o segundo leva 409
    url = f"/api/obras/{obra.id}/marks/{first.id}/values"
    read: dict[str, Any] = (await client.get(url, headers=fab)).json()
    row_version = read["values"][0]["row_version"]
    r = await client.put(
        url,
        json={"changes": [{"def_id": def_id, "value": "F-13", "row_version": row_version}]},
        headers=admin,
    )
    assert r.status_code == 200
    r = await client.put(
        url,
        json={"changes": [{"def_id": def_id, "value": "F-12", "row_version": row_version}]},
        headers=fab,
    )
    assert (r.status_code, r.json()["code"]) == (409, "stale")
    assert r.json()["changed_by_name"] == users[Role.ADMIN].name
    final = (await client.get(url, headers=fab)).json()["values"][0]["value"]
    assert final == "F-13"  # aviso em vez de sobrescrever
