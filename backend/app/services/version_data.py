"""Leitura dos dados de uma versão processada: marcas (com dbIds) e elementos."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cmp_to_key
from typing import Any

from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ModelVersion
from app.models.enums import VersionStatus
from app.services.errors import ConflictError, NotFoundError


class VersionNotReadyError(ConflictError):
    code = "version_not_ready"


@dataclass(frozen=True)
class SourceCount:
    """Peças da marca cujo nome veio deste parâmetro da regra."""

    name: str
    pieces: int


@dataclass(frozen=True)
class SecondaryValues:
    """Outro parâmetro da regra preenchido nas peças da marca: valores distintos e quantas
    peças têm valor. Mais de um valor = as peças da marca divergem nesse parâmetro."""

    name: str
    values: list[str]
    pieces: int


@dataclass(frozen=True)
class MarkPieces:
    mark_id: int
    code: str
    category: str
    count: int
    dbids: list[int]
    # dbIds dos membros das peças (consolos, geometria): um clique neles acha a marca
    member_dbids: list[int] = field(default_factory=list)
    sources: list[SourceCount] = field(default_factory=list)
    secondary: list[SecondaryValues] = field(default_factory=list)
    # tipo das peças (o mais comum): pilar | quadro | laje | escada | outros
    piece_type: str = "outros"


@dataclass(frozen=True)
class ElementDetail:
    dbid: int
    external_id: str | None
    name: str | None
    category: str | None
    mark_raw: str | None
    mark: MarkPieces | None
    groups: list[dict[str, Any]] = field(default_factory=list)
    mark_source: str | None = None
    mark_alt: list[list[str]] = field(default_factory=list)


async def get_ready_version(session: AsyncSession, version_id: int) -> ModelVersion:
    version = await session.get(ModelVersion, version_id)
    if version is None:
        raise NotFoundError("Versão não encontrada.")
    if version.status != VersionStatus.READY.value:
        raise VersionNotReadyError(
            "Esta versão ainda não foi processada; as peças aparecem quando ela ficar pronta."
        )
    return version


async def list_marks(session: AsyncSession, version_id: int) -> list[MarkPieces]:
    """Marcas da versão com a quantidade e os dbIds das peças (sem peças sem Marca)."""
    await get_ready_version(session, version_id)
    dbids = func.array_agg(aggregate_order_by(Element.dbid, Element.dbid))
    rows = await session.execute(
        select(Mark.id, Mark.code, Mark.category, func.count(), dbids)
        .join(Element, Element.mark_id == Mark.id)
        .where(Element.version_id == version_id)
        .group_by(Mark.id)
        .order_by(Mark.category, Mark.code)
    )
    members: dict[int, list[int]] = {}
    for mark_id, member_dbids in await session.execute(
        select(Element.mark_id, Element.member_dbids).where(
            Element.version_id == version_id,
            Element.mark_id.is_not(None),
            Element.member_dbids != literal([], JSONB),
        )
    ):
        members.setdefault(mark_id, []).extend(member_dbids)
    origins = await _origins(session, version_id)
    types = await _piece_types(session, version_id)
    return [
        MarkPieces(
            mark_id=r[0],
            code=r[1],
            category=r[2],
            count=r[3],
            dbids=list(r[4]),
            member_dbids=sorted(members.get(r[0], [])),
            sources=origins[r[0]].sources() if r[0] in origins else [],
            secondary=origins[r[0]].secondary() if r[0] in origins else [],
            piece_type=types.get(r[0], "outros"),
        )
        for r in rows
    ]


async def _piece_types(session: AsyncSession, version_id: int) -> dict[int, str]:
    """Tipo de cada marca: o das suas peças (o mais comum; empate, o primeiro na ordem)."""
    counts: dict[int, dict[str, int]] = {}
    for mark_id, kind, n in await session.execute(
        select(Element.mark_id, Element.piece_type, func.count())
        .where(Element.version_id == version_id, Element.mark_id.is_not(None))
        .group_by(Element.mark_id, Element.piece_type)
    ):
        if mark_id is not None:  # filtrado na consulta; o tipo da coluna admite nulo
            counts.setdefault(mark_id, {})[kind or "outros"] = n
    return {m: max(sorted(c), key=lambda k: c[k]) for m, c in counts.items()}


class _Origin:
    """Acumula, por marca, as origens e os parâmetros secundários das peças."""

    def __init__(self) -> None:
        self.by_source: dict[str, int] = {}
        # parâmetro -> (valores distintos na ordem em que apareceram, peças com valor)
        self.alt: dict[str, tuple[dict[str, str], list[int]]] = {}

    def add(self, source: str | None, alt: list[Any]) -> None:
        if source:
            self.by_source[source] = self.by_source.get(source, 0) + 1
        for item in alt:
            if not isinstance(item, list) or len(item) != 2:
                continue
            name, value = str(item[0]), str(item[1]).strip()
            values, count = self.alt.setdefault(name, ({}, [0]))
            values.setdefault(value.casefold(), value)
            count[0] += 1

    def sources(self) -> list[SourceCount]:
        ordered = sorted(self.by_source.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
        return [SourceCount(name=n, pieces=c) for n, c in ordered]

    def secondary(self) -> list[SecondaryValues]:
        return [
            SecondaryValues(name=n, values=sorted(v.values(), key=_key), pieces=c[0])
            for n, (v, c) in self.alt.items()
        ]


async def _origins(session: AsyncSession, version_id: int) -> dict[int, _Origin]:
    out: dict[int, _Origin] = {}
    for mark_id, source, alt in await session.execute(
        select(Element.mark_id, Element.mark_source, Element.mark_alt)
        .where(Element.version_id == version_id, Element.mark_id.is_not(None))
        .order_by(Element.dbid)  # ordem estável dos secundários (a da regra, peça a peça)
    ):
        out.setdefault(mark_id, _Origin()).add(source, alt or [])
    return out


def _compare(a: str, b: str) -> int:
    """Ordem alfabética sem diferenciar maiúsculas (estável entre sistemas)."""
    ka, kb = a.casefold(), b.casefold()
    return (ka > kb) - (ka < kb) or (a > b) - (a < b)


_key = cmp_to_key(_compare)  # não depende do locale do servidor


def group_properties(props: dict[str, Any]) -> list[dict[str, Any]]:
    """{grupo: {nome: valor}} -> [{name, properties: [{name, value}]}], em ordem alfabética.

    O JSONB do Postgres não preserva a ordem das chaves do Model Derivative; por isso
    os grupos e as propriedades são ordenados alfabeticamente. Valores fora de grupo
    (raros) vão para o grupo "Outros".
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    loose: list[dict[str, Any]] = []
    for group_name, content in props.items():
        if isinstance(content, dict):
            groups[group_name] = [
                {"name": k, "value": v}
                for k, v in sorted(content.items(), key=lambda kv: _key(kv[0]))
            ]
        else:
            loose.append({"name": group_name, "value": content})
    if loose:
        groups.setdefault("Outros", []).extend(loose)
    return [
        {"name": name, "properties": groups[name]}
        for name in sorted(groups, key=_key)
        if groups[name]
    ]


