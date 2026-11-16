"""6.3 · Edição em lote: batch-preview, batch-apply e POST /api/batches/{id}/undo."""

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
    obra = Obra(code="OB-L1", name="Obra lote")
    other = Obra(code="OB-L2", name="Outra")
    session.add_all([obra, other])
    await session.flush()
    pilares = [Mark(obra_id=obra.id, code=f"PP{i:03d}", category="Pilar") for i in range(1, 11)]
    vigas = [Mark(obra_id=obra.id, code=f"V{i:02d}", category="Viga") for i in range(1, 4)]
    alheia = Mark(obra_id=other.id, code="PP001", category="Pilar")
    session.add_all([*pilares, *vigas, alheia])
    d = {
        "forma": ParamDef(
            name="Tipo de forma",
            type="list",
            options=["F-11", "F-12", "F-13"],
            categories=["Pilar"],
            scope="global",
        ),
        "cura": ParamDef(name="Ciclo de cura", type="number", unit="h", scope="global"),
        "obs": ParamDef(name="Observação", type="text", scope="obra", obra_id=obra.id),
        "viga": ParamDef(name="Só viga", type="text", categories=["Viga"], scope="global"),
    }
    session.add_all(d.values())
    await session.flush()
    await include_params(session, obra.id, *d.values())
    return {
        "obra": obra,
        "pilares": pilares,
        "vigas": vigas,
        "alheia": alheia,
        "d": d,
        "users": users,
        "fab": as_user(users[Role.FABRICA]),
        "url": f"/api/obras/{obra.id}/marks",
    }


async def _post(
    client: httpx.AsyncClient,
    ctx: dict[str, Any],
    what: str,
    marks: list[Mark],
    changes: dict[str, Any] | None = None,
    mode: str = "overwrite",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        f"{ctx['url']}/batch-{what}",
        json={"mark_ids": [m.id for m in marks], "changes": changes or {}, "mode": mode},
        headers=headers or ctx["fab"],
    )


async def _values(session: AsyncSession, def_id: int) -> dict[int, Any]:
    rows = await session.execute(
        select(ParamValue.mark_id, ParamValue.value).where(ParamValue.def_id == def_id)
    )
    return {mark_id: value for mark_id, value in rows if value is not None}


async def _set(session: AsyncSession, mark: Mark, param: ParamDef, value: Any) -> None:
    session.add(ParamValue(mark_id=mark.id, def_id=param.id, value=value))
    await session.flush()


# --------------------------------------------------------------------------- preview


