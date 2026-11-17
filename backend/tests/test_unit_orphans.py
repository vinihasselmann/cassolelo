"""Revisões do modelo e unidades órfãs (P5): o diff da versão (perderam a peça / novas /
voltaram), a fila, religar a outra peça da mesma marca (com conflito), arquivar, a volta
pela chave e a auditoria."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    ParamDef,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
    VersionDiff,
)
from app.models.enums import Role
from app.services import piece_units
from app.services.events import MemoryEventBus
from app.services.unit_matching import ElementIn, UnitIn, match
from tests.conftest import as_user


async def _version(
    session: AsyncSession, obra: Obra, number: int, pieces: list[tuple[int, str, Mark]]
) -> tuple[ModelVersion, piece_units.LinkSummary]:
    """Versão pronta com as peças; o diff da versão existe antes de ligar (como no
    process_version, em que a reconciliação das marcas vem antes)."""
    v = ModelVersion(
        obra_id=obra.id, acc_version_id=f"urn:uo:{obra.id}:{number}", version_number=number
    )
    session.add(v)
    await session.flush()
    session.add(VersionDiff(version_id=v.id, diff={"totals": {}}))
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
    summary = await piece_units.link_version(session, v)
    v.status = "ready"
    await session.flush()
    return v, summary


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    obra = Obra(code="OB-UO", name="Obra unidades órfãs", acc_item_name="uo.rvt")
    session.add(obra)
    await session.flush()
    pp = Mark(obra_id=obra.id, code="PP001", category="Pilar")
    vg = Mark(obra_id=obra.id, code="V01", category="Viga")
    session.add_all([pp, vg])
    await session.flush()
    six = [(10 + i, f"p{i + 1}", pp) for i in range(6)]
    v1, _ = await _version(session, obra, 1, [*six, (20, "v1", vg)])
    fab = ParamDef(name="Data de fabricação", type="date", scope="obra", obra_id=obra.id)
    fab.level = "piece"
    session.add(fab)
    await session.flush()
    units = {
        u.number: u
        for u in await session.scalars(select(PieceUnit).where(PieceUnit.mark_id == pp.id))
    }
    # PP001-3 (peça "p3") e PP001-5 com valor; as outras vazias
    for n, day in ((3, "2026-11-03"), (5, "2026-11-05")):
        session.add(PieceValue(unit_id=units[n].id, def_id=fab.id, value=day))
    await session.flush()
    return {
        "obra": obra,
        "pp": pp,
        "vg": vg,
        "v1": v1,
        "six": six,
        "fab": fab,
        "u": units,
        "fab_user": as_user(users[Role.FABRICA]),
        "read": as_user(users[Role.LEITURA]),
    }


def _url(ctx: dict[str, Any], tail: str) -> str:
    return f"/api/obras/{ctx['obra'].id}{tail}"


async def _v2_without_p3(session: AsyncSession, ctx: dict[str, Any]) -> ModelVersion:
    """v2: a peça "p3" (PP001-3, com valor) saiu do modelo; o resto igual."""
    pieces = [(100 + d, ext, m) for d, ext, m in ctx["six"] if ext != "p3"]
    v2, summary = await _version(session, ctx["obra"], 2, [*pieces, (120, "v1", ctx["vg"])])
    assert (summary.orphans, summary.new) == (1, 0)
    return v2


async def _status(session: AsyncSession, unit: PieceUnit) -> str:
    await session.refresh(unit)
    return unit.status


async def test_version_with_one_piece_less_leaves_orphan_with_values(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    v2 = await _v2_without_p3(session, ctx)
    u3 = ctx["u"][3]
    assert await _status(session, u3) == "orphan"
    assert u3.since_version_id == v2.id
    # valores preservados na unidade
    value = await session.scalar(select(PieceValue.value).where(PieceValue.unit_id == u3.id))
    assert value == "2026-11-03"

    # banner: diff da versão
    r = await client.get(f"/api/versions/{v2.id}/diff", headers=ctx["read"])
    assert r.status_code == 200, r.text
    units = r.json()["units"]
    assert units["lost"] == 1 and units["new"] == 0 and units["orphans_open"] == 1
    assert units["lost_units"] == [{"unit_id": u3.id, "label": "PP001-3"}]

    # fila
    r = await client.get(_url(ctx, "/unit-orphans"), headers=ctx["read"])
    assert r.status_code == 200
    [row] = r.json()
    assert row["label"] == "PP001-3" and row["status"] == "orphan"
    assert row["since_version_number"] == 2 and row["mark_in_model"] is True
    assert row["values"] == [
        {
            "def_id": ctx["fab"].id,
            "name": "Data de fabricação",
            "type": "date",
            "value": "2026-11-03",
        }
    ]
    # auditoria da órfã
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "piece_unit",
            AuditLog.entity_id == str(u3.id),
            AuditLog.action == "orphan",
        )
    )
    assert audit is not None


async def test_new_units_appear_in_the_diff(session: AsyncSession, ctx: dict[str, Any]) -> None:
    pieces = [(100 + d, ext, m) for d, ext, m in ctx["six"]]
    v2, summary = await _version(
        session, ctx["obra"], 2, [*pieces, (106, "p7", ctx["pp"]), (120, "v1", ctx["vg"])]
    )
    assert summary.new == 1
    diff = await session.scalar(select(VersionDiff.diff).where(VersionDiff.version_id == v2.id))
    assert diff is not None
    assert diff["units"]["new"] == 1
    assert diff["units"]["new_units"][0]["label"] == "PP001-7"
    assert diff["units"]["lost"] == 0


async def test_relink_to_another_piece_recovers_values(
    client: httpx.AsyncClient,
    session: AsyncSession,
    ctx: dict[str, Any],
    event_bus: MemoryEventBus,
) -> None:
    v2 = await _v2_without_p3(session, ctx)
    u3, u6 = ctx["u"][3], ctx["u"][6]  # PP001-6: vazia, peça "p6"
    r = await client.post(
        _url(ctx, f"/units/{u3.id}/relink"),
        json={"target_unit_id": u6.id},
        headers=ctx["fab_user"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "PP001-3" and body["displaced_label"] == "PP001-6"
    assert body["displaced_status"] == "unlinked"

    await session.refresh(u3)
    await session.refresh(u6)
    assert (u3.status, u3.external_id) == ("linked", "p6")
    assert (u6.status, u6.external_id, u6.since_version_id) == ("unlinked", None, v2.id)
    link = await session.scalar(
        select(PieceUnitLink).where(
            PieceUnitLink.version_id == v2.id, PieceUnitLink.unit_id == u3.id
        )
    )
    assert link is not None and link.method == "manual"
    # a peça mostra os valores recuperados (lista de unidades da marca)
    r = await client.get(_url(ctx, f"/marks/{ctx['pp'].id}/units"), headers=ctx["read"])
    row = next(u for u in r.json()["units"] if u["label"] == "PP001-3")
    assert row["element"]["external_id"] == "p6" and row["element"]["method"] == "manual"
    assert row["values"][0]["value"] == "2026-11-03"
    # fila vazia; auditoria das duas unidades; evento
    assert (await client.get(_url(ctx, "/unit-orphans"), headers=ctx["read"])).json() == []
    actions = {
        (a.entity_id, a.action)
        for a in await session.scalars(select(AuditLog).where(AuditLog.entity == "piece_unit"))
    }
    assert {(str(u3.id), "relink"), (str(u6.id), "displaced")} <= actions
    assert any(e.type == "unit_orphan_changed" for e in event_bus.history[ctx["obra"].id])

    # v3 igual à v2: a unidade religada segue na peça pela chave
    pieces = [(200 + d, ext, m) for d, ext, m in ctx["six"] if ext != "p3"]
    v3, _ = await _version(session, ctx["obra"], 3, [*pieces, (220, "v1", ctx["vg"])])
    method = await session.scalar(
        select(PieceUnitLink.method).where(
            PieceUnitLink.version_id == v3.id, PieceUnitLink.unit_id == u3.id
        )
    )
    assert method == "key"


async def test_relink_to_piece_with_values_needs_confirmation(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2_without_p3(session, ctx)
    u3, u5 = ctx["u"][3], ctx["u"][5]  # PP001-5 tem valor
    url = _url(ctx, f"/units/{u3.id}/relink")
    r = await client.post(url, json={"target_unit_id": u5.id}, headers=ctx["fab_user"])
    assert r.status_code == 409
    assert r.json()["code"] == "unit_relink_conflict"
    assert await _status(session, u3) == "orphan"  # nada mudou

    r = await client.post(
        url, json={"target_unit_id": u5.id, "confirm": True}, headers=ctx["fab_user"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["displaced_status"] == "orphan"
    assert await _status(session, u5) == "orphan"
    # os valores da deslocada continuam nela
    assert (
        await session.scalar(select(PieceValue.value).where(PieceValue.unit_id == u5.id))
        == "2026-11-05"
    )


async def test_relink_rules(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2_without_p3(session, ctx)
    u3 = ctx["u"][3]
    viga = await session.scalar(select(PieceUnit).where(PieceUnit.mark_id == ctx["vg"].id))
    assert viga is not None
    # outra marca
    r = await client.post(
        _url(ctx, f"/units/{u3.id}/relink"),
        json={"target_unit_id": viga.id},
        headers=ctx["fab_user"],
    )
    assert r.status_code == 422
    # não órfã
    r = await client.post(
        _url(ctx, f"/units/{ctx['u'][1].id}/relink"),
        json={"target_unit_id": ctx["u"][2].id},
        headers=ctx["fab_user"],
    )
    assert r.status_code == 409
    # leitura não grava
    r = await client.post(
        _url(ctx, f"/units/{u3.id}/relink"),
        json={"target_unit_id": ctx["u"][6].id},
        headers=ctx["read"],
    )
    assert r.status_code == 403


async def test_archive_keeps_values_and_returns_only_by_key(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _v2_without_p3(session, ctx)
    u3 = ctx["u"][3]
    r = await client.post(_url(ctx, f"/units/{u3.id}/archive"), headers=ctx["fab_user"])
    assert r.status_code == 200, r.text
    assert r.json() == {"id": u3.id, "label": "PP001-3", "status": "archived"}
    assert (await client.get(_url(ctx, "/unit-orphans"), headers=ctx["read"])).json() == []
    archived = (
        await client.get(_url(ctx, "/unit-orphans?archived=true"), headers=ctx["read"])
    ).json()
    assert [a["label"] for a in archived] == ["PP001-3"]
    assert (
        await session.scalar(select(PieceValue.value).where(PieceValue.unit_id == u3.id))
        == "2026-11-03"
    )
    r = await client.post(_url(ctx, f"/units/{u3.id}/archive"), headers=ctx["fab_user"])
    assert r.status_code == 409  # já arquivada

    # v3 com uma peça NOVA: a arquivada não é ligada pela ordem; vira unidade nova
    pieces = [(200 + d, ext, m) for d, ext, m in ctx["six"] if ext != "p3"]
    _, s3 = await _version(
        session, ctx["obra"], 3, [*pieces, (206, "p-nova", ctx["pp"]), (220, "v1", ctx["vg"])]
    )
    assert s3.new == 1 and s3.returned == 0
    assert await _status(session, u3) == "archived"

    # v4: a chave "p3" reaparece -> a arquivada volta, com os valores
    pieces = [(300 + d, ext, m) for d, ext, m in ctx["six"]]
    v4, s4 = await _version(session, ctx["obra"], 4, [*pieces, (320, "v1", ctx["vg"])])
    assert s4.returned == 1
    assert await _status(session, u3) == "linked"
    diff = await session.scalar(select(VersionDiff.diff).where(VersionDiff.version_id == v4.id))
    assert diff is not None and diff["units"]["returned"] == 1
    actions = [
        a.action
        for a in await session.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "piece_unit", AuditLog.entity_id == str(u3.id))
            .order_by(AuditLog.id)
        )
    ]
    assert actions == ["orphan", "archive", "returned"]


def test_match_archived_units_only_by_key() -> None:
    units = [UnitIn(1, 1, "a", True, key_only=True), UnitIn(2, 2, "b", False)]
    elements = [ElementIn(10, "x", None, None)]
    r = match(units, elements)
    # a arquivada não pega o elemento sem par: a unidade 2 pega pela ordem
    assert [(lk.unit_id, lk.method) for lk in r.links] == [(2, "order")]
    assert r.leftover == []  # a arquivada que não voltou fica de fora da sobra
    r = match(units, [ElementIn(10, "a", None, None)])
    assert [(lk.unit_id, lk.method) for lk in r.links] == [(1, "key")]
