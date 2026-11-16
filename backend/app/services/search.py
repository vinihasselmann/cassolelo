"""Busca de marcas numa versão (Fase 5.1).

A busca é feita no nível das PEÇAS (elements com marca) e o resultado é agrupado por
marca: com filtro de nível, por exemplo, uma marca traz só as peças daquele nível.

Textos (marca, categoria, nomes e valores) são comparados sem diferenciar maiúsculas
nem acentos (`f_unaccent`, migração 0009): "terreo" acha "TÉRREO".

- texto livre (`q`): cada palavra precisa aparecer em algum lugar: código da marca,
  categoria, `elements.search_text` (nome, nível, tipo, seção...) ou valor de um
  parâmetro da fábrica da marca;
- filtros por categoria e nível;
- filtro por propriedade "Nome=valor" (grupos tirados de version_property_names): o
  valor bate como texto ou, se for número, pelo número do modelo sem exigir a unidade
  ("Largura=60" acha "60.000 cm"; "60 cm" também; "60x60" não é número);
- "sem <parâmetro>": marcas sem valor no parâmetro da fábrica;
- atalhos (Pendentes, Parciais, A revisar, Novas na versão, Órfãs): são FILTROS SALVOS de
  sistema (`saved_filters.system_key`), avaliados pelo motor de filtros. As órfãs não têm
  peças na versão: entram com 0 peças e só o texto livre (marca ou categoria) as filtra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Numeric,
    Text,
    and_,
    cast,
    exists,
    false,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ParamDef, ParamValue, VersionPropertyName
from app.services import filters, saved_filters
from app.services.errors import ValidationError
from app.services.filters import FIRST_VERSION_NOTE
from app.services.param_defs import has_value
from app.services.param_defs import in_obra as param_in_obra
from app.services.version_data import MarkPieces, get_ready_version

MAX_PAGE_SIZE = 500
__all__ = ["FIRST_VERSION_NOTE", "SearchParams", "SearchResult", "Shortcut", "search_marks"]


class Shortcut(StrEnum):
    """Atalhos da busca. Cada um (menos ALL) é um filtro salvo de sistema com o mesmo
    `system_key` (migração 0014)."""

    ALL = "all"
    PENDING = "pending"
    PARTIAL = "partial"
    REVIEW = "review"
    NEW = "new"
    ORPHANS = "orphans"


class UnknownParamError(ValidationError):
    code = "unknown_param"


@dataclass(frozen=True)
class SearchParams:
    q: str = ""
    categories: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    props: list[tuple[str, str]] = field(default_factory=list)
    missing: str | None = None
    shortcut: Shortcut = Shortcut.ALL
    page: int = 1
    page_size: int = 50
    order: Literal["asc", "desc"] = "asc"
    today: date | None = None  # "hoje" das datas relativas (padrão: data do servidor)
    # filtro da tela (F3): regras do motor e o texto dele (`definition.q`; `q` é ignorado)
    definition: filters.FilterDef | None = None


@dataclass(frozen=True)
class SearchResult:
    total_marks: int
    total_pieces: int
    page: int
    page_size: int
    items: list[MarkPieces]
    mark_ids: list[int]  # todas as marcas do resultado (todas as páginas)
    dbids: list[int]  # todas as peças do resultado (para o 3D)
    note: str | None = None


def _like(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _norm(value: Any) -> ColumnElement[str]:
    """Texto em minúsculas e sem acentos (para comparar nomes e valores)."""
    return func.f_unaccent(func.lower(value))


def _ilike(column: Any, token: str) -> ColumnElement[bool]:
    """`column` contém `token`, sem diferenciar maiúsculas nem acentos."""
    return func.f_unaccent(column).ilike(func.f_unaccent(literal(_like(token))), escape="\\")


# Número (ponto ou vírgula decimal) e, opcionalmente, uma unidade sem dígitos.
# Unidade sem dígitos, salvo expoente: "cm", "m^3", "m²".
_NUMBER_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*((?:[^\d\s^]|\^\d)*)\s*$")
# O mesmo no Postgres: captura só o número; o resto não pode ter dígitos ("60x60" fica fora).
_SQL_NUMBER = r"^\s*(-?[0-9]+(?:[.,][0-9]+)?)\s*(?:[^0-9^]|\^[0-9])*$"
_SQL_UNIT = r"^\s*-?[0-9]+(?:[.,][0-9]+)?\s*(.*)$"


def _parse_number(value: str) -> tuple[Decimal, str] | None:
    """ "60" → (60, ""); "60,5 cm" → (60.5, "cm"); "60x60" → None."""
    match = _NUMBER_RE.match(value)
    if match is None:
        return None
    try:
        number = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:  # pragma: no cover - a regex já garante o formato
        return None
    return number, match.group(2).replace(" ", "")


def _value_condition(stored: ColumnElement[str], value: str) -> ColumnElement[bool]:
    """O valor do modelo bate com o digitado: texto igual (sem maiúsculas/acentos) ou,
    se o digitado for número, o mesmo número (com a unidade, se ela foi digitada)."""
    options: list[ColumnElement[bool]] = [_norm(func.btrim(stored)) == _norm(literal(value))]
    parsed = _parse_number(value)
    if parsed is not None:
        number, unit = parsed
        stored_number = cast(func.replace(func.substring(stored, _SQL_NUMBER), ",", "."), Numeric)
        same_number: ColumnElement[bool] = stored_number == number
        if unit:
            stored_unit = _norm(
                func.regexp_replace(func.substring(stored, _SQL_UNIT), "[[:space:]]", "", "g")
            )
            same_number = and_(same_number, stored_unit == _norm(literal(unit)))
        options.append(same_number)
    return or_(*options)


async def _prop_condition(
    session: AsyncSession, version_id: int, name: str, value: str
) -> ColumnElement[bool]:
    rows = await session.execute(
        select(VersionPropertyName.group_name, VersionPropertyName.prop_name).where(
            VersionPropertyName.version_id == version_id,
            _norm(VersionPropertyName.prop_name) == _norm(literal(name.strip())),
        )
    )
    options = [
        _value_condition(func.jsonb_extract_path_text(Element.props, group, prop), value.strip())
        for group, prop in rows
    ]
    return or_(*options) if options else false()


async def _param_def_ids(session: AsyncSession, obra_id: int, name: str) -> list[int]:
    ids = list(
        await session.scalars(
            select(ParamDef.id).where(
                _norm(ParamDef.name) == _norm(literal(name.strip())),
                ParamDef.active.is_(True),
                param_in_obra(obra_id),
            )
        )
    )
    if not ids:
        raise UnknownParamError(f'Parâmetro da fábrica "{name.strip()}" não existe.')
    return ids


def _text_condition(token: str) -> ColumnElement[bool]:
    in_params = exists(
        select(ParamValue.id).where(
            ParamValue.mark_id == Mark.id, _ilike(cast(ParamValue.value, Text), token)
        )
    )
    return or_(
        _ilike(Mark.code, token),
        _ilike(Mark.category, token),
        _ilike(Element.search_text, token),
        in_params,
    )


def _paginate(
    marks: list[MarkPieces], params: SearchParams, note: str | None = None
) -> SearchResult:
    marks = _ordered(marks, params)
    size = max(1, min(params.page_size, MAX_PAGE_SIZE))
    page = max(1, params.page)
    start = (page - 1) * size
    return SearchResult(
        total_marks=len(marks),
        total_pieces=sum(m.count for m in marks),
        page=page,
        page_size=size,
        items=marks[start : start + size],
        mark_ids=[m.mark_id for m in marks],
        dbids=sorted(d for m in marks for d in m.dbids),
        note=note,
    )


def _orphan_rows(orphans: list[filters.OrphanMark], params: SearchParams) -> list[MarkPieces]:
    """Marcas órfãs do filtro (sem peças nesta versão): count 0. Só o texto livre as
    filtra, por marca ou categoria (como antes: elas não têm nível nem propriedades)."""
    tokens = [filters._fold(t) for t in params.q.split()]
    return [
        MarkPieces(mark_id=o.mark_id, code=o.code, category=o.category, count=0, dbids=[])
        for o in orphans
        if all(t in filters._fold(o.code) or t in filters._fold(o.category) for t in tokens)
    ]


async def search_marks(
    session: AsyncSession, version_id: int, params: SearchParams
) -> SearchResult:
    marks, note = await find_marks(session, version_id, params)
    return _paginate(marks, params, note)


def _ordered(marks: list[MarkPieces], params: SearchParams) -> list[MarkPieces]:
    return sorted(marks, key=lambda m: (m.code, m.category), reverse=params.order == "desc")


async def find_marks(
    session: AsyncSession, version_id: int, params: SearchParams
) -> tuple[list[MarkPieces], str | None]:
    """Resultado INTEIRO da busca (sem paginar), na ordem da tela, e a nota.
    Usado pela busca paginada e pela exportação (o Excel é a mesma lista da tela)."""
    version = await get_ready_version(session, version_id)
    compiled: filters.CompiledFilter | None = None
    today = params.today or date.today()
    if params.definition is not None:
        compiled = await filters.compile_filter(session, version_id, params.definition, today)
    elif params.shortcut is not Shortcut.ALL:
        definition = await saved_filters.system_definition(session, params.shortcut.value)
        compiled = await filters.compile_filter(session, version_id, definition, today)

    conds: list[ColumnElement[bool]] = [
        Element.version_id == version_id,
        Element.mark_id.is_not(None),
    ]
    if params.categories:
        conds.append(Element.category.in_(params.categories))
    if params.levels:
        conds.append(Element.level.in_(params.levels))
    for name, value in params.props:
        conds.append(await _prop_condition(session, version_id, name, value))
    if params.definition is None:  # com filtro, o texto já está na condição do motor
        for token in params.q.split():
            conds.append(_text_condition(token))
    if params.missing:
        def_ids = await _param_def_ids(session, version.obra_id, params.missing)
        conds.append(
            ~exists(
                select(ParamValue.id).where(
                    ParamValue.mark_id == Mark.id,
                    ParamValue.def_id.in_(def_ids),
                    has_value(ParamValue.value),
                )
            )
        )
    if compiled is not None:
        conds.append(compiled.condition)

    rows = await session.execute(
        select(Mark.id, Mark.code, Mark.category, Element.dbid)
        .join(Element, Element.mark_id == Mark.id)
        .where(*conds)
        .order_by(Element.dbid)
    )
    grouped: dict[int, tuple[str, str, list[int]]] = {}
    for mark_id, code, category, dbid in rows:
        grouped.setdefault(mark_id, (code, category, []))[2].append(dbid)
    marks = [
        MarkPieces(mark_id=mid, code=code, category=cat, count=len(ids), dbids=ids)
        for mid, (code, cat, ids) in grouped.items()
    ]
    if compiled is None:
        return _ordered(marks, params), None
    marks += [m for m in _orphan_rows(compiled.orphan_marks, params) if m.mark_id not in grouped]
    return _ordered(marks, params), (compiled.notes[0] if compiled.notes else None)


@dataclass(frozen=True)
class Facets:
    categories: list[tuple[str, int]]
    levels: list[tuple[str, int]]
    pieces_without_level: int


async def facets(session: AsyncSession, version_id: int) -> Facets:
    """Categorias e níveis (com nº de peças com marca) para montar os filtros."""
    await get_ready_version(session, version_id)
    base = [Element.version_id == version_id, Element.mark_id.is_not(None)]
    cats = await session.execute(
        select(Element.category, func.count())
        .where(*base)
        .group_by(Element.category)
        .order_by(Element.category)
    )
    levels = await session.execute(
        select(Element.level, func.count())
        .where(*base)
        .group_by(Element.level)
        .order_by(Element.level)
    )
    level_rows = [(lv, n) for lv, n in levels]
    return Facets(
        categories=[(c or "", n) for c, n in cats],
        levels=[(lv, n) for lv, n in level_rows if lv],
        pieces_without_level=sum(n for lv, n in level_rows if not lv),
    )
