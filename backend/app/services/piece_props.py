"""Valores de cada peça por campo (`piece_props`): a base do motor de filtros.

Três origens, cada uma com sua regra de atualização:
- **model:** propriedades do modelo (`elements.props`), chave `"<grupo>/<nome>"`.
  Montadas no fim do `process_version` (ou pelo backfill) e imutáveis depois.
- **system:** campos do app. Categoria, nível, Nome da montagem, nome do elemento e
  versão em que a montagem surgiu são montados com a versão. O **status de produção**
  depende dos valores da fábrica e é sincronizado com eles.
- **factory:** parâmetros da fábrica (chave = id do parâmetro). O valor é da MARCA e
  vai para cada peça dela, em todas as versões da obra. Sincronizado sempre que valores
  ou parâmetros mudam (`sync_factory`).

Cada valor fica como texto (até 500 caracteres). Quando converte, também como número
(vírgula decimal e unidade aceitas: "60,5 cm" → 60.5) e/ou data (ISO ou AAAAMMDD).
O tipo de uma propriedade do modelo é inferido pelos valores da versão: data se todos
forem datas, número se todos converterem, senão texto. Fica em `version_property_names`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Element,
    Mark,
    ModelVersion,
    ParamDef,
    ParamValue,
    PieceProp,
    PieceUnitLink,
    PieceValue,
    VersionPropertyName,
)
from app.models.enums import ParamScope, ReviewStatus
from app.services import mark_status
from app.services.param_defs import has_value, in_obra

MODEL, FACTORY, SYSTEM = "model", "factory", "system"
SOURCES = (MODEL, FACTORY, SYSTEM)
TEXT, NUMBER, DATE = "text", "number", "date"
MAX_TEXT = 500
MAX_KEY = 600
CHUNK = 5000

# Campos de sistema: chave -> (nome exibido, tipo)
SYSTEM_FIELDS: dict[str, tuple[str, str]] = {
    "category": ("Categoria", TEXT),
    "level": ("Nível", TEXT),
    "mark": ("Nome da montagem", TEXT),
    "name": ("Nome do elemento", TEXT),
    "status": ("Status de produção", TEXT),
    "first_version": ("Versão em que surgiu", NUMBER),
}
STATUS_LABELS = {
    mark_status.MarkStatus.PENDING: "Pendente",
    mark_status.MarkStatus.PARTIAL: "Parcial",
    mark_status.MarkStatus.COMPLETE: "Completa",
    mark_status.MarkStatus.REVIEW: "Revisar",
}
# tipo do parâmetro da fábrica -> tipo do campo
PARAM_FIELD_TYPE = {"text": TEXT, "list": TEXT, "bool": TEXT, "number": NUMBER, "date": DATE}

_NUMBER = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*((?:[^\d\s^]|\^\d)*)\s*$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


# ------------------------------------------------------------------ conversões


def parse_number(text: str) -> Decimal | None:
    """ "60" → 60; "60,5 cm" → 60.5; "2.504 m^3" → 2.504; "60x60" → None."""
    match = _NUMBER.match(text)
    if match is None:
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:  # pragma: no cover - a regex garante o formato
        return None


def parse_date(text: str) -> date | None:
    """ "2026-11-13" (ou com hora) e "20261113" → data; o resto → None."""
    match = _ISO_DATE.match(text.strip()) or _COMPACT_DATE.match(text.strip())
    if match is None:
        return None
    try:
        value = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return value if 1900 <= value.year <= 2200 else None


def infer_type(values: Iterable[str]) -> str:
    items = [v for v in values if v]
    if not items:
        return TEXT
    if all(parse_date(v) is not None for v in items):
        return DATE
    if all(parse_number(v) is not None for v in items):
        return NUMBER
    return TEXT


def scalar_text(raw: Any) -> str | None:
    """Valor de uma propriedade do modelo como texto (lista → 1º item; vazio → None)."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None or isinstance(raw, dict):
        return None
    if isinstance(raw, bool):
        return "Sim" if raw else "Não"
    text = str(raw).strip()
    return text or None


def model_key(group: str, name: str) -> str:
    return f"{group}/{name}"[:MAX_KEY]


def _row(
    version_id: int, piece_id: int, mark_id: int | None, source: str, key: str, text: str
) -> dict[str, Any]:
    return {
        "version_id": version_id,
        "piece_id": piece_id,
        "mark_id": mark_id,
        "source": source,
        "key": key[:MAX_KEY],
        "value_text": text[:MAX_TEXT],
        "value_num": parse_number(text),
        "value_date": parse_date(text),
    }


_COLUMNS = (
    "version_id",
    "piece_id",
    "mark_id",
    "source",
    "key",
    "value_text",
    "value_num",
    "value_date",
)


