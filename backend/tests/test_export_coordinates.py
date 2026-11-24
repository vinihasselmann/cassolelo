"""Excel: colunas X/Y/Z (centro de gravidade) e sequência de montagem (2026-11-18).

Ordem de montagem: Z → X → Y, crescente, faixas de 0,10 m (de baixo para cima; decisão
de 2026-11-19, volta à proposta inicial). As linhas ficam por marca e número da peça (PP001-1,
PP001-2… seguidas); a sequência vai na coluna "Ordem de montagem".
Usa a obra da fixture `ctx` de test_export.py (6 peças com marca).
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element
from app.services.assembly_order import sequence
from tests.test_export import _rows
from tests.test_export import ctx as ctx  # fixture

# ------------------------------------------------------------------ ordem (função pura)


def test_z_first_then_x_then_y() -> None:
    """De baixo para cima: o Z decide antes de tudo, mesmo com X maior."""
    items = [("x0-topo", (0.0, 0.0, 13.6)), ("x5-baixo", (5.0, 9.0, 2.6))]
    assert sequence(items) == ["x5-baixo", "x0-topo"]


def test_same_band_in_z_decides_by_x_then_y() -> None:
    items = [
        ("b", (5.0, 0.0, 2.62)),
        ("a", (0.0, 9.0, 2.60)),  # 2 cm em Z: mesma faixa de Z → decide o X
        ("c", (5.04, -1.0, 2.61)),  # mesmo X (faixa de 0,10) que "b" → decide o Y
    ]
    assert sequence(items) == ["a", "c", "b"]


def test_band_starts_at_first_value() -> None:
    """Faixas contadas do início: 0,00 / 0,08 juntos; 0,15 já é outra faixa de Z."""
    items = [("z15", (0.0, 0.0, 0.15)), ("z08", (9.0, 0.0, 0.08)), ("z00", (5.0, 0.0, 0.0))]
    assert sequence(items) == ["z00", "z08", "z15"]


def test_legacy_xyz_order_for_obras_numbered_before() -> None:
    """X → Y → Z: a ordem das obras numeradas antes de 2026-11-19 (ligação no NWD)."""
    items = [("x5-baixo", (5.0, 0.0, 2.6)), ("x0-topo", (0.0, 0.0, 13.6))]
    assert sequence(items, order="xyz") == ["x0-topo", "x5-baixo"]
    with pytest.raises(ValueError):
        sequence(items, order="yzx")


def test_identical_points_keep_input_order() -> None:
    items = [("PP001-1", (1.0, 1.0, 1.0)), ("PP001-2", (1.0, 1.0, 1.0))]
    assert sequence(items) == ["PP001-1", "PP001-2"]


# ------------------------------------------------------------------ Excel


async def _post(
    client: httpx.AsyncClient, ctx: dict[str, Any], coordinates: dict[str, Any] | None
) -> httpx.Response:
    body: dict[str, Any] = {"version_id": ctx["v"].id}
    if coordinates is not None:
        body["coordinates"] = coordinates
    return await client.post(
        f"/api/obras/{ctx['obra'].id}/export.xlsx", json=body, headers=ctx["fab"]
    )


async def _dbids(session: AsyncSession, ctx: dict[str, Any]) -> list[int]:
    return list(
        await session.scalars(
            select(Element.dbid)
            .where(Element.version_id == ctx["v"].id, Element.mark_id.is_not(None))
            .order_by(Element.dbid)
        )
    )


async def test_pieces_sheet_by_mark_with_xyz_and_assembly_order_column(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    r0 = await _post(client, ctx, None)
    by_mark = _rows(load_workbook(io.BytesIO(r0.content))["Peças"])  # sem coordenadas
    dbids = await _dbids(session, ctx)
    assert len(dbids) == 6
    # Z decrescente pela ordem de dbId (X crescente, para provar que o Z decide antes): a
    # ordem de montagem é a INVERSA; a última fica sem
    coords = {str(d): [float(i), 1.0, 10.0 - i * 2.5] for i, d in enumerate(dbids[:-1])}
    r = await _post(client, ctx, coords)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    rows = _rows(wb["Peças"])
    # as linhas não mudam de lugar: por marca e número (PP001-1, PP001-2… seguidas)
    assert [p["dbId"] for p in rows] == [p["dbId"] for p in by_mark]
    for code in {p["Marca"] for p in rows}:
        nums = [int(str(p["Peça"]).rsplit("-", 1)[1]) for p in rows if p["Marca"] == code]
        assert nums == sorted(nums)
    order = {p["dbId"]: p["Ordem de montagem"] for p in rows}
    assert [order[d] for d in reversed(dbids[:-1])] == [1, 2, 3, 4, 5]
    assert order[dbids[-1]] is None  # sem coordenada: sem ordem
    first = next(p for p in rows if p["Ordem de montagem"] == 1)
    assert (first["X (m)"], first["Y (m)"], first["Z (m)"]) == (4.0, 1.0, 0.0)
    assert wb["Peças"].cell(row=2, column=7).number_format == "0.000"
    header = [c.value for c in wb["Peças"][1]]
    assert header[6:10] == ["X (m)", "Y (m)", "Z (m)", "Ordem de montagem"]

    about = dict((row[0].value, row[1].value) for row in wb["Sobre"].iter_rows())
    assert "centro de gravidade" in str(about["Coordenadas"])
    assert "origem interna" in str(about["Coordenadas"])
    assert about["Ordem das peças"] == (
        'por marca e número da peça; coluna "Ordem de montagem": sequência de montagem '
        "Z → X → Y, crescente, em faixas de 0,10 m (ordene por ela); "
        "1 peça(s) sem coordenada, sem ordem de montagem"
    )


async def test_without_coordinates_keeps_mark_order(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r = await _post(client, ctx, None)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    codes = [p["Marca"] for p in _rows(wb["Peças"])]
    assert codes == sorted(codes, key=lambda c: c)  # por marca
    about = dict((row[0].value, row[1].value) for row in wb["Sobre"].iter_rows())
    assert about["Ordem das peças"] == "por marca e número da peça"
    assert str(about["Coordenadas"]).startswith("não calculadas")


async def test_coordinates_of_other_versions_are_ignored(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    dbids = await _dbids(session, ctx)
    r = await _post(client, ctx, {"999999": [0, 0, 0], str(dbids[0]): [1, 2, 3]})
    assert r.status_code == 200, r.text
    rows = _rows(load_workbook(io.BytesIO(r.content))["Peças"])
    assert rows[0]["dbId"] == dbids[0] and 999999 not in [p["dbId"] for p in rows]


async def test_invalid_coordinates_are_rejected(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    for bad in ({"10": [1, 2]}, {"10": ["x", 0, 0]}, {"10": [1e9, 0, 0]}, {"abc": [0, 0, 0]}):
        r = await _post(client, ctx, bad)
        assert r.status_code == 422, (bad, r.text)


async def test_stored_centroids_are_used_without_browser_coordinates(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    """Centros já guardados (unit_sequence): o Excel sai com X/Y/Z sem recalcular."""
    dbids = await _dbids(session, ctx)
    for i, d in enumerate(dbids):
        el = await session.scalar(
            select(Element).where(Element.version_id == ctx["v"].id, Element.dbid == d)
        )
        assert el is not None
        el.centroid = [10.0 - i, 0.0, 0.0]
    await session.flush()
    r = await _post(client, ctx, None)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    order = {p["dbId"]: p["Ordem de montagem"] for p in _rows(wb["Peças"])}
    assert [order[d] for d in reversed(dbids)] == [1, 2, 3, 4, 5, 6]
    about = dict((row[0].value, row[1].value) for row in wb["Sobre"].iter_rows())
    assert "Z → X → Y" in str(about["Ordem das peças"])
