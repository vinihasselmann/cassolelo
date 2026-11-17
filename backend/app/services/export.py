"""Exportação da obra para Excel (Fase 9.1).

O arquivo é a MESMA lista da tela: usa `search.find_marks` com os filtros da busca
(texto, categoria, nível, Nome=valor, "sem <parâmetro>", atalhos) na versão escolhida.

Aba "Marcas" (uma linha por marca): Marca, Categoria, Peças, Seção, Comprimento (cm),
Status, uma coluna por parâmetro ativo da obra ("Nome (unidade)"), Última alteração e
Autor (só os parâmetros POR MARCA). Aba "Peças": Marca, Categoria, externalId, Nível,
dbId, Peça (unidade de peça, ex.: PP001-3) e uma coluna por parâmetro POR PEÇA (P3).
Aba "Sobre": obra, versão, filtros, quando e quem gerou.

Cabeçalho congelado e filtro automático; números como número, datas como data do Excel
(no fuso DISPLAY_TIMEZONE). Parâmetro que não se aplica à categoria da marca: célula
vazia e cinza.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Element,
    ModelVersion,
    Obra,
    ParamDef,
    ParamValue,
    PieceUnit,
    PieceUnitLink,
    PieceValue,
    User,
)
from app.models.enums import ParamLevel, ParamType, VersionStatus
from app.services import filters as filters_engine
from app.services import mark_status, search
from app.services.errors import NotFoundError
from app.services.extraction import find_prop
from app.services.mark_status import MarkStatus
from app.services.mark_validation import to_mm
from app.services.param_defs import in_obra as param_in_obra
from app.services.version_data import get_ready_version

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Propriedades do modelo para as colunas Seção e Comprimento (Revit da Cassol, Revit em
# inglês e IFC). Seção = Largura x Altura em cm; sem as duas, o nome do tipo.
WIDTH_NAMES = ["SEÇÃO-Largura", "Largura", "Width"]
HEIGHT_NAMES = ["SEÇÃO-Altura", "Altura", "Height"]
LENGTH_NAMES = ["PEÇA-Comprimento", "Comprimento", "Length"]
TYPE_NAMES = ["Nome do tipo", "Type Name", "ObjectType", "Tipo", "Type"]

STATUS_LABELS = {
    MarkStatus.PENDING: "Pendente",
    MarkStatus.PARTIAL: "Parcial",
    MarkStatus.COMPLETE: "Completa",
    MarkStatus.REVIEW: "Revisar",
}
BASE_HEADERS = ["Marca", "Categoria", "Peças", "Seção", "Comprimento (cm)", "Status"]
DATE_FMT = "dd/mm/yyyy"
DATETIME_FMT = "dd/mm/yyyy hh:mm"
HEADER_FILL = PatternFill("solid", fgColor="DCE6F2")
NA_FILL = PatternFill("solid", fgColor="EEEEEE")


def rev_label(n: int) -> str:
    """Nome da versão como no Autodesk Docs (V1, V2…)."""
    return f"V{n}"


def _num(value: float) -> float | int:
    rounded = round(value, 1)
    return int(rounded) if rounded.is_integer() else rounded


def _cm(raw: str | None) -> float | None:
    mm = to_mm(raw) if raw else None
    return None if mm is None else _num(mm / 10)


def _join(values: list[Any]) -> Any:
    """Um valor só → o próprio (número continua número); vários → texto "a / b"."""
    distinct = list(dict.fromkeys(values))
    if not distinct:
        return None
    if len(distinct) == 1:
        return distinct[0]
    return " / ".join(
        str(v).replace(".", ",") if isinstance(v, float) else str(v) for v in distinct
    )


def piece_section(props: dict[str, Any]) -> str | None:
    w, h = _cm(find_prop(props, WIDTH_NAMES)), _cm(find_prop(props, HEIGHT_NAMES))
    if w is not None and h is not None:
        return f"{w}x{h}".replace(".", ",")
    return find_prop(props, TYPE_NAMES)


def cell_value(ptype: str, value: Any) -> Any:
    """Valor do parâmetro como a célula deve guardar (número, data, texto)."""
    if value is None or value == "":
        return None
    kind = ParamType(ptype)
    if kind is ParamType.NUMBER and isinstance(value, int | float) and not isinstance(value, bool):
        return value
    if kind is ParamType.DATE and isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    if kind is ParamType.BOOL:
        return "Sim" if value is True else "Não" if value is False else str(value)
    return value if isinstance(value, str | int | float) else str(value)


@dataclass(frozen=True)
class ExportFile:
    content: bytes
    filename: str
    marks: int
    pieces: int


def _style_sheet(ws: Worksheet, widths: list[int]) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, min(width + 2, 50))


def _widths(rows: list[list[Any]]) -> list[int]:
    out: list[int] = []
    for row in rows:
        for i, value in enumerate(row):
            text = (
                value.strftime("%d/%m/%Y %H:%M")
                if isinstance(value, datetime)
                else str(value or "")
            )
            size = len(text)
            if i < len(out):
                out[i] = max(out[i], size)
            else:
                out.append(size)
    return out


async def build_workbook(
    session: AsyncSession,
    obra_id: int,
    version_id: int | None,
    params: search.SearchParams,
    actor: User,
    timezone: str = "America/Sao_Paulo",
) -> ExportFile:
    obra = await session.get(Obra, obra_id)
    if obra is None:
        raise NotFoundError("Obra não encontrada.")
    if version_id is None:
        version_id = await session.scalar(
            select(ModelVersion.id)
            .where(
                ModelVersion.obra_id == obra_id, ModelVersion.status == VersionStatus.READY.value
            )
            .order_by(ModelVersion.version_number.desc())
            .limit(1)
        )
        if version_id is None:
            raise NotFoundError("A obra ainda não tem versão pronta para exportar.")
    version = await get_ready_version(session, version_id)
    if version.obra_id != obra_id:
        raise NotFoundError("Versão não encontrada nesta obra.")
    tz = ZoneInfo(timezone)

    marks, _note = await search.find_marks(session, version.id, params)
    mark_ids = [m.mark_id for m in marks]
    dbids = {d for m in marks for d in m.dbids}

    # Peças do resultado (props para Seção/Comprimento; nível e externalId para a aba Peças)
    pieces: dict[int, list[Element]] = defaultdict(list)
    if mark_ids:
        rows = await session.scalars(
            select(Element)
            .where(Element.version_id == version.id, Element.mark_id.in_(mark_ids))
            .order_by(Element.dbid)
        )
        for el in rows:
            if el.dbid in dbids and el.mark_id is not None:
                pieces[el.mark_id].append(el)

    params_defs = list(
        await session.scalars(
            select(ParamDef)
            .where(
                ParamDef.active.is_(True),
                param_in_obra(obra_id),
            )
            .order_by(func.lower(ParamDef.name), ParamDef.id)
        )
    )
    values: dict[tuple[int, int], ParamValue] = {}
    if mark_ids and params_defs:
        for v in await session.scalars(
            select(ParamValue).where(
                ParamValue.mark_id.in_(mark_ids),
                ParamValue.def_id.in_([p.id for p in params_defs]),
            )
        ):
            values[(v.mark_id, v.def_id)] = v
    author_ids = {v.updated_by for v in values.values() if v.updated_by}
    names: dict[int, str] = {}
    if author_ids:
        rows_names = await session.execute(
            select(User.id, User.name).where(User.id.in_(author_ids))
        )
        names = {uid: name for uid, name in rows_names}
    statuses = (await mark_status.version_statuses(session, version.id)).statuses

    wb = Workbook()
    ws = wb.create_sheet("Marcas", 0)
    wb.remove(wb.worksheets[1])  # a planilha vazia padrão
    headers = (
        BASE_HEADERS
        + [f"{p.name} ({p.unit})" if p.unit else p.name for p in params_defs]
        + ["Última alteração", "Autor"]
    )
    ws.append(headers)
    table: list[list[Any]] = [headers]
    for m in marks:
        els = pieces.get(m.mark_id, [])
        applicable = [p for p in params_defs if not p.categories or m.category in p.categories]
        rows_of_mark = [
            values[(m.mark_id, p.id)] for p in applicable if (m.mark_id, p.id) in values
        ]
        last = max(rows_of_mark, key=lambda v: v.updated_at, default=None)
        row: list[Any] = [
            m.code,
            m.category,
            m.count,
            _join([s for s in (piece_section(e.props) for e in els) if s]),
            _join(
                [c for c in (_cm(find_prop(e.props, LENGTH_NAMES)) for e in els) if c is not None]
            ),
            STATUS_LABELS[statuses.get(m.mark_id, MarkStatus.PENDING)],
        ]
        for p in params_defs:
            pv = values.get((m.mark_id, p.id))
            row.append(cell_value(p.type, pv.value) if pv is not None and p in applicable else None)
        row.append(last.updated_at.astimezone(tz).replace(tzinfo=None) if last else None)
        row.append(names.get(last.updated_by) if last and last.updated_by else None)
        ws.append(row)
        table.append(row)
        r = ws.max_row
        for i, p in enumerate(params_defs):
            cell = ws.cell(row=r, column=len(BASE_HEADERS) + i + 1)
            if p not in applicable:
                cell.fill = NA_FILL
            elif isinstance(cell.value, date):
                cell.number_format = DATE_FMT
        ws.cell(row=r, column=len(headers) - 1).number_format = DATETIME_FMT
    _style_sheet(ws, _widths(table))

    # Parâmetros POR PEÇA: valor da unidade ligada a cada peça nesta versão.
    piece_defs = list(
        await session.scalars(
            select(ParamDef)
            .where(
                ParamDef.active.is_(True),
                param_in_obra(obra_id, level=ParamLevel.PIECE.value),
            )
            .order_by(func.lower(ParamDef.name), ParamDef.id)
        )
    )
    element_ids = [el.id for els in pieces.values() for el in els]
    units: dict[int, tuple[int, int]] = {}  # elemento -> (unidade, número)
    if element_ids:
        for el_id, unit_id, number in await session.execute(
            select(PieceUnitLink.element_id, PieceUnit.id, PieceUnit.number)
            .join(PieceUnit, PieceUnit.id == PieceUnitLink.unit_id)
            .where(
                PieceUnitLink.version_id == version.id,
                PieceUnitLink.element_id.in_(element_ids),
            )
        ):
            units[el_id] = (unit_id, number)
    unit_values: dict[tuple[int, int], Any] = {}
    if units and piece_defs:
        for unit_id, def_id, value in await session.execute(
            select(PieceValue.unit_id, PieceValue.def_id, PieceValue.value).where(
                PieceValue.unit_id.in_({u for u, _ in units.values()}),
                PieceValue.def_id.in_([p.id for p in piece_defs]),
            )
        ):
            unit_values[(unit_id, def_id)] = value

    ps = wb.create_sheet("Peças")
    pheaders = ["Marca", "Categoria", "externalId", "Nível", "dbId", "Peça"] + [
        f"{p.name} ({p.unit})" if p.unit else p.name for p in piece_defs
    ]
    ps.append(pheaders)
    ptable: list[list[Any]] = [pheaders]
    first_param_col = 7
    for m in marks:
        applicable = [p for p in piece_defs if not p.categories or m.category in p.categories]
        for el in pieces.get(m.mark_id, []):
            unit = units.get(el.id)
            prow: list[Any] = [
                m.code,
                m.category,
                el.external_id,
                el.level,
                el.dbid,
                f"{m.code}-{unit[1]}" if unit else None,
            ]
            for p in piece_defs:
                raw = unit_values.get((unit[0], p.id)) if unit and p in applicable else None
                prow.append(cell_value(p.type, raw) if raw is not None else None)
            ps.append(prow)
            ptable.append(prow)
            r = ps.max_row
            for i, p in enumerate(piece_defs):
                cell = ps.cell(row=r, column=first_param_col + i)
                if p not in applicable:
                    cell.fill = NA_FILL
                elif isinstance(cell.value, date):
                    cell.number_format = DATE_FMT
    _style_sheet(ps, _widths(ptable))

    now = datetime.now(UTC).astimezone(tz)
    about = wb.create_sheet("Sobre")
    filters = (
        await _describe_definition(session, version, params.definition)
        if params.definition is not None
        else _describe_filters(params)
    )
    for key, value in (
        ("Obra", f"{obra.code} — {obra.name}"),
        ("Versão", rev_label(version.version_number)),
        ("Filtros", filters or "nenhum (todas as marcas)"),
        ("Marcas", len(marks)),
        ("Peças", sum(m.count for m in marks)),
        ("Gerado em", now.replace(tzinfo=None)),
        ("Gerado por", actor.name),
    ):
        about.append([key, value])
    about.cell(row=6, column=2).number_format = DATETIME_FMT
    about.column_dimensions["A"].width = 14
    about.column_dimensions["B"].width = 60
    for cell in about["A"]:
        cell.font = Font(bold=True)
    wb.properties.title = f"{obra.code} {rev_label(version.version_number)}"
    wb.properties.creator = "Cassol Elo"

    buffer = io.BytesIO()
    wb.save(buffer)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", obra.code).strip("-") or "obra"
    filename = f"{safe}_{rev_label(version.version_number)}_{now:%Y-%m-%d}.xlsx"
    return ExportFile(buffer.getvalue(), filename, len(marks), sum(m.count for m in marks))


MODE_WORDS = {"isolate": "", "hide": "ocultar ", "highlight": "destacar "}


async def _describe_definition(
    session: AsyncSession, version: ModelVersion, definition: filters_engine.FilterDef
) -> str:
    """Filtro da tela em texto, para a aba Sobre: 'texto "pp"; Categoria é um de Pilar'."""
    parts = [f'texto "{definition.q.strip()}"'] if definition.q.strip() else []
    for rule in definition.rules:
        field = await filters_engine.resolve_field(session, version, rule.field)
        op = filters_engine.OP_LABELS[rule.op]
        value = rule.value
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        tail = f"{op} {value}" if value not in (None, "") else op
        parts.append(f"{MODE_WORDS[definition.rule_mode(rule)]}{field.name} {tail}")
    if definition.logic == "or" and len(definition.rules) > 1:
        parts.append("(qualquer regra)")
    return "; ".join(parts)


def _describe_filters(p: search.SearchParams) -> str:
    parts = []
    if p.q:
        parts.append(f'texto "{p.q}"')
    if p.categories:
        parts.append("categoria: " + ", ".join(p.categories))
    if p.levels:
        parts.append("nível: " + ", ".join(p.levels))
    parts += [f"{n}={v}" for n, v in p.props]
    if p.missing:
        parts.append(f"sem {p.missing}")
    if p.shortcut is not search.Shortcut.ALL:
        parts.append(f"atalho: {p.shortcut.value}")
    return "; ".join(parts)
