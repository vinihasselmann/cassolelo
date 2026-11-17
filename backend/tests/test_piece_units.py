"""Unidades de peça no banco (P1): ligação a cada versão, órfãs, auditoria, reprocesso,
versão anterior, NWD e o nível do parâmetro (por marca / por peça)."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import func, select
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
)
from app.models.enums import Role
from app.services import param_defs, piece_units
from tests.conftest import as_user, include_params

Piece = tuple[int, str | None]  # (dbid, externalId)


async def _obra(session: AsyncSession, item: str = "obra.rvt") -> tuple[Obra, Mark]:
    obra = Obra(code=f"OB-U-{item}", name="Obra unidades", acc_item_name=item)
    session.add(obra)
    await session.flush()
    mark = Mark(obra_id=obra.id, code="PP001", category="Pilar")
    session.add(mark)
    await session.flush()
    return obra, mark


async def _version(
    session: AsyncSession, obra: Obra, mark: Mark, number: int, pieces: list[Piece]
) -> tuple[ModelVersion, piece_units.LinkSummary]:
    v = ModelVersion(
        obra_id=obra.id, acc_version_id=f"urn:u:{obra.id}:{number}", version_number=number
    )
    session.add(v)
    await session.flush()
    for dbid, ext in pieces:
        session.add(
            Element(
                version_id=v.id,
                dbid=dbid,
                external_id=ext,
                category="Pilar",
                mark_id=mark.id,
                level="TÉRREO",
                name=f"Pilar {ext}",
            )
        )
    await session.flush()
    summary = await piece_units.link_version(session, v)
    v.status = "ready"
    await session.flush()
    return v, summary


async def _units(session: AsyncSession, obra: Obra) -> dict[int, tuple[str | None, str]]:
    """número -> (chave, situação)."""
    rows = await session.execute(
        select(PieceUnit.number, PieceUnit.external_id, PieceUnit.status).where(
            PieceUnit.obra_id == obra.id
        )
    )
    return {n: (ext, st) for n, ext, st in rows}


async def _linked(session: AsyncSession, v: ModelVersion) -> dict[str | None, tuple[int, str]]:
    """chave do elemento -> (número da unidade, método)."""
    rows = await session.execute(
        select(Element.external_id, PieceUnit.number, PieceUnitLink.method)
        .join(PieceUnitLink, PieceUnitLink.element_id == Element.id)
        .join(PieceUnit, PieceUnit.id == PieceUnitLink.unit_id)
        .where(PieceUnitLink.version_id == v.id)
    )
    return {ext: (n, m) for ext, n, m in rows}


async def _piece_param(session: AsyncSession, obra: Obra) -> ParamDef:
    p = ParamDef(name="Data de fabricação", type="date", scope="obra", obra_id=obra.id)
    p.level = "piece"
    session.add(p)
    await session.flush()
    return p


async def _unit(session: AsyncSession, obra: Obra, number: int) -> PieceUnit:
    unit = await session.scalar(
        select(PieceUnit).where(PieceUnit.obra_id == obra.id, PieceUnit.number == number)
    )
    assert unit is not None
    return unit


async def test_units_follow_pieces_across_versions(session: AsyncSession) -> None:
    obra, mark = await _obra(session)

    # v1: 3 peças -> unidades 1..3 (novas)
    _, s1 = await _version(session, obra, mark, 1, [(10, "a"), (11, "b"), (12, "c")])
    assert (s1.new, s1.by_key) == (3, 0)
    assert await _units(session, obra) == {
        1: ("a", "linked"),
        2: ("b", "linked"),
        3: ("c", "linked"),
    }

    # v2: peças movidas (dbId muda, chave igual) -> mesmas unidades, pela chave
    v2, s2 = await _version(session, obra, mark, 2, [(50, "c"), (51, "a"), (52, "b")])
    assert (s2.by_key, s2.new, s2.by_order) == (3, 0, 0)
    assert await _linked(session, v2) == {"a": (1, "key"), "b": (2, "key"), "c": (3, "key")}

    # valor por peça na unidade 2 (a "b")
    param = await _piece_param(session, obra)
    unit2 = await _unit(session, obra, 2)
    session.add(PieceValue(unit_id=unit2.id, def_id=param.id, value="2026-11-10"))
    await session.flush()

    # v3: a "b" foi apagada e recriada (chave nova) -> a unidade 2 continua, pela ordem
    v3, s3 = await _version(session, obra, mark, 3, [(60, "a"), (61, "b2"), (62, "c")])
    assert (s3.by_key, s3.by_order, s3.new) == (2, 1, 0)
    assert await _linked(session, v3) == {"a": (1, "key"), "b2": (2, "order"), "c": (3, "key")}
    assert (await _units(session, obra))[2] == ("b2", "linked")  # a chave acompanha
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "piece_unit",
            AuditLog.entity_id == str(unit2.id),
            AuditLog.action == "link_order",
        )
    )
    assert audit is not None and audit.before == {"external_id": "b", "status": "linked"}

    # v4: a quantidade sobe -> unidade 4 nova, vazia
    _, s4 = await _version(session, obra, mark, 4, [(70, "a"), (71, "b2"), (72, "c"), (73, "d")])
    assert (s4.by_key, s4.new) == (3, 1)
    assert (await _units(session, obra))[4] == ("d", "linked")

    # v5: a quantidade desce: some a "b2" (unidade 2, COM valor) e a "d" (4, sem valor)
    v5, s5 = await _version(session, obra, mark, 5, [(80, "a"), (82, "c")])
    assert (s5.orphans, s5.unlinked) == (1, 1)
    units = await _units(session, obra)
    assert units[2] == ("b2", "orphan") and units[4] == ("d", "unlinked")
    orphan = await _unit(session, obra, 2)
    assert orphan.since_version_id == v5.id
    value = await session.scalar(select(PieceValue).where(PieceValue.unit_id == orphan.id))
    assert value is not None and value.value == "2026-11-10"  # nunca apagar em silêncio
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity == "piece_unit", AuditLog.action == "orphan")
        )
        == 1
    )

    # reprocessar a v5: nada duplica, nada muda
    again = await piece_units.link_version(session, v5)
    assert (again.by_key, again.new, again.orphans) == (2, 0, 1)
    assert await _units(session, obra) == units
    links = await session.scalar(
        select(func.count()).select_from(PieceUnitLink).where(PieceUnitLink.version_id == v5.id)
    )
    assert links == 2

    # v6: a peça "b2" volta -> a órfã volta a ser ligada pela chave (sem número novo)
    _, s6 = await _version(session, obra, mark, 6, [(90, "a"), (91, "b2"), (92, "c")])
    assert (s6.by_key, s6.new) == (3, 0)
    assert (await _units(session, obra))[2] == ("b2", "linked")
    assert (await _unit(session, obra, 2)).since_version_id is None


async def test_older_version_only_links(session: AsyncSession) -> None:
    obra, mark = await _obra(session, "antiga.rvt")
    await _version(session, obra, mark, 2, [(10, "a"), (11, "b")])
    # a v1 chega (ou é reprocessada) DEPOIS da v2: só liga, não cria nem muda situação
    v1, s1 = await _version(session, obra, mark, 1, [(1, "a"), (2, "x"), (3, "y")])
    assert (s1.latest, s1.new, s1.by_key, s1.by_order) == (False, 0, 1, 1)
    assert set(await _units(session, obra)) == {1, 2}
    assert await _linked(session, v1) == {"a": (1, "key"), "x": (2, "order")}
    assert (await _units(session, obra))[2] == ("b", "linked")  # a chave não muda


async def test_nwd_links_by_order_only(session: AsyncSession) -> None:
    obra, mark = await _obra(session, "modelo.nwd")
    await _version(session, obra, mark, 1, [(10, "0/1/0"), (11, "0/1/1")])
    v2, s2 = await _version(session, obra, mark, 2, [(20, "0/1/0"), (21, "0/1/1")])
    assert (s2.by_key, s2.by_order) == (0, 2)
    assert {m for _, m in (await _linked(session, v2)).values()} == {"order"}


async def test_marks_rule_change_orphans_units_of_the_mark_that_left(
    session: AsyncSession,
) -> None:
    obra, mark = await _obra(session, "regra.rvt")
    await _version(session, obra, mark, 1, [(10, "a"), (11, "b")])
    param = await _piece_param(session, obra)
    unit1 = await _unit(session, obra, 1)
    session.add(PieceValue(unit_id=unit1.id, def_id=param.id, value="2026-11-01"))
    other = Mark(obra_id=obra.id, code="P-A", category="Pilar")
    session.add(other)
    await session.flush()
    # mesma peça física, agora em outra marca (a regra de identificação mudou)
    _, summary = await _version(session, obra, other, 2, [(10, "a"), (11, "b")])
    assert (summary.new, summary.orphans, summary.unlinked) == (2, 1, 1)
    rows = await session.execute(
        select(PieceUnit.mark_id, PieceUnit.number, PieceUnit.status)
        .where(PieceUnit.obra_id == obra.id)
        .order_by(PieceUnit.mark_id, PieceUnit.number)
    )
    assert list(rows) == [
        (mark.id, 1, "orphan"),
        (mark.id, 2, "unlinked"),
        (other.id, 1, "linked"),
        (other.id, 2, "linked"),
    ]


# ------------------------------------------------------------------ nível do parâmetro


async def test_param_level_create_list_and_lock(
    client: httpx.AsyncClient, session: AsyncSession, users: dict[Role, User]
) -> None:
    obra, mark = await _obra(session, "nivel.rvt")
    await _version(session, obra, mark, 1, [(10, "a")])
    h = as_user(users[Role.FABRICA])

    r = await client.post(
        "/api/param-defs",
        json={
            "name": "Data de fabricação",
            "type": "date",
            "scope": "obra",
            "obra_id": obra.id,
            "level": "piece",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    piece = r.json()
    assert piece["level"] == "piece"
    r = await client.post(
        "/api/param-defs",
        json={"name": "Lote", "type": "text", "scope": "obra", "obra_id": obra.id},
        headers=h,
    )
    assert r.json()["level"] == "mark"  # padrão
    bad = await client.post(
        "/api/param-defs",
        json={"name": "X", "type": "text", "scope": "obra", "obra_id": obra.id, "level": "lote"},
        headers=h,
    )
    assert bad.status_code == 422 and "Nível inválido" in bad.json()["detail"]

    # o catálogo mostra os dois níveis; os fluxos da marca, só os por marca
    listed = await client.get(f"/api/param-defs?obra_id={obra.id}", headers=h)
    assert {p["name"]: p["level"] for p in listed.json()} == {
        "Data de fabricação": "piece",
        "Lote": "mark",
    }
    mark_level = await session.scalars(
        select(ParamDef.name).where(param_defs.in_obra(obra.id), ParamDef.active.is_(True))
    )
    assert list(mark_level) == ["Lote"]
    values = await client.get(f"/api/obras/{obra.id}/marks/{mark.id}/values", headers=h)
    assert [v["name"] for v in values.json()["values"]] == ["Lote"]

    # sem valores, o nível ainda pode mudar; com valor numa unidade, não
    r = await client.patch(f"/api/param-defs/{piece['id']}", json={"level": "mark"}, headers=h)
    assert r.status_code == 200 and r.json()["level"] == "mark"
    r = await client.patch(f"/api/param-defs/{piece['id']}", json={"level": "piece"}, headers=h)
    assert r.json()["level"] == "piece"
    unit = await _unit(session, obra, 1)
    session.add(PieceValue(unit_id=unit.id, def_id=piece["id"], value="2026-11-16"))
    await session.flush()
    r = await client.patch(f"/api/param-defs/{piece['id']}", json={"level": "mark"}, headers=h)
    assert r.status_code == 409 and "Por marca / por peça" in r.json()["detail"]
    listed = await client.get(f"/api/param-defs?obra_id={obra.id}", headers=h)
    counts: dict[str, Any] = {p["name"]: p["values_count"] for p in listed.json()}
    assert counts["Data de fabricação"] == 1  # unidades com valor


async def test_library_param_level_needs_inclusion_like_any_other(
    session: AsyncSession, users: dict[Role, User]
) -> None:
    obra, _ = await _obra(session, "lib.rvt")
    lib = ParamDef(name="Data lib", type="date", scope="global")
    lib.level = "piece"
    session.add(lib)
    await session.flush()
    visible = select(ParamDef.id).where(param_defs.in_obra(obra.id, level=None))
    assert list(await session.scalars(visible)) == []
    await include_params(session, obra.id, lib)
    assert list(await session.scalars(visible)) == [lib.id]
    assert list(await session.scalars(select(ParamDef.id).where(param_defs.in_obra(obra.id)))) == []
