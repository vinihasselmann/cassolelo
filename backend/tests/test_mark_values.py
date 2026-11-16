"""6.2 · Valores por marca: GET/PUT /api/obras/{id}/marks/{mark_id}/values e /history."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Mark, Obra, ParamDef, ParamValue, User
from app.models.enums import Role
from tests.conftest import as_user, include_params


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-V1", name="Obra valores")
    other = Obra(code="OB-V2", name="Outra")
    session.add_all([obra, other])
    await session.flush()
    pp = Mark(obra_id=obra.id, code="PP001", category="Pilar")
    viga = Mark(obra_id=obra.id, code="V-01", category="Viga")
    alheia = Mark(obra_id=other.id, code="PP001", category="Pilar")
    session.add_all([pp, viga, alheia])
    d = {
        "forma": ParamDef(
            name="Tipo de forma",
            type="list",
            options=["F-11", "F-12", "F-13"],
            required=True,
            categories=["Pilar"],
            scope="global",
        ),
        "cura": ParamDef(name="Ciclo de cura", type="number", unit="h", scope="global"),
        "data": ParamDef(name="Data de concretagem", type="date", scope="global"),
        "insert": ParamDef(name="Peça com insert", type="bool", scope="global"),
        "obs": ParamDef(name="Observação", type="text", scope="obra", obra_id=obra.id),
        "viga": ParamDef(name="Só viga", type="text", categories=["Viga"], scope="global"),
        "outra": ParamDef(name="Da outra obra", type="text", scope="obra", obra_id=other.id),
        "inativo": ParamDef(name="Excluído", type="text", scope="global", active=False),
    }
    session.add_all(d.values())
    await session.flush()
    await include_params(session, obra.id, *d.values())
    return {
        "obra": obra,
        "pp": pp,
        "viga": viga,
        "alheia": alheia,
        "d": d,
        "users": users,
        "fab": as_user(users[Role.FABRICA]),
        "admin": as_user(users[Role.ADMIN]),
        "url": f"/api/obras/{obra.id}/marks/{pp.id}",
    }


async def _put(
    client: httpx.AsyncClient, ctx: dict[str, Any], changes: list[dict[str, Any]], h: str = "fab"
) -> httpx.Response:
    return await client.put(f"{ctx['url']}/values", json={"changes": changes}, headers=ctx[h])


def _by_name(body: Any) -> dict[str, Any]:
    return {v["name"]: v for v in body["values"]}


async def test_get_only_applicable_params(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    r = await client.get(f"{ctx['url']}/values", headers=as_user(ctx["users"][Role.LEITURA]))
    assert r.status_code == 200
    body = r.json()
    assert body["mark"] == {
        "id": ctx["pp"].id,
        "code": "PP001",
        "category": "Pilar",
        "review_status": "ok",
        "review_note": None,
    }
    # sem "Só viga" (categoria), "Da outra obra" (escopo) e "Excluído" (inativo); ordem alfabética
    assert [v["name"] for v in body["values"]] == [
        "Ciclo de cura",
        "Data de concretagem",
        "Observação",
        "Peça com insert",
        "Tipo de forma",
    ]
    forma = _by_name(body)["Tipo de forma"]
    assert (forma["required"], forma["options"], forma["value"], forma["row_version"]) == (
        True,
        ["F-11", "F-12", "F-13"],
        None,
        None,
    )
    assert _by_name(body)["Ciclo de cura"]["unit"] == "h"
    assert body["last_change_by"] is None


async def test_put_normalizes_by_type(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    d = ctx["d"]
    r = await _put(
        client,
        ctx,
        [
            {"def_id": d["cura"].id, "value": "1,5"},
            {"def_id": d["forma"].id, "value": " f-12 "},
            {"def_id": d["data"].id, "value": "2026-11-20"},
            {"def_id": d["insert"].id, "value": "sim"},
            {"def_id": d["obs"].id, "value": "  peça   com  chanfro "},
        ],
    )
    assert r.status_code == 200, r.text
    v = _by_name(r.json())
    assert v["Ciclo de cura"]["value"] == 1.5  # vírgula decimal
    assert v["Tipo de forma"]["value"] == "F-12"  # forma do catálogo
    assert v["Data de concretagem"]["value"] == "2026-11-20"
    assert v["Peça com insert"]["value"] is True
    assert v["Observação"]["value"] == "peça com chanfro"
    assert v["Tipo de forma"]["row_version"] == 1
    assert v["Tipo de forma"]["updated_by_name"] == ctx["users"][Role.FABRICA].name
    assert r.json()["last_change_by"] == ctx["users"][Role.FABRICA].name

    r = await _put(client, ctx, [{"def_id": d["cura"].id, "value": 12, "row_version": 1}])
    assert _by_name(r.json())["Ciclo de cura"]["value"] == 12


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("cura", "abc", '"abc" não é um número'),
        ("cura", "1,2,3", "não é um número"),
        ("forma", "F-99", '"F-99" não é uma das opções (F-11, F-12, F-13)'),
        ("data", "20/11/2026", "data inválida"),
        ("data", "2026-02-30", "data inválida"),
        ("insert", "talvez", "use sim ou não"),
        ("viga", "x", "não se aplica a esta marca"),
        ("outra", "x", "não se aplica"),
        ("inativo", "x", "não se aplica"),
    ],
)
async def test_validation_and_nothing_saved(
    session: AsyncSession,
    client: httpx.AsyncClient,
    ctx: dict[str, Any],
    key: str,
    value: str,
    message: str,
) -> None:
    d = ctx["d"]
    r = await _put(
        client, ctx, [{"def_id": d["obs"].id, "value": "ok"}, {"def_id": d[key].id, "value": value}]
    )
    assert r.status_code == 422, r.text
    assert message in r.json()["detail"]
    # tudo ou nada: a Observação válida também não foi gravada
    assert await session.scalar(select(ParamValue).where(ParamValue.def_id == d["obs"].id)) is None


async def test_duplicate_param_in_request(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    d = ctx["d"]
    r = await _put(
        client, ctx, [{"def_id": d["obs"].id, "value": "a"}, {"def_id": d["obs"].id, "value": "b"}]
    )
    assert r.status_code == 422


async def test_optimistic_conflict_reports_who_and_when(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    forma = ctx["d"]["forma"].id
    obs = ctx["d"]["obs"].id
    # admin salva primeiro (versão 1)
    assert (
        await _put(client, ctx, [{"def_id": forma, "value": "F-11"}], "admin")
    ).status_code == 200

    # fábrica abriu a tela antes (não havia valor) e tenta salvar
    r = await _put(client, ctx, [{"def_id": obs, "value": "x"}, {"def_id": forma, "value": "F-12"}])
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "stale"
    assert body["changed_by_name"] == ctx["users"][Role.ADMIN].name
    assert body["changed_at"] and body["conflict_def_ids"] == [forma]
    assert "alterou esta marca" in body["detail"]
    # nada foi gravado (nem a Observação, que não conflitava)
    assert await session.scalar(select(ParamValue).where(ParamValue.def_id == obs)) is None

    # recarregou (versão 1): agora salva e a versão sobe
    r = await _put(client, ctx, [{"def_id": forma, "value": "F-12", "row_version": 1}])
    assert r.status_code == 200 and _by_name(r.json())["Tipo de forma"]["row_version"] == 2
    # quem ainda tem a versão 1 leva 409
    r = await _put(client, ctx, [{"def_id": forma, "value": "F-13", "row_version": 1}], "admin")
    assert r.status_code == 409 and r.json()["changed_by_name"] == ctx["users"][Role.FABRICA].name


async def test_clear_value_and_unchanged_is_noop(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    forma = ctx["d"]["forma"].id
    await _put(client, ctx, [{"def_id": forma, "value": "F-11"}])
    # mesmo valor: não grava, não audita, versão não muda
    r = await _put(client, ctx, [{"def_id": forma, "value": "f-11", "row_version": 1}])
    assert _by_name(r.json())["Tipo de forma"]["row_version"] == 1
    # vazio apaga
    r = await _put(client, ctx, [{"def_id": forma, "value": "", "row_version": 1}])
    v = _by_name(r.json())["Tipo de forma"]
    assert v["value"] is None and v["row_version"] == 2
    actions = list(
        await session.scalars(
            select(AuditLog.action).where(AuditLog.entity == "mark_value").order_by(AuditLog.id)
        )
    )
    assert actions == ["set", "clear"]


async def test_each_changed_field_is_audited(
    session: AsyncSession, client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    d = ctx["d"]
    await _put(client, ctx, [{"def_id": d["forma"].id, "value": "F-11"}])
    await _put(
        client,
        ctx,
        [
            {"def_id": d["forma"].id, "value": "F-13", "row_version": 1},
            {"def_id": d["cura"].id, "value": "8"},
            {"def_id": d["obs"].id, "value": None},  # já estava vazio: não conta
        ],
    )
    rows = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "mark_value").order_by(AuditLog.id)
        )
    )
    assert len(rows) == 3
    first, *second = rows
    assert first.batch_id != second[0].batch_id and second[0].batch_id == second[1].batch_id
    upd = next(r for r in second if r.action == "update")
    assert upd.before == {
        "mark_id": ctx["pp"].id,
        "mark": "PP001",
        "def_id": d["forma"].id,
        "param": "Tipo de forma",
        "value": "F-11",
    }
    assert upd.after is not None and upd.after["value"] == "F-13"
    assert upd.entity_id == str(ctx["pp"].id) and upd.user_id == ctx["users"][Role.FABRICA].id


async def test_history(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    forma = ctx["d"]["forma"].id
    await _put(client, ctx, [{"def_id": forma, "value": "F-11"}])
    await _put(client, ctx, [{"def_id": forma, "value": "F-12", "row_version": 1}], "admin")
    r = await client.get(f"{ctx['url']}/history", headers=as_user(ctx["users"][Role.LEITURA]))
    assert r.status_code == 200
    h = [(e["param"], e["before"], e["after"], e["user_name"], e["action"]) for e in r.json()]
    assert h == [
        ("Tipo de forma", "F-11", "F-12", ctx["users"][Role.ADMIN].name, "update"),
        ("Tipo de forma", None, "F-11", ctx["users"][Role.FABRICA].name, "set"),
    ]


@pytest.mark.parametrize("role", [Role.PROJETOS, Role.LEITURA])
async def test_only_fabrica_and_admin_edit(
    client: httpx.AsyncClient, ctx: dict[str, Any], role: Role
) -> None:
    r = await client.put(
        f"{ctx['url']}/values",
        json={"changes": [{"def_id": ctx["d"]["obs"].id, "value": "x"}]},
        headers=as_user(ctx["users"][role]),
    )
    assert r.status_code == 403
    assert (
        await client.get(f"{ctx['url']}/values", headers=as_user(ctx["users"][role]))
    ).status_code == 200


async def test_mark_must_belong_to_obra(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    url = f"/api/obras/{ctx['obra'].id}/marks/{ctx['alheia'].id}"
    for path in ("values", "history"):
        r = await client.get(f"{url}/{path}", headers=ctx["fab"])
        assert r.status_code == 404 and r.json()["detail"] == "Marca não encontrada nesta obra."
    r = await client.put(f"{url}/values", json={"changes": []}, headers=ctx["fab"])
    assert r.status_code == 404