async def get_element(session: AsyncSession, version_id: int, dbid: int) -> ElementDetail:
    await get_ready_version(session, version_id)
    element = await session.scalar(
        select(Element).where(Element.version_id == version_id, Element.dbid == dbid)
    )
    if element is None:  # clique num membro (consolo, alça) ou na geometria da peça
        element = await session.scalar(
            select(Element)
            .where(Element.version_id == version_id, Element.member_dbids.contains([dbid]))
            .order_by(Element.dbid)
            .limit(1)
        )
    if element is None:
        raise NotFoundError("Peça não encontrada nesta versão do modelo.")

    mark: MarkPieces | None = None
    if element.mark_id is not None:
        row = (
            await session.execute(
                select(
                    Mark.id,
                    Mark.code,
                    Mark.category,
                    func.array_agg(aggregate_order_by(Element.dbid, Element.dbid)),
                )
                .join(Element, Element.mark_id == Mark.id)
                .where(Mark.id == element.mark_id, Element.version_id == version_id)
                .group_by(Mark.id)
            )
        ).one()
        mark = MarkPieces(
            mark_id=row[0], code=row[1], category=row[2], count=len(row[3]), dbids=list(row[3])
        )

    return ElementDetail(
        dbid=element.dbid,
        external_id=element.external_id,
        name=element.name,
        category=element.category,
        mark_raw=element.mark_raw,
        mark=mark,
        mark_source=element.mark_source,
        mark_alt=[[str(a[0]), str(a[1])] for a in element.mark_alt or [] if len(a) == 2],
        groups=group_properties(element.props or {}),
    )
