"""Ensaio do aceite P6 (tests/real_units_acceptance.py) com dados sintéticos: preencher as
unidades de uma marca, revisão com uma peça MOVIDA (dbId novo, mesma chave) e uma
APAGADA E RECRIADA (chave nova), e conferir que os valores seguiram as peças certas."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Element, Mark, ModelVersion, Obra, User
from app.models.enums import Role
from app.services import piece_units
from tests import real_units_acceptance as acc

UID = "f6c5d130-0254-44a5-9353-a5410320f029-"


def _key(element_id: int) -> str:
    return f"{UID}{element_id:08x}"


async def _version(
    session: AsyncSession, obra: Obra, number: int, pieces: Sequence[tuple[int, str, Mark | None]]
) -> ModelVersion:
    v = ModelVersion(
        obra_id=obra.id, acc_version_id=f"urn:p6:{obra.id}:{number}", version_number=number
    )
    session.add(v)
    await session.flush()
    for dbid, ext, mark in pieces:
        session.add(
            Element(
                version_id=v.id,
                dbid=dbid,
                external_id=ext,
                category="Pilares estruturais",
                mark_id=mark.id if mark else None,
                level="TÉRREO",
                name=f"CASSOL-PREO-Pilar-R [{int(ext[-8:], 16)}]",
            )
        )
    await session.flush()
    await piece_units.link_version(session, v)
    v.status = "ready"
    await session.flush()
    return v


IDS = [6657284, 6657285, 6657286, 6657456, 6657457, 6657458]


async def _setup(
    session: AsyncSession, users: dict[Role, User]
) -> tuple[Obra, Mark, dict[str, Any]]:
    obra = Obra(code="OB-P6", name="Aceite P6", acc_item_name="orc.rvt")
    session.add(obra)
    await session.flush()
    mark = Mark(obra_id=obra.id, code="PP005", category="Pilares estruturais")
    session.add(mark)
    await session.flush()
    await _version(session, obra, 1, [(87 + i, _key(e), mark) for i, e in enumerate(IDS)])
    snap = await acc.prepare(session, obra.id, "PP005", "Data de fabricação", users[Role.FABRICA])
    return obra, mark, snap


def test_revit_element_id() -> None:
    assert acc.revit_element_id(_key(6657284)) == 6657284
    assert acc.revit_element_id("pec-0012") is None
    assert acc.revit_element_id(None) is None


async def test_prepare_fills_a_distinct_value_per_unit(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    obra, _, snap = await _setup(session, users)
    assert [u["label"] for u in snap["units"]] == [f"PP005-{n}" for n in range(1, 7)]
    assert [u["revit_element_id"] for u in snap["units"]] == IDS
    assert [u["value"] for u in snap["units"]] == [f"2026-11-0{n}" for n in range(1, 7)]
    # pelo serviço normal: auditado
    audits = list(await session.scalars(select(AuditLog).where(AuditLog.entity == "piece_value")))
    assert len(audits) == 6
    # rodar de novo reaproveita o parâmetro e não muda nada
    again = await acc.prepare(session, obra.id, "PP005", "data de fabricação", users[Role.FABRICA])
    assert again["param_id"] == snap["param_id"]


async def test_moved_and_recreated_pieces_keep_their_values(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    obra, mark, snap = await _setup(session, users)
    # v2: PP005-1 movida (dbId novo, mesma chave); PP005-3 apagada e recriada (chave nova)
    pieces = [(200 + i, _key(e), mark) for i, e in enumerate(IDS) if e != 6657286]
    pieces.append((300, _key(6700001), mark))
    await _version(session, obra, 2, pieces)

    report = await acc.check(session, snap)
    assert report.ok, acc.render(report)
    by = {u.label: u for u in report.units}
    assert by["PP005-1"].verdict == "seguiu a mesma peça pela chave (dbId mudou)"
    assert by["PP005-3"].verdict == "peça recriada: ligada pela ordem à peça nova (conferir)"
    assert by["PP005-3"].key_now == _key(6700001)
    assert all(u.value_now == u.value_before for u in report.units)
    text = acc.render(report)
    assert "Resultado: **OK**" in text and "6657286 → 6700001" in text


async def test_recreated_piece_without_the_mark_leaves_an_orphan(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    obra, mark, snap = await _setup(session, users)
    # a peça recriada ficou SEM a Marca (Revit não copia): PP005-3 fica órfã
    pieces: list[tuple[int, str, Mark | None]] = [
        (200 + i, _key(e), mark) for i, e in enumerate(IDS) if e != 6657286
    ]
    pieces.append((300, _key(6700001), None))
    await _version(session, obra, 2, pieces)
    report = await acc.check(session, snap)
    by = {u.label: u for u in report.units}
    assert by["PP005-3"].verdict.startswith("sem peça (orphan)")
    assert by["PP005-3"].value_now == "2026-11-03"  # o valor não se perdeu


async def test_no_new_version_yet(session: AsyncSession, users: dict[Role, User]) -> None:
    _, _, snap = await _setup(session, users)
    report = await acc.check(session, snap)
    assert not report.ok
    assert "Ainda não há versão nova pronta" in acc.render(report)
