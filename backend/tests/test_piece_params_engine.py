"""P3: parâmetros POR PEÇA no motor de filtros, nas cores, no status/progresso e no Excel.

Obra com PP001 (Pilar, 3 peças) e V01 (Viga, 2 peças). Parâmetros por peça:
"Data de fabricação" (data, OBRIGATÓRIO, todas as categorias) e "Obs. da viga" (texto,
só Viga). A PP001-1 e a PP001-2 recebem data; a PP001-3 e as vigas ficam vazias.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion, Obra, ParamDef, PieceUnit, User
from app.models.enums import Role
from app.services import colors, filters, piece_props, piece_units
from app.services.export import NA_FILL
from tests.conftest import as_user

TODAY = date(2026, 11, 16)


async def _version(
    session: AsyncSession, obra: Obra, number: int, pieces: list[tuple[int, str, Mark]]
) -> ModelVersion:
    v = ModelVersion(
        obra_id=obra.id, acc_version_id=f"urn:pe:{obra.id}:{number}", version_number=number
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
                member_dbids=[dbid * 100],
            )
        )
    await session.flush()
    await piece_units.link_version(session, v)
    v.status = "ready"
    await session.flush()
    await piece_props.build_version(session, v.id)
    return v


@pytest.fixture
async def ctx(
    session: AsyncSession, users: dict[Role, User], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    monkeypatch.setattr(filters, "today", lambda _tz: TODAY)
    obra = Obra(code="OB-PE", name="Obra motor por peça", acc_item_name="pe.rvt")
    session.add(obra)
    await session.flush()
    pp = Mark(obra_id=obra.id, code="PP001", category="Pilar")
    vg = Mark(obra_id=obra.id, code="V01", category="Viga")
    session.add_all([pp, vg])
    await session.flush()
    pieces = [(10, "a", pp), (11, "b", pp), (12, "c", pp), (20, "v1", vg), (21, "v2", vg)]
    v1 = await _version(session, obra, 1, pieces)
    # v2: os mesmos elementos com outros dbIds (o valor acompanha a unidade, não o dbId)
    v2 = await _version(session, obra, 2, [(d + 100, e, m) for d, e, m in pieces])
    fab = ParamDef(
        name="Data de fabricação", type="date", scope="obra", obra_id=obra.id, required=True
    )
    fab.level = "piece"
    obs = ParamDef(
        name="Obs. da viga", type="text", scope="obra", obra_id=obra.id, categories=["Viga"]
    )
    obs.level = "piece"
    session.add_all([fab, obs])
    await session.flush()
    await piece_props.sync_factory(session, obra.id)
    units = {
        f"{m.code}-{u.number}": u
        for m in (pp, vg)
        for u in await session.scalars(select(PieceUnit).where(PieceUnit.mark_id == m.id))
    }
    c = {
        "obra": obra,
        "pp": pp,
        "vg": vg,
        "v1": v1,
        "v2": v2,
        "fab": fab,
        "obs": obs,
        "u": units,
        "h": as_user(users[Role.FABRICA]),
    }
    return c


async def _put(client: httpx.AsyncClient, ctx: dict[str, Any], unit: str, value: Any) -> None:
    r = await client.put(
        f"/api/obras/{ctx['obra'].id}/units/{ctx['u'][unit].id}/values",
        json={"changes": [{"def_id": ctx["fab"].id, "value": value, "row_version": None}]},
        headers=ctx["h"],
    )
    assert r.status_code == 200, r.text


async def _filled(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    await _put(client, ctx, "PP001-1", "2026-11-10")
    await _put(client, ctx, "PP001-2", "2026-10-02")


def _rule(ctx: dict[str, Any], op: str, value: Any = None) -> dict[str, Any]:
    return {"field": {"source": "factory", "key": str(ctx["fab"].id)}, "op": op, "value": value}


async def _evaluate(
    client: httpx.AsyncClient, ctx: dict[str, Any], version: str, rules: list[dict[str, Any]]
) -> dict[str, Any]:
    r = await client.post(
        f"/api/versions/{ctx[version].id}/filter/evaluate",
        json={"mode": "isolate", "rules": rules},
        headers=ctx["h"],
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


async def test_field_is_listed_with_piece_counts(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    await _filled(client, ctx)
    r = await client.get(f"/api/versions/{ctx['v2'].id}/fields", headers=ctx["h"])
    fields = {(f["source"], f["key"]): f for f in r.json()}
    f = fields[("factory", str(ctx["fab"].id))]
    assert (f["name"], f["group"], f["type"], f["pieces"], f["distinct_values"]) == (
        "Data de fabricação",
        "Fábrica",
        "date",
        2,
        2,
    )
    values = await client.get(
        f"/api/versions/{ctx['v2'].id}/fields/factory/{ctx['fab'].id}/values", headers=ctx["h"]
    )
    assert sorted((v["value"], v["pieces"]) for v in values.json()) == [
        ("2026-10-02", 1),
        ("2026-11-10", 1),
    ]


async def test_filter_matches_only_the_filled_pieces(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    await _filled(client, ctx)
    filled = await _evaluate(client, ctx, "v2", [_rule(ctx, "not_empty")])
    assert [p["dbid"] for p in filled["pieces"]] == [110, 111]  # PP001-1 e PP001-2, não a -3
    assert [(g["code"], g["matched"], g["total"]) for g in filled["groups"]] == [("PP001", 2, 3)]
    month = await _evaluate(client, ctx, "v2", [_rule(ctx, "this_month")])
    assert [p["dbid"] for p in month["pieces"]] == [110]
    empty = await _evaluate(client, ctx, "v2", [_rule(ctx, "empty")])
    assert [p["dbid"] for p in empty["pieces"]] == [112, 120, 121]
    # na versão anterior, os elementos dela (o valor está na unidade, não no dbId)
    old = await _evaluate(client, ctx, "v1", [_rule(ctx, "not_empty")])
    assert [p["dbid"] for p in old["pieces"]] == [10, 11]


async def test_colorize_legend_counts_pieces(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    await _filled(client, ctx)
    field = {"source": "factory", "key": str(ctx["fab"].id)}
    r = await client.post(
        f"/api/versions/{ctx['v2'].id}/colorize",
        json={"field": field, "mode": "distinct"},
        headers=ctx["h"],
    )
    assert r.status_code == 200, r.text
    legend = [(i["label"], i["pieces"], i["dbids"]) for i in r.json()["legend"]]
    assert sorted(legend[:2]) == [("2026-10-02", 1, [111]), ("2026-11-10", 1, [110])]
    assert legend[2] == ("Sem valor", 3, [112, 120, 121])
    c = r.json()["colors"]
    assert c["110"] == c["11000"] == colors.stable_color("2026-11-10")  # peça e membros

    ranged = await client.post(
        f"/api/versions/{ctx['v2'].id}/colorize",
        json={"field": field, "mode": "range"},
        headers=ctx["h"],
    )
    bands = ranged.json()["legend"]
    assert bands[0]["min"] == "2026-10-02" and bands[0]["dbids"] == [111]
    assert bands[-1] == bands[-1] | {"label": "Sem valor", "pieces": 3}

    # esquema de cores com um filtro inline no parâmetro por peça
    scheme = await client.post(
        f"/api/versions/{ctx['v2'].id}/color-scheme/evaluate",
        json={
            "rules": [
                {
                    "filter": {"mode": "isolate", "rules": [_rule(ctx, "not_empty")]},
                    "color": "#FF0000",
                    "label": "Fabricadas",
                }
            ]
        },
        headers=ctx["h"],
    )
    rule = scheme.json()["rules"][0]
    assert (rule["pieces"], rule["dbids"]) == (2, [110, 111])


async def _status(client: httpx.AsyncClient, ctx: dict[str, Any]) -> dict[int, str]:
    r = await client.get(f"/api/versions/{ctx['v2'].id}/marks/status", headers=ctx["h"])
    return {i["mark_id"]: i["status"] for i in r.json()["items"]}


async def test_status_and_progress_count_piece_by_piece(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    pp, vg = ctx["pp"].id, ctx["vg"].id
    assert await _status(client, ctx) == {pp: "pending", vg: "pending"}
    await _filled(client, ctx)
    # 2 de 3 unidades preenchidas: a marca fica PARCIAL
    assert await _status(client, ctx) == {pp: "partial", vg: "pending"}
    progress = (await client.get(f"/api/versions/{ctx['v2'].id}/progress", headers=ctx["h"])).json()
    [req] = progress["required"]
    assert (req["name"], req["level"]) == ("Data de fabricação", "piece")
    assert (req["marks_total"], req["marks_filled"], req["pieces_total"], req["pieces_filled"]) == (
        2,
        0,
        5,
        2,
    )

    # status POR PEÇA no motor: as 2 preenchidas ficam Completa e a 3ª continua Pendente
    # (a marca, agregada, é que fica Parcial); preencher uma peça não muda as outras.
    async def pieces_with(label: str) -> list[int]:
        rule = {"field": {"source": "system", "key": "status"}, "op": "eq", "value": label}
        return [p["dbid"] for p in (await _evaluate(client, ctx, "v2", [rule]))["pieces"]]

    assert await pieces_with("Completa") == [110, 111]
    assert await pieces_with("Pendente") == [112, 120, 121]
    assert await pieces_with("Parcial") == []
    counts = (
        await client.get(f"/api/versions/{ctx['v2'].id}/marks/status", headers=ctx["h"])
    ).json()["counts"]
    by = {c["status"]: (c["marks"], c["pieces"]) for c in counts}
    assert by["partial"] == (1, 0) and by["complete"] == (0, 2) and by["pending"] == (1, 3)

    await _put(client, ctx, "PP001-3", "2026-11-12")
    assert await _status(client, ctx) == {pp: "complete", vg: "pending"}
    [req] = (await client.get(f"/api/versions/{ctx['v2'].id}/progress", headers=ctx["h"])).json()[
        "required"
    ]
    assert (req["marks_filled"], req["pieces_filled"]) == (1, 3)

    # lote nas vigas e desfazer: status e motor acompanham
    r = await client.post(
        f"/api/obras/{ctx['obra'].id}/units/batch-apply",
        json={
            "unit_ids": [ctx["u"]["V01-1"].id, ctx["u"]["V01-2"].id],
            "changes": {ctx["fab"].id: "2026-11-14"},
        },
        headers=ctx["h"],
    )
    assert await _status(client, ctx) == {pp: "complete", vg: "complete"}
    undo = await client.post(f"/api/batches/{r.json()['batch_id']}/undo", headers=ctx["h"])
    assert undo.status_code == 200
    assert await _status(client, ctx) == {pp: "complete", vg: "pending"}
    empty = await _evaluate(client, ctx, "v2", [_rule(ctx, "empty")])
    assert [p["dbid"] for p in empty["pieces"]] == [120, 121]


async def test_excel_pieces_sheet_has_unit_and_piece_params(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    await _filled(client, ctx)
    r = await client.post(
        f"/api/obras/{ctx['obra'].id}/export.xlsx",
        json={"version_id": ctx["v2"].id},
        headers=ctx["h"],
    )
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    marks_header = [c.value for c in next(wb["Marcas"].iter_rows(max_row=1))]
    assert "Data de fabricação" not in marks_header  # parâmetro por peça não vai por marca
    ws = wb["Peças"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    assert header == [
        "Marca",
        "Categoria",
        "externalId",
        "Nível",
        "dbId",
        "Peça",
        "Data de fabricação",
        "Obs. da viga",
    ]
    by_unit = {row[5]: row for row in rows[1:]}
    assert set(by_unit) == {"PP001-1", "PP001-2", "PP001-3", "V01-1", "V01-2"}
    assert by_unit["PP001-1"][6] == datetime(2026, 11, 10)
    assert by_unit["PP001-3"][6] is None
    # célula do parâmetro que não vale para a categoria: cinza
    pilar_row = next(i for i, row in enumerate(rows) if row[5] == "PP001-1") + 1
    assert ws.cell(row=pilar_row, column=8).fill.fgColor.rgb == NA_FILL.fgColor.rgb
    viga_row = next(i for i, row in enumerate(rows) if row[5] == "V01-1") + 1
    assert ws.cell(row=viga_row, column=8).fill.fgColor.rgb != NA_FILL.fgColor.rgb
    assert ws.cell(row=pilar_row, column=7).number_format == "dd/mm/yyyy"