async def _insert(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Grava em lote. No Postgres (asyncpg) usa COPY, na MESMA transação da sessão:
    ~50x mais rápido que INSERT para centenas de milhares de linhas."""
    if not rows:
        return
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    driver = getattr(raw, "driver_connection", None)
    if driver is not None and hasattr(driver, "copy_records_to_table"):
        records = [tuple(r[c] for c in _COLUMNS) for r in rows]
        await driver.copy_records_to_table("piece_props", records=records, columns=_COLUMNS)
        return
    for i in range(0, len(rows), CHUNK):  # pragma: no cover - outro driver
        await session.execute(insert(PieceProp), rows[i : i + CHUNK])


# -------------------------------------------------------- modelo + sistema (versão)


@dataclass
class _KeyStats:
    pieces: int = 0
    values: set[str] | None = None


async def build_version(session: AsyncSession, version_id: int) -> int:
    """Reconstrói as linhas model e system da versão (menos o status) e os tipos das
    propriedades do modelo. Sem commit. Devolve quantas linhas gravou."""
    await session.execute(
        delete(PieceProp).where(
            PieceProp.version_id == version_id, PieceProp.source.in_([MODEL, SYSTEM])
        )
    )
    version = await session.get(ModelVersion, version_id)
    if version is None:
        return 0
    first_version = await _first_versions(session, version.obra_id)
    pieces = await session.execute(
        select(
            Element.id,
            Element.mark_id,
            Element.name,
            Element.category,
            Element.level,
            Element.props,
            Mark.code,
        )
        .outerjoin(Mark, Mark.id == Element.mark_id)
        .where(Element.version_id == version_id)
        .order_by(Element.id)
    )
    rows: list[dict[str, Any]] = []
    stats: dict[tuple[str, str], _KeyStats] = defaultdict(lambda: _KeyStats(0, set()))
    for piece_id, mark_id, name, category, level, props, code in pieces:
        system = {
            "category": category,
            "level": level,
            "mark": code,
            "name": name,
            "first_version": str(first_version[mark_id]) if mark_id in first_version else None,
        }
        for key, value in system.items():
            if value:
                rows.append(_row(version_id, piece_id, mark_id, SYSTEM, key, str(value)))
        for group, content in (props or {}).items():
            if not isinstance(content, dict):
                continue
            for prop, raw in content.items():
                text = scalar_text(raw)
                if text is None:
                    continue
                rows.append(
                    _row(version_id, piece_id, mark_id, MODEL, model_key(group, prop), text)
                )
                st = stats[(group[:255], prop[:255])]
                st.pieces += 1
                if st.values is not None:
                    st.values.add(text[:MAX_TEXT])
    await _insert(session, rows)

    for (group, prop), st in stats.items():
        values = st.values or set()
        await session.execute(
            update(VersionPropertyName)
            .where(
                VersionPropertyName.version_id == version_id,
                VersionPropertyName.group_name == group,
                VersionPropertyName.prop_name == prop,
            )
            .values(value_type=infer_type(values), pieces=st.pieces, distinct_values=len(values))
        )
    # Estatísticas do planejador em dia logo após a versão nova (sem isso, as primeiras
    # consultas podem escolher plano ruim até o autovacuum passar). ANALYZE é por amostra.
    await session.execute(sql_text("ANALYZE piece_props"))
    return len(rows)


async def _first_versions(session: AsyncSession, obra_id: int) -> dict[int, int]:
    """Marca -> menor número de versão em que ela tem peças (a "versão em que surgiu")."""
    rows = await session.execute(
        select(Element.mark_id, func.min(ModelVersion.version_number))
        .join(ModelVersion, ModelVersion.id == Element.version_id)
        .where(ModelVersion.obra_id == obra_id, Element.mark_id.is_not(None))
        .group_by(Element.mark_id)
    )
    return {mark_id: int(n) for mark_id, n in rows if mark_id is not None}


# ------------------------------------------------- fábrica + status (sincronizados)


def _factory_text(param_type: str, value: Any) -> str | None:
    if value is None or value == "":
        return None
    if param_type == "bool":
        return "Sim" if value is True else "Não" if value is False else None
    return str(value).strip() or None


async def sync_factory(
    session: AsyncSession, obra_id: int, mark_ids: Iterable[int] | None = None
) -> int:
    """Refaz as linhas factory e o status (system/status) das peças das marcas dadas,
    em TODAS as versões da obra (None = a obra inteira). Sem commit.

    Chamar sempre que valores da fábrica, parâmetros da obra ou o "a revisar" mudarem."""
    ids = None if mark_ids is None else sorted(set(mark_ids))
    if ids is not None and not ids:
        return 0
    versions = select(ModelVersion.id).where(ModelVersion.obra_id == obra_id)
    scope = [PieceProp.version_id.in_(versions)]
    if ids is not None:
        scope.append(PieceProp.mark_id.in_(ids))
    await session.execute(
        delete(PieceProp).where(
            *scope,
            (PieceProp.source == FACTORY)
            | ((PieceProp.source == SYSTEM) & (PieceProp.key == "status")),
        )
    )

    mark_filter = [Mark.obra_id == obra_id]
    if ids is not None:
        mark_filter.append(Mark.id.in_(ids))
    marks = {
        m.id: m
        for m in await session.scalars(
            select(Mark).where(*mark_filter, Mark.id.in_(select(Element.mark_id)))
        )
    }
    if not marks:
        return 0
    params = list(
        await session.scalars(
            select(ParamDef).where(ParamDef.active.is_(True), in_obra(obra_id, level=None))
        )
    )
    by_id = {p.id: p for p in params}
    mark_defs = [p.id for p in params if not mark_status.is_piece(p)]
    piece_defs = [p.id for p in params if mark_status.is_piece(p)]
    values: dict[int, dict[int, Any]] = defaultdict(dict)  # mark -> def -> valor
    if mark_defs:
        for mark_id, def_id, value in await session.execute(
            select(ParamValue.mark_id, ParamValue.def_id, ParamValue.value).where(
                ParamValue.mark_id.in_(list(marks)),
                ParamValue.def_id.in_(mark_defs),
                has_value(ParamValue.value),
            )
        ):
            values[mark_id][def_id] = value

    # Valores POR PEÇA: cada elemento recebe o valor da unidade ligada a ele na versão.
    unit_values: dict[int, dict[int, Any]] = defaultdict(dict)  # unit -> def -> valor
    element_unit: dict[int, int] = {}  # elemento -> unidade (em qualquer versão da obra)
    if piece_defs:
        for el_id, unit_id in await session.execute(
            select(PieceUnitLink.element_id, PieceUnitLink.unit_id)
            .join(Element, Element.id == PieceUnitLink.element_id)
            .where(
                PieceUnitLink.version_id.in_(versions),
                Element.mark_id.in_(list(marks)),
            )
        ):
            element_unit[el_id] = unit_id
        if element_unit:
            for unit_id, def_id, value in await session.execute(
                select(PieceValue.unit_id, PieceValue.def_id, PieceValue.value).where(
                    PieceValue.unit_id.in_(set(element_unit.values())),
                    PieceValue.def_id.in_(piece_defs),
                    has_value(PieceValue.value),
                )
            ):
                unit_values[unit_id][def_id] = value

    pieces = list(
        await session.execute(
            select(Element.version_id, Element.id, Element.mark_id).where(
                Element.version_id.in_(versions), Element.mark_id.in_(list(marks))
            )
        )
    )
    # Status de CADA peça: parâmetros por marca pela marca; por peça, pela unidade ligada
    # a esta peça (preencher uma peça não muda as outras da marca).
    rows: list[dict[str, Any]] = []
    for version_id, piece_id, mark_id in pieces:
        if mark_id is None:  # pragma: no cover - a consulta só traz peças com marca
            continue
        mark = marks[mark_id]
        category = mark.category
        unit = element_unit.get(piece_id)
        if mark.review_status == ReviewStatus.REVIEW.value:
            status = mark_status.MarkStatus.REVIEW
        else:
            status = mark_status.status_of(
                params,
                category,
                set(values[mark_id]),
                set(unit_values.get(unit, {})) if unit is not None else set(),
            )
        rows.append(_row(version_id, piece_id, mark_id, SYSTEM, "status", STATUS_LABELS[status]))
        own = {**values[mark_id], **(unit_values.get(unit, {}) if unit is not None else {})}
        for def_id, value in own.items():
            param = by_id[def_id]
            if not mark_status.applies(param, category):
                continue
            text = _factory_text(param.type, value)
            if text is not None:
                rows.append(_row(version_id, piece_id, mark_id, FACTORY, str(def_id), text))
    await _insert(session, rows)
    return len(rows)


async def sync_param(session: AsyncSession, param: ParamDef) -> None:
    """Depois de criar/editar/excluir um parâmetro: refaz as obras afetadas."""
    from app.models import ObraParam

    if param.scope == ParamScope.OBRA.value and param.obra_id is not None:
        obra_ids = [param.obra_id]
    else:
        obra_ids = list(
            await session.scalars(select(ObraParam.obra_id).where(ObraParam.def_id == param.id))
        )
    for obra_id in obra_ids:
        await sync_factory(session, obra_id)


async def rebuild_version(session: AsyncSession, version_id: int) -> int:
    """Backfill: model + system da versão e, depois, factory + status da obra."""
    count = await build_version(session, version_id)
    version = await session.get(ModelVersion, version_id)
    if version is not None:
        count += await sync_factory(session, version.obra_id)
    return count
