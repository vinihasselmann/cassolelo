"""Importar valores pelo Excel (2026-11-19).

Cada teste parte do Excel EXPORTADO pelo app (export.build_workbook), edita como a fábrica
faria (openpyxl) e envia de volta: prévia (nada gravado) e aplicação (um lote só).
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Element,
    Mark,
    ModelVersion,
    Obra,
    ParamDef,
    ParamValue,
    PieceUnit,
    PieceValue,
    User,
)
from app.models.enums import Role
from app.services import export, piece_units, search
from tests.conftest import as_user

XLSX = export.XLSX


async def _version(
    session: AsyncSession, obra: Obra, pieces: list[tuple[int, str, Mark]]
) -> ModelVersion:
    v = ModelVersion(obra_id=obra.id, acc_version_id=f"urn:xi:{obra.id}", version_number=1)
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


def _param(obra: Obra, name: str, ptype: str, level: str = "mark", **kw: Any) -> ParamDef:
    p = ParamDef(name=name, type=ptype, scope="obra", obra_id=obra.id, **kw)
    p.level = level
    return p


@pytest.fixture
async def ctx(session: AsyncSession, users: dict[Role, User]) -> dict[str, Any]:
    """2 vigas (V01 ×2, V02 ×1) com Concretagem preenchida e 2 pilares (P01 ×2, P02 ×1)
    sem; parâmetro por peça "Data de fabricação"."""
    obra = Obra(code="OB-IMP", name="Importação", acc_item_name="imp.rvt")
    session.add(obra)
    await session.flush()
    marks = {
        code: Mark(obra_id=obra.id, code=code, category=cat)
        for code, cat in (("V01", "Viga"), ("V02", "Viga"), ("P01", "Pilar"), ("P02", "Pilar"))
    }
    session.add_all(marks.values())
    await session.flush()
    await _version(
        session,
        obra,
        [
            (1, "v01-a", marks["V01"]),
            (2, "v01-b", marks["V01"]),
            (3, "v02-a", marks["V02"]),
            (4, "p01-a", marks["P01"]),
            (5, "p01-b", marks["P01"]),
            (6, "p02-a", marks["P02"]),
        ],
    )
    params = {
        "concretagem": _param(obra, "Concretagem", "date"),
        "forma": _param(obra, "Tipo de forma", "list", options=["F-11", "F-12"]),
        "obs": _param(obra, "Obs. da viga", "text", categories=["Viga"]),
        "fab": _param(obra, "Data de fabricação", "date", level="piece"),
    }
    session.add_all(params.values())
    await session.flush()
    for code in ("V01", "V02"):
        session.add(
            ParamValue(mark_id=marks[code].id, def_id=params["concretagem"].id, value="2026-11-10")
        )
    session.add(ParamValue(mark_id=marks["V01"].id, def_id=params["forma"].id, value="F-11"))
    await session.flush()
    units = {
        f"{m.code}-{u.number}": u
        for m in marks.values()
        for u in await session.scalars(select(PieceUnit).where(PieceUnit.mark_id == m.id))
    }
    return {"obra": obra, "marks": marks, "params": params, "units": units, "users": users}


async def _export(session: AsyncSession, ctx: dict[str, Any]) -> Any:
    f = await export.build_workbook(
        session, ctx["obra"].id, None, search.SearchParams(), ctx["users"][Role.ADMIN]
    )
    return load_workbook(io.BytesIO(f.content))


def _col(ws: Any, header: str) -> int:
    for cell in ws[1]:
        if cell.value == header:
            return int(cell.column)
    raise AssertionError(f"coluna {header} não existe")


def _set(ws: Any, key_header: str, key: str, header: str, value: Any) -> None:
    kc, vc = _col(ws, key_header), _col(ws, header)
    for row in ws.iter_rows(min_row=2):
        if row[kc - 1].value == key:
            ws.cell(row=row[0].row, column=vc, value=value)
            return
    raise AssertionError(f"linha {key} não existe")


def _bytes(wb: Any) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _url(ctx: dict[str, Any], step: str) -> str:
    return f"/api/obras/{ctx['obra'].id}/import-xlsx/{step}"


async def _preview(client: httpx.AsyncClient, ctx: dict[str, Any], content: bytes) -> Any:
    r = await client.post(
        _url(ctx, "preview"),
        content=content,
        headers={**as_user(ctx["users"][Role.FABRICA]), "Content-Type": XLSX},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _apply(
    client: httpx.AsyncClient, ctx: dict[str, Any], content: bytes, fp: str, overwrite: bool = False
) -> httpx.Response:
    return await client.post(
        _url(ctx, "apply"),
        params={"fingerprint": fp, "overwrite": str(overwrite).lower()},
        content=content,
        headers={**as_user(ctx["users"][Role.FABRICA]), "Content-Type": XLSX},
    )


async def _mark_value(session: AsyncSession, mark: Mark, param: ParamDef) -> Any:
    return await session.scalar(
        select(ParamValue.value).where(ParamValue.mark_id == mark.id, ParamValue.def_id == param.id)
    )


async def test_gestora_fills_concretagem_of_pilares(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    """Vigas preenchidas, pilares não: preenche os pilares no Excel e importa."""
    wb = await _export(session, ctx)
    ws = wb["Marcas"]
    _set(ws, "Marca", "P01", "Concretagem", datetime(2026, 11, 20))  # data do Excel
    _set(ws, "Marca", "P02", "Concretagem", "21/11/2026")  # texto dd/mm/aaaa
    content = _bytes(wb)

    p = await _preview(client, ctx, content)
    assert (p["fills"], p["changes"], p["errors"]) == (2, 0, [])
    assert p["unchanged"] == 3  # Concretagem das vigas e a forma da V01, iguais ao app
    assert p["params"] == [
        {
            "def_id": ctx["params"]["concretagem"].id,
            "name": "Concretagem",
            "level": "mark",
            "fills": 2,
            "changes": 0,
        }
    ]
    assert {(i["target"], i["new"]) for i in p["fill_items"]} == {
        ("P01", "2026-11-20"),
        ("P02", "2026-11-21"),
    }
    # a prévia não grava nada
    assert await _mark_value(session, ctx["marks"]["P01"], ctx["params"]["concretagem"]) is None

    r = await _apply(client, ctx, content, p["fingerprint"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["marks_changed"], body["units_changed"], body["fields_changed"]) == (2, 0, 2)
    concretagem = ctx["params"]["concretagem"]
    assert await _mark_value(session, ctx["marks"]["P01"], concretagem) == "2026-11-20"
    assert await _mark_value(session, ctx["marks"]["P02"], concretagem) == "2026-11-21"
    assert await _mark_value(session, ctx["marks"]["V01"], concretagem) == "2026-11-10"

    log = list(await session.scalars(select(AuditLog).where(AuditLog.batch_id == body["batch_id"])))
    assert len(log) == 2
    assert all(e.after and e.after["source"] == "import" for e in log)
    assert all(e.user_id == ctx["users"][Role.FABRICA].id for e in log)


async def test_changes_only_with_overwrite_and_empty_cell_never_clears(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    wb = await _export(session, ctx)
    ws = wb["Marcas"]
    _set(ws, "Marca", "V01", "Concretagem", datetime(2026, 12, 1))  # alterar
    _set(ws, "Marca", "V02", "Concretagem", None)  # vazio: não apaga
    _set(ws, "Marca", "P01", "Tipo de forma", "f-12")  # preencher (opção sem diferenciar caixa)
    content = _bytes(wb)
    p = await _preview(client, ctx, content)
    assert (p["fills"], p["changes"]) == (1, 1)
    assert p["change_items"][0] | {"row": 0} == {
        "sheet": "Marcas",
        "row": 0,
        "target": "V01",
        "category": "Viga",
        "param": "Concretagem",
        "old": "2026-11-10",
        "new": "2026-12-01",
    }

    # padrão: só preenche os vazios
    r = await _apply(client, ctx, content, p["fingerprint"])
    assert r.status_code == 200 and r.json()["skipped_changes"] == 1
    concretagem = ctx["params"]["concretagem"]
    assert await _mark_value(session, ctx["marks"]["V01"], concretagem) == "2026-11-10"
    assert await _mark_value(session, ctx["marks"]["V02"], concretagem) == "2026-11-10"
    assert await _mark_value(session, ctx["marks"]["P01"], ctx["params"]["forma"]) == "F-12"

    # com "também alterar"
    p = await _preview(client, ctx, content)
    assert (p["fills"], p["changes"]) == (0, 1)
    r = await _apply(client, ctx, content, p["fingerprint"], overwrite=True)
    assert r.status_code == 200 and r.json()["fields_changed"] == 1
    assert await _mark_value(session, ctx["marks"]["V01"], concretagem) == "2026-12-01"


async def test_invalid_rows_are_listed_and_valid_ones_applied(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    wb = await _export(session, ctx)
    ws = wb["Marcas"]
    _set(ws, "Marca", "P01", "Concretagem", "31/02/2026")
    _set(ws, "Marca", "P01", "Tipo de forma", "F-99")
    _set(ws, "Marca", "P02", "Obs. da viga", "pilar não tem")
    _set(ws, "Marca", "P02", "Concretagem", datetime(2026, 11, 25))  # válida
    ws.append(["X99", "Pilar", 1, None, None, None, datetime(2026, 11, 25)])
    p = await _preview(client, ctx, _bytes(wb))
    messages = sorted(e["message"] for e in p["errors"])
    assert messages == sorted(
        [
            "Concretagem: Data inválida: use dd/mm/aaaa",
            'Tipo de forma: "F-99" não é uma das opções (F-11, F-12).',
            '"Obs. da viga" não vale para a categoria Pilar.',
            "Marca X99 (Pilar) não está na versão ativa da obra.",
        ]
    )
    assert all(e["sheet"] == "Marcas" and e["row"] for e in p["errors"])
    assert p["fills"] == 1
    r = await _apply(client, ctx, _bytes(wb), p["fingerprint"])
    assert r.status_code == 200 and r.json()["errors"] == 4
    concretagem = ctx["params"]["concretagem"]
    assert await _mark_value(session, ctx["marks"]["P02"], concretagem) == "2026-11-25"
    assert await _mark_value(session, ctx["marks"]["P01"], concretagem) is None


async def test_piece_values_by_external_id_with_warning_and_label_fallback(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    wb = await _export(session, ctx)
    ws = wb["Peças"]
    fab = "Data de fabricação"
    _set(ws, "externalId", "p01-a", fab, datetime(2026, 11, 3))
    _set(ws, "externalId", "p01-b", fab, datetime(2026, 11, 4))
    # numeração mudou depois do export: o rótulo antigo não manda, o externalId sim
    label_col = _col(ws, "Peça")
    ext_col = _col(ws, "externalId")
    for row in ws.iter_rows(min_row=2):
        if row[ext_col - 1].value == "p01-b":
            right_label = row[label_col - 1].value
            ws.cell(row=row[0].row, column=label_col, value="P01-9")
        if row[ext_col - 1].value == "v02-a":  # sem externalId (NWD): vale o rótulo
            ws.cell(row=row[0].row, column=ext_col, value=None)
            ws.cell(row=row[0].row, column=_col(ws, fab), value="05/11/2026")
    p = await _preview(client, ctx, _bytes(wb))
    assert p["errors"] == []
    assert p["fills"] == 3
    assert [w["message"] for w in p["warnings"]] == [
        f"Conferir: no arquivo P01-9, hoje é {right_label} (ligada pelo externalId;"
        " a numeração mudou depois do export)."
    ]
    r = await _apply(client, ctx, _bytes(wb), p["fingerprint"])
    assert r.status_code == 200 and r.json()["units_changed"] == 3

    async def fab_of(label: str) -> Any:
        return await session.scalar(
            select(PieceValue.value).where(
                PieceValue.unit_id == ctx["units"][label].id,
                PieceValue.def_id == ctx["params"]["fab"].id,
            )
        )

    by_ext = {u.external_id: label for label, u in ctx["units"].items()}
    assert await fab_of(by_ext["p01-a"]) == "2026-11-03"
    assert await fab_of(by_ext["p01-b"]) == "2026-11-04"
    assert await fab_of(by_ext["v02-a"]) == "2026-11-05"


async def test_mixed_import_is_one_batch_and_undo_restores_everything(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    wb = await _export(session, ctx)
    _set(wb["Marcas"], "Marca", "P01", "Concretagem", datetime(2026, 11, 20))
    _set(wb["Peças"], "externalId", "p02-a", "Data de fabricação", datetime(2026, 11, 2))
    content = _bytes(wb)
    p = await _preview(client, ctx, content)
    body = (await _apply(client, ctx, content, p["fingerprint"])).json()
    assert (body["marks_changed"], body["units_changed"]) == (1, 1)

    r = await client.post(
        f"/api/batches/{body['batch_id']}/undo", headers=as_user(ctx["users"][Role.FABRICA])
    )
    assert r.status_code == 200, r.text
    assert r.json()["restored"] == 2
    assert await _mark_value(session, ctx["marks"]["P01"], ctx["params"]["concretagem"]) is None
    left = await session.scalar(
        select(PieceValue.value).where(PieceValue.def_id == ctx["params"]["fab"].id)
    )
    assert left is None


async def test_state_changed_since_preview_is_409(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    wb = await _export(session, ctx)
    _set(wb["Marcas"], "Marca", "P01", "Concretagem", datetime(2026, 11, 20))
    content = _bytes(wb)
    p = await _preview(client, ctx, content)
    # alguém preenche o mesmo campo pela tela, entre a prévia e o aplicar
    session.add(
        ParamValue(
            mark_id=ctx["marks"]["P01"].id,
            def_id=ctx["params"]["concretagem"].id,
            value="2026-11-30",
        )
    )
    await session.flush()
    r = await _apply(client, ctx, content, p["fingerprint"])
    assert r.status_code == 409
    assert "mudaram desde a prévia" in r.json()["detail"]


async def test_duplicate_row_with_other_value_is_error(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    wb = await _export(session, ctx)
    ws = wb["Marcas"]
    _set(ws, "Marca", "P01", "Concretagem", datetime(2026, 11, 20))
    ws.append(["P01", "Pilar", 2, None, None, None, datetime(2026, 11, 22)])
    p = await _preview(client, ctx, _bytes(wb))
    assert [e["message"] for e in p["errors"]] == [
        f"P01 aparece de novo (linha {_find_row(ws, 'P01')}) com outro valor."
    ]


def _find_row(ws: Any, code: str) -> int:
    for row in ws.iter_rows(min_row=2):
        if row[0].value == code:
            return int(row[0].row)
    raise AssertionError(code)


async def test_rejects_wrong_files(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    h = {**as_user(ctx["users"][Role.FABRICA]), "Content-Type": XLSX}

    async def detail(content: bytes) -> str:
        r = await client.post(_url(ctx, "preview"), content=content, headers=h)
        assert r.status_code == 422, r.text
        return str(r.json()["detail"])

    assert "não é um Excel" in await detail(b"Marca;Categoria\nP01;Pilar")
    assert "Envie o arquivo" in await detail(b"")

    # de outra obra
    wb = await _export(session, ctx)
    wb["Sobre"]["B1"] = "OB-OUTRA — Outra"
    assert "é da obra OB-OUTRA, não da OB-IMP" in await detail(_bytes(wb))

    # sem a aba Sobre
    wb = await _export(session, ctx)
    del wb["Sobre"]
    assert 'Aba "Sobre" não encontrada' in await detail(_bytes(wb))

    # com macro
    buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(_bytes(await _export(session, ctx)))) as src,
        zipfile.ZipFile(buf, "w") as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("xl/vbaProject.bin", b"macro")
    assert "macro" in await detail(buf.getvalue())

    # grande demais
    assert "grande demais" in await detail(b"PK" + b"0" * (5 * 1024 * 1024))


async def test_only_factory_and_admin_import(
    client: httpx.AsyncClient, session: AsyncSession, ctx: dict[str, Any]
) -> None:
    content = _bytes(await _export(session, ctx))
    for role in (Role.PROJETOS, Role.LEITURA):
        r = await client.post(
            _url(ctx, "preview"),
            content=content,
            headers={**as_user(ctx["users"][role]), "Content-Type": XLSX},
        )
        assert r.status_code == 403, role
