"""9.1 · GET /api/obras/{id}/export.xlsx: o arquivo tem as mesmas linhas e valores da tela.

"Tela" = as rotas que a tela usa: busca (mesmos filtros), status por marca e valores da
marca (GET .../values). Modelo `validacao`: PP001 = 10 (40x40), 11 (40x50) TÉRREO;
PP002 = 12, 13 (30x30, 1º PAVIMENTO); V-01 = 20 (TÉRREO), 21 (1º PAVIMENTO); 30 sem Marca.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps.client import ApsClient
from app.models import Mark, ModelVersion, Obra, ParamDef, User
from app.models.enums import Role
from app.services.processing import ProcessingConfig, process_version
from tests.apsfakes import Sleeps, mock_model, mock_token
from tests.conftest import as_user

CONFIG = ProcessingConfig(
    mark_names=["Marca"], category_names=["Category"], level_names=["Nível base"]
)
TZ = ZoneInfo("America/Sao_Paulo")
STATUS_PT = {
    "pending": "Pendente",
    "partial": "Parcial",
    "complete": "Completa",
    "review": "Revisar",
}


@pytest.fixture
async def ctx(
    session: AsyncSession,
    aps: ApsClient,
    sleeps: Sleeps,
    users: dict[Role, User],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    obra = Obra(code="OB-EXP 1", name="Obra exportação")
    session.add(obra)
    await session.flush()
    v = ModelVersion(obra_id=obra.id, acc_version_id="urn:exp:1", version_number=2, urn="dXJuZXhw")
    session.add(v)
    await session.flush()
    with respx.mock:
        mock_token()
        mock_model("validacao", "dXJuZXhw")
        assert (await process_version(session, aps, v.id, CONFIG, sleep=sleeps)).status == "ready"  # type: ignore[union-attr]
    d = {
        "forma": ParamDef(
            name="Tipo de forma",
            type="list",
            options=["F-11", "F-12"],
            required=True,
            categories=["Structural Columns"],
            scope="obra",
            obra_id=obra.id,
        ),
        "cura": ParamDef(
            name="Ciclo de cura", type="number", unit="h", scope="obra", obra_id=obra.id
        ),
        "data": ParamDef(name="Data de concretagem", type="date", scope="obra", obra_id=obra.id),
        "insert": ParamDef(name="Peça com insert", type="bool", scope="obra", obra_id=obra.id),
        "obs": ParamDef(
            name="Obs viga",
            type="text",
            categories=["Structural Framing"],
            scope="obra",
            obra_id=obra.id,
        ),
    }
    session.add_all(d.values())
    await session.flush()
    marks = {m.code: m for m in await session.scalars(select(Mark).where(Mark.obra_id == obra.id))}
    fab = as_user(users[Role.FABRICA])
    admin = as_user(users[Role.ADMIN])
    url = f"/api/obras/{obra.id}/marks"

    async def put(code: str, changes: list[tuple[str, Any]], headers: dict[str, str]) -> None:
        r = await client.put(
            f"{url}/{marks[code].id}/values",
            json={
                "changes": [
                    {"def_id": d[k].id, "value": val, "row_version": None} for k, val in changes
                ]
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text

    await put(
        "PP001",
        [("forma", "F-11"), ("cura", "12,5"), ("data", "2026-12-20"), ("insert", True)],
        fab,
    )
    await put("PP002", [("cura", "8")], admin)
    await put("V-01", [("obs", "içar com cuidado")], fab)
    return {"obra": obra, "v": v, "d": d, "marks": marks, "fab": fab, "users": users}


async def _export(
    client: httpx.AsyncClient, ctx: dict[str, Any], **params: Any
) -> tuple[httpx.Response, Any]:
    r = await client.get(
        f"/api/obras/{ctx['obra'].id}/export.xlsx", params=params, headers=ctx["fab"]
    )
    assert r.status_code == 200, r.text
    return r, load_workbook(io.BytesIO(r.content))


def _rows(ws: Worksheet) -> list[dict[str, Any]]:
    values = list(ws.iter_rows(values_only=True))
    header = [str(h) for h in values[0]]
    return [dict(zip(header, row, strict=True)) for row in values[1:]]


async def _screen(client: httpx.AsyncClient, ctx: dict[str, Any], **params: Any) -> dict[str, Any]:
    """O que a tela mostra: busca + status + valores de cada marca."""
    vid = ctx["v"].id
    search = (
        await client.get(
            f"/api/versions/{vid}/marks/search",
            params={**params, "page_size": 500},
            headers=ctx["fab"],
        )
    ).json()
    status = (await client.get(f"/api/versions/{vid}/marks/status", headers=ctx["fab"])).json()
    st = {i["mark_id"]: i["status"] for i in status["items"]}
    values = {}
    for item in search["items"]:
        values[item["code"]] = (
            await client.get(
                f"/api/obras/{ctx['obra'].id}/marks/{item['mark_id']}/values", headers=ctx["fab"]
            )
        ).json()
    return {"search": search, "status": st, "values": values}


def _expected_cell(field: dict[str, Any]) -> Any:
    v = field["value"]
    if v is None:
        return None
    if field["type"] == "date":
        return datetime.fromisoformat(v)  # openpyxl lê data do Excel como datetime
    if field["type"] == "bool":
        return "Sim" if v else "Não"
    return v


async def test_same_rows_and_values_as_the_screen(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r, wb = await _export(client, ctx)
    screen = await _screen(client, ctx)
    rows = _rows(wb["Marcas"])
    items = screen["search"]["items"]
    assert len(rows) == screen["search"]["total_marks"] == 3
    assert [(row["Marca"], row["Categoria"], row["Peças"]) for row in rows] == [
        (i["code"], i["category"], i["count"]) for i in items
    ]
    for row, item in zip(rows, items, strict=True):
        assert row["Status"] == STATUS_PT[screen["status"][item["mark_id"]]]
        mv = screen["values"][item["code"]]
        shown = {
            (f"{f['name']} ({f['unit']})" if f["unit"] else f["name"]): _expected_cell(f)
            for f in mv["values"]
        }
        for header, value in shown.items():
            assert row[header] == value, (item["code"], header)
        assert row["Autor"] == mv["last_change_by"]
        at = datetime.fromisoformat(mv["last_change_at"]).astimezone(TZ).replace(tzinfo=None)
        assert abs((row["Última alteração"] - at).total_seconds()) < 1
    # peças: as mesmas da tela (dbids do resultado)
    pieces = _rows(wb["Peças"])
    assert sorted(p["dbId"] for p in pieces) == screen["search"]["dbids"]
    assert r.headers["x-export-marks"] == "3" and r.headers["x-export-pieces"] == "6"


async def test_filters_are_the_same_as_the_search(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    for params in (
        {"q": "pp"},
        {"level": "TÉRREO"},
        {"category": "Structural Framing"},
        {"missing": "Tipo de forma"},
        {"shortcut": "partial"},
        {"q": "pp", "order": "desc"},
        {"prop": "Altura=50.0 cm"},
    ):
        _, wb = await _export(client, ctx, **params)
        search = (await _screen(client, ctx, **params))["search"]
        rows = _rows(wb["Marcas"])
        assert [(r["Marca"], r["Peças"]) for r in rows] == [
            (i["code"], i["count"]) for i in search["items"]
        ], params
        assert sorted(p["dbId"] for p in _rows(wb["Peças"])) == search["dbids"], params
    # nível filtra PEÇAS: o PP002 (1º PAVIMENTO) some e a V-01 vem com 1 peça
    _, wb = await _export(client, ctx, level="TÉRREO")
    assert [(r["Marca"], r["Peças"]) for r in _rows(wb["Marcas"])] == [("PP001", 2), ("V-01", 1)]


async def test_types_formats_section_and_layout(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    r, wb = await _export(client, ctx)
    ws = wb["Marcas"]
    header = [c.value for c in ws[1]]
    assert header == [
        "Marca",
        "Categoria",
        "Peças",
        "Seção",
        "Comprimento (cm)",
        "Status",
        "Ciclo de cura (h)",
        "Data de concretagem",
        "Obs viga",
        "Peça com insert",
        "Tipo de forma",
        "Última alteração",
        "Autor",
    ]
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == ws.dimensions
    assert wb["Peças"].freeze_panes == "A2" and wb["Peças"].auto_filter.ref
    rows = {row[0].value: row for row in ws.iter_rows(min_row=2)}
    pp1, pp2, v01 = rows["PP001"], rows["PP002"], rows["V-01"]
    col = {h: i for i, h in enumerate(header)}
    assert pp1[col["Seção"]].value == "40x40 / 40x50"  # peças divergentes: as duas
    assert pp2[col["Seção"]].value == "30x30"
    # comprimento como NÚMERO (cm); 600.0 cm e 600.3 cm → texto com os dois
    assert (
        v01[col["Comprimento (cm)"]].value == 600 and v01[col["Comprimento (cm)"]].data_type == "n"
    )
    assert pp2[col["Comprimento (cm)"]].value == "600 / 600,3"
    cura = pp1[col["Ciclo de cura (h)"]]
    assert cura.value == 12.5 and cura.data_type == "n"
    data = pp1[col["Data de concretagem"]]
    assert data.value == datetime(2026, 12, 20) and data.number_format == "dd/mm/yyyy"
    assert pp1[col["Peça com insert"]].value == "Sim"
    assert pp1[col["Última alteração"]].number_format == "dd/mm/yyyy hh:mm"
    # não se aplica: vazio e cinza (Tipo de forma é só de pilar; Obs viga, só de viga)
    na = v01[col["Tipo de forma"]]
    assert na.value is None and na.fill.fgColor.rgb.endswith("EEEEEE")
    assert pp1[col["Obs viga"]].value is None and pp1[col["Obs viga"]].fill.fgColor.rgb.endswith(
        "EEEEEE"
    )
    assert v01[col["Obs viga"]].value == "içar com cuidado"
    assert pp2[col["Autor"]].value == ctx["users"][Role.ADMIN].name
    # peças: nível e externalId
    pieces = {p["dbId"]: p for p in _rows(wb["Peças"])}
    assert pieces[10] == {
        "Marca": "PP001",
        "Categoria": "Structural Columns",
        "externalId": "val-0010",
        "Nível": "TÉRREO",
        "dbId": 10,
    }
    assert 30 not in pieces  # sem Marca
    about = dict((r[0].value, r[1].value) for r in wb["Sobre"].iter_rows())
    assert about["Versão"] == "Rev.02" and about["Marcas"] == 3 and about["Peças"] == 6
    assert about["Gerado por"] == ctx["users"][Role.FABRICA].name
    disposition = r.headers["content-disposition"]
    assert disposition.startswith(
        'attachment; filename="OB-EXP-1_Rev.02_'
    ) and disposition.endswith(".xlsx")
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")


async def test_version_choice_permissions_and_errors(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    url = f"/api/obras/{ctx['obra'].id}/export.xlsx"
    leitura = as_user(ctx["users"][Role.LEITURA])
    r = await client.get(url, params={"version_id": ctx["v"].id}, headers=leitura)
    assert r.status_code == 200  # todos os papéis exportam
    assert (await client.get(url)).status_code == 401
    other = Obra(code="OB-EXP2", name="Outra")
    session.add(other)
    await session.flush()
    r = await client.get(f"/api/obras/{other.id}/export.xlsx", headers=leitura)
    assert r.status_code == 404 and "versão pronta" in r.json()["detail"]
    r = await client.get(
        f"/api/obras/{other.id}/export.xlsx", params={"version_id": ctx["v"].id}, headers=leitura
    )
    assert r.status_code == 404  # versão de outra obra
    r = await client.get(url, params={"prop": "sem-igual"}, headers=leitura)
    assert r.status_code == 422
