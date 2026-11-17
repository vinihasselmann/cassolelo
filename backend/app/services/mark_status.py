"""Status de produção (Fase 6.4; por PEÇA desde 2026-11-16, docs/bugs/data-por-peca.md).
Calculado na hora.

Regra:
- O status é de cada PEÇA. base = parâmetros OBRIGATÓRIOS que se aplicam à peça (escopo +
  categoria da marca); se não há obrigatórios para ela, qualquer parâmetro aplicável conta.
- Um parâmetro POR MARCA está feito quando a marca tem valor; um POR PEÇA, quando a
  unidade de peça ligada a ESTA peça tem valor (preencher uma peça não muda as outras).
- nenhum da base feito (ou base vazia) → pending; todos → complete; senão → partial.
- review ("a revisar"): a reconciliação (Fase 7.2) marcou a marca (marks.review_status);
  vale para todas as peças dela e tem precedência até a fábrica "Manter valores" ou editar.
- Status da MARCA (listas, atalhos, Excel) = agregado das peças: todas iguais → esse;
  diferentes → partial; review tem precedência.
- O progresso dos parâmetros por peça conta peça a peça.

Só entram as marcas que têm peças na versão (as órfãs não têm cor nem progresso).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Element, Mark, ParamDef, ParamValue, PieceUnitLink, PieceValue
from app.models.enums import ParamLevel, ReviewStatus
from app.services.errors import NotFoundError
from app.services.param_defs import has_value
from app.services.param_defs import in_obra as param_in_obra
from app.services.version_data import get_ready_version


class MarkStatus(StrEnum):
    PENDING = "pending"
    PARTIAL = "partial"
    COMPLETE = "complete"
    REVIEW = "review"


@dataclass(frozen=True)
class _VersionMark:
    id: int
    category: str
    pieces: int
    review: bool = False


@dataclass
class _Snapshot:
    marks: list[_VersionMark]
    params: list[ParamDef]  # ativos da obra (globais + da obra), por marca e por peça
    filled: dict[int, set[int]]  # mark_id -> def_ids POR MARCA com valor
    # mark_id -> def_id POR PEÇA -> unidades (ligadas nesta versão) com valor
    piece_filled: dict[int, dict[int, int]] = field(default_factory=dict)
    # peças da versão com marca: (element_id, mark_id)
    elements: list[tuple[int, int]] = field(default_factory=list)
    # element_id -> def_ids POR PEÇA com valor na unidade ligada a esta peça
    element_filled: dict[int, set[int]] = field(default_factory=dict)


def applies(param: ParamDef, category: str) -> bool:
    return not param.categories or category in param.categories


def is_piece(param: ParamDef) -> bool:
    return param.level == ParamLevel.PIECE.value


def status_of(
    params: list[ParamDef],
    category: str,
    filled: Collection[int],
    piece_filled: Collection[int] = (),
) -> MarkStatus:
    """Status de UMA PEÇA. `filled`: parâmetros POR MARCA com valor na marca dela;
    `piece_filled`: parâmetros POR PEÇA com valor na unidade ligada a esta peça."""
    applicable = [p for p in params if applies(p, category)]
    required = [p for p in applicable if p.required]
    base = required or applicable
    done = sum(1 for p in base if p.id in (piece_filled if is_piece(p) else filled))
    if not base or done == 0:
        return MarkStatus.PENDING
    return MarkStatus.COMPLETE if done == len(base) else MarkStatus.PARTIAL


def aggregate(statuses: Iterable[MarkStatus]) -> MarkStatus:
    """Status da MARCA a partir das peças: todas iguais → esse; diferentes → parcial."""
    found = set(statuses)
    if MarkStatus.REVIEW in found:
        return MarkStatus.REVIEW
    if not found:
        return MarkStatus.PENDING
    return found.pop() if len(found) == 1 else MarkStatus.PARTIAL


async def element_fill(
    session: AsyncSession, version_id: int, def_ids: list[int]
) -> dict[int, set[int]]:
    """element_id -> parâmetros por peça com valor na unidade ligada à peça nesta versão."""
    out: dict[int, set[int]] = defaultdict(set)
    if not def_ids:
        return out
    rows = await session.execute(
        select(PieceUnitLink.element_id, PieceValue.def_id)
        .join(PieceValue, PieceValue.unit_id == PieceUnitLink.unit_id)
        .where(
            PieceUnitLink.version_id == version_id,
            PieceValue.def_id.in_(def_ids),
            has_value(PieceValue.value),
        )
    )
    for element_id, def_id in rows:
        out[element_id].add(def_id)
    return out


async def piece_fill(
    session: AsyncSession, version_id: int, def_ids: list[int]
) -> dict[int, dict[int, int]]:
    """mark_id -> def_id -> unidades ligadas nesta versão com valor no parâmetro por peça."""
    out: dict[int, dict[int, int]] = defaultdict(dict)
    if not def_ids:
        return out
    rows = await session.execute(
        select(Element.mark_id, PieceValue.def_id, func.count(func.distinct(PieceValue.unit_id)))
        .join(PieceUnitLink, PieceUnitLink.element_id == Element.id)
        .join(PieceValue, PieceValue.unit_id == PieceUnitLink.unit_id)
        .where(
            PieceUnitLink.version_id == version_id,
            PieceValue.def_id.in_(def_ids),
            has_value(PieceValue.value),
        )
        .group_by(Element.mark_id, PieceValue.def_id)
    )
    for mark_id, def_id, n in rows:
        if mark_id is not None:
            out[mark_id][def_id] = int(n)
    return out


async def _snapshot(session: AsyncSession, version_id: int) -> _Snapshot:
    version = await get_ready_version(session, version_id)
    rows = await session.execute(
        select(Mark.id, Mark.category, func.count(), Mark.review_status)
        .join(Element, Element.mark_id == Mark.id)
        .where(Element.version_id == version_id)
        .group_by(Mark.id)
    )
    marks = [_VersionMark(r[0], r[1], r[2], r[3] == ReviewStatus.REVIEW.value) for r in rows]
    params = list(
        await session.scalars(
            select(ParamDef)
            .where(
                ParamDef.active.is_(True),
                param_in_obra(version.obra_id, level=None),
            )
            .order_by(func.lower(ParamDef.name), ParamDef.id)
        )
    )
    filled: dict[int, set[int]] = defaultdict(set)
    mark_params = [p for p in params if not is_piece(p)]
    if marks and mark_params:
        mark_ids = select(Element.mark_id).where(
            Element.version_id == version_id, Element.mark_id.is_not(None)
        )
        values = await session.execute(
            select(ParamValue.mark_id, ParamValue.def_id).where(
                ParamValue.mark_id.in_(mark_ids),
                ParamValue.def_id.in_([p.id for p in mark_params]),
                has_value(ParamValue.value),
            )
        )
        for mark_id, def_id in values:
            filled[mark_id].add(def_id)
    piece_defs = [p.id for p in params if is_piece(p)]
    pieces = await piece_fill(session, version_id, piece_defs)
    elements = [
        (el_id, mark_id)
        for el_id, mark_id in await session.execute(
            select(Element.id, Element.mark_id).where(
                Element.version_id == version_id, Element.mark_id.is_not(None)
            )
        )
        if mark_id is not None
    ]
    return _Snapshot(
        marks,
        params,
        filled,
        pieces,
        elements,
        await element_fill(session, version_id, piece_defs),
    )


@dataclass(frozen=True)
class StatusResult:
    statuses: dict[int, MarkStatus]  # mark_id -> status da marca (agregado das peças)
    counts: dict[MarkStatus, int]  # marcas por status (inclui zeros)
    pieces: dict[MarkStatus, int]  # peças por status (o status de CADA peça)
    piece_statuses: dict[int, MarkStatus] = field(default_factory=dict)  # element_id -> status


async def version_statuses(session: AsyncSession, version_id: int) -> StatusResult:
    snap = await _snapshot(session, version_id)
    by_mark = {m.id: m for m in snap.marks}
    piece_statuses: dict[int, MarkStatus] = {}
    per_mark: dict[int, list[MarkStatus]] = defaultdict(list)
    for el_id, mark_id in snap.elements:
        m = by_mark.get(mark_id)
        if m is None:  # pragma: no cover - toda peça com marca tem a marca na lista
            continue
        st = (
            MarkStatus.REVIEW
            if m.review
            else status_of(
                snap.params,
                m.category,
                snap.filled.get(m.id, set()),
                snap.element_filled.get(el_id, set()),
            )
        )
        piece_statuses[el_id] = st
        per_mark[mark_id].append(st)
    statuses = {m.id: aggregate(per_mark.get(m.id, [])) for m in snap.marks}
    counts = Counter(statuses.values())
    pieces = Counter(piece_statuses.values())
    return StatusResult(
        statuses=statuses,
        counts={s: counts.get(s, 0) for s in MarkStatus},
        pieces={s: pieces.get(s, 0) for s in MarkStatus},
        piece_statuses=piece_statuses,
    )


async def marks_with_status(
    session: AsyncSession, version_id: int, wanted: MarkStatus
) -> list[int]:
    result = await version_statuses(session, version_id)
    return [mid for mid, s in result.statuses.items() if s is wanted]


@dataclass(frozen=True)
class ParamProgress:
    def_id: int
    name: str
    marks_total: int  # marcas da versão em que o parâmetro se aplica
    marks_filled: int  # por peça: marcas com TODAS as peças preenchidas
    pieces_total: int
    pieces_filled: int  # por peça: peça a peça
    level: str = ParamLevel.MARK.value


@dataclass(frozen=True)
class Progress:
    marks: int
    pieces: int
    required: list[ParamProgress]


async def progress(session: AsyncSession, version_id: int) -> Progress:
    """Progresso por parâmetro OBRIGATÓRIO (marcas e peças em que se aplica)."""
    snap = await _snapshot(session, version_id)
    out = []
    for p in snap.params:
        if not p.required:
            continue
        target = [m for m in snap.marks if applies(p, m.category)]
        if is_piece(p):
            units = {
                m.id: min(snap.piece_filled.get(m.id, {}).get(p.id, 0), m.pieces) for m in target
            }
            out.append(
                ParamProgress(
                    def_id=p.id,
                    name=p.name,
                    marks_total=len(target),
                    marks_filled=sum(1 for m in target if m.pieces and units[m.id] >= m.pieces),
                    pieces_total=sum(m.pieces for m in target),
                    pieces_filled=sum(units.values()),
                    level=p.level,
                )
            )
            continue
        done = [m for m in target if p.id in snap.filled.get(m.id, set())]
        out.append(
            ParamProgress(
                def_id=p.id,
                name=p.name,
                marks_total=len(target),
                marks_filled=len(done),
                pieces_total=sum(m.pieces for m in target),
                pieces_filled=sum(m.pieces for m in done),
            )
        )
    return Progress(marks=len(snap.marks), pieces=sum(m.pieces for m in snap.marks), required=out)


@dataclass(frozen=True)
class ParamValues:
    param: ParamDef
    values: dict[int, Any]  # mark_id -> valor (só marcas em que se aplica; None = vazio)


async def param_values(session: AsyncSession, version_id: int, def_id: int) -> ParamValues:
    """Valor de UM parâmetro em cada marca da versão (para "Colorir por parâmetro")."""
    snap = await _snapshot(session, version_id)
    # só parâmetros POR MARCA (os por peça não têm um valor por marca)
    param = next((p for p in snap.params if p.id == def_id and not is_piece(p)), None)
    if param is None:
        raise NotFoundError("Parâmetro não encontrado nesta obra.")
    target = {m.id for m in snap.marks if applies(param, m.category)}
    values: dict[int, Any] = dict.fromkeys(target)
    if target:
        rows = await session.execute(
            select(ParamValue.mark_id, ParamValue.value).where(
                ParamValue.def_id == def_id,
                ParamValue.mark_id.in_(target),
                has_value(ParamValue.value),
            )
        )
        for mark_id, value in rows:
            values[mark_id] = value
    return ParamValues(param, values)
