"""Lote por peça com várias marcas selecionadas (2026-11-18): as peças das marcas ligadas
na versão aberta, e o lote que já existe aplicado a elas."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Obra, ParamDef, PieceUnit, PieceValue, User
from app.models.enums import Role, UnitStatus
from app.services import piece_units
from tests.conftest import as_user
from tests.test_piece_units import _version


@dataclass
class Ctx:
    obra: Obra
    v: ModelVersion
    p1: Mark
    p2: Mark
    alien: Mark
    fab: User
    param: ParamDef


async def _setup(session: AsyncSession) -> Ctx:
    obra = Obra(code="OB-LOTE", name="Lote por peça", acc_item_name="o.rvt")
    other = Obra(code="OB-LOTE-2", name="Outra", acc_item_name="o.rvt")
    session.add_all([obra, other])
    await session.flush()
    p1 = Mark(obra_id=obra.id, code="PP001", category="Pilar")
    p2 = Mark(obra_id=obra.id, code="PP002", category="Pilar")
    alien = Mark(obra_id=other.id, code="PP001", category="Pilar")
    fab = User(name="Fab", email="fab-lote@test", role=Role.FABRICA)
    session.add_all([p1, p2, alien, fab])
    await session.flush()
    # versão com as duas marcas: PP001 com 2 peças, PP002 com 1
    v, _ = await _version(session, obra, p1, 1, [(10, "a"), (11, "b")])
    session.add(Element(version_id=v.id, dbid=20, external_id="c", category="Pilar", mark_id=p2.id))
    await session.flush()
    await piece_units.link_version(session, v)
    # unidade órfã da PP001 (sem peça nesta versão): fica de fora
    session.add(PieceUnit(obra_id=obra.id, mark_id=p1.id, number=9, status=UnitStatus.ORPHAN.value))
    param = ParamDef(name="Concretagem", type="text", scope="obra", obra_id=obra.id)
    param.level = "piece"
    session.add(param)
    await session.flush()
    return Ctx(obra, v, p1, p2, alien, fab, param)


async def test_units_of_marks_and_batch_across_marks(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    c = await _setup(session)
    h = as_user(c.fab)
    r = await client.post(
        f"/api/obras/{c.obra.id}/units/of-marks",
        json={"version_id": c.v.id, "mark_ids": [c.p2.id, c.p1.id]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    units = r.json()
    assert [u["label"] for u in units] == ["PP001-1", "PP001-2", "PP002-1"]  # sem a órfã
    assert {u["mark_id"] for u in units} == {c.p1.id, c.p2.id}

    # o lote que já existe aplica nas peças das duas marcas
    r = await client.post(
        f"/api/obras/{c.obra.id}/units/batch-apply",
        json={"unit_ids": [u["unit_id"] for u in units], "changes": {str(c.param.id): "L1"}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["units_changed"] == 3
    rows = await session.execute(
        select(PieceUnit.mark_id, PieceUnit.number, PieceValue.value)
        .join(PieceValue, PieceValue.unit_id == PieceUnit.id)
        .where(PieceUnit.obra_id == c.obra.id)
    )
    assert sorted(rows.tuples()) == sorted(
        [(c.p1.id, 1, "L1"), (c.p1.id, 2, "L1"), (c.p2.id, 1, "L1")]
    )  # a órfã (PP001-9) não recebeu nada


async def test_units_of_marks_rejects_marks_of_other_obra(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    c = await _setup(session)
    r = await client.post(
        f"/api/obras/{c.obra.id}/units/of-marks",
        json={"version_id": c.v.id, "mark_ids": [c.p1.id, c.alien.id]},
        headers=as_user(c.fab),
    )
    assert r.status_code == 404, r.text
