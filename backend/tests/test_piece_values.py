"""API dos valores POR PEÇA (P2): listar unidades, gravar com row_version (409), lote em
peças de marcas diferentes (só nas vazias / sobrescrever), desfazer, histórico e SSE."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Element, Mark, ModelVersion, Obra, ParamDef, PieceUnit, User
from app.models.enums import Role
from app.services import events, piece_units
from app.services.events import MemoryEventBus
from tests.conftest import as_user


async def _version(
    session: AsyncSession, obra: Obra, number: int, pieces: list[tuple[int, str, Mark]]
) -> ModelVersion:
    v = ModelVersion(
        obra_id=obra.id, acc_version_id=f"urn:pv:{obra.id}:{number}", version_number=number
    )
    session.add(v)
    await session.flush()
    for dbid, ext, mark in pieces:
        session.add(
            Element(
                version_id=v.id,
                dbid=dbid,
                external_id=ext,
                category=mark.category,
                mark_id=mark.id,
                level="TÉRREO",
                name=f"{mark.code} {ext}",
            )
        )
    await session.flush()
    await piece_units.link_version(session, v)
    v.status = "ready"
    await session.flush()
    return v


def _param(obra: Obra, name: str, ptype: str, level: str, **kw: Any) -> ParamDef:
    p = ParamDef(name=name, type=ptype, scope="obra", obra_id=obra.id, **kw)
    p.level = level
    return p


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-PV", name="Obra valores por peça", acc_item_name="pv.rvt")
    other = Obra(code="OB-PV2", name="Outra obra")
    session.add_all([obra, other])
    await session.flush()
    pp = Mark(obra_id=obra.id, code="PP001", category="Pilar")
    vg = Mark(obra_id=obra.id, code="V01", category="Viga")
    session.add_all([pp, vg])
    await session.flush()
    v1 = await _version(
        session,
        obra,
        1,
        [(10, "a", pp), (11, "b", pp), (12, "c", pp), (20, "v1", vg), (21, "v2", vg)],
    )
    # v2: a peça "b" foi recriada (chave nova) -> PP001-2 ligada pela ordem
    v2 = await _version(
        session,
        obra,
        2,
        [(30, "a", pp), (31, "b-nova", pp), (32, "c", pp), (40, "v1", vg), (41, "v2", vg)],
    )
    params = {
        "fab": _param(obra, "Data de fabricação", "date", "piece"),
        "nota": _param(obra, "Observação da peça", "text", "piece", categories=["Viga"]),
        "marca": _param(obra, "Liberação", "text", "mark"),
    }
    session.add_all(params.values())
    await session.flush()
    units = {
        f"{m.code}-{u.number}": u
        for m in (pp, vg)
        for u in await session.scalars(select(PieceUnit).where(PieceUnit.mark_id == m.id))
    }
    return {
        "obra": obra,
        "other": other,
        "pp": pp,
        "vg": vg,
        "v1": v1,
        "v2": v2,
        "p": params,
        "u": units,
        "users": users,
        "fab": as_user(users[Role.FABRICA]),
        "read": as_user(users[Role.LEITURA]),
    }


def _url(ctx: dict[str, Any], tail: str) -> str:
    return f"/api/obras/{ctx['obra'].id}{tail}"


async def _put(
    client: httpx.AsyncClient,
    ctx: dict[str, Any],
    unit: str,
    def_key: str,
    value: Any,
    row_version: int | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.put(
        _url(ctx, f"/units/{ctx['u'][unit].id}/values"),
        json={
            "changes": [
                {"def_id": ctx["p"][def_key].id, "value": value, "row_version": row_version}
            ]
        },
        headers=headers or ctx["fab"],
    )


# ------------------------------------------------------------------ listar


async def test_list_units_with_params_values_and_linked_element(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r = await client.get(_url(ctx, f"/marks/{ctx['pp'].id}/units"), headers=ctx["read"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["version_id"] == ctx["v2"].id  # padrão: a pronta mais recente
    # só os parâmetros POR PEÇA que valem na categoria (Pilar): nada de "Liberação" ou de Viga
    assert [p["name"] for p in out["params"]] == ["Data de fabricação"]
    rows = [
        (u["label"], u["status"], u["element"]["dbid"], u["element"]["method"])
        for u in out["units"]
    ]
    assert rows == [
        ("PP001-1", "linked", 30, "key"),
        ("PP001-2", "linked", 31, "order"),
        ("PP001-3", "linked", 32, "key"),
    ]
    assert out["units"][0]["values"] == [
        {
            "def_id": ctx["p"]["fab"].id,
            "value": None,
            "row_version": None,
            "updated_at": None,
            "updated_by_name": None,
        }
    ]

    # na versão anterior, o elemento ligado é o dela
    old = await client.get(
        _url(ctx, f"/marks/{ctx['pp'].id}/units?version_id={ctx['v1'].id}"), headers=ctx["read"]
    )
    assert [u["element"]["dbid"] for u in old.json()["units"]] == [10, 11, 12]

    viga = await client.get(_url(ctx, f"/marks/{ctx['vg'].id}/units"), headers=ctx["read"])
    assert [p["name"] for p in viga.json()["params"]] == [
        "Data de fabricação",
        "Observação da peça",
    ]

    missing = await client.get(
        f"/api/obras/{ctx['other'].id}/marks/{ctx['pp'].id}/units", headers=ctx["read"]
    )
    assert missing.status_code == 404


# ------------------------------------------------------------------ gravar


async def test_save_values_with_row_version_and_conflict(
    client: httpx.AsyncClient, ctx: dict[str, Any], session: AsyncSession, event_bus: MemoryEventBus
) -> None:
    r = await _put(client, ctx, "PP001-2", "fab", "2026-11-10T08:00:00")
    assert r.status_code == 200, r.text
    field = r.json()["unit"]["values"][0]
    assert (field["value"], field["row_version"]) == ("2026-11-10", 1)  # data normalizada
    assert field["updated_by_name"] == ctx["users"][Role.FABRICA].name

    # só a PP001-2 recebeu o valor; as outras peças da marca continuam vazias
    listed = await client.get(_url(ctx, f"/marks/{ctx['pp'].id}/units"), headers=ctx["fab"])
    assert [u["values"][0]["value"] for u in listed.json()["units"]] == [None, "2026-11-10", None]

    # outro usuário (admin) salva antes; quem leu a versão 1 recebe 409 "stale"
    admin = as_user(ctx["users"][Role.ADMIN])
    assert (await _put(client, ctx, "PP001-2", "fab", "2026-11-11", 1, admin)).status_code == 200
    stale = await _put(client, ctx, "PP001-2", "fab", "2026-11-12", 1)
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "stale" and body["changed_by_name"] == ctx["users"][Role.ADMIN].name
    assert "PP001-2" in body["detail"]
    current = await client.get(_url(ctx, f"/units/{ctx['u']['PP001-2'].id}"), headers=ctx["fab"])
    assert current.json()["unit"]["values"][0]["value"] == "2026-11-11"  # nada gravado no 409

    # auditoria campo a campo e evento SSE para as outras abas
    rows = list(
        await session.scalars(
            select(AuditLog).where(AuditLog.entity == "piece_value").order_by(AuditLog.id)
        )
    )
    assert [(a.action, (a.after or {})["unit"], (a.after or {})["value"]) for a in rows] == [
        ("set", "PP001-2", "2026-11-10"),
        ("update", "PP001-2", "2026-11-11"),
    ]
    await events.drain()
    evs = [e for e in event_bus.history[ctx["obra"].id] if e.type == "unit_values_changed"]
    assert [e.data["unit"] for e in evs] == ["PP001-2", "PP001-2"]
    assert evs[0].data["changes"][0]["after"] == "2026-11-10"


async def test_save_validation_and_roles(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    # parâmetro por MARCA não se grava numa peça
    r = await _put(client, ctx, "PP001-1", "marca", "Ok")
    assert r.status_code == 422 and "não é por peça" in r.json()["detail"]
    # parâmetro por peça de outra categoria
    r = await _put(client, ctx, "PP001-1", "nota", "x")
    assert r.status_code == 422 and "Pilar" in r.json()["detail"]
    r = await _put(client, ctx, "PP001-1", "fab", "13/11/2026")
    assert r.status_code == 422 and r.json()["detail"] == "Data inválida: use dd/mm/aaaa"
    # o bug de 2026-11-16: ano parcial (0002) não é data válida
    r = await _put(client, ctx, "PP001-1", "fab", "0002-05-05")
    assert r.status_code == 422 and r.json()["detail"] == "Data inválida: use dd/mm/aaaa"
    assert r.json()["param"] == "Data de fabricação"
    # leitura e projetos não gravam
    for role in (Role.LEITURA, Role.PROJETOS):
        r = await _put(
            client, ctx, "PP001-1", "fab", "2026-11-10", headers=as_user(ctx["users"][role])
        )
        assert r.status_code == 403
    # peça de outra obra
    r = await client.put(
        f"/api/obras/{ctx['other'].id}/units/{ctx['u']['PP001-1'].id}/values",
        json={"changes": []},
        headers=ctx["fab"],
    )
    assert r.status_code == 404


# ------------------------------------------------------------------ lote e desfazer


async def test_batch_across_marks_modes_and_undo(
    client: httpx.AsyncClient, ctx: dict[str, Any], event_bus: MemoryEventBus
) -> None:
    fab, nota = ctx["p"]["fab"].id, ctx["p"]["nota"].id
    assert (await _put(client, ctx, "PP001-1", "fab", "2026-11-01")).status_code == 200
    ids = [ctx["u"][k].id for k in ("PP001-1", "PP001-2", "V01-1")]

    pre = await client.post(
        _url(ctx, "/units/batch-preview"),
        json={"unit_ids": ids, "changes": {fab: "2026-11-15", nota: "ok"}, "mode": "only_empty"},
        headers=ctx["read"],  # prévia: todos os papéis
    )
    assert pre.status_code == 200, pre.text
    p = pre.json()
    assert (p["units"], p["marks"], p["categories"]) == (3, 2, ["Pilar", "Viga"])
    fields = {f["name"]: (f["applies_to"], f["filled"], f["mixed"]) for f in p["fields"]}
    assert fields == {"Data de fabricação": (3, 1, True), "Observação da peça": (1, 0, False)}
    changes = {
        c["def_id"]: (c["applies_to"], c["to_change"], c["other_value"]) for c in p["changes"]
    }
    assert changes == {fab: (3, 2, 1), nota: (1, 1, 0)}
    assert (p["units_to_change_only_empty"], p["units_to_change_overwrite"]) == (2, 3)

    # "só nas vazias": a PP001-1 (já preenchida) não muda
    r = await client.post(
        _url(ctx, "/units/batch-apply"),
        json={"unit_ids": ids, "changes": {fab: "2026-11-15"}, "mode": "only_empty"},
        headers=ctx["fab"],
    )
    assert r.status_code == 200, r.text
    assert (r.json()["units_changed"], r.json()["fields_changed"]) == (2, 2)
    values = await client.get(_url(ctx, f"/marks/{ctx['pp'].id}/units"), headers=ctx["fab"])
    assert [u["values"][0]["value"] for u in values.json()["units"]] == [
        "2026-11-01",
        "2026-11-15",
        None,
    ]

    # "sobrescrever" e desfazer
    r = await client.post(
        _url(ctx, "/units/batch-apply"),
        json={"unit_ids": ids, "changes": {fab: "2026-11-20"}, "mode": "overwrite"},
        headers=ctx["fab"],
    )
    batch = r.json()["batch_id"]
    assert r.json()["units_changed"] == 3
    undo = await client.post(f"/api/batches/{batch}/undo", headers=ctx["fab"])
    assert undo.status_code == 200, undo.text
    assert undo.json()["restored"] == 3
    values = await client.get(_url(ctx, f"/marks/{ctx['pp'].id}/units"), headers=ctx["fab"])
    assert [u["values"][0]["value"] for u in values.json()["units"]] == [
        "2026-11-01",
        "2026-11-15",
        None,
    ]
    again = await client.post(f"/api/batches/{batch}/undo", headers=ctx["fab"])
    assert again.status_code == 409 and "já foi desfeito" in again.json()["detail"]

    # alterado depois do lote: desfazer recusa (não apaga trabalho alheio)
    r = await client.post(
        _url(ctx, "/units/batch-apply"),
        json={"unit_ids": ids[:2], "changes": {fab: "2026-11-21"}, "mode": "overwrite"},
        headers=ctx["fab"],
    )
    later = r.json()["batch_id"]
    assert (await _put(client, ctx, "PP001-1", "fab", "2026-11-22", 4)).status_code == 200
    refused = await client.post(f"/api/batches/{later}/undo", headers=ctx["fab"])
    assert refused.status_code == 409 and refused.json()["changed_since"] == 1

    # leitura não aplica lote
    denied = await client.post(
        _url(ctx, "/units/batch-apply"),
        json={"unit_ids": ids, "changes": {fab: "2026-11-15"}},
        headers=ctx["read"],
    )
    assert denied.status_code == 403

    await events.drain()
    types = [e.type for e in event_bus.history[ctx["obra"].id]]
    assert "unit_batch_applied" in types and "unit_batch_undone" in types


async def test_batch_validation(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    url = _url(ctx, "/units/batch-apply")
    r = await client.post(url, json={"unit_ids": [], "changes": {1: "x"}}, headers=ctx["fab"])
    assert r.status_code == 422 and "ao menos uma peça" in r.json()["detail"]
    r = await client.post(
        url,
        json={"unit_ids": [ctx["u"]["PP001-1"].id], "changes": {ctx["p"]["nota"].id: "x"}},
        headers=ctx["fab"],
    )
    assert r.status_code == 422 and "nenhuma peça selecionada" in r.json()["detail"]
    r = await client.post(
        f"/api/obras/{ctx['other'].id}/units/batch-apply",
        json={"unit_ids": [ctx["u"]["PP001-1"].id], "changes": {ctx["p"]["fab"].id: "2026-11-01"}},
        headers=ctx["fab"],
    )
    assert r.status_code == 404


async def test_mark_batches_still_undo_as_before(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    # parâmetro por marca na obra: o lote por marca e o desfazer continuam iguais
    r = await client.post(
        _url(ctx, "/marks/batch-apply"),
        json={"mark_ids": [ctx["pp"].id], "changes": {ctx["p"]["marca"].id: "Ok"}},
        headers=ctx["fab"],
    )
    assert r.status_code == 200, r.text
    undo = await client.post(f"/api/batches/{r.json()['batch_id']}/undo", headers=ctx["fab"])
    assert undo.status_code == 200 and undo.json()["restored"] == 1


# ------------------------------------------------------------------ histórico


async def test_unit_history_shows_values_and_model_links(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    assert (await _put(client, ctx, "PP001-2", "fab", "2026-11-10")).status_code == 200
    assert (await _put(client, ctx, "PP001-2", "fab", None, 1)).status_code == 200  # apagar
    r = await client.get(_url(ctx, f"/units/{ctx['u']['PP001-2'].id}/history"), headers=ctx["read"])
    assert r.status_code == 200, r.text
    rows = [(h["action"], h["param"], h["before"], h["after"]) for h in r.json()]
    assert rows == [
        ("clear", "Data de fabricação", "2026-11-10", None),
        ("set", "Data de fabricação", None, "2026-11-10"),
        ("link_order", "Peça do modelo", "b", "b-nova"),  # peça recriada na v2
    ]
