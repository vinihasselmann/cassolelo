"""Importar a planilha do Plannix (2026-11-24).

A planilha de cada teste imita a exportação real (plannix/tabela.xlsx): uma linha por
peça física, "Código" único, "Peça" com o sufixo das lajes, "Seq." em texto ou convertida
em data pelo Excel e as peças recusadas com "Status de Projeto" vazio.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    ObraParam,
    ParamDef,
    PieceUnit,
    PieceValue,
    User,
)
from app.models.enums import Role
from app.services import export, piece_units
from app.services.plannix_import import STAGES, mark_code, parse_seq
from tests.conftest import as_user

XLSX = export.XLSX
HEADER = [
    "Código",
    "Peça",
    "Obra",
    "Sigla",
    "Seq.",
    "Status de Projeto",
    "Data CD",
    "Status CD",
    "Data AR",
    "Data FO",
    "Data FA",
    "Data CO",
    "Data Aca",
]
NAMES = [name for _, name in STAGES]
LAJE = "LA3008-LP15 7X9,5-75%-125"


# --------------------------------------------------------------------------- funções puras


@pytest.mark.parametrize(
    ("value", "fmt", "expected"),
    [
        ("13/20", "General", (13, 20)),
        (" 2 / 3 ", "General", (2, 3)),
        (datetime(2026, 2, 1), "d-mmm", (1, 2)),  # "1/2" virou 01/fev
        (datetime(2026, 1, 1), "d-mmm", (1, 1)),
        (datetime(1936, 12, 1), "mmm-yy", (12, 36)),  # "12/36" virou dez/1936
        (datetime(2020, 1, 1), "mmm-yy", (1, 20)),
        ("abc", "General", None),
        ("0/3", "General", None),
        (None, "General", None),
    ],
)
def test_parse_seq_undoes_excel_dates(value: Any, fmt: str, expected: Any) -> None:
    assert parse_seq(value, fmt) == expected


def test_mark_code_is_the_longest_prefix_in_the_model() -> None:
    model = {"LA3008", "P-06", "PP301"}
    assert mark_code(LAJE, model) == "LA3008"
    assert mark_code(f"{LAJE} /R", model) == "LA3008"
    assert mark_code(" PP301 ", model) == "PP301"
    assert mark_code("P-06", model) == "P-06"  # marca com hífen
    assert mark_code("p-06", model) == "P-06"  # maiúsculas, como marks.code
    assert mark_code("VA3099-X 1", model) == "VA3099"  # fora do modelo: o mais curto


# --------------------------------------------------------------------------- cenário


async def _version(
    session: AsyncSession, obra: Obra, pieces: list[tuple[int, str, Mark]]
) -> ModelVersion:
    v = ModelVersion(obra_id=obra.id, acc_version_id=f"urn:px:{obra.id}", version_number=1)
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
                name=f"{mark.code} {ext}",
            )
        )
    await session.flush()
    await piece_units.link_version(session, v)
    v.status = "ready"
    await session.flush()
    return v


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    """Obra 9480: PP301 ×3, LA3008 ×2, VA3014 ×1 (o Plannix tem 2)."""
    obra = Obra(code="9480", name="Garden Park", acc_item_name="9480.rvt")
    session.add(obra)
    await session.flush()
    marks = {
        code: Mark(obra_id=obra.id, code=code, category=cat)
        for code, cat in (
            ("PP301", "Pilares estruturais"),
            ("LA3008", "Quadro estrutural"),
            ("VA3014", "Quadro estrutural"),
        )
    }
    session.add_all(marks.values())
    await session.flush()
    pieces = [(1, "pp-a", marks["PP301"]), (2, "pp-b", marks["PP301"]), (3, "pp-c", marks["PP301"])]
    pieces += [(4, "la-a", marks["LA3008"]), (5, "la-b", marks["LA3008"])]
    pieces += [(6, "va-a", marks["VA3014"])]
    await _version(session, obra, pieces)
    units = {
        f"{m.code}-{u.number}": u
        for m in marks.values()
        for u in await session.scalars(select(PieceUnit).where(PieceUnit.mark_id == m.id))
    }
    return {"obra": obra, "marks": marks, "units": units, "users": users}


def _row(
    code: int,
    piece: str,
    seq: Any,
    *,
    status: str | None = "Liberado",
    sigla: Any = 9480,
    **dates: Any,
) -> list[Any]:
    """Linha do Plannix. `dates`: cd, ar, fo, fa, co, aca."""
    return [
        code,
        piece,
        "GARDEN PARK FG - B. CAMBORIU/SC",
        sigla,
        seq,
        status,
        dates.get("cd"),
        "Liberado" if dates.get("cd") else None,
        dates.get("ar"),
        dates.get("fo"),
        dates.get("fa"),
        dates.get("co"),
        dates.get("aca"),
    ]


D1, D2, D3 = datetime(2026, 11, 10), datetime(2026, 11, 11), datetime(2026, 11, 12)


def _rows() -> list[list[Any]]:
    return [
        # Seq. "1/3" convertida pelo Excel em 01/mar (formato dia/mês)
        _row(1001, "PP301", datetime(2026, 3, 1), cd=D1, ar=D1, co=D2),
        _row(1002, "PP301", "2/3", cd=D1, co="05/11/2026"),
        _row(1003, "PP301", datetime(2026, 3, 3)),  # ainda sem datas
        _row(2001, LAJE, datetime(2026, 2, 1), cd=D3),
        _row(2099, f"{LAJE} /R", "1/2", status=None, cd=D1),  # recusada: fica de fora
        _row(2002, LAJE, "2/2", cd=D3, aca=D3),
        _row(3001, "VA3014", "1/2", fo=D2),
        _row(3002, "VA3014", "2/2", fo=D2),  # o modelo só tem 1: sobra
        _row(4001, "VA3099", "1/1", cd=D1),  # não está no modelo
    ]


def _file(rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws: Any = wb.active
    ws.title = "Planilha1"
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2):
        seq = row[HEADER.index("Seq.")]
        if isinstance(seq.value, datetime):
            seq.number_format = "d-mmm" if seq.value.year == 2026 else "mmm-yy"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _url(ctx: dict[str, Any], step: str) -> str:
    return f"/api/obras/{ctx['obra'].id}/import-xlsx/{step}"


async def _preview(
    client: httpx.AsyncClient, ctx: dict[str, Any], content: bytes, status: int = 200
) -> Any:
    r = await client.post(
        _url(ctx, "preview"),
        content=content,
        headers={**as_user(ctx["users"][Role.FABRICA]), "Content-Type": XLSX},
    )
    assert r.status_code == status, r.text
    return r.json()


async def _apply(client: httpx.AsyncClient, ctx: dict[str, Any], content: bytes) -> Any:
    p = await _preview(client, ctx, content)
    r = await client.post(
        _url(ctx, "apply"),
        params={"fingerprint": p["fingerprint"]},
        content=content,
        headers={**as_user(ctx["users"][Role.FABRICA]), "Content-Type": XLSX},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _params(session: AsyncSession) -> dict[str, ParamDef]:
    return {
        p.name: p
        for p in await session.scalars(select(ParamDef).where(ParamDef.source == "plannix"))
    }


async def _values(session: AsyncSession, ctx: dict[str, Any]) -> dict[tuple[str, str], Any]:
    params = {p.id: p.name for p in (await _params(session)).values()}
    labels = {u.id: label for label, u in ctx["units"].items()}
    out = {}
    for v in await session.scalars(select(PieceValue).where(PieceValue.def_id.in_(params))):
        if v.value is not None:
            out[(labels[v.unit_id], params[v.def_id])] = v.value
    return out


# --------------------------------------------------------------------------- testes


async def test_preview_links_by_seq_and_reports_what_is_off(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    p = await _preview(client, ctx, _file(_rows()))
    px = p["plannix"]
    assert px == {
        "rows": 8,
        "rejected": 1,
        "linked": 6,  # PP301 ×3, LA3008 ×2, VA3014 1/2
        "new_links": 6,
        "leftovers": 1,  # VA3014 2/2
        "new_params": NAMES,
        "check_marks": [{"code": "VA3014", "plannix": 2, "model": 1}],
        "outside_model": [{"code": "VA3099", "rows": 1}],
    }
    assert p["errors"] == []
    assert sorted(w["message"] for w in p["warnings"]) == [
        "Conferir VA3014: 2 no Plannix, 1 no modelo.",
        "VA3014 2/2: o modelo tem 1 peças; ficou sem peça.",
    ]
    # PP301-1: CD, AR, CO · PP301-2: CD, CO · LA3008-1: CD · LA3008-2: CD, Aca · VA3014-1: FO
    assert (p["fills"], p["changes"], p["clears"]) == (9, 0, 0)
    assert {(i["target"], i["param"], i["new"]) for i in p["fill_items"]} >= {
        ("PP301-1", "Armação", "2026-11-10"),
        ("PP301-2", "Concretagem", "2026-11-05"),  # texto dd/mm/aaaa
        ("LA3008-2", "Acabamento", "2026-11-12"),
    }
    assert [s["name"] for s in p["params"]] == [
        "Corte e dobra",
        "Armação",
        "Forma",
        "Concretagem",
        "Acabamento",
    ]
    # a prévia não grava nada
    assert await _params(session) == {}
    assert all(u.plannix_code is None for u in ctx["units"].values())


async def test_apply_creates_params_links_codes_and_writes_dates(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    body = await _apply(client, ctx, _file(_rows()))
    assert (body["units_changed"], body["fields_changed"], body["skipped_changes"]) == (5, 9, 0)

    params = await _params(session)
    assert sorted(params) == sorted(NAMES)
    assert {(p.level, p.type, p.scope, p.required) for p in params.values()} == {
        ("piece", "date", "global", True)  # obrigatórias: contam no status
    }
    included = set(
        await session.scalars(select(ObraParam.def_id).where(ObraParam.obra_id == ctx["obra"].id))
    )
    assert {p.id for p in params.values()} <= included

    for u in ctx["units"].values():
        await session.refresh(u)
    codes = {label: u.plannix_code for label, u in ctx["units"].items()}
    assert codes == {
        "PP301-1": "1001",
        "PP301-2": "1002",
        "PP301-3": "1003",
        "LA3008-1": "2001",
        "LA3008-2": "2002",
        "VA3014-1": "3001",
    }
    values = await _values(session, ctx)
    assert values[("PP301-1", "Concretagem")] == "2026-11-11"
    assert values[("LA3008-1", "Corte e dobra")] == "2026-11-12"  # não a da recusada
    assert len(values) == 9

    log = list(await session.scalars(select(AuditLog).where(AuditLog.batch_id == body["batch_id"])))
    assert {e.entity for e in log} == {"piece_value", "piece_unit"}
    assert all(e.after and e.after["source"] == "plannix" for e in log)


async def test_next_import_follows_the_code_overwrites_and_clears(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _apply(client, ctx, _file(_rows()))
    rows = _rows()
    # no Plannix a Seq. das duas primeiras trocou: o Código manda
    rows[0] = _row(1001, "PP301", "2/3", cd=D1, ar=D1, co=D3)  # CO mudou
    rows[1] = _row(1002, "PP301", "1/3", cd=None, co="05/11/2026")  # CD apagado
    p = await _preview(client, ctx, _file(rows))
    assert p["plannix"]["new_links"] == 0
    assert (p["fills"], p["changes"], p["clears"]) == (0, 2, 1)
    assert {(i["target"], i["param"], i["old"], i["new"]) for i in p["change_items"]} == {
        ("PP301-1", "Concretagem", "2026-11-11", "2026-11-12"),
        ("PP301-2", "Corte e dobra", "2026-11-10", None),
    }
    body = await _apply(client, ctx, _file(rows))
    assert body["fields_changed"] == 2
    values = await _values(session, ctx)
    assert values[("PP301-1", "Concretagem")] == "2026-11-12"
    assert ("PP301-2", "Corte e dobra") not in values

    # Desfazer devolve o que havia
    r = await client.post(
        f"/api/batches/{body['batch_id']}/undo", headers=as_user(ctx["users"][Role.FABRICA])
    )
    assert r.status_code == 200, r.text
    values = await _values(session, ctx)
    assert values[("PP301-1", "Concretagem")] == "2026-11-11"
    assert values[("PP301-2", "Corte e dobra")] == "2026-11-10"


async def test_unit_taken_by_another_code_is_left_out(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _apply(client, ctx, _file(_rows()))
    rows = _rows()
    rows[2] = _row(1009, "PP301", "3/3", cd=D1)  # peça nova no Plannix na vaga de 1003
    p = await _preview(client, ctx, _file(rows))
    assert "PP301 3/3: PP301-3 já está ligada a outra linha (Código 1003)." in [
        w["message"] for w in p["warnings"]
    ]
    assert p["plannix"]["new_links"] == 0


async def test_plannix_params_are_read_only_on_screen(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _apply(client, ctx, _file(_rows()))
    params = await _params(session)
    unit = ctx["units"]["PP301-3"]
    headers = as_user(ctx["users"][Role.FABRICA])
    r = await client.put(
        f"/api/obras/{ctx['obra'].id}/units/{unit.id}/values",
        json={"changes": [{"def_id": params["Forma"].id, "value": "2026-11-20"}]},
        headers=headers,
    )
    assert r.status_code == 422
    assert "Forma é preenchido pelo Plannix" in r.text
    r = await client.post(
        f"/api/obras/{ctx['obra'].id}/units/batch-apply",
        json={"unit_ids": [unit.id], "changes": {str(params["Forma"].id): "2026-11-20"}},
        headers=headers,
    )
    assert r.status_code == 422
    # e a tela sabe que é do Plannix
    r = await client.get(f"/api/obras/{ctx['obra'].id}/units/{unit.id}", headers=headers)
    body = r.json()
    assert {p["name"]: p["source"] for p in body["params"]}["Forma"] == "plannix"
    assert body["unit"]["plannix_code"] == "1003"


async def test_wrong_obra_and_mixed_obras_are_refused(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    other = [_row(1001, "PP301", "1/3", sigla=9121, cd=D1)]
    p = await _preview(client, ctx, _file(other), status=422)
    assert "é da obra 9121, não da 9480" in p["detail"]
    mixed = [*_rows(), _row(9001, "PP101", "1/1", sigla=9121)]
    p = await _preview(client, ctx, _file(mixed), status=422)
    assert "outras obras (Sigla 9121)" in p["detail"]


async def test_manual_param_with_the_same_name_blocks_the_import(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    session.add(ParamDef(name="concretagem", type="date", scope="global", level="piece"))
    await session.flush()
    p = await _preview(client, ctx, _file(_rows()), status=422)
    assert 'Já existe o parâmetro "concretagem" criado à mão (na biblioteca)' in p["detail"]


async def test_bad_seq_and_bad_date_are_listed(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> None:
    rows = _rows()
    rows[0] = _row(1001, "PP301", "x", cd=D1)
    rows[1] = _row(1002, "PP301", "2/3", co="31/02/2026")
    p = await _preview(client, ctx, _file(rows))
    messages = sorted(e["message"] for e in p["errors"])
    assert messages == [
        "PP301-2 · Concretagem: Data inválida: use dd/mm/aaaa",
        "PP301: Seq. inválida (use n/total, ex.: 13/20).",
    ]


async def test_leitura_cannot_import(client: httpx.AsyncClient, ctx: dict[str, Any]) -> None:
    r = await client.post(
        _url(ctx, "preview"),
        content=_file(_rows()),
        headers={**as_user(ctx["users"][Role.LEITURA]), "Content-Type": XLSX},
    )
    assert r.status_code == 403


async def test_stage_dates_are_required_and_drive_the_piece_status(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    """As 6 datas são obrigatórias: só a peça com todas fica Completa."""
    from app.services.mark_status import MarkStatus, version_statuses

    rows = _rows()
    rows[2] = _row(1003, "PP301", "3/3", cd=D1, ar=D1, fo=D1, fa=D1, co=D1, aca=D1)
    await _apply(client, ctx, _file(rows))
    version = await session.scalar(
        select(ModelVersion).where(ModelVersion.obra_id == ctx["obra"].id)
    )
    assert version is not None
    result = await version_statuses(session, version.id)
    element_of = {
        e.external_id: e.id
        for e in await session.scalars(select(Element).where(Element.version_id == version.id))
    }

    def status(label: str) -> MarkStatus:
        return result.piece_statuses[element_of[ctx["units"][label].external_id]]

    assert status("PP301-3") is MarkStatus.COMPLETE
    assert status("PP301-1") is MarkStatus.PARTIAL  # 3 das 6
    assert status("VA3014-1") is MarkStatus.PARTIAL  # só Forma


async def test_plannix_param_keeps_its_name_but_required_can_change(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    await _apply(client, ctx, _file(_rows()))
    forma = (await _params(session))["Forma"]
    headers = as_user(ctx["users"][Role.FABRICA])
    r = await client.patch(f"/api/param-defs/{forma.id}", json={"name": "Fôrma"}, headers=headers)
    assert r.status_code == 422
    assert "O nome de “Forma” não pode mudar: é um parâmetro do Plannix" in r.json()["detail"]
    r = await client.patch(f"/api/param-defs/{forma.id}", json={"required": False}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["required"] is False and r.json()["source"] == "plannix"
