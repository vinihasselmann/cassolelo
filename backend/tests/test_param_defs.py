"""6.1 · Catálogo de parâmetros: CRUD /api/param-defs e cada regra do prompt."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Mark, Obra, ParamDef, ParamValue, User
from app.models.enums import Role
from tests.conftest import as_user

URL = "/api/param-defs"


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-P1", name="Obra parâmetros")
    other = Obra(code="OB-P2", name="Outra obra")
    session.add_all([obra, other])
    await session.flush()
    marks = [Mark(obra_id=obra.id, code=f"PP00{i}", category="Pilar") for i in range(1, 4)]
    session.add_all(marks)
    await session.flush()
    return {
        "obra": obra,
        "other": other,
        "marks": marks,
        "fab": as_user(users[Role.FABRICA]),
        "admin": as_user(users[Role.ADMIN]),
        "users": users,
    }


async def _create(client: httpx.AsyncClient, h: dict[str, str], **body: Any) -> httpx.Response:
    body.setdefault("type", "text")
    return await client.post(URL, json=body, headers=h)


async def _value(session: AsyncSession, mark: Mark, def_id: int, value: Any) -> None:
    session.add(ParamValue(mark_id=mark.id, def_id=def_id, value=value))
    await session.flush()


# --------------------------------------------------------------------------- criação


async def test_create_and_audit(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r = await _create(client, ctx["fab"], name="  Tipo   de forma ", required=True)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Tipo de forma"  # espaços normalizados
    assert (body["type"], body["scope"], body["required"], body["active"]) == (
        "text",
        "global",
        True,
        True,
    )
    assert body["categories"] is None and body["values_count"] == 0
    assert body["created_by_name"] == ctx["users"][Role.FABRICA].name

    entry = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "param_def", AuditLog.entity_id == str(body["id"])
        )
    )
    assert entry is not None and entry.action == "create"
    assert entry.user_id == ctx["users"][Role.FABRICA].id
    assert entry.after is not None and entry.after["name"] == "Tipo de forma"


@pytest.mark.parametrize("role", [Role.PROJETOS, Role.LEITURA])
async def test_only_fabrica_and_admin_write(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any], role: Role
) -> None:
    h = as_user(ctx["users"][role])
    assert (await _create(client, h, name="X")).status_code == 403
    p = ParamDef(name="Existente", type="text", scope="global")
    session.add(p)
    await session.flush()
    assert (await client.patch(f"{URL}/{p.id}", json={"name": "Y"}, headers=h)).status_code == 403
    assert (await client.delete(f"{URL}/{p.id}", headers=h)).status_code == 403
    assert (await client.get(URL, headers=h)).status_code == 200  # leitura para todos
    assert (await _create(client, ctx["admin"], name="Do admin")).status_code == 201


async def test_requires_user(client: httpx.AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"name": "   "}, "Informe o nome do parâmetro."),
        ({"name": "x" * 201}, "no máximo 200"),
        ({"name": "A", "type": "texto"}, "Tipo inválido"),
        ({"name": "A", "type": "list"}, "pelo menos duas opções"),
        ({"name": "A", "type": "list", "options": ["F-01"]}, "pelo menos duas opções"),
        ({"name": "A", "type": "list", "options": ["F-01", " f-01 "]}, "opções repetidas"),
        ({"name": "A", "scope": "obra"}, "Informe a obra"),
        ({"name": "A", "scope": "todas"}, "Escopo inválido"),
    ],
)
async def test_validation_messages(
    client: httpx.AsyncClient, ctx: dict[str, Any], body: dict[str, Any], message: str
) -> None:
    r = await _create(client, ctx["fab"], **body)
    assert r.status_code == 422, r.text
    assert message in r.json()["detail"]


async def test_type_specific_fields(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    num = (
        await _create(client, ctx["fab"], name="Ciclo de cura", type="number", unit=" h ")
    ).json()
    assert num["unit"] == "h" and num["options"] is None
    txt = (await _create(client, ctx["fab"], name="Obs", unit="kg", options=["a", "b"])).json()
    assert txt["unit"] is None and txt["options"] is None  # unidade/opções só no tipo certo
    lst = (
        await _create(client, ctx["fab"], name="Forma", type="list", options=["F-01", "F-02", ""])
    ).json()
    assert lst["options"] == ["F-01", "F-02"]
    for t in ("date", "bool"):
        assert (await _create(client, ctx["fab"], name=f"P {t}", type=t)).status_code == 201


async def test_categories_empty_means_all_and_dedupe(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    a = (await _create(client, ctx["fab"], name="A", categories=[])).json()
    assert a["categories"] is None
    b = (await _create(client, ctx["fab"], name="B", categories=["Pilar", " Pilar", "Viga"])).json()
    assert b["categories"] == ["Pilar", "Viga"]


async def test_obra_scope(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    r = await _create(client, ctx["fab"], name="Pista", scope="obra", obra_id=ctx["obra"].id)
    assert r.status_code == 201 and r.json()["obra_code"] == "OB-P1"
    r = await _create(client, ctx["fab"], name="Pista2", scope="obra", obra_id=999999)
    assert r.status_code == 404
    # global ignora obra_id
    assert (await _create(client, ctx["fab"], name="G", obra_id=ctx["obra"].id)).json()[
        "obra_id"
    ] is None


# --------------------------------------------------------------------------- nome único


async def test_name_unique_case_insensitive(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    assert (await _create(client, ctx["fab"], name="Forma")).status_code == 201
    r = await _create(client, ctx["fab"], name="FORMA")
    assert (
        r.status_code == 409
        and r.json()["detail"] == 'Já existe um parâmetro "Forma" no catálogo global.'
    )


async def test_name_unique_across_scopes(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    obra, other = ctx["obra"].id, ctx["other"].id
    assert (
        await _create(client, ctx["fab"], name="Pista", scope="obra", obra_id=obra)
    ).status_code == 201
    # mesma obra: conflito; outra obra: permitido
    assert (
        await _create(client, ctx["fab"], name="pista", scope="obra", obra_id=obra)
    ).status_code == 409
    assert (
        await _create(client, ctx["fab"], name="pista", scope="obra", obra_id=other)
    ).status_code == 201
    # global não pode repetir o nome de um parâmetro de obra (e vice-versa)
    r = await _create(client, ctx["fab"], name="PISTA")
    assert r.status_code == 409 and "em uma obra" in r.json()["detail"]
    assert (await _create(client, ctx["fab"], name="Cura")).status_code == 201
    assert (
        await _create(client, ctx["fab"], name="cura", scope="obra", obra_id=obra)
    ).status_code == 409


async def test_rename_checks_uniqueness(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    await _create(client, ctx["fab"], name="Forma")
    b = (await _create(client, ctx["fab"], name="Pista")).json()
    r = await client.patch(f"{URL}/{b['id']}", json={"name": "forma"}, headers=ctx["fab"])
    assert r.status_code == 409
    r = await client.patch(f"{URL}/{b['id']}", json={"name": "PISTA"}, headers=ctx["fab"])
    assert r.status_code == 200 and r.json()["name"] == "PISTA"  # só a caixa mudou


async def test_deleted_name_can_be_reused(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    a = (await _create(client, ctx["fab"], name="Forma")).json()
    assert (await client.delete(f"{URL}/{a['id']}", headers=ctx["fab"])).status_code == 204
    assert (await _create(client, ctx["fab"], name="forma")).status_code == 201


# --------------------------------------------------------------------------- edição com valores


async def test_type_cannot_change_with_values(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (await _create(client, ctx["fab"], name="Cura", type="number")).json()
    # sem valores: pode trocar
    r = await client.patch(f"{URL}/{p['id']}", json={"type": "text"}, headers=ctx["fab"])
    assert r.status_code == 200 and r.json()["type"] == "text"
    await _value(session, ctx["marks"][0], p["id"], "12h")
    r = await client.patch(f"{URL}/{p['id']}", json={"type": "number"}, headers=ctx["fab"])
    assert r.status_code == 409
    assert (
        r.json()["detail"]
        == "O tipo não pode ser alterado: 1 marca(s) já têm valor neste parâmetro."
    )
    # outras alterações continuam possíveis
    r = await client.patch(
        f"{URL}/{p['id']}", json={"required": True, "name": "Cura (h)"}, headers=ctx["fab"]
    )
    assert r.status_code == 200 and r.json()["required"] is True


async def test_empty_values_do_not_lock_type(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (await _create(client, ctx["fab"], name="Obs")).json()
    await _value(session, ctx["marks"][0], p["id"], None)
    await _value(session, ctx["marks"][1], p["id"], "")
    r = await client.patch(f"{URL}/{p['id']}", json={"type": "number"}, headers=ctx["fab"])
    assert r.status_code == 200


async def test_options_in_use_cannot_be_removed(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (
        await _create(
            client, ctx["fab"], name="Forma", type="list", options=["F-01", "F-02", "F-03"]
        )
    ).json()
    await _value(session, ctx["marks"][0], p["id"], "F-02")
    await _value(session, ctx["marks"][1], p["id"], "F-03")

    got = (await client.get(URL, headers=ctx["fab"])).json()[0]
    assert got["values_count"] == 2 and got["options_in_use"] == ["F-02", "F-03"]

    r = await client.patch(
        f"{URL}/{p['id']}", json={"options": ["F-01", "F-02"]}, headers=ctx["fab"]
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Opções em uso não podem ser removidas: F-03."
    # tirar a que não está em uso, acrescentar e reordenar: pode
    r = await client.patch(
        f"{URL}/{p['id']}", json={"options": ["F-03", "F-02", "F-04"]}, headers=ctx["fab"]
    )
    assert r.status_code == 200 and r.json()["options"] == ["F-03", "F-02", "F-04"]
    # e a lista continua precisando de 2 opções sem repetir
    r = await client.patch(f"{URL}/{p['id']}", json={"options": ["F-03"]}, headers=ctx["fab"])
    assert r.status_code == 422


async def test_scope_cannot_change_with_values(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (await _create(client, ctx["fab"], name="Pista")).json()
    r = await client.patch(
        f"{URL}/{p['id']}", json={"scope": "obra", "obra_id": ctx["obra"].id}, headers=ctx["fab"]
    )
    assert r.status_code == 200 and r.json()["scope"] == "obra"
    await _value(session, ctx["marks"][0], p["id"], "P1")
    r = await client.patch(f"{URL}/{p['id']}", json={"scope": "global"}, headers=ctx["fab"])
    assert r.status_code == 409 and "escopo não pode ser alterado" in r.json()["detail"]


async def test_change_to_list_requires_options(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (await _create(client, ctx["fab"], name="Forma")).json()
    r = await client.patch(f"{URL}/{p['id']}", json={"type": "list"}, headers=ctx["fab"])
    assert r.status_code == 422
    r = await client.patch(
        f"{URL}/{p['id']}", json={"type": "list", "options": ["A", "B"]}, headers=ctx["fab"]
    )
    assert r.status_code == 200 and r.json()["options"] == ["A", "B"]
    r = await client.patch(f"{URL}/{p['id']}", json={"type": "text"}, headers=ctx["fab"])
    assert r.json()["options"] is None  # opções saem com a troca de tipo


async def test_update_is_audited(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (await _create(client, ctx["fab"], name="Forma")).json()
    await client.patch(f"{URL}/{p['id']}", json={"name": "Tipo de forma"}, headers=ctx["admin"])
    entry = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "param_def",
            AuditLog.entity_id == str(p["id"]),
            AuditLog.action == "update",
        )
    )
    assert entry is not None and entry.before is not None and entry.after is not None
    assert (entry.before["name"], entry.after["name"]) == ("Forma", "Tipo de forma")
    assert entry.user_id == ctx["users"][Role.ADMIN].id


# --------------------------------------------------------------------------- exclusão lógica


async def test_delete_is_logical_and_keeps_values_in_audit(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    p = (
        await _create(client, ctx["fab"], name="Forma", type="list", options=["F-01", "F-02"])
    ).json()
    await _value(session, ctx["marks"][0], p["id"], "F-01")
    await _value(session, ctx["marks"][2], p["id"], "F-02")

    assert (await client.delete(f"{URL}/{p['id']}", headers=ctx["fab"])).status_code == 204

    row = await session.get(ParamDef, p["id"])
    assert row is not None and row.active is False  # continua no banco
    values = list(await session.scalars(select(ParamValue).where(ParamValue.def_id == p["id"])))
    assert len(values) == 2  # valores não são apagados

    entry = await session.scalar(
        select(AuditLog).where(AuditLog.entity_id == str(p["id"]), AuditLog.action == "delete")
    )
    assert entry is not None and entry.after is not None
    assert entry.after["active"] is False
    assert entry.after["values"] == [
        {"mark_id": ctx["marks"][0].id, "value": "F-01"},
        {"mark_id": ctx["marks"][2].id, "value": "F-02"},
    ]

    # some da lista (e só volta pedindo os excluídos); não edita nem exclui de novo
    assert (await client.get(URL, headers=ctx["fab"])).json() == []
    all_ = (await client.get(URL, params={"include_inactive": True}, headers=ctx["fab"])).json()
    assert [(x["name"], x["active"]) for x in all_] == [("Forma", False)]
    assert (
        await client.patch(f"{URL}/{p['id']}", json={"name": "X"}, headers=ctx["fab"])
    ).status_code == 404
    assert (await client.delete(f"{URL}/{p['id']}", headers=ctx["fab"])).status_code == 404


# --------------------------------------------------------------------------- listagem


async def test_list_by_obra(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    await _create(client, ctx["fab"], name="Global")
    await _create(client, ctx["fab"], name="Da obra", scope="obra", obra_id=ctx["obra"].id)
    await _create(client, ctx["fab"], name="Da outra", scope="obra", obra_id=ctx["other"].id)
    names = [
        p["name"]
        for p in (
            await client.get(URL, params={"obra_id": ctx["obra"].id}, headers=ctx["fab"])
        ).json()
    ]
    # biblioteca não vale para nenhuma obra até ser incluída (decisão de 2026-11-13)
    assert names == ["Da obra"]
    lib = (
        await client.get(
            URL, params={"obra_id": ctx["obra"].id, "library": "true"}, headers=ctx["fab"]
        )
    ).json()
    assert [(p["name"], p["in_obra"]) for p in lib] == [("Da obra", True), ("Global", False)]
    assert len((await client.get(URL, headers=ctx["fab"])).json()) == 3


async def test_include_and_exclude_library_param_per_obra(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    from app.models import AuditLog, Mark, ParamValue

    obra_id, fab = ctx["obra"].id, ctx["fab"]
    gid = (await _create(client, fab, name="Liberação")).json()["id"]
    url = f"/api/obras/{obra_id}/params/{gid}"

    async def listed() -> httpx.Response:
        return await client.get(URL, params={"obra_id": obra_id}, headers=fab)

    r = await client.post(url, headers=fab)
    assert r.status_code == 200 and r.json() == {
        "obra_id": obra_id,
        "def_id": gid,
        "in_obra": True,
        "changed": True,
    }
    assert (await client.post(url, headers=fab)).json()["changed"] is False  # idempotente
    assert [p["name"] for p in (await listed()).json()] == ["Liberação"]
    assert (await listed()).json()[0]["obras_count"] == 1

    # um valor preenchido sobrevive a retirar e incluir de novo
    mark = Mark(obra_id=obra_id, code="PP1", category="Pilar")
    session.add(mark)
    await session.flush()
    session.add(ParamValue(mark_id=mark.id, def_id=gid, value="ok"))
    await session.flush()
    r = await client.delete(url, headers=fab)
    assert r.status_code == 200 and r.json()["in_obra"] is False
    assert (await listed()).json() == []
    await client.post(url, headers=fab)
    values = (await client.get(f"/api/obras/{obra_id}/marks/{mark.id}/values", headers=fab)).json()
    assert [v["value"] for v in values["values"] if v["def_id"] == gid] == ["ok"]

    actions = list(
        await session.scalars(
            select(AuditLog.action).where(AuditLog.entity == "obra_param").order_by(AuditLog.id)
        )
    )
    assert actions == ["include", "exclude", "include"]

    # papéis: leitura e projetos não incluem; parâmetro de obra não se inclui
    proj = as_user(ctx["users"][Role.PROJETOS])
    assert (await client.post(url, headers=proj)).status_code == 403
    own = (await _create(client, fab, name="Só desta", scope="obra", obra_id=obra_id)).json()
    r = await client.post(f"/api/obras/{obra_id}/params/{own['id']}", headers=fab)
    assert r.status_code == 422


async def test_create_library_param_from_an_obra_includes_it(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r = await _create(client, ctx["fab"], name="Ciclo", include_in_obra_id=ctx["obra"].id)
    assert r.status_code == 201
    names = [
        p["name"]
        for p in (
            await client.get(URL, params={"obra_id": ctx["obra"].id}, headers=ctx["fab"])
        ).json()
    ]
    other = (await client.get(URL, params={"obra_id": ctx["other"].id}, headers=ctx["fab"])).json()
    assert names == ["Ciclo"] and other == []