async def test_preview_without_changes_summarizes_fields(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d = ctx["pilares"], ctx["d"]
    await _set(session, p[0], d["forma"], "F-11")
    await _set(session, p[0], d["cura"], 12)
    await _set(session, p[1], d["cura"], 12)
    r = await _post(
        client, ctx, "preview", [p[0], p[1]], headers=as_user(ctx["users"][Role.LEITURA])
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["marks"], body["categories"], body["changes"]) == (2, ["Pilar"], [])
    fields = {f["name"]: f for f in body["fields"]}
    assert list(fields) == ["Ciclo de cura", "Observação", "Tipo de forma"]  # sem "Só viga"
    cura = fields["Ciclo de cura"]
    assert (cura["mixed"], cura["common_value"]) == (False, 12)
    assert (fields["Tipo de forma"]["mixed"], fields["Tipo de forma"]["filled"]) == (True, 1)
    assert (fields["Observação"]["mixed"], fields["Observação"]["common_value"]) == (False, None)


async def test_preview_counts_marks_to_change_and_other_values(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d = ctx["pilares"], ctx["d"]
    await _set(session, p[0], d["forma"], "F-11")  # outro valor
    await _set(session, p[1], d["forma"], "F-12")  # já igual
    r = await _post(client, ctx, "preview", p, {str(d["forma"].id): "f-12"})
    body = r.json()
    assert body["marks_to_change"] == 9  # 10 - a que já tem F-12
    assert body["marks_to_change_overwrite"] == 9
    assert body["marks_to_change_only_empty"] == 8
    assert body["marks_with_other_value"] == 1
    assert body["changes"] == [
        {"def_id": d["forma"].id, "applies_to": 10, "to_change": 9, "other_value": 1}
    ]
    r = await _post(client, ctx, "preview", p, {str(d["forma"].id): "F-12"}, mode="only_empty")
    assert r.json()["marks_to_change"] == 8


async def test_mixed_categories_only_apply_where_param_applies(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    d = ctx["d"]
    marks = [*ctx["pilares"][:2], *ctx["vigas"]]
    r = await _post(client, ctx, "preview", marks)
    body = r.json()
    assert body["categories"] == ["Pilar", "Viga"]
    applies = {f["name"]: f["applies_to"] for f in body["fields"]}
    assert applies == {"Ciclo de cura": 5, "Observação": 5, "Só viga": 3, "Tipo de forma": 2}

    r = await _post(client, ctx, "apply", marks, {str(d["forma"].id): "F-13"})
    assert r.status_code == 200, r.text
    assert (r.json()["marks_changed"], r.json()["fields_changed"]) == (2, 2)
    assert set(await _values(session, d["forma"].id)) == {m.id for m in ctx["pilares"][:2]}


# --------------------------------------------------------------------------- apply + undo


async def test_apply_to_10_marks_and_undo_restores_previous_state(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d = ctx["pilares"], ctx["d"]
    await _set(session, p[0], d["forma"], "F-11")
    await _set(session, p[3], d["forma"], "F-13")
    await _set(session, p[5], d["cura"], 8)
    before_forma = await _values(session, d["forma"].id)
    before_cura = await _values(session, d["cura"].id)

    r = await _post(
        client, ctx, "apply", p, {str(d["forma"].id): "F-12", str(d["cura"].id): "12,5"}
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert (result["marks_changed"], result["fields_changed"]) == (10, 20)
    assert await _values(session, d["forma"].id) == {m.id: "F-12" for m in p}
    assert await _values(session, d["cura"].id) == {m.id: 12.5 for m in p}

    audit = list(
        await session.scalars(select(AuditLog).where(AuditLog.batch_id == result["batch_id"]))
    )
    assert len(audit) == 20
    assert {a.action for a in audit} == {"set", "update"}
    assert all(a.after and a.after["source"] == "batch" for a in audit)

    r = await client.post(f"/api/batches/{result['batch_id']}/undo", headers=ctx["fab"])
    assert r.status_code == 200, r.text
    assert r.json()["restored"] == 20
    assert await _values(session, d["forma"].id) == before_forma
    assert await _values(session, d["cura"].id) == before_cura

    # o desfazer também é auditado (outro lote) e não pode ser repetido
    undo_rows = list(
        await session.scalars(select(AuditLog).where(AuditLog.batch_id == r.json()["batch_id"]))
    )
    assert len(undo_rows) == 20
    assert all(u.after and u.after["undo_of"] == result["batch_id"] for u in undo_rows)
    again = await client.post(f"/api/batches/{result['batch_id']}/undo", headers=ctx["fab"])
    assert (again.status_code, again.json()["code"]) == (409, "conflict")


async def test_only_empty_does_not_touch_filled_marks(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d = ctx["pilares"], ctx["d"]
    await _set(session, p[0], d["forma"], "F-11")
    await _set(session, p[1], d["forma"], "F-13")
    r = await _post(client, ctx, "apply", p, {str(d["forma"].id): "F-12"}, mode="only_empty")
    assert r.status_code == 200, r.text
    assert r.json()["marks_changed"] == 8
    values = await _values(session, d["forma"].id)
    assert (values[p[0].id], values[p[1].id]) == ("F-11", "F-13")
    assert all(values[m.id] == "F-12" for m in p[2:])


async def test_only_empty_clear_does_nothing_and_overwrite_clears(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d = ctx["pilares"], ctx["d"]
    await _set(session, p[0], d["obs"], "trinca")
    r = await _post(client, ctx, "apply", p[:3], {str(d["obs"].id): ""}, mode="only_empty")
    assert (r.json()["batch_id"], r.json()["marks_changed"]) == (None, 0)
    r = await _post(client, ctx, "apply", p[:3], {str(d["obs"].id): None})
    assert r.json()["marks_changed"] == 1
    assert await _values(session, d["obs"].id) == {}


async def test_undo_refuses_when_changed_after_batch(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d = ctx["pilares"], ctx["d"]
    r = await _post(client, ctx, "apply", p[:3], {str(d["forma"].id): "F-12"})
    batch_id = r.json()["batch_id"]
    # outro salvamento individual depois do lote
    row = (await session.scalars(select(ParamValue).where(ParamValue.mark_id == p[1].id))).one()
    put = await client.put(
        f"{ctx['url']}/{p[1].id}/values",
        json={
            "changes": [{"def_id": d["forma"].id, "value": "F-13", "row_version": row.row_version}]
        },
        headers=ctx["fab"],
    )
    assert put.status_code == 200, put.text
    r = await client.post(f"/api/batches/{batch_id}/undo", headers=ctx["fab"])
    assert r.status_code == 409
    assert r.json()["changed_since"] == 1
    assert (await _values(session, d["forma"].id))[p[0].id] == "F-12"  # nada desfeito


# --------------------------------------------------------------------------- regras


async def test_permissions(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p, d, users = ctx["pilares"], ctx["d"], ctx["users"]
    change = {str(d["forma"].id): "F-12"}
    for role in (Role.LEITURA, Role.PROJETOS):
        r = await _post(client, ctx, "apply", p[:2], change, headers=as_user(users[role]))
        assert r.status_code == 403
    r = await _post(client, ctx, "apply", p[:2], change)
    batch_id = r.json()["batch_id"]

    outro = User(name="Outro da fábrica", email="outro@dev.local", role=Role.FABRICA.value)
    session.add(outro)
    await session.flush()
    r = await client.post(f"/api/batches/{batch_id}/undo", headers=as_user(outro))
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    r = await client.post(f"/api/batches/{batch_id}/undo", headers=as_user(users[Role.ADMIN]))
    assert r.status_code == 200


async def test_validation(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    p, d = ctx["pilares"], ctx["d"]
    r = await _post(client, ctx, "apply", [p[0], ctx["alheia"]], {str(d["cura"].id): 1})
    assert r.status_code == 404  # marca de outra obra
    r = await _post(client, ctx, "apply", p[:2], {str(d["viga"].id): "x"})
    assert r.status_code == 422  # não se aplica a nenhuma marca selecionada
    r = await _post(client, ctx, "apply", p[:2], {str(d["forma"].id): "F-99"})
    assert r.status_code == 422 and "F-99" in r.json()["detail"]
    r = await _post(client, ctx, "apply", p[:2], {})
    assert r.status_code == 422
    r = await _post(client, ctx, "apply", [], {str(d["cura"].id): 1})
    assert r.status_code == 422
    r = await client.post(
        "/api/batches/00000000-0000-0000-0000-000000000000/undo", headers=ctx["fab"]
    )
    assert r.status_code == 404
